"""网站流水线入口：python tools/run_all.py [--artifact <批次> --from-step <步骤>] [--to-step <步骤>]

模块划分：
- pipeline_core.py   配置加载/语义名迁移、变量展开、逐步执行（步骤命令见 configs/pipeline.yaml）
- upstream_pin.py    运行开始固定 all_cars_data 已发布交付物（所有步骤读同一份）
- import_compressed_tables.py  导入产线全量表与压缩表（原 import_a2_compressed.py，旧名保留兼容入口）
- build_publish_site.py / site_promote.py  在 work 内构建并完整校验站点，成功后切换 public，失败回滚
- site_batch.py      v3 批次清单、站点字节去重存储与恢复
- run_legacy.py      旧手工输入的增量模式
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # 直接运行 tools/run_all.py 时保证 `tools` 包可导入
    sys.path.insert(0, str(ROOT))

from tools.pipeline_core import (  # noqa: E402,F401  (测试与旧调用方从 run_all 导入这些名称)
    PATH_KEY_ALIASES,
    STEP_ALIASES,
    STEP_RENAMES,
    WORK_ROOT,
    build_variables,
    check_required_paths,
    configured_public_dir,
    copy_path,
    deep_merge,
    enabled_step_names,
    execute_case_pipeline,
    format_command,
    load_config,
    next_artifact_dir,
    normalize_config,
    resolve_artifact_dir,
    resolve_from_root,
    run_configured_step,
    run_step,
    scan_cases,
    selected_step_names,
    work_dir_for,
    work_root,
)
from tools.run_legacy import (  # noqa: E402,F401
    find_project_case,
    replace_workspace_transactionally,
    run_incremental,
    select_project_data_dir,
    workspace_fingerprint,
)
from tools.site_promote import mirror_directory, rename_with_retry  # noqa: E402,F401

UPSTREAM_KEYS = ("a0_output_dir", "compressed_output_dir", "sales_output_dir")
SITE_MANIFEST = "site_manifest.json"
NAS_STATUS = "nas_publish.json"
PUBLIC_STEP = "build_public_site"
NAS_STEP = "publish_nas_site"


SIZE_CODE_MAP_DELIVERABLE = "US/新旧尺码对应.csv"  # A0 正式接口（2026-10-14 起）


def resolve_size_code_map(config: dict[str, Any], context: dict[str, Any], batch, *, resuming: bool) -> Path | None:
    """新旧尺码对应：优先用固定的 A0 发布物；A0 尚未发布该文件时退回 paths.size_code_map_file（A0 data/，兼容模式）并快照进批次。"""
    from tools.site_batch import sha256_file

    a0 = context["sources"].get("a0_output_dir")
    if a0 and any(item["file"] == SIZE_CODE_MAP_DELIVERABLE for item in a0["files"]):
        path = Path(a0["pinned_dir"]) / SIZE_CODE_MAP_DELIVERABLE
        record = {"interface": "a0_output", "file": SIZE_CODE_MAP_DELIVERABLE, "sha256": sha256_file(path)}
    else:
        configured = (config.get("paths") or {}).get("size_code_map_file")
        if not configured:
            return None
        path = resolve_from_root(configured)
        if not path.is_file():
            raise FileNotFoundError(f"A0 未发布 {SIZE_CODE_MAP_DELIVERABLE}，兼容路径 paths.size_code_map_file 也不存在：{path}")
        print(f"[size-code-map] 警告：A0 {a0['version'] if a0 else ''} 未发布 {SIZE_CODE_MAP_DELIVERABLE}，兼容模式读取 {path}；请重新发布 A0")
        record = {"interface": "legacy_a0_data", "path": str(path), "sha256": sha256_file(path)}
        if resuming:
            recorded = (batch.manifest.get("size_code_map") or {}).get("sha256")
            if recorded and recorded != record["sha256"]:
                raise RuntimeError(f"{path} 在批次创建后已改动，无法恢复；请重新运行创建新批次")
        else:
            batch.add_extra(path, "upstream_size_code_map.csv", compress=False)
    if not resuming:
        batch.manifest["size_code_map"] = record
        batch.save()
    return path


def config_files(source_config: Path) -> list[Path]:
    """登记到批次的配置：configs/ 下全部文件（含 include 链与本机覆盖）。"""
    files = {source_config.resolve()}
    configs_dir = ROOT / "configs"
    if configs_dir.is_dir():
        files.update(path.resolve() for path in configs_dir.iterdir() if path.is_file())
    return sorted(files)


def external_repos(config: dict[str, Any], variables: dict[str, str], steps: list[str]) -> dict[str, tuple[Path, bool]]:
    """本次运行实际使用的外部仓库：步骤 repo 与命令中出现的、位于本仓库之外的现存路径所在 Git 仓库。"""
    from tools.site_batch import run_git

    upstream_roots = set()
    for key in UPSTREAM_KEYS:
        configured = (config.get("paths") or {}).get(key)
        if configured:
            top = run_git(resolve_from_root(configured), "rev-parse", "--show-toplevel")
            if top:
                upstream_roots.add(Path(top.decode().strip()).resolve())
    found: dict[str, tuple[Path, bool]] = {}
    for name in steps:
        step = config["steps"][name]
        candidates = [resolve_from_root(config["repos"][step["repo"]])]
        for part in format_command(step.get("command") or [], variables):
            path = Path(part)
            if path.is_absolute() and path.exists():
                candidates.append(path if path.is_dir() else path.parent)
        for candidate in candidates:
            top = run_git(candidate, "rev-parse", "--show-toplevel") if candidate.exists() else None
            if not top:
                continue
            repo = Path(top.decode().strip()).resolve()
            if repo == ROOT.resolve() or repo in upstream_roots:
                continue
            found[repo.name] = (repo, True)
    compress = (config.get("repos") or {}).get("compress")
    if compress:
        path = resolve_from_root(compress)
        found.setdefault(path.name, (path, False))  # 只供旧模式：登记版本但正式模式不要求存在
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fitment pipeline for configured Excel/CSV inputs.")
    parser.add_argument(
        "--config",
        help="Path to pipeline config yaml; defaults to configs/pipeline.local.yaml when present "
        "(untracked per-machine overrides that include pipeline.yaml), else configs/pipeline.yaml.",
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        help="未完成的 v3 批次名/路径，配合 --from-step 恢复；省略时创建新批次 YYYY-MM-DD_NN_pipeline。",
    )
    parser.add_argument("--from-step", help="Resume from this configured step, e.g. build_user_size_json.")
    parser.add_argument("--to-step", help="Stop after this configured step.")
    parser.add_argument("--list-steps", action="store_true", help="Print enabled step names and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    parser.add_argument("--keep-work", action="store_true", help="成功后保留 work/<批次>/ 中间文件（默认删除；失败总是保留）")
    args = parser.parse_args()

    from tools.site_batch import SiteBatch, can_resume, read_manifest
    from tools.upstream_pin import UpstreamPinError, load_context, pin_upstream, verify_pinned

    local_config = resolve_from_root("configs/pipeline.local.yaml")
    source_config = resolve_from_root(args.config) if args.config else (
        local_config if local_config.is_file() else resolve_from_root("configs/pipeline.yaml")
    )
    config = normalize_config(load_config(source_config))
    config["_config_path"] = str(source_config)
    if args.list_steps:
        print("\n".join(enabled_step_names(config)))
        return 0

    run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.from_step and not args.artifact:
        parser.error("--from-step requires --artifact so the existing batch can be resumed safely.")

    selected_steps = selected_step_names(config, from_step=args.from_step, to_step=args.to_step)
    enabled_steps = enabled_step_names(config)
    artifact_dir = resolve_artifact_dir(config, args.artifact)
    resuming = args.artifact is not None
    if resuming:
        if not artifact_dir.is_dir():
            parser.error(f"--artifact does not exist: {artifact_dir}")
        ok, reason = can_resume(artifact_dir)
        if not ok:
            parser.error(reason)
        work_dir = resolve_from_root(read_manifest(artifact_dir)["work_dir"])
        if not work_dir.is_dir():
            parser.error(f"批次 {artifact_dir.name} 的工作目录 {work_dir} 已不存在，无法恢复；请重新运行创建新批次")
    else:
        work_dir = work_dir_for(artifact_dir, config)
    all_cars_data = (config.get("input") or {}).get("source") == "all_cars_data"
    cases = scan_cases(config, artifact_dir, work_dir=work_dir)

    if not cases:
        print("No configured Excel/CSV input files found.")
        return 0

    logs_root = resolve_from_root(Path(config["paths"]["logs_dir"]) / run_id)
    logs_root.mkdir(parents=True, exist_ok=True)
    stop_on_error = config.get("run", {}).get("stop_on_error", True)

    print(f"Found {len(cases)} case(s): {', '.join(case['case_name'] for case in cases)}")
    print(f"Artifact: {artifact_dir}")
    print(f"Work: {work_dir}")
    print(f"Logs: {logs_root}")

    if args.dry_run:
        for case in cases:
            execute_case_pipeline(case=case, config=config, selected_steps=selected_steps, logs_root=logs_root, dry_run=True)
        return 0

    if resuming:
        batch = SiteBatch(artifact_dir)
        batch.manifest["status"] = "running"
        batch.save()
    else:
        if work_dir.exists():
            parser.error(f"工作目录已存在：{work_dir}（可能是同名批次的残留，请检查后删除）")
        batch = SiteBatch.create(artifact_dir, work_dir=work_dir, config_path=source_config, steps=enabled_steps)
    batch.manifest["logs"] = rel_to_root(logs_root)
    batch.save()

    try:
        if all_cars_data:
            if resuming:
                context = load_context(work_dir)
                if context is None:
                    raise UpstreamPinError(f"{work_dir} 缺少 run_context.json，无法恢复；请重新运行创建新批次")
                missing = set(UPSTREAM_KEYS) - set(context["sources"])
                if missing:
                    raise UpstreamPinError(f"旧批次缺少固定输入 {sorted(missing)}，请创建新批次")
                verify_pinned(context)
            else:
                sources = {key: resolve_from_root((config["paths"])[key]) for key in UPSTREAM_KEYS}
                context = pin_upstream(sources, work_dir)
                batch.record_upstream(context)
                print("Pinned upstream: " + ", ".join(f"{s['node']} {s['version']}" for s in context["sources"].values()))
            size_code_map = resolve_size_code_map(config, context, batch, resuming=resuming)
            for case in cases:
                case["upstream_dirs"] = {key: Path(source["pinned_dir"]) for key, source in context["sources"].items()}
                if size_code_map is not None:
                    case["upstream_dirs"]["size_code_map_file"] = size_code_map
        else:
            batch.manifest["inputs"] = [rel_to_root(path) for path in cases[0]["input_files"]]
            batch.save()
        if not resuming:
            variables = build_variables(cases[0], config)
            batch.record_repo(ROOT.name, ROOT, used_paths=["tools", "configs", "site_overrides"])
            for name, (path, required) in external_repos(config, variables, [s for s in enabled_steps if s in selected_steps]).items():
                batch.record_repo(name, path, required=required)
            batch.record_configs(config_files(source_config))
    except Exception as exc:
        batch.finish("failed", f"准备阶段失败：{exc}")
        print(f"FAILED: {exc}")
        return 1

    def on_step(name: str, status: str, error: Exception | None) -> None:
        if status == "failed":
            batch.step(name, "failed", error=str(error)[-4000:])
            log = logs_root / cases[0]["case_name"] / f"{name}.log"
            if log.is_file():
                batch.add_extra(log, f"logs/{name}.log")
            if name == PUBLIC_STEP:
                batch.set_publish("public", status="failed", note="构建或校验失败，public 保持上一版")
            elif name == NAS_STEP:
                batch.set_publish("nas", status="failed", error=str(error)[-1000:])
            return
        batch.step(name, status)
        if status != "succeeded":
            return
        if name in ("import_compressed_tables", "normalize_store_inputs"):
            batch.add_extra(cases[0]["pipeline_config"], compress=False)
        elif name == "build_user_size_json":
            batch.add_extra(work_dir / "02_user_size.json")
            batch.add_extra(work_dir / "02_type_待确认.csv", compress=False)
        elif name == PUBLIC_STEP:
            manifest_path = work_dir / SITE_MANIFEST
            expected = json.loads(manifest_path.read_text(encoding="utf-8"))["files"] if manifest_path.is_file() else None
            summary = batch.store_site(configured_public_dir(config["paths"]), expected)
            batch.set_publish("public", status="promoted", path=rel_to_root(configured_public_dir(config["paths"])), **summary)
            print(f"[batch] site: {summary}")
        elif name == NAS_STEP:
            status_path = work_dir / NAS_STATUS
            record = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else {"status": "unknown"}
            batch.set_publish("nas", **record)

    for name in enabled_steps:
        if not resuming and name not in selected_steps:
            batch.step(name, "skipped")
    if NAS_STEP not in enabled_steps:
        batch.set_publish("nas", status="disabled")

    failures: list[str] = []
    for case in cases:
        try:
            execute_case_pipeline(
                case=case,
                config=config,
                selected_steps=selected_steps,
                logs_root=logs_root,
                dry_run=False,
                require_interactive_checks=False,
                on_step=on_step,
            )
        except Exception as exc:
            failures.append(f"{case['case_name']}: {exc}")
            print(f"FAILED: {failures[-1]}")
            if stop_on_error:
                break

    if failures:
        batch.finish("failed", "\n".join(failures))
        print("\nFailures:")
        for failure in failures:
            print(f"- {failure}")
        print(f"诊断信息：{artifact_dir / 'artifact.json'}；中间文件保留在 {work_dir}；public 未被修改（除非已成功切换）")
        return 1

    step_states = {name: batch.manifest["steps"].get(name, {}).get("status") for name in enabled_steps}
    completed = all(state == "succeeded" for state in step_states.values())
    batch.finish("complete" if completed else "partial")
    if completed and not args.keep_work:
        remove_work_dir(work_dir, work_root(config))
    print(f"\nAll cases completed. Batch {artifact_dir.name}: {'complete' if completed else 'partial'}")
    return 0


def rel_to_root(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(Path(path).resolve())


def remove_work_dir(work_dir: Path, root: Path) -> None:
    """只删除工作目录根下的批次工作目录。"""
    resolved = work_dir.resolve()
    if resolved.parent != root.resolve():
        raise RuntimeError(f"拒绝删除 work/ 以外的目录：{resolved}")
    shutil.rmtree(resolved)


if __name__ == "__main__":
    sys.exit(main())

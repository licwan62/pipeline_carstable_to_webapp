"""网站流水线的步骤执行核心：配置加载与语义名迁移、批次/工作目录定位、变量展开、逐步执行。

运行编排（批次清单、固定上游、发布状态）在 run_all.py；旧手工输入/增量模式在 run_legacy.py。
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import locale
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.materialize_input_sources import discover_input_files  # noqa: E402

ERROR_LOG_TAIL_LINES = 40
WORK_ROOT = "work"
# 语义名迁移（2026-10-14）：A2 时代的配置键/步骤名 -> 语义名；旧名继续可用并提示迁移
PATH_KEY_ALIASES = {"a2_output_dir": "compressed_output_dir"}
STEP_RENAMES = {"import_a2_compressed": "import_compressed_tables"}
STEP_ALIASES = {
    "import": "import_compressed_tables",
    "import_a2_compressed": "import_compressed_tables",
    "prepare_inputs": "normalize_store_inputs",
    "compress": "compress_store_fitment",
    "user_size_json": "build_user_size_json",
    "inplace_table": "export_store_csv",
    "get_html": "generate_store_html",
    "publish": "build_public_site",
}


def deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(config_path: Path, _loading: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Load YAML with optional relative ``include`` files and deep overrides."""
    config_path = config_path.resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    if config_path in _loading:
        chain = " -> ".join(str(path) for path in (*_loading, config_path))
        raise ValueError(f"Circular config include: {chain}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Config root must be a mapping: {config_path}")
    includes = raw.pop("include", [])
    if isinstance(includes, str):
        includes = [includes]

    merged: dict[str, Any] = {}
    for included in includes:
        included_path = (config_path.parent / included).resolve()
        merged = deep_merge(merged, load_config(included_path, (*_loading, config_path)))
    return deep_merge(merged, raw)


def normalize_config(config: dict[str, Any], *, warn=print) -> dict[str, Any]:
    """把旧配置键与步骤名迁移为语义名；新旧同时出现且不一致时报错。返回同一个 config。"""
    paths = config.setdefault("paths", {})
    for old, new in PATH_KEY_ALIASES.items():
        if old not in paths:
            continue
        if new in paths and str(paths[new]) != str(paths[old]):
            raise ValueError(f"paths.{old}（旧名）与 paths.{new} 同时配置且不一致：{paths[old]!r} != {paths[new]!r}；请只保留 {new}")
        if new not in paths:
            warn(f"[config] paths.{old} 已更名为 paths.{new}，请更新配置（旧名仍兼容）")
            paths[new] = paths[old]
        paths[old] = paths[new]  # 旧变量名 {a2_output_dir} 继续可用于命令模板
    steps = config.get("steps") or {}
    for old, new in STEP_RENAMES.items():
        if old not in steps:
            continue
        if new in steps:
            raise ValueError(f"steps 同时定义了旧名 {old} 与新名 {new}，请只保留 {new}")
        warn(f"[config] 步骤 {old} 已更名为 {new}，请更新配置（旧名仍兼容）")
        config["steps"] = {new if name == old else name: step for name, step in steps.items()}
    return config


def resolve_from_root(path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path.resolve()
    return (ROOT / path).resolve()


def configured_public_dir(paths: dict[str, Any]) -> Path:
    """Resolve the publish root, accepting legacy configs during migration."""
    configured = paths.get("public_dir") or paths.get("output_dir")
    if not configured:
        raise ValueError("paths.public_dir is required")
    return resolve_from_root(configured)


def next_artifact_dir(config: dict[str, Any], *, today: dt.date | None = None) -> Path:
    artifact_root = resolve_from_root(config["paths"]["artifact_root"])
    date_text = (today or dt.date.today()).isoformat()
    used: set[int] = set()
    if artifact_root.is_dir():
        for path in artifact_root.glob(f"{date_text}_??_*"):
            try:
                used.add(int(path.name.split("_", 2)[1]))
            except (IndexError, ValueError):
                continue
    sequence = next((number for number in range(1, 100) if number not in used), None)
    if sequence is None:
        raise RuntimeError(f"Artifact sequence exhausted for {date_text}")
    return artifact_root / f"{date_text}_{sequence:02d}_pipeline"


def resolve_artifact_dir(config: dict[str, Any], requested: Path | None) -> Path:
    if requested is None:
        return next_artifact_dir(config)
    if requested.is_absolute():
        return requested.resolve()
    if len(requested.parts) == 1:
        return (resolve_from_root(config["paths"]["artifact_root"]) / requested).resolve()
    return resolve_from_root(requested)


def work_root(config: dict[str, Any] | None = None) -> Path:
    """中间工作目录的根：paths.work_root，缺省 <仓库>/work（.gitignore 已忽略）。"""
    return resolve_from_root(((config or {}).get("paths") or {}).get("work_root") or WORK_ROOT)


def work_dir_for(artifact_dir: Path, config: dict[str, Any] | None = None) -> Path:
    """批次的中间工作目录：<work_root>/<批次名>/（不纳入 Git，成功后删除，失败保留诊断）。"""
    return work_root(config) / artifact_dir.name


def scan_cases(
    config: dict[str, Any], artifact_dir: Path, only_case: str | None = None, work_dir: Path | None = None
) -> list[dict[str, Any]]:
    """work_dir 缺省为 artifact_dir（旧布局，中间文件写在批次内）；新运行传入 work/<批次>/。"""
    paths = config["paths"]
    work_dir = work_dir or artifact_dir
    if (config.get("input") or {}).get("source") == "all_cars_data":
        # 产线输入来自 all_cars_data 的 A0/A1.压缩尺寸信息 发布物（由 import_compressed_tables 步骤校验导入）
        input_files = [
            resolve_from_root(paths[key]) / "manifest.json"
            for key in ("a0_output_dir", "compressed_output_dir" if "compressed_output_dir" in paths else "a2_output_dir")
        ]
        missing = [path for path in input_files if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"all_cars_data 发布物缺少 manifest.json：{missing}")
    else:
        input_dir = resolve_from_root(paths["input_dir"])
        input_files = discover_input_files(input_dir, config)
        if not input_files:
            return []

    manifest_path = artifact_dir / "artifact.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    case_name = str(manifest.get("case") or (config.get("input") or {}).get("case_name") or "stores").strip()
    if not case_name:
        raise ValueError("input.case_name must not be empty")
    if only_case and case_name != only_case:
        return []

    prepared_root = work_dir / "00_input"
    return [
        {
            "case_name": case_name,
            "input_files": input_files,
            "input_tables_dir": prepared_root / "tables",
            "pipeline_config": prepared_root / "pipeline.generated.json",
            "case_middle": work_dir,
            "artifact_dir": artifact_dir,
            "work_dir": work_dir,
            "case_public": configured_public_dir(paths),
        }
    ]


def build_variables(case: dict[str, Any], config: dict[str, Any]) -> dict[str, str]:
    paths = config["paths"]
    public_dir = str(configured_public_dir(paths))
    variables = {
        "root": str(ROOT),
        "source_config": str(config.get("_config_path") or resolve_from_root("configs/pipeline.yaml")),
        "case_name": str(case["case_name"]),
        "input_tables_dir": str(case["input_tables_dir"]),
        "pipeline_config": str(case.get("pipeline_config") or resolve_from_root("configs/pipeline.yaml")),
        "case_middle": str(case["case_middle"]),
        "case_public": str(case["case_public"]),
        "case_output": str(case["case_public"]),
        "input_dir": str(resolve_from_root(paths["input_dir"])),
        "artifact_dir": str(case["artifact_dir"]),
        "work_dir": str(case.get("work_dir") or case["artifact_dir"]),
        "public_dir": public_dir,
        "nas_publish_dir": str(paths.get("nas_publish_dir", "")),
        "output_dir": public_dir,
        "logs_dir": str(resolve_from_root(paths["logs_dir"])),
        "a0_output_dir": str(resolve_from_root(paths["a0_output_dir"])) if paths.get("a0_output_dir") else "",
        "size_code_map_file": str(resolve_from_root(paths["size_code_map_file"])) if paths.get("size_code_map_file") else "",
        "python": sys.executable,
    }
    variables["sales_output_dir"] = str(resolve_from_root(paths["sales_output_dir"])) if paths.get("sales_output_dir") else ""
    compressed = paths.get("compressed_output_dir") or paths.get("a2_output_dir")
    variables["compressed_output_dir"] = str(resolve_from_root(compressed)) if compressed else ""
    # 运行开始固定的上游副本优先：所有步骤读同一份输入（见 upstream_pin.py）
    for key, value in (case.get("upstream_dirs") or {}).items():
        variables[key] = str(value)
    variables["a2_output_dir"] = variables["compressed_output_dir"]  # 旧变量名兼容

    for key, value in config.get("variables", {}).items():
        formatted = str(value).format(**variables)
        if "/" in formatted or "\\" in formatted:
            formatted = str(Path(formatted))
        variables[key] = formatted

    legacy_stage_dirs = {
        "compressed_fitment_dir": case["artifact_dir"] / "01_compress",
        "store_csv_dir": case["artifact_dir"] / "03_user_size_exports",
        "store_html_dir": case["artifact_dir"] / "04_html",
        "site_workspace_dir": case["artifact_dir"] / "05_publish_workspace",
    }
    for variable_name, legacy_path in legacy_stage_dirs.items():
        configured_path = Path(variables.get(variable_name, ""))
        if legacy_path.exists() and not configured_path.exists():
            variables[variable_name] = str(legacy_path)

    return variables


def format_command(command: list[str], variables: dict[str, str]) -> list[str]:
    return [part.format(**variables) for part in command]


def format_path(value: str | Path, variables: dict[str, str]) -> Path:
    return resolve_from_root(str(value).format(**variables))


def format_path_list(values: list[str | Path] | None, variables: dict[str, str]) -> list[Path]:
    return [format_path(value, variables) for value in values or []]


def copy_path(source: Path, target: Path, *, overwrite: bool = True, dry_run: bool = False) -> None:
    print(f"[copy] {source} -> {target}")
    if dry_run:
        return
    if not source.exists():
        raise FileNotFoundError(f"Copy source does not exist: {source}")
    if source.is_dir():
        if target.exists() and overwrite:
            shutil.rmtree(target)
        shutil.copytree(source, target, dirs_exist_ok=overwrite)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.is_dir():
        target = target / source.name
    shutil.copy2(source, target)


def check_required_paths(paths: list[Path], *, step_name: str) -> None:
    missing = [path for path in paths if not path.exists()]
    if missing:
        missing_text = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"Step '{step_name}' did not produce required path(s):\n{missing_text}")


def read_log_tail(log_file: Path, line_count: int = ERROR_LOG_TAIL_LINES) -> str:
    if not log_file.exists():
        return ""
    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = lines[-line_count:]
    return "\n".join(tail).strip()


def format_step_failure(step_name: str, log_file: Path, result_code: int) -> str:
    message = f"Step failed: {step_name} (exit code {result_code}). See log: {log_file}"
    log_tail = read_log_tail(log_file)
    if log_tail:
        message += f"\n\nLast log lines:\n{log_tail}"
    return message


def run_step(
    *,
    step_name: str,
    repo_path: Path,
    command: list[str] | None,
    log_file: Path,
    dry_run: bool,
) -> None:
    if not command:
        return

    printable = " ".join(command)
    print(f"[{step_name}] {printable}")

    if dry_run:
        return

    if not repo_path.exists():
        raise FileNotFoundError(f"Repo path for step '{step_name}' does not exist: {repo_path}")

    with log_file.open("w", encoding="utf-8") as log:
        log.write(f"cwd: {repo_path}\n")
        log.write(f"command: {printable}\n\n")
        log.flush()
        process = subprocess.Popen(
            command,
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=locale.getpreferredencoding(False),
            errors="replace",
            env={**os.environ, "PYTHONUNBUFFERED": "1"},  # 子进程输出经管道时也实时传回进度
        )

        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
        result_code = process.wait()

    if result_code != 0:
        raise RuntimeError(format_step_failure(step_name, log_file, result_code))


def run_configured_step(
    *,
    step_name: str,
    step: dict[str, Any],
    repo_path: Path,
    variables: dict[str, str],
    log_file: Path,
    dry_run: bool,
) -> None:
    for copy_rule in step.get("copy_before", []):
        copy_path(
            format_path(copy_rule["from"], variables),
            format_path(copy_rule["to"], variables),
            overwrite=copy_rule.get("overwrite", True),
            dry_run=dry_run,
        )

    command = format_command(step["command"], variables) if step.get("command") else None
    run_step(
        step_name=step_name,
        repo_path=repo_path,
        command=command,
        log_file=log_file,
        dry_run=dry_run,
    )

    for copy_rule in step.get("copy_after", []):
        copy_path(
            format_path(copy_rule["from"], variables),
            format_path(copy_rule["to"], variables),
            overwrite=copy_rule.get("overwrite", True),
            dry_run=dry_run,
        )

    if not dry_run:
        try:
            check_required_paths(format_path_list(step.get("check_exists"), variables), step_name=step_name)
        except FileNotFoundError as exc:
            log_tail = read_log_tail(log_file)
            if log_tail:
                raise FileNotFoundError(f"{exc}\n\nLast log lines:\n{log_tail}") from exc
            raise


def wait_for_manual_check(
    message: str,
    variables: dict[str, str],
    dry_run: bool,
    *,
    require_interactive: bool = False,
) -> None:
    text = message.format(**variables)
    if dry_run:
        print(f"[manual-check] {text}")
        return
    try:
        input(f"{text}\nPress Enter to continue...")
    except EOFError:
        if require_interactive:
            raise RuntimeError("Incremental mode requires an interactive manual-check confirmation.")
        print(f"{text}\nNo interactive input available; continuing.")


def enabled_step_names(config: dict[str, Any]) -> list[str]:
    return [name for name, step in config["steps"].items() if step.get("enabled", True)]


def selected_step_names(
    config: dict[str, Any],
    *,
    from_step: str | None,
    to_step: str | None,
) -> set[str]:
    names = enabled_step_names(config)
    from_step = STEP_ALIASES.get(from_step, from_step)
    to_step = STEP_ALIASES.get(to_step, to_step)
    if from_step and from_step not in names:
        raise ValueError(f"Unknown --from-step '{from_step}'. Available steps: {', '.join(names)}")
    if to_step and to_step not in names:
        raise ValueError(f"Unknown --to-step '{to_step}'. Available steps: {', '.join(names)}")

    start = names.index(from_step) if from_step else 0
    end = names.index(to_step) if to_step else len(names) - 1
    if start > end:
        raise ValueError("--from-step must be before or equal to --to-step.")
    return set(names[start : end + 1])


def execute_case_pipeline(
    *,
    case: dict[str, Any],
    config: dict[str, Any],
    selected_steps: set[str],
    logs_root: Path,
    dry_run: bool,
    require_interactive_checks: bool = False,
    manual_workbook_dir: Path | None = None,
    on_step=None,
) -> None:
    """依次执行选中的步骤；on_step(name, status, error) 用于批次清单记录 running/succeeded/failed/skipped。"""
    if not dry_run:
        case["artifact_dir"].mkdir(parents=True, exist_ok=True)
        if case.get("work_dir"):
            Path(case["work_dir"]).mkdir(parents=True, exist_ok=True)
    case_log_dir = logs_root / case["case_name"]
    case_log_dir.mkdir(parents=True, exist_ok=True)

    variables = build_variables(case, config)
    repos = config["repos"]
    print(f"\n=== {case['case_name']} ===")
    for step_name, step in config["steps"].items():
        if not step.get("enabled", True):
            print(f"[{step_name}] skipped")
            continue
        if step_name not in selected_steps:
            print(f"[{step_name}] skipped by range")
            continue

        repo_key = step.get("repo")
        if not repo_key:
            raise KeyError(f"Step '{step_name}' is missing repo")

        repo_path = resolve_from_root(repos[repo_key])
        log_file = case_log_dir / f"{step_name}.log"
        if on_step:
            on_step(step_name, "running", None)
        try:
            run_configured_step(
                step_name=step_name,
                step=step,
                repo_path=repo_path,
                variables=variables,
                log_file=log_file,
                dry_run=dry_run,
            )
        except Exception as exc:
            if on_step:
                on_step(step_name, "failed", exc)
            raise
        if on_step:
            on_step(step_name, "succeeded", None)

        pause = step.get("pause_after")
        if pause:
            wait_for_manual_check(
                str(pause),
                variables,
                dry_run,
                require_interactive=require_interactive_checks,
            )



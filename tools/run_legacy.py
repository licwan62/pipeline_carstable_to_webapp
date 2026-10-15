"""旧手工输入（input/*.xlsx）的增量合并模式：隔离工作区运行完整流水线后整体替换 input/middle/public。

仅供 input.source 不是 all_cars_data 的旧流程使用；正式模式（all_cars_data 发布物）不经过这里，
也不依赖 compress_to_size_chart 外部仓库。从 run_all 导入这些名称仍然可用。
"""

from __future__ import annotations

import copy
import datetime as dt
import shutil
import sys
from pathlib import Path
from typing import Any

from tools.pipeline_core import (  # noqa: F401
    ROOT,
    configured_public_dir,
    enabled_step_names,
    execute_case_pipeline,
    resolve_from_root,
    run_step,
)
from tools.site_promote import mirror_directory  # noqa: F401

def select_project_data_dir(container: Path, case_name: str, markers: tuple[str, ...]) -> Path:
    """Select flat data layout, falling back to the legacy <case_name> layout."""
    nested = container / case_name
    if any((container / marker).exists() for marker in markers):
        return container
    if nested.is_dir() and any((nested / marker).exists() for marker in markers):
        return nested
    return container


def find_project_case(project_dir: Path, incremental_path: Path | None = None) -> dict[str, Any]:
    project_dir = resolve_from_root(project_dir)
    artifact_root = project_dir / "artifact"
    legacy_data_root = project_dir / "data"
    if (artifact_root / "input").is_dir():
        workspace_root = artifact_root
        public_root = project_dir / "public"
        legacy_layout = False
    else:
        workspace_root = legacy_data_root
        public_root = legacy_data_root / "output"
        legacy_layout = True
    input_dir = workspace_root / "input"
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Case directory has no artifact/input or legacy data/input: {project_dir}")

    candidates = sorted(
        path.resolve()
        for path in input_dir.glob("*.xlsx")
        if not path.name.startswith("~$")
        and (incremental_path is None or path.resolve() != incremental_path.resolve())
    )
    if not candidates:
        raise FileNotFoundError(f"Case directory has no base xlsx: {input_dir}")
    if len(candidates) > 1:
        names = ", ".join(path.stem for path in candidates)
        raise ValueError(f"Case directory contains multiple base xlsx files ({names}): {input_dir}")

    base_path = candidates[0]
    case_name = base_path.stem
    middle = select_project_data_dir(
        workspace_root / "middle",
        case_name,
        ("01_compress", "02_user_size_workbooks"),
    )
    if legacy_layout:
        output = select_project_data_dir(public_root, case_name, ("site",))
    else:
        output = public_root
    result = {
        "case_name": base_path.stem,
        "input_file": base_path,
        "project_dir": project_dir,
        "source_dirs": {
            "input": input_dir,
            "middle": middle,
            "output": output,
        },
    }
    if (project_dir / "manifest.json").is_file():
        result["source_backup_dir"] = project_dir
    return result


def workspace_fingerprint(
    paths: list[Path],
    *,
    ignored_roots: tuple[Path, ...] = (),
) -> tuple[tuple[str, int, int], ...]:
    ignored = tuple(path.resolve() for path in ignored_roots)
    records: list[tuple[str, int, int]] = []
    for root in paths:
        if not root.exists():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            resolved = path.resolve()
            if any(resolved == ignored_root or ignored_root in resolved.parents for ignored_root in ignored):
                continue
            stat = path.stat()
            records.append((str(resolved), stat.st_size, stat.st_mtime_ns))
    return tuple(records)


def replace_workspace_transactionally(
    *,
    current_dirs: dict[str, Path],
    staged_dirs: dict[str, Path],
    rollback_root: Path,
) -> None:
    """Promote a staged workspace without renaming the live root directories.

    Windows directory watchers (Explorer, WPS cloud, antivirus, etc.) can deny a
    rename of ``artifact/middle`` even when none of its files is open. Keep a local
    rollback copy and mirror each staged directory in place instead.
    """
    for name, staged in staged_dirs.items():
        if not staged.is_dir():
            raise FileNotFoundError(f"Staged workspace directory is missing: {staged}")

    rollback_root.mkdir(parents=True, exist_ok=False)
    existed_before = {name: path.exists() for name, path in current_dirs.items()}
    for name, current in current_dirs.items():
        if current.exists():
            shutil.copytree(current, rollback_root / name)

    try:
        for name, current in current_dirs.items():
            mirror_directory(staged_dirs[name], current)
    except Exception as promotion_error:
        try:
            for name, current in current_dirs.items():
                if existed_before[name]:
                    mirror_directory(rollback_root / name, current)
                elif current.exists():
                    shutil.rmtree(current)
        except Exception as rollback_error:
            raise RuntimeError(
                f"Workspace promotion failed ({promotion_error}); automatic rollback also failed "
                f"({rollback_error}). Recovery copy kept at: {rollback_root}"
            ) from promotion_error
        raise
    else:
        shutil.rmtree(rollback_root)


def run_incremental(
    *,
    config: dict[str, Any],
    incremental_path: Path,
    case_dir: Path,
    dry_run: bool,
    run_id: str,
) -> int:
    from backup import create_backup, verify_backup
    from tools.merge_incremental_compress_outputs import merge_compress_outputs
    from tools.merge_incremental_workbook import merge_workbooks

    incremental_path = resolve_from_root(incremental_path)
    if not incremental_path.is_file():
        raise FileNotFoundError(f"Incremental input not found: {incremental_path}")
    base_case = find_project_case(case_dir, incremental_path)
    base_path = Path(base_case["input_file"])
    if base_path == incremental_path:
        raise ValueError("Incremental input must be different from the base project workbook.")

    stage_root = resolve_from_root(Path("work/incremental") / f"{base_case['case_name']}_{run_id}")
    logs_root = resolve_from_root(Path(config["paths"]["logs_dir"]) / run_id)
    check_root = stage_root / "incremental_atom_check"
    print(f"Base project: {base_path}")
    print(f"Case directory: {base_case['project_dir']}")
    print(f"Source middle: {base_case['source_dirs']['middle']}")
    print(f"User size JSON: {base_case['source_dirs']['middle'] / '02_user_size.json'}")
    print(f"Incremental input: {incremental_path}")
    print(f"Isolated workspace: {stage_root}")
    if dry_run:
        print("[incremental] would atom-check increment, merge workbook, run full isolated pipeline, then promote workspace")
        return 0

    current_dirs = {
        "input": resolve_from_root(config["paths"]["input_dir"]),
        "middle": resolve_from_root(config["paths"]["middle_dir"]),
        "output": configured_public_dir(config["paths"]),
    }
    manual_workbook_dir = current_dirs["middle"] / "02_user_size_workbooks"
    fingerprint_ignored = (manual_workbook_dir,)
    initial_fingerprint = workspace_fingerprint(
        list(current_dirs.values()),
        ignored_roots=fingerprint_ignored,
    )
    stage_root.mkdir(parents=True, exist_ok=False)
    logs_root.mkdir(parents=True, exist_ok=True)

    try:
        source_backup_dir = base_case.get("source_backup_dir")
        if source_backup_dir:
            backup_errors = verify_backup(Path(source_backup_dir))
            if backup_errors:
                details = "\n".join(f"- {error}" for error in backup_errors[:20])
                raise ValueError(f"Base backup verification failed:\n{details}")

        profile = resolve_from_root("configs/pipeline.yaml")
        compress_repo = resolve_from_root(config["repos"]["compress"])
        increment_log_dir = logs_root / base_case["case_name"]
        increment_log_dir.mkdir(parents=True, exist_ok=True)
        run_step(
            step_name="incremental_atom_compress",
            repo_path=compress_repo,
            command=[
                sys.executable,
                "process_tsv.py",
                str(incremental_path),
                "--output-dir",
                str(check_root),
                "--field-profile",
                str(profile),
                "--check-atom",
                "--no-progress",
                "--no-xlsx",
            ],
            log_file=increment_log_dir / "incremental_atom_compress.log",
            dry_run=False,
        )
        run_step(
            step_name="incremental_atom_validate",
            repo_path=ROOT,
            command=[sys.executable, "tools/validate_atom_checks.py", "--root", str(check_root)],
            log_file=increment_log_dir / "incremental_atom_validate.log",
            dry_run=False,
        )

        staged_dirs = {
            "input": stage_root / "artifact" / "input",
            "middle": stage_root / "artifact" / "middle",
            "output": stage_root / "public",
        }
        source_dirs = base_case["source_dirs"]
        for name, current in current_dirs.items():
            source = Path(source_dirs[name])
            if source.is_dir():
                shutil.copytree(source, staged_dirs[name])
            else:
                staged_dirs[name].mkdir(parents=True)

        try:
            relative_increment = incremental_path.relative_to(current_dirs["input"])
        except ValueError:
            relative_increment = None
        if relative_increment is not None:
            copied_increment = staged_dirs["input"] / relative_increment
            if copied_increment.exists() and copied_increment.resolve() != (staged_dirs["input"] / base_path.name).resolve():
                copied_increment.unlink()

        merged_path = staged_dirs["input"] / base_path.name
        input_sheets = tuple(str(sheet) for sheet in config.get("input", {}).get("sheets", []))
        if not input_sheets:
            raise ValueError("pipeline config must define input.sheets")
        summary = merge_workbooks(base_path, incremental_path, merged_path, sheet_names=input_sheets)
        for sheet_name, counts in summary.items():
            print(f"[merge] {sheet_name}: added={counts['appended']} duplicate={counts['duplicates']}")

        compress_merge_summary = merge_compress_outputs(
            staged_dirs["middle"] / "01_compress", check_root, datasets=input_sheets
        )
        for dataset, tables in compress_merge_summary.items():
            atom_counts = tables["原子事实表.tsv"]
            print(
                f"[compress-merge] {dataset}: "
                f"atoms {atom_counts[0]}+{atom_counts[1]}->{atom_counts[2]}"
            )

        staged_config = copy.deepcopy(config)
        staged_config["paths"]["input_dir"] = str(staged_dirs["input"])
        staged_config["paths"]["middle_dir"] = str(staged_dirs["middle"])
        staged_config["paths"]["public_dir"] = str(staged_dirs["output"])
        staged_config["paths"].pop("output_dir", None)
        staged_config["steps"]["compress"]["enabled"] = False
        staged_config["steps"]["atom_validate"]["enabled"] = True
        staged_config["steps"]["atom_validate"]["command"] = [
            sys.executable,
            "tools/validate_incremental_atom_scope.py",
            "--incremental-root",
            str(check_root),
            "--full-root",
            "{compress_output_root}",
            "--compress-repo",
            str(compress_repo),
        ]
        for input_sheet in input_sheets:
            staged_config["steps"]["atom_validate"]["command"].extend(["--dataset", input_sheet])
        staged_case = {
            "case_name": base_case["case_name"],
            "input_file": merged_path,
            "case_middle": staged_dirs["middle"],
            "case_public": staged_dirs["output"],
        }
        execute_case_pipeline(
            case=staged_case,
            config=staged_config,
            selected_steps=set(enabled_step_names(staged_config)),
            logs_root=logs_root,
            dry_run=False,
            require_interactive_checks=True,
            manual_workbook_dir=manual_workbook_dir,
        )

        if workspace_fingerprint(
            list(current_dirs.values()),
            ignored_roots=fingerprint_ignored,
        ) != initial_fingerprint:
            raise RuntimeError("Current workspace changed during incremental run; staged result was not promoted.")

        backup_name = (
            f"{base_case['case_name']}_pre_incremental_"
            + dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        )
        safety_backup = create_backup(ROOT, backup_name)
        replace_workspace_transactionally(
            current_dirs=current_dirs,
            staged_dirs=staged_dirs,
            rollback_root=stage_root / "rollback",
        )
        shutil.rmtree(stage_root)
        print(f"Incremental update promoted. Safety backup: {safety_backup}")
        return 0
    except Exception:
        print(f"Incremental update failed; current workspace is unchanged. Staging kept at: {stage_root}")
        raise



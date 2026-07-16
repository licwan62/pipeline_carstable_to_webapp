from __future__ import annotations

import argparse
import copy
import datetime as dt
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).parent.resolve()
ERROR_LOG_TAIL_LINES = 40


def rename_with_retry(source: Path, target: Path, attempts: int = 20) -> None:
    for attempt in range(attempts):
        try:
            source.rename(target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.1)


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


def resolve_from_root(path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path.resolve()
    return (ROOT / path).resolve()


def scan_cases(config: dict[str, Any], only_case: str | None = None) -> list[dict[str, Any]]:
    paths = config["paths"]
    file_rules = config.get("file_rules", {})
    input_dir = resolve_from_root(paths["input_dir"])
    pattern = file_rules.get("input_pattern", "*.xlsx")

    cases: list[dict[str, Any]] = []
    for input_file in sorted(input_dir.glob(pattern)):
        if input_file.name.startswith("~$"):
            continue

        case_name = input_file.stem
        if only_case and case_name != only_case:
            continue

        cases.append(
            {
                "case_name": case_name,
                "input_file": input_file.resolve(),
                "case_middle": resolve_from_root(paths["middle_dir"]),
                "case_output": resolve_from_root(paths["output_dir"]),
            }
        )

    return cases


def build_variables(case: dict[str, Any], config: dict[str, Any]) -> dict[str, str]:
    paths = config["paths"]
    variables = {
        "root": str(ROOT),
        "case_name": str(case["case_name"]),
        "input_file": str(case["input_file"]),
        "case_middle": str(case["case_middle"]),
        "case_output": str(case["case_output"]),
        "input_dir": str(resolve_from_root(paths["input_dir"])),
        "middle_dir": str(resolve_from_root(paths["middle_dir"])),
        "output_dir": str(resolve_from_root(paths["output_dir"])),
        "logs_dir": str(resolve_from_root(paths["logs_dir"])),
        "python": sys.executable,
    }

    for key, value in config.get("variables", {}).items():
        formatted = str(value).format(**variables)
        if "/" in formatted or "\\" in formatted:
            formatted = str(Path(formatted))
        variables[key] = formatted

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
            encoding="utf-8",
            errors="replace",
        )

        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            log.write(line)
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
) -> None:
    case["case_middle"].mkdir(parents=True, exist_ok=True)
    case["case_output"].mkdir(parents=True, exist_ok=True)
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
        run_configured_step(
            step_name=step_name,
            step=step,
            repo_path=repo_path,
            variables=variables,
            log_file=log_file,
            dry_run=dry_run,
        )

        pause = step.get("pause_after")
        if pause:
            pause_variables = variables
            staged_workbook_dir: Path | None = None
            if step_name == "user_size_template" and manual_workbook_dir is not None:
                staged_workbook_dir = Path(variables["user_size_dir"])
                print(f"[manual-workbooks] {staged_workbook_dir} -> {manual_workbook_dir}")
                if not dry_run:
                    manual_workbook_dir.mkdir(parents=True, exist_ok=True)
                    for workbook in staged_workbook_dir.glob("*.xlsx"):
                        shutil.copy2(workbook, manual_workbook_dir / workbook.name)
                pause_variables = dict(variables)
                pause_variables["user_size_dir"] = str(manual_workbook_dir)
            wait_for_manual_check(
                str(pause),
                pause_variables,
                dry_run,
                require_interactive=require_interactive_checks,
            )
            if staged_workbook_dir is not None and not dry_run:
                expected = [manual_workbook_dir / f"{store}_用户尺码模板.xlsx" for store in ("ALL", "TM", "HNT")]
                missing = [path for path in expected if not path.is_file()]
                if missing:
                    missing_text = "\n".join(f"- {path}" for path in missing)
                    raise FileNotFoundError(f"人工确认目录缺少工作簿:\n{missing_text}")
                for workbook in expected:
                    shutil.copy2(workbook, staged_workbook_dir / workbook.name)
                print(f"[manual-workbooks] saved changes synced back to {staged_workbook_dir}")


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
    data_root = project_dir / "data"
    input_dir = data_root / "input"
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Case directory has no data/input: {project_dir}")

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
        data_root / "middle",
        case_name,
        ("01_compress", "02_user_size_workbooks"),
    )
    output = select_project_data_dir(data_root / "output", case_name, ("site",))
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
    rename of ``data/middle`` even when none of its files is open.  Keep a local
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


def mirror_directory(source: Path, target: Path) -> None:
    """Make target match source while keeping target's root directory in place."""
    target.mkdir(parents=True, exist_ok=True)
    source_items = {path.relative_to(source): path for path in source.rglob("*")}

    for relative, path in sorted(source_items.items(), key=lambda item: len(item[0].parts)):
        destination = target / relative
        if path.is_dir():
            if destination.exists() and not destination.is_dir():
                destination.unlink()
            destination.mkdir(parents=True, exist_ok=True)

    for relative, path in source_items.items():
        if not path.is_file():
            continue
        destination = target / relative
        if destination.exists() and destination.is_dir():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)

    for path in sorted(target.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.relative_to(target) in source_items:
            continue
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink()


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
    print(f"User size workbooks: {base_case['source_dirs']['middle'] / '02_user_size_workbooks'}")
    print(f"Incremental input: {incremental_path}")
    print(f"Isolated workspace: {stage_root}")
    if dry_run:
        print("[incremental] would atom-check increment, merge workbook, run full isolated pipeline, then promote workspace")
        return 0

    current_dirs = {
        "input": resolve_from_root(config["paths"]["input_dir"]),
        "middle": resolve_from_root(config["paths"]["middle_dir"]),
        "output": resolve_from_root(config["paths"]["output_dir"]),
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

        profile = resolve_from_root(
            config.get("incremental", {}).get("field_profile", "configs/compress-field-profile.yaml")
        )
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

        staged_dirs = {name: stage_root / "data" / name for name in current_dirs}
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
        summary = merge_workbooks(base_path, incremental_path, merged_path)
        for sheet_name, counts in summary.items():
            print(f"[merge] {sheet_name}: added={counts['appended']} duplicate={counts['duplicates']}")

        compress_merge_summary = merge_compress_outputs(staged_dirs["middle"] / "01_compress", check_root)
        for dataset, tables in compress_merge_summary.items():
            atom_counts = tables["原子事实表.tsv"]
            print(
                f"[compress-merge] {dataset}: "
                f"atoms {atom_counts[0]}+{atom_counts[1]}->{atom_counts[2]}"
            )

        staged_config = copy.deepcopy(config)
        staged_config["paths"]["input_dir"] = str(staged_dirs["input"])
        staged_config["paths"]["middle_dir"] = str(staged_dirs["middle"])
        staged_config["paths"]["output_dir"] = str(staged_dirs["output"])
        staged_config["steps"]["compress"]["enabled"] = False
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
        template_command = staged_config["steps"].get("user_size_template", {}).get("command", [])
        if "--sync-existing" not in template_command:
            template_command.append("--sync-existing")

        staged_case = {
            "case_name": base_case["case_name"],
            "input_file": merged_path,
            "case_middle": staged_dirs["middle"],
            "case_output": staged_dirs["output"],
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fitment pipeline for xlsx files.")
    parser.add_argument("--config", default="configs/pipeline.yaml", help="Path to pipeline config yaml.")
    parser.add_argument(
        "--case",
        type=Path,
        default=Path("."),
        help=r"Project directory containing data/, e.g. . or bak\20260716_111604.",
    )
    parser.add_argument(
        "--incremental",
        type=Path,
        help="New-vehicle xlsx to atom-check and merge into the selected --case directory.",
    )
    parser.add_argument("--from-step", help="Resume from this configured step, e.g. user_size_validate.")
    parser.add_argument("--to-step", help="Stop after this configured step.")
    parser.add_argument("--list-steps", action="store_true", help="Print enabled step names and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    args = parser.parse_args()

    config = load_config(resolve_from_root(args.config))
    if args.list_steps:
        print("\n".join(enabled_step_names(config)))
        return 0

    run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.incremental:
        if args.from_step or args.to_step:
            parser.error("--incremental always runs the complete isolated pipeline; step ranges are not supported.")
        try:
            return run_incremental(
                config=config,
                incremental_path=args.incremental,
                case_dir=args.case,
                dry_run=args.dry_run,
                run_id=run_id,
            )
        except Exception as exc:
            print(f"FAILED: {exc}")
            return 1
    if resolve_from_root(args.case) != ROOT:
        parser.error("A non-workspace --case directory is only valid together with --incremental.")

    selected_steps = selected_step_names(config, from_step=args.from_step, to_step=args.to_step)
    cases = scan_cases(config)

    if not cases:
        print("No input xlsx files found.")
        return 0
    if len(cases) > 1:
        names = ", ".join(case["case_name"] for case in cases)
        print(f"Workspace mode only supports one project at a time. Found: {names}")
        print("Keep one xlsx in data/input.")
        return 2

    logs_root = resolve_from_root(Path(config["paths"]["logs_dir"]) / run_id)
    logs_root.mkdir(parents=True, exist_ok=True)

    stop_on_error = config.get("run", {}).get("stop_on_error", True)

    print(f"Found {len(cases)} case(s): {', '.join(case['case_name'] for case in cases)}")
    print(f"Logs: {logs_root}")

    failures: list[str] = []
    for case in cases:
        try:
            execute_case_pipeline(
                case=case,
                config=config,
                selected_steps=selected_steps,
                logs_root=logs_root,
                dry_run=args.dry_run,
                require_interactive_checks=False,
            )
        except Exception as exc:
            failures.append(f"{case['case_name']}: {exc}")
            print(f"FAILED: {failures[-1]}")
            if stop_on_error:
                break

    if failures:
        print("\nFailures:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nAll cases completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

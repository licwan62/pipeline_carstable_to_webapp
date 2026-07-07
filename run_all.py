from __future__ import annotations

import argparse
import datetime as dt
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).parent.resolve()
ERROR_LOG_TAIL_LINES = 40


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}


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
                "case_middle": resolve_from_root(Path(paths["middle_dir"]) / case_name),
                "case_output": resolve_from_root(Path(paths["output_dir"]) / case_name),
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


def wait_for_manual_check(message: str, variables: dict[str, str], dry_run: bool) -> None:
    text = message.format(**variables)
    if dry_run:
        print(f"[manual-check] {text}")
        return
    try:
        input(f"{text}\nPress Enter to continue...")
    except EOFError:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fitment pipeline for xlsx files.")
    parser.add_argument("--config", default="configs/pipeline.yaml", help="Path to pipeline config yaml.")
    parser.add_argument("--case", help="Run only one case by input file stem, e.g. nike.")
    parser.add_argument("--from-step", help="Resume from this configured step, e.g. user_size_validate.")
    parser.add_argument("--to-step", help="Stop after this configured step.")
    parser.add_argument("--list-steps", action="store_true", help="Print enabled step names and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    args = parser.parse_args()

    config = load_config(resolve_from_root(args.config))
    if args.list_steps:
        print("\n".join(enabled_step_names(config)))
        return 0

    selected_steps = selected_step_names(config, from_step=args.from_step, to_step=args.to_step)
    cases = scan_cases(config, only_case=args.case)

    if not cases:
        print("No input xlsx files found.")
        return 0

    run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    logs_root = resolve_from_root(Path(config["paths"]["logs_dir"]) / run_id)
    logs_root.mkdir(parents=True, exist_ok=True)

    repos = config["repos"]
    stop_on_error = config.get("run", {}).get("stop_on_error", True)

    print(f"Found {len(cases)} case(s): {', '.join(case['case_name'] for case in cases)}")
    print(f"Logs: {logs_root}")

    failures: list[str] = []
    for case in cases:
        case["case_middle"].mkdir(parents=True, exist_ok=True)
        case["case_output"].mkdir(parents=True, exist_ok=True)
        case_log_dir = logs_root / case["case_name"]
        case_log_dir.mkdir(parents=True, exist_ok=True)

        variables = build_variables(case, config)
        print(f"\n=== {case['case_name']} ===")

        try:
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
                    dry_run=args.dry_run,
                )

                pause = step.get("pause_after")
                if pause:
                    wait_for_manual_check(str(pause), variables, args.dry_run)

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

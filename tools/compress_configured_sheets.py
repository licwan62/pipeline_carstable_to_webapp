from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


def expected_output(root: Path, case_name: str, sheet: str) -> Path:
    stem = f"{case_name}_{sheet}"
    return root / stem / "compress" / f"{stem}_非皮卡高度压缩表.tsv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compress only configured sheets whose outputs are missing.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--compress-script", type=Path, required=True)
    parser.add_argument("--force", action="store_true", help="Recompress every configured sheet.")
    parser.add_argument("--sheet", action="append", help="Only process this configured sheet (repeatable).")
    parser.add_argument("--dry-run", action="store_true", help="Print selected sheets without running compression.")
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    sheets = [str(sheet) for sheet in config.get("input", {}).get("sheets", [])]
    if not sheets:
        raise ValueError(f"No input.sheets configured in {args.config}")
    if args.sheet:
        unknown = [sheet for sheet in args.sheet if sheet not in sheets]
        if unknown:
            raise ValueError(f"Unknown configured sheets: {unknown}")
        sheets = args.sheet
    missing = sheets if args.force else [
        sheet for sheet in sheets
        if not expected_output(args.output_root, args.input.stem, sheet).is_file()
    ]
    reused = [sheet for sheet in sheets if sheet not in missing]
    for sheet in reused:
        print(f"[reuse] {sheet}")
    if not missing:
        print("All configured sheet outputs already exist; compression skipped.")
        return
    print(f"[compress-new] {', '.join(missing)}")
    if args.dry_run:
        return

    profile = {
        "input": {"sheets": missing},
        "columns": config.get("columns", {}),
        "defaults": config.get("defaults", {}),
    }
    with tempfile.TemporaryDirectory(prefix="compress-profile-") as temporary_dir:
        profile_path = Path(temporary_dir) / "profile.yaml"
        profile_path.write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")
        command = [
            sys.executable,
            str(args.compress_script),
            str(args.input),
            "--output-dir",
            str(args.output_root),
            "--field-profile",
            str(profile_path),
            "--check-atom",
        ]
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()

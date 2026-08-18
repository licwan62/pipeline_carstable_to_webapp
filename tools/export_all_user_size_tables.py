from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


STORES = ["ALL", "TM", "HNT"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export all stores from one user-size workbook to TSV tables.")
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    script = Path(__file__).with_name("export_user_size_tables.py")
    for store in STORES:
        output_dir = args.output_root / store
        command = [
            sys.executable,
            str(script),
            "--workbook",
            str(args.workbook),
            "--output-dir",
            str(output_dir),
            "--store",
            store,
        ]
        print(f"[{store}] {' '.join(command)}")
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()

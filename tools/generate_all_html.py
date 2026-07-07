from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


STORES = ["ALL", "TM", "HNT"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate ALL/TM/HNT HTML outputs from exported TSV tables.")
    parser.add_argument("--export-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--config-path", type=Path, required=True)
    parser.add_argument("--html-script", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for store in STORES:
        store_output = args.output_root / store
        if store_output.exists():
            shutil.rmtree(store_output)

        non_pickup_command = [
            sys.executable,
            str(args.html_script),
            "--non-pickup-input",
            str(args.export_root / store / "non_pickup.tsv"),
            "--order",
            "non-pickup",
            "--config-path",
            str(args.config_path),
            "--output",
            str(store_output / "nonpick" / "output.html"),
        ]
        print(f"[{store}/nonpick] {' '.join(non_pickup_command)}")
        subprocess.run(non_pickup_command, check=True)

        pickup_command = [
            sys.executable,
            str(args.html_script),
            "--pickup-input",
            str(args.export_root / store / "pickup.tsv"),
            "--order",
            "pickup",
            "--config-path",
            str(args.config_path),
            "--output",
            str(store_output / "pick" / "output.html"),
        ]
        print(f"[{store}/pick] {' '.join(pickup_command)}")
        subprocess.run(pickup_command, check=True)


if __name__ == "__main__":
    main()

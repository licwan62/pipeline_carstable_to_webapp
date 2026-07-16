from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


STORES = ["ALL", "TM", "HNT"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate ALL/TM/HNT HTML outputs from exported TSV tables.")
    parser.add_argument("--export-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--config-path", type=Path, required=True)
    parser.add_argument("--html-script", type=Path, required=True)
    return parser.parse_args()


def deep_merge(base: dict, overrides: dict) -> dict:
    result = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_profile(path: Path, loading: tuple[Path, ...] = ()) -> dict:
    path = path.resolve()
    if path in loading:
        raise ValueError(f"HTML config has a circular extends chain: {path}")
    profile = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    parent = profile.pop("extends", None)
    if not parent:
        return profile
    return deep_merge(load_profile(path.parent / parent, (*loading, path)), profile)


def generate_all(args: argparse.Namespace, config_path: Path) -> None:
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
            str(config_path),
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
            str(config_path),
            "--output",
            str(store_output / "pick" / "output.html"),
        ]
        print(f"[{store}/pick] {' '.join(pickup_command)}")
        subprocess.run(pickup_command, check=True)


def main() -> None:
    args = parse_args()
    profile = load_profile(args.config_path)
    with tempfile.TemporaryDirectory(prefix="html-config-") as temporary_dir:
        materialized = Path(temporary_dir) / "preference.yaml"
        materialized.write_text(
            yaml.safe_dump(profile, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        generate_all(args, materialized)


if __name__ == "__main__":
    main()

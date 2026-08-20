from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

SIZE_FREE_STORES = {"TM-拆分"}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate ALL/TM/HNT HTML outputs from exported TSV tables.")
    parser.add_argument("--export-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--config-path", type=Path, required=True)
    parser.add_argument("--html-script", type=Path, required=True)
    parser.add_argument("--store", action="append", help="Only generate this store (repeatable).")
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


def has_data_rows(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        next(reader, None)
        return next(reader, None) is not None


def add_generator_size_columns(source: Path, target: Path) -> Path:
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
        columns = list(reader.fieldnames or [])
    columns.extend(column for column in ("BACKSIZE", "SIZE") if column not in columns)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    return target


def generate_all(args: argparse.Namespace, config_path: Path) -> None:
    stores = sorted(path.name for path in args.export_root.iterdir() if path.is_dir())
    if args.store:
        stores = [store for store in stores if store in set(args.store)]
    if not stores:
        raise FileNotFoundError(f"No store export directories found: {args.export_root}")
    for store in stores:
        store_output = args.output_root / store
        if store_output.exists():
            shutil.rmtree(store_output)

        non_pickup_input = args.export_root / store / "non_pickup.tsv"
        pickup_input = args.export_root / store / "pickup.tsv"
        store_config = config_path
        extra_non_args: list[str] = []
        extra_pick_args: list[str] = []
        if store in SIZE_FREE_STORES:
            temporary_root = config_path.parent
            non_pickup_input = add_generator_size_columns(non_pickup_input, temporary_root / f"{store}-non-pickup.tsv")
            pickup_input = add_generator_size_columns(pickup_input, temporary_root / f"{store}-pickup.tsv")
            special_profile = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            special_profile["exclude_rows"] = "BACKSIZE=无可用尺码"
            store_config = temporary_root / f"{store}-preference.yaml"
            store_config.write_text(yaml.safe_dump(special_profile, allow_unicode=True, sort_keys=False), encoding="utf-8")
            extra_non_args = ["--table-columns", "MODEL,YEAR,TYPE"]
            extra_pick_args = ["--table-columns", "YEAR,CAB,BED"]
        non_pickup_command = [
            sys.executable,
            str(args.html_script),
            "--non-pickup-input",
            str(non_pickup_input),
            "--order",
            "non-pickup",
            "--config-path",
            str(store_config),
            "--output",
            str(store_output / "nonpick" / "output.html"),
            *extra_non_args,
        ]
        if has_data_rows(non_pickup_input):
            print(f"[{store}/nonpick] {' '.join(non_pickup_command)}")
            subprocess.run(non_pickup_command, check=True)
        else:
            print(f"[{store}/nonpick] skipped: no publishable rows")

        pickup_command = [
            sys.executable,
            str(args.html_script),
            "--pickup-input",
            str(pickup_input),
            "--order",
            "pickup",
            "--config-path",
            str(store_config),
            "--output",
            str(store_output / "pick" / "output.html"),
            *extra_pick_args,
        ]
        if has_data_rows(pickup_input):
            print(f"[{store}/pick] {' '.join(pickup_command)}")
            subprocess.run(pickup_command, check=True)
        else:
            print(f"[{store}/pick] skipped: no publishable rows")


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

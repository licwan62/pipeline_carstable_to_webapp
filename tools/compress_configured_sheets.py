from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


def load_config(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if path.suffix.casefold() == ".json" else (yaml.safe_load(text) or {})


def expected_output(root: Path, store_name: str) -> Path:
    stem = store_name
    return root / stem / "compress" / f"{stem}_非皮卡高度压缩表.csv"


def csv_to_tsv(source: Path, target: Path) -> None:
    with source.open("r", encoding="utf-8-sig", newline="") as input_file:
        with target.open("w", encoding="utf-8-sig", newline="") as output_file:
            csv.writer(output_file, delimiter="\t").writerows(csv.reader(input_file))


def tsv_to_csv(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("r", encoding="utf-8-sig", newline="") as input_file:
        with target.open("w", encoding="utf-8-sig", newline="") as output_file:
            csv.writer(output_file).writerows(csv.reader(input_file, delimiter="\t"))


def publish_csv_outputs(temporary_output: Path, output_root: Path) -> None:
    for source in temporary_output.rglob("*.tsv"):
        relative = source.relative_to(temporary_output).with_suffix(".csv")
        tsv_to_csv(source, output_root / relative)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compress normalized CSV sources and retain only CSV/JSON artifacts."
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--compress-script", type=Path, required=True)
    parser.add_argument("--force", action="store_true", help="Recompress every configured source.")
    parser.add_argument("--store", action="append", help="Only process this store (repeatable).")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    stores = list((config.get("input") or {}).get("stores") or [])
    if not stores:
        raise ValueError(f"No input.stores configured in {args.config}")
    if args.store:
        selected = set(args.store)
        unknown = selected - {str(store.get("store")) for store in stores}
        if unknown:
            raise ValueError(f"Unknown configured stores: {sorted(unknown)}")
        stores = [store for store in stores if str(store.get("store")) in selected]

    for store in stores:
        store_name = str(store["store"])
        sheet = str(store["sheet"])
        output = expected_output(args.output_root, store_name)
        if output.is_file() and not args.force:
            print(f"[reuse] {store_name}")
            continue
        csv_path = (args.config.parent / str(store["path"])).resolve()
        if not csv_path.is_file():
            raise FileNotFoundError(f"Normalized input CSV does not exist: {csv_path}")
        print(f"[compress-new] {store_name}: {csv_path}")
        if args.dry_run:
            continue

        stem = store_name
        profile = {"columns": config.get("columns", {}), "defaults": config.get("defaults", {})}
        with tempfile.TemporaryDirectory(prefix="compress-csv-") as temporary_dir:
            temporary_root = Path(temporary_dir)
            input_tsv = temporary_root / f"{stem}.tsv"
            output_dir = temporary_root / "output"
            profile_path = temporary_root / "profile.yaml"
            csv_to_tsv(csv_path, input_tsv)
            profile_path.write_text(
                yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            subprocess.run(
                [
                    sys.executable,
                    str(args.compress_script),
                    str(input_tsv),
                    "--output-dir",
                    str(output_dir),
                    "--field-profile",
                    str(profile_path),
                    "--check-atom",
                ],
                check=True,
            )
            destination = args.output_root / stem
            if destination.exists():
                shutil.rmtree(destination)
            publish_csv_outputs(output_dir, args.output_root)


if __name__ == "__main__":
    main()

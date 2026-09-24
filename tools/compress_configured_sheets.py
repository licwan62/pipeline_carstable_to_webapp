from __future__ import annotations

import argparse
import csv
import hashlib
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


FINGERPRINT_NAME = "compress-input.sha256"


def input_fingerprint(csv_path: Path, profile: dict) -> str:
    """输入 CSV 内容 + 字段配置；两者都不变时压缩结果可复用。"""
    digest = hashlib.sha256(csv_path.read_bytes())
    digest.update(json.dumps(profile, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def batch_fingerprint(batch: Path, candidate: Path, store: dict) -> str | None:
    """批次已记录的指纹；老批次没有指纹文件时，用其 00_input 快照回算。"""
    marker = candidate / FINGERPRINT_NAME
    if marker.is_file():
        return marker.read_text(encoding="utf-8").strip()
    snapshot, config_file = batch / "00_input" / str(store["path"]), batch / "00_input" / "pipeline.generated.json"
    if not (snapshot.is_file() and config_file.is_file()):
        return None
    old = load_config(config_file)
    return input_fingerprint(snapshot, {"columns": old.get("columns", {}), "defaults": old.get("defaults", {})})


def find_history(output_root: Path, store: dict, fingerprint: str) -> Path | None:
    """在同级历史批次中找同店铺、同指纹且压缩成功的产物目录（新批次优先）。"""
    store_name = str(store["store"])
    for batch in sorted(output_root.parent.parent.iterdir(), reverse=True):
        candidate = batch / output_root.name / store_name
        if candidate == output_root / store_name or not expected_output(batch / output_root.name, store_name).is_file():
            continue
        if batch_fingerprint(batch, candidate, store) == fingerprint:
            return candidate
    return None


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
        stem = store_name
        profile = {"columns": config.get("columns", {}), "defaults": config.get("defaults", {})}
        fingerprint = input_fingerprint(csv_path, profile)
        history = None if args.force else find_history(args.output_root, store, fingerprint)
        if history:
            print(f"[reuse-history] {store_name}: {history}")
            if not args.dry_run:
                shutil.copytree(history, args.output_root / stem, dirs_exist_ok=True)
            continue
        print(f"[compress-new] {store_name}: {csv_path}")
        if args.dry_run:
            continue

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
            (destination / FINGERPRINT_NAME).write_text(fingerprint, encoding="utf-8")


if __name__ == "__main__":
    main()

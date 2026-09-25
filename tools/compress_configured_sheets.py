from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
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


_PRINT_LOCK = threading.Lock()


def locked_print(text: str) -> None:
    with _PRINT_LOCK:
        print(text, flush=True)


def compress_store(
    store_name: str,
    csv_path: Path,
    profile: dict,
    fingerprint: str,
    output_root: Path,
    compress_script: Path,
) -> None:
    """在临时目录压缩单个店铺，逐行转出带店铺前缀的子进程输出，成功后发布 CSV。"""
    with tempfile.TemporaryDirectory(prefix="compress-csv-") as temporary_dir:
        temporary_root = Path(temporary_dir)
        input_tsv = temporary_root / f"{store_name}.tsv"
        output_dir = temporary_root / "output"
        profile_path = temporary_root / "profile.yaml"
        csv_to_tsv(csv_path, input_tsv)
        profile_path.write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")
        command = [
            sys.executable,
            str(compress_script),
            str(input_tsv),
            "--output-dir",
            str(output_dir),
            "--field-profile",
            str(profile_path),
            "--check-atom",
            "--no-xlsx",
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
        )
        assert process.stdout is not None
        for line in process.stdout:
            locked_print(f"[{store_name}] {line.rstrip()}")
        if process.wait() != 0:
            raise subprocess.CalledProcessError(process.returncode, command)
        destination = output_root / store_name
        if destination.exists():
            shutil.rmtree(destination)
        publish_csv_outputs(output_dir, output_root)
        (destination / FINGERPRINT_NAME).write_text(fingerprint, encoding="utf-8")


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
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        help="Stores compressed in parallel; 0 (default) = one per store, capped at CPU count.",
    )
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # 子进程输出含本地编码无法表示的字符时不中断

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

    jobs: list[tuple[str, Path, dict, str]] = []
    for store in stores:
        store_name = str(store["store"])
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
        locked_print(f"[compress-new] {store_name}: {csv_path}")
        if not args.dry_run:
            jobs.append((stem, csv_path, profile, fingerprint))

    if not jobs:
        return
    workers = args.jobs if args.jobs > 0 else min(len(jobs), os.cpu_count() or 1)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(compress_store, *job, args.output_root, args.compress_script) for job in jobs
        ]
        errors = [future.exception() for future in futures]
    failed = [(job[0], error) for job, error in zip(jobs, errors) if error is not None]
    if failed:
        for store_name, error in failed:
            locked_print(f"[compress-failed] {store_name}: {error}")
        raise failed[0][1]


if __name__ == "__main__":
    main()

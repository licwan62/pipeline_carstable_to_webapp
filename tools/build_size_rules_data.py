#!/usr/bin/env python3
"""把上游 A0.尺码计算/output 发布的尺码规则和店铺货架转成网站参考页数据。

读取 manifest.json 校验 sha256 后，写出：
  size-rules.json   {source, regions: {US/EU/RU: {headers, rows}}}
  store-groups.json {source, stores: {店铺: [{匹配尺码, 发货尺码}]}}
US/EU/RU 三套规则各自独立读取，不互相推导。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path

DEFAULT_SOURCE = Path(__file__).resolve().parents[2] / "all_cars_data" / "A0.尺码计算" / "output"
REGION_FILES = {"US": "尺码匹配规则.csv", "EU": "尺码匹配规则_EU.csv", "RU": "尺码匹配规则_RU.csv"}
SHELF_FILE = "店铺货架.csv"


def read_verified_csv(source_dir: Path, manifest: dict, name: str) -> tuple[list[str], list[dict[str, str]]]:
    expected = next((item["sha256"] for item in manifest["deliverables"] if item["file"] == name), None)
    path = source_dir / name
    if expected is None or not path.is_file():
        raise ValueError(f"上游发布源缺少 {name}")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"{name} 与 manifest.json 的 sha256 不一致，请重新发布上游")
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    rows = [row for row in rows if any(row.values())]
    return list(reader.fieldnames or []), rows


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


def build(source_dir: Path, out_dir: Path) -> dict[str, int]:
    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    source = {"node": manifest["node"], "version": manifest["version"], "published_at": manifest["published_at"]}
    regions = {}
    for region, name in REGION_FILES.items():
        headers, rows = read_verified_csv(source_dir, manifest, name)
        if not rows:
            raise ValueError(f"{name} 没有规则行")
        regions[region] = {"file": name, "headers": headers, "rows": rows}
    _, shelf = read_verified_csv(source_dir, manifest, SHELF_FILE)
    stores: dict[str, list[dict[str, str]]] = {}
    for row in shelf:
        stores.setdefault(row["店铺"], []).append({"匹配尺码": row["匹配尺码"], "发货尺码": row["发货尺码"]})
    if not stores:
        raise ValueError(f"{SHELF_FILE} 没有店铺")
    write_json(out_dir / "size-rules.json", {"source": source, "regions": regions})
    write_json(out_dir / "store-groups.json", {"source": source, "stores": stores})
    return {**{region: len(item["rows"]) for region, item in regions.items()}, "stores": len(stores)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parents[1] / "public" / "data" / "generated")
    args = parser.parse_args()
    print(json.dumps(build(args.source_dir, args.out_dir), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

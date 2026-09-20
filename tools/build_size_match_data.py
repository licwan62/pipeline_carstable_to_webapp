#!/usr/bin/env python3
"""用上游 A1.全量汇总/output/全量表_汇总.csv 生成尺码配对页的 US / EU 数据源。

校验 A1 manifest 的 sha256 后，按 DIMENSION-ID 末尾的区域拆分，各区域按 MAKE 分片写入
public/data/generated/size-match-full-<区域>-NN-<make>.json，并写入清单 size-match-full.json。
尺码配对页默认只加载 US，在侧栏大纲切换 EU 时才读取 EU 分片。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent / "all_cars_data" / "A1.全量汇总" / "output"
STORE_SOURCE = ROOT.parent / "all_cars_data" / "A0.尺码计算" / "output"
REGIONS = ("US", "EU", "RU")
# US 源下的店铺选择：名称 -> A0 店铺全量文件（自动尺码为该店铺的发货尺码）
STORES = {"HNT": "店铺全量_HNT.csv", "TM": "店铺全量_TM.csv", "TM_拆分": "店铺全量_TM_拆分.csv"}
NAME = "全量表_汇总.csv"
COLUMNS = ["CODE", "MODEL", "版本", "YEAR", "TYPE", "CAB", "BED", "销量合计", "L-MM", "W-MM", "H-MM", "长度余量", "SIZE"]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


def parse_years(text: str) -> list[int]:
    numbers = [int(part) for part in re.findall(r"\d{4}", text)]
    if len(numbers) == 1:
        return numbers
    return list(range(numbers[0], numbers[-1] + 1)) if numbers else []


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "other"


def to_record(row: dict[str, str], region: str) -> dict:
    values = dict(row)
    values["长度余量"] = row.get("自动长度余量", "")
    values["CONST"] = row.get("结构", "")
    values["TYPE"] = row.get("结构", "")
    values["SIZE"] = row.get("自动尺码", "")
    values["SOURCE"] = region
    values["CODE"] = row.get("DIMENSION-CODE", "")  # 来自 02.代码映射，经 A0 写入全量表
    return {
        "make": row["MAKE"], "model": row["MODEL"], "year": row["YEAR"], "years": parse_years(row["YEAR"]),
        "construct": row.get("结构", ""), "cab": row.get("CAB", ""), "bed": row.get("BED", ""),
        "type": row.get("结构", ""), "size": row.get("自动尺码", ""), "values": values,
    }


def read_verified(source_dir: Path, name: str) -> tuple[dict, list[dict[str, str]]]:
    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    expected = next((i["sha256"] for i in manifest["deliverables"] if i["file"] == name), None)
    data = (source_dir / name).read_bytes()
    if expected is None or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"{name} 与 {manifest['node']} 的 manifest.json sha256 不一致，请重新发布上游")
    return manifest, list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def build(source_dir: Path, out_dir: Path, store_dir: Path | None = None) -> dict[str, int]:
    manifest, rows = read_verified(source_dir, NAME)
    store_dir = store_dir or STORE_SOURCE
    for stale in out_dir.glob("size-match-full*.json"):
        stale.unlink()
    sources, counts = [], {}
    store_rows = {store: read_verified(store_dir, file)[1] for store, file in STORES.items()}
    datasets = [(region, region, [r for r in rows if r["DIMENSION-ID"].endswith(f" {region}")]) for region in REGIONS]
    datasets[1:1] = [(store, "US", data) for store, data in store_rows.items()]  # US 全量之后紧跟 US 店铺
    for name, group, dataset in datasets:
        by_make: dict[str, list[dict]] = {}
        for row in dataset:
            by_make.setdefault(row["MAKE"], []).append(to_record(row, name))
        if not by_make:
            raise ValueError(f"{name} 没有数据")
        groups = []
        for index, make in enumerate(sorted(by_make, key=str.lower), 1):
            file_name = f"size-match-full-{slug(name)}-{index:03d}-{slug(make)}.json"
            write_json(out_dir / file_name, {"name": name, "make": make, "columns": COLUMNS, "records": by_make[make]})
            groups.append({"make": make, "records_path": file_name, "record_count": len(by_make[make])})
        counts[name] = sum(g["record_count"] for g in groups)
        sources.append({"name": name, "group": group, "label": name if name in REGIONS else f"US · {name}",
                        "sheet": f"{name}全量", "columns": COLUMNS, "record_count": counts[name], "make_groups": groups})
    write_json(out_dir / "size-match-full.json", {
        "format_version": 3, "columns": COLUMNS, "sources": sources,
        "origin": {"node": manifest["node"], "version": manifest["version"], "published_at": manifest["published_at"]},
    })
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "public" / "data" / "generated")
    args = parser.parse_args()
    print(json.dumps(build(args.source_dir, args.out_dir), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

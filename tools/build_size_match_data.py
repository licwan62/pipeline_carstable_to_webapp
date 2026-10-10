#!/usr/bin/env python3
"""用上游 A0.尺码计算/output 的国别全量表与 US 店铺全量表生成尺码配对页的数据源。

校验 A0 manifest 的 sha256 后，各数据源（US、各店铺、EU、RU）按 类别（非皮卡/皮卡）+ MAKE 分片写入
public/data/generated/size-match-full-NN-<区域>-<类别>-NNN-<make>.json，并写入清单 size-match-full.json。
尺码配对页默认只加载 US 非皮卡，在侧栏大纲切换 EU、或切换到皮卡时才读取对应分片。
类别按 A0 `分类` 判定：分类为“皮卡”的（含 EU 的 Chassis Cab 等）归皮卡，其余为非皮卡。
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

from pipeline_paths import configured_path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = configured_path("a0_output_dir")  # configs/pipeline.yaml paths.a0_output_dir
REGIONS = ("US", "EU", "RU")
# A0 output 按 <国别>/<类别>/ 分目录
REGION_FILES = {region: f"{region}/全量/全量表.csv" for region in REGIONS}
# US 源下的店铺选择：名称 -> A0 店铺全量文件（自动尺码为该店铺的发货尺码）
STORES = {store: f"US/店铺/店铺全量_{store}.csv" for store in ("HNT", "TM", "TM_拆分")}
COLUMNS = ["MODEL", "版本", "YEAR", "TYPE", "CAB", "BED", "销量合计", "L-MM", "W-MM", "H-MM", "长度余量", "SIZE"]
# 非皮卡与皮卡分开检索：分片与清单 make_groups 都带 kind，前端按当前类别只加载一种
KINDS = ("nonpick", "pick")
PICKUP_CATEGORY = "皮卡"


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


def write_make_groups(
    out_dir: Path, prefix: str, source_index: int, name: str, columns: list[str], records: list[dict]
) -> list[dict]:
    """按 类别 + MAKE 分片写出记录，返回清单 make_groups（非皮卡在前，各类别内 MAKE 按字母序）。"""
    by_kind_make: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        by_kind_make.setdefault((record["kind"], record["make"]), []).append(record)
    groups = []
    for kind in KINDS:
        makes = sorted((make for k, make in by_kind_make if k == kind), key=str.lower)
        for index, make in enumerate(makes, 1):
            shard = by_kind_make[(kind, make)]
            file_name = f"{prefix}-{source_index:02d}-{slug(name)}-{kind}-{index:03d}-{slug(make)}.json"
            write_json(out_dir / file_name, {"name": name, "make": make, "kind": kind, "columns": columns, "records": shard})
            groups.append({"make": make, "kind": kind, "records_path": file_name, "record_count": len(shard)})
    return groups


def kind_counts(groups: list[dict]) -> dict[str, int]:
    return {kind: sum(group["record_count"] for group in groups if group["kind"] == kind) for kind in KINDS}


def to_record(row: dict[str, str], region: str) -> dict:
    values = dict(row)
    values["长度余量"] = row.get("自动长度余量", "")
    values["销量合计"] = row.get("销量合计") or row.get("尺寸组销量", "")  # A0 2026-09-28 起改名 尺寸组销量
    values["CONST"] = row.get("结构", "")
    values["TYPE"] = row.get("结构", "")
    values["SIZE"] = row.get("自动尺码", "")
    values["SOURCE"] = region
    return {
        "make": row["MAKE"], "model": row["MODEL"], "year": row["YEAR"], "years": parse_years(row["YEAR"]),
        "construct": row.get("结构", ""), "cab": row.get("CAB", ""), "bed": row.get("BED", ""),
        "type": row.get("结构", ""), "size": row.get("自动尺码", ""), "values": values,
        "kind": "pick" if row.get("分类") == PICKUP_CATEGORY else "nonpick",
    }


def read_verified(source_dir: Path, name: str) -> tuple[dict, list[dict[str, str]]]:
    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    expected = next((i["sha256"] for i in manifest["deliverables"] if i["file"] == name), None)
    data = (source_dir / name).read_bytes()
    if expected is None or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"{name} 与 {manifest['node']} 的 manifest.json sha256 不一致，请重新发布上游")
    return manifest, list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def build(source_dir: Path, out_dir: Path) -> dict[str, int]:
    region_rows = {region: read_verified(source_dir, name) for region, name in REGION_FILES.items()}
    manifest = region_rows["US"][0]
    for stale in out_dir.glob("size-match-full*.json"):
        stale.unlink()
    sources, counts = [], {}
    store_rows = {store: read_verified(source_dir, file)[1] for store, file in STORES.items()}
    datasets = [(region, region, rows) for region, (_, rows) in region_rows.items()]
    datasets[1:1] = [(store, "US", data) for store, data in store_rows.items()]  # US 全量之后紧跟 US 店铺
    for source_index, (name, group, dataset) in enumerate(datasets, 1):
        if not dataset:
            raise ValueError(f"{name} 没有数据")
        groups = write_make_groups(out_dir, "size-match-full", source_index, name, COLUMNS, [to_record(row, name) for row in dataset])
        counts[name] = sum(g["record_count"] for g in groups)
        sources.append({"name": name, "group": group, "label": name if name in REGIONS else f"US · {name}",
                        "sheet": f"{name}全量", "columns": COLUMNS, "record_count": counts[name],
                        "kind_counts": kind_counts(groups), "make_groups": groups})
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

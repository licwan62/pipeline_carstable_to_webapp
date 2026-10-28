#!/usr/bin/env python3
"""尺码配对页全量表视图的 A0 行：读上游 A0.尺码计算/output 的国别全量表与 US 店铺全量表（校验 manifest sha256）并转成页面记录。

本模块只提供共用函数；数据文件由 build_size_match_code_data.build 写出（size-match-data.json 与分片：
每个分片同时存 A0 行 records 与引用这些行的 A1 压缩记录，页面控件切换压缩表/全量表，见该模块说明）。
类别按 A0 `分类` 判定：分类为“皮卡”的（含 EU 的 Chassis Cab 等）归皮卡，其余为非皮卡。
"""

from __future__ import annotations

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
# SHAPE：03.车形分类核定 COVER_SHAPE 经 A0 add_cover_shape 回填的车形（不参与尺码计算），紧跟 TYPE 显示
COLUMNS = ["MODEL", "版本", "YEAR", "TYPE", "SHAPE", "CAB", "BED", "销量合计", "市场潜力", "L-MM", "W-MM", "H-MM", "长度余量", "SIZE"]
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

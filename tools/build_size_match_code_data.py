#!/usr/bin/env python3
"""用上游 A1.压缩尺寸信息/output 的 US 区域压缩尺码表（含 CODE 代号列）生成「压缩代号」页的数据源。

页面与尺码配对共用 viewer.js，数据格式同 build_size_match_data（format_version 3：数据源 → MAKE 分片）：
校验 A2 manifest 的 sha256 后，每条产线（US、HNT、TM、TM_拆分）为一个数据源，非皮卡与皮卡两张表分开检索：
按 类别 + MAKE 分片写入 public/data/generated/size-match-code-NN-<产线>-<类别>-NNN-<make>.json（make_groups 带 kind），
清单为 size-match-code.json。
列映射：VERSION → 版本，CONST → TYPE（皮卡为 Pickup，同 A0 全量表结构），尺码销量总和 → 销量合计，BACKSIZE → SIZE，
最大长/宽/高-MM → L-MM/W-MM/H-MM（记录覆盖的来源行中的最大值）。
CODE = 02.代码映射 MAKE_CODE + MODEL_CODE + YEARCODE（由 A2 生成）。
每条记录带 sources：A1 <产线>/压缩来源.csv 中该记录（压缩类型 + 记录序号）覆盖的 A0 全量表行，页面点击记录展开各年份长宽高。
另写 vehicle-codes.json：CODE 前四位（MAKE_CODE + MODEL_CODE）→ MAKE、MODEL 与所在类别，供 viewer.js 全局搜索把
8 位车型代码（如 01039426 = Ford Mustang 1994-2026）解析为 MAKE + MODEL + 年份区间。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from build_size_match_data import kind_counts, parse_years, read_verified, write_json, write_make_groups
from pipeline_paths import configured_path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = configured_path("a2_output_dir")  # configs/pipeline.yaml paths.a2_output_dir
# 只有 US 区域产线带 CODE（02.代码映射只维护 US）
LINES = ("US", "HNT", "TM", "TM_拆分")
TABLES = (("压缩尺码表.csv", False), ("压缩尺码表_皮卡.csv", True))
SOURCES_FILE = "压缩来源.csv"
SOURCE_KINDS = {False: "非皮卡", True: "皮卡"}  # 压缩来源.csv 的 压缩类型
CODE_COLUMN = "CODE"
CODE_PATTERN = re.compile(r"\d{8}")
VEHICLE_CODES_FILE = "vehicle-codes.json"
COLUMNS = ["CODE", "MODEL", "版本", "YEAR", "TYPE", "CAB", "BED", "销量合计", "L-MM", "W-MM", "H-MM", "SIZE"]
DIMENSIONS = {"L-MM": "最大长-MM", "W-MM": "最大宽-MM", "H-MM": "最大高-MM"}
PICKUP_TYPE = "Pickup"


def to_source(row: dict[str, str], pickup: bool) -> dict[str, str]:
    """压缩来源的一行：记录覆盖的 A0 全量表行（YEAR 为被此记录覆盖的年份）。"""
    return {
        "DIMENSION-ID": row["DIMENSION-ID"], "MODEL": row["MODEL"], "版本": row.get("版本", ""), "YEAR": row["YEAR"],
        "TYPE": PICKUP_TYPE if pickup else row.get("结构", ""), "CAB": row.get("CAB", ""), "BED": row.get("BED", ""),
        **{column: row.get(column, "") for column in DIMENSIONS},
    }


def to_record(row: dict[str, str], line: str, pickup: bool, sources: list[dict[str, str]] | None = None) -> dict:
    construct = PICKUP_TYPE if pickup else row.get("CONST", "")
    values = {
        "CODE": row[CODE_COLUMN], "MAKE": row["MAKE"], "MODEL": row["MODEL"], "版本": row.get("VERSION", ""),
        "YEAR": row["YEAR"], "TYPE": construct, "CONST": construct, "CAB": row.get("CAB", ""), "BED": row.get("BED", ""),
        "销量合计": row.get("尺码销量总和", ""), "SIZE": row.get("BACKSIZE", ""), "SOURCE": line,
        **{column: row.get(source, "") for column, source in DIMENSIONS.items()},
    }
    return {
        "make": row["MAKE"], "model": row["MODEL"], "year": row["YEAR"], "years": parse_years(row["YEAR"]),
        "construct": construct, "cab": values["CAB"], "bed": values["BED"], "type": construct,
        "size": values["SIZE"], "values": values, "kind": "pick" if pickup else "nonpick", "sources": sources or [],
    }


def group_sources(rows: list[dict[str, str]]) -> dict[tuple[str, int], list[dict[str, str]]]:
    """(压缩类型, 记录序号) -> 来源行，保持 A1 的顺序（按记录、首年）。"""
    grouped: dict[tuple[str, int], list[dict[str, str]]] = {}
    for row in rows:
        pickup = row["压缩类型"] == SOURCE_KINDS[True]
        grouped.setdefault((row["压缩类型"], int(row["记录序号"])), []).append(to_source(row, pickup))
    return grouped


def add_vehicle_code(codes: dict[str, dict], row: dict[str, str], kind: str, where: str) -> None:
    """登记 CODE 前四位 → MAKE、MODEL、类别；同一前四位对应不同车型说明上游代码映射有误。"""
    code = row[CODE_COLUMN]
    if not CODE_PATTERN.fullmatch(code):
        raise ValueError(f"{where} 的 CODE 不是 8 位数字：{code!r}")
    entry = codes.setdefault(code[:4], {"make": row["MAKE"], "model": row["MODEL"], "kinds": []})
    if (entry["make"], entry["model"]) != (row["MAKE"], row["MODEL"]):
        raise ValueError(f"{where} 的 CODE 前四位 {code[:4]} 同时对应 {entry['make']} {entry['model']} 与 {row['MAKE']} {row['MODEL']}")
    if kind not in entry["kinds"]:
        entry["kinds"].append(kind)


def build(source_dir: Path, out_dir: Path) -> dict[str, int]:
    for stale in out_dir.glob("size-match-code*.json"):
        stale.unlink()
    manifest, sources, counts, vehicle_codes = None, [], {}, {}
    for source_index, line in enumerate(LINES, 1):
        records: list[dict] = []
        _, source_rows = read_verified(source_dir, f"{line}/{SOURCES_FILE}")
        record_sources = group_sources(source_rows)
        for name, pickup in TABLES:
            manifest, rows = read_verified(source_dir, f"{line}/{name}")
            if rows and CODE_COLUMN not in rows[0]:
                raise ValueError(f"{line}/{name} 缺少 {CODE_COLUMN} 列，请先在 all_cars_data 重新运行并发布 A2")
            for number, row in enumerate(rows, 1):
                add_vehicle_code(vehicle_codes, row, "pick" if pickup else "nonpick", f"{line}/{name}")
                records.append(to_record(row, line, pickup, record_sources.pop((SOURCE_KINDS[pickup], number), [])))
        if record_sources:
            raise ValueError(f"{line}/{SOURCES_FILE} 有 {len(record_sources)} 个记录序号不在压缩表中，请重新发布 A1")
        if not records:
            raise ValueError(f"{line} 没有数据")
        groups = write_make_groups(out_dir, "size-match-code", source_index, line, COLUMNS, records)
        counts[line] = sum(group["record_count"] for group in groups)
        sources.append({"name": line, "group": "US", "label": "US 全量" if line == "US" else f"US · {line}",
                        "sheet": f"{line}压缩尺码表", "columns": COLUMNS, "record_count": counts[line],
                        "kind_counts": kind_counts(groups), "make_groups": groups})
    origin = {"node": manifest["node"], "version": manifest["version"], "published_at": manifest["published_at"]}
    write_json(out_dir / "size-match-code.json", {
        "format_version": 3, "columns": COLUMNS, "sources": sources, "origin": origin,
    })
    write_json(out_dir / VEHICLE_CODES_FILE, {
        "format_version": 1, "codes": dict(sorted(vehicle_codes.items())), "origin": origin,
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

#!/usr/bin/env python3
"""用上游 A2.压缩尺寸信息/output 的 US 区域压缩尺码表（含 CODE 代号列）生成「压缩代号」页的数据源。

页面与尺码配对共用 viewer.js，数据格式同 build_size_match_data（format_version 3：数据源 → MAKE 分片）：
校验 A2 manifest 的 sha256 后，每条产线（US、HNT、TM、TM_拆分）的非皮卡与皮卡两张表合为一个数据源，
按 MAKE 分片写入 public/data/generated/size-match-code-NN-<产线>-NNN-<make>.json，清单为 size-match-code.json。
列映射：VERSION → 版本，CONST → TYPE（皮卡为 Pickup，同 A0 全量表结构），尺码销量总和 → 销量合计，BACKSIZE → SIZE。
CODE = 02.代码映射 MAKE_CODE + MODEL_CODE + YEARCODE（由 A2 生成）。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_size_match_data import parse_years, read_verified, slug, write_json
from pipeline_paths import configured_path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = configured_path("a2_output_dir")  # configs/pipeline.yaml paths.a2_output_dir
# 只有 US 区域产线带 CODE（02.代码映射只维护 US）
LINES = ("US", "HNT", "TM", "TM_拆分")
TABLES = (("压缩尺码表.csv", False), ("压缩尺码表_皮卡.csv", True))
CODE_COLUMN = "CODE"
COLUMNS = ["CODE", "MODEL", "版本", "YEAR", "TYPE", "CAB", "BED", "销量合计", "SIZE"]
PICKUP_TYPE = "Pickup"


def to_record(row: dict[str, str], line: str, pickup: bool) -> dict:
    construct = PICKUP_TYPE if pickup else row.get("CONST", "")
    values = {
        "CODE": row[CODE_COLUMN], "MAKE": row["MAKE"], "MODEL": row["MODEL"], "版本": row.get("VERSION", ""),
        "YEAR": row["YEAR"], "TYPE": construct, "CONST": construct, "CAB": row.get("CAB", ""), "BED": row.get("BED", ""),
        "销量合计": row.get("尺码销量总和", ""), "SIZE": row.get("BACKSIZE", ""), "SOURCE": line,
    }
    return {
        "make": row["MAKE"], "model": row["MODEL"], "year": row["YEAR"], "years": parse_years(row["YEAR"]),
        "construct": construct, "cab": values["CAB"], "bed": values["BED"], "type": construct,
        "size": values["SIZE"], "values": values,
    }


def build(source_dir: Path, out_dir: Path) -> dict[str, int]:
    for stale in out_dir.glob("size-match-code*.json"):
        stale.unlink()
    manifest, sources, counts = None, [], {}
    for source_index, line in enumerate(LINES, 1):
        by_make: dict[str, list[dict]] = {}
        for name, pickup in TABLES:
            manifest, rows = read_verified(source_dir, f"{line}/{name}")
            if rows and CODE_COLUMN not in rows[0]:
                raise ValueError(f"{line}/{name} 缺少 {CODE_COLUMN} 列，请先在 all_cars_data 重新运行并发布 A2")
            for row in rows:
                by_make.setdefault(row["MAKE"], []).append(to_record(row, line, pickup))
        if not by_make:
            raise ValueError(f"{line} 没有数据")
        groups = []
        for index, make in enumerate(sorted(by_make, key=str.lower), 1):
            file_name = f"size-match-code-{source_index:02d}-{slug(line)}-{index:03d}-{slug(make)}.json"
            write_json(out_dir / file_name, {"name": line, "make": make, "columns": COLUMNS, "records": by_make[make]})
            groups.append({"make": make, "records_path": file_name, "record_count": len(by_make[make])})
        counts[line] = sum(group["record_count"] for group in groups)
        sources.append({"name": line, "group": "US", "label": "US 全量" if line == "US" else f"US · {line}",
                        "sheet": f"{line}压缩尺码表", "columns": COLUMNS, "record_count": counts[line], "make_groups": groups})
    write_json(out_dir / "size-match-code.json", {
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

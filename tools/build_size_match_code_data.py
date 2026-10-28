#!/usr/bin/env python3
"""生成尺码配对页（size-match.html）的唯一数据源：A0 全量行 + A1 压缩记录，同一份分片，页面控件切换「压缩表 / 全量表」。

校验 A0、A1 manifest 的 sha256 后，每条产线（US、HNT、TM、TM_拆分、EU、RU）为一个数据源，按 类别（非皮卡/皮卡）+ MAKE 分片写入
public/data/generated/size-match-data-NN-<产线>-<类别>-NNN-<make>.json，清单为 size-match-data.json（format_version 4）。
每个分片只存一份字节：
- records：A0 同产线全量表的行（全量表视图；车型可视化的历史也读它），格式同 build_size_match_data.to_record；
- compressed：A1 压缩尺码表记录（压缩表视图），只存记录自身的聚合值 values 与 refs（[行号, 被覆盖年份]，行号指向本分片 records）。
  页面按 refs 还原「压缩来源」行（点 CODE 展开各年份长宽高），不再重复存放 A0 行。构建时逐行核对 A1 压缩来源.csv 与 A0 行一致，
  且记录覆盖的来源行与记录同 MAKE、同类别（同一分片），否则失败。
压缩记录列映射：VERSION → 版本，CONST → TYPE（皮卡为 Pickup，同 A0 全量表结构），尺码销量总和 → 销量合计，
BACKSIZE（RU 为 亚马逊尺码）→ SIZE，最大长/宽/高-MM → L-MM/W-MM/H-MM（记录覆盖的来源行中的最大值）。
CODE = 02.代码映射 MAKE_CODE + MODEL_CODE + YEARCODE（由 A1 生成，只有 US 区域产线有；EU/RU 为空）。
记录的 SHAPE 为来源行车形去重，长度余量取来源行最小值（最长的车决定余量），来源行规则ID 一致时记录带规则ID。
另写 vehicle-codes.json：CODE 前四位（MAKE_CODE + MODEL_CODE）→ MAKE、MODEL 与所在类别，供 viewer.js 全局搜索把
8 位车型代码（如 01039426 = Ford Mustang 1994-2026）解析为 MAKE + MODEL + 年份区间。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from build_size_match_data import (
    COLUMNS as FULL_COLUMNS, DEFAULT_SOURCE as A0_SOURCE, KINDS, REGION_FILES, STORES, parse_years, read_verified, slug, write_json,
)
from build_size_match_data import to_record as full_record
from pipeline_paths import configured_path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = configured_path("compressed_output_dir")  # configs/pipeline.yaml paths.compressed_output_dir（原 a2_output_dir）
# 产线 → 所属区域（尺码规则、侧栏大纲按区域分组）；只有 US 区域产线带 CODE（02.代码映射只维护 US）
LINES = {"US": "US", "HNT": "US", "TM": "US", "TM_拆分": "US", "EU": "EU", "RU": "RU"}
CODE_LINES = ("US", "HNT", "TM", "TM_拆分")
# 产线对应的 A0 全量表：区域产线读 <区域>/全量/全量表.csv，US 店铺读 US/店铺/店铺全量_<店铺>.csv
A0_FILES = {**REGION_FILES, **STORES}
TABLES = (("压缩尺码表.csv", False), ("压缩尺码表_皮卡.csv", True))
SOURCES_FILE = "压缩来源.csv"
SOURCE_KINDS = {False: "非皮卡", True: "皮卡"}  # 压缩来源.csv 的 压缩类型
CODE_COLUMN = "CODE"
CODE_PATTERN = re.compile(r"\d{8}")
VEHICLE_CODES_FILE = "vehicle-codes.json"
COLUMNS = ["CODE", "MODEL", "版本", "YEAR", "TYPE", "SHAPE", "CAB", "BED", "销量合计", "市场潜力", "L-MM", "W-MM", "H-MM", "长度余量", "SIZE"]
# 同一份数据的两种视图（页面 tableModes 控件切换）：压缩表 = compressed 记录，全量表 = records（A0 行）
DATA_PREFIX = "size-match-data"
DATA_MANIFEST = f"{DATA_PREFIX}.json"
VIEWS = {"compressed": {"label": "压缩表", "columns": COLUMNS}, "full": {"label": "全量表", "columns": FULL_COLUMNS}}
DEFAULT_VIEW = "compressed"
# 旧版两套数据（压缩表分片 sources 内嵌 A0 行 + 另一套 A0 全量分片），重建时一并清除
STALE_PREFIXES = ("size-match-code", "size-match-full", DATA_PREFIX)
# A1 压缩来源.csv 与 A0 行必须一致的字段（页面按 refs 从 A0 行还原来源行，YEAR 为被覆盖年份单独存）
SOURCE_FIELDS = ("MAKE", "MODEL", "版本", "结构", "CAB", "BED", "L-MM", "W-MM", "H-MM")
DIMENSIONS = {"L-MM": "最大长-MM", "W-MM": "最大宽-MM", "H-MM": "最大高-MM"}
SIZE_COLUMNS = ("BACKSIZE", "亚马逊尺码")  # RU 压缩表的亚马逊尺码即 A0 RU 自动尺码
PICKUP_TYPE = "Pickup"
A0_NODE = "size-calculation"
# SHAPE（03.车形分类核定 COVER_SHAPE，车罩外形分类，不参与尺码计算）的中文名与说明；
# 说明取自 03 车型族研究的标签定义（code/qwen_family_research.py LABELS），页面 SHAPE 悬停显示。
SHAPE_LABELS = {
    "LOW_FASTBACK": ("低矮溜背", "低矮车身，车顶后部长而连续地下降到车尾"),
    "LOW_NOTCHBACK": ("低矮阶背", "低矮车身，后窗之后有明显独立尾箱台阶"),
    "SPORT_LIFTBACK": ("运动掀背", "运动化乘员舱，倾斜的掀背/溜背尾门"),
    "STANDARD_SEDAN": ("常规三厢", "常规三厢比例，明显行李厢"),
    "COMPACT_HATCH": ("紧凑两厢", "车长较短、车头短、乘员舱较高、尾部短"),
    "TALL_BOX": ("高顶厢式", "高且长的车顶、尾部近乎直立（厢式车、MPV、Kia Soul 类）"),
    "WAGON": ("旅行车", "长车顶、载物舱连续延伸、尾部较直立的旅行车"),
    "SLOPED_CROSSOVER": ("溜背跨界 SUV", "较高车体、车顶向车尾倾斜的跨界/轿跑 SUV"),
    "BOXY_SUV": ("方正 SUV", "较高车体、直立车尾、长而高的车顶"),
    "PICKUP": ("皮卡", "独立驾驶室 + 开放货箱"),
    "OTHER": ("其他", "以上外形都不合适的特殊车辆"),
}


def unique_join(values: list[str]) -> str:
    return " / ".join(dict.fromkeys(value for value in values if value))


def min_margin(values: list[str]) -> str:
    numbers = []
    for value in values:
        try:
            numbers.append((float(value), value))
        except ValueError:
            continue
    if not numbers:
        return ""
    number, text = min(numbers)
    return str(int(number)) if number.is_integer() else text


def to_source(row: dict[str, str], pickup: bool, full: dict[str, str]) -> dict[str, str]:
    """压缩来源的一行：记录覆盖的 A0 全量表行（YEAR 为被此记录覆盖的年份），附 A0 同行的 SHAPE、长度余量与命中规则。"""
    return {
        "DIMENSION-ID": row["DIMENSION-ID"], "MODEL": row["MODEL"], "版本": row.get("版本", ""), "YEAR": row["YEAR"],
        "TYPE": PICKUP_TYPE if pickup else row.get("结构", ""), "CAB": row.get("CAB", ""), "BED": row.get("BED", ""),
        **{column: row.get(column, "") for column in DIMENSIONS},
        "SHAPE": full.get("SHAPE", ""), "长度余量": full.get("自动长度余量", ""),
        "规则ID": full.get("规则ID", ""), "匹配尺码": full.get("匹配尺码", ""),
    }


def to_record(row: dict[str, str], line: str, pickup: bool, sources: list[dict[str, str]]) -> dict:
    construct = PICKUP_TYPE if pickup else row.get("CONST", "")
    size = next((row[column] for column in SIZE_COLUMNS if row.get(column)), "")
    rule_ids = {(source["规则ID"], source["匹配尺码"]) for source in sources}
    rule_id, match_size = next(iter(rule_ids)) if len(rule_ids) == 1 else ("", "")
    values = {
        "CODE": row.get(CODE_COLUMN, ""), "MAKE": row["MAKE"], "MODEL": row["MODEL"], "版本": row.get("VERSION", ""),
        "YEAR": row["YEAR"], "TYPE": construct, "CONST": construct, "CAB": row.get("CAB", ""), "BED": row.get("BED", ""),
        "SHAPE": unique_join([source["SHAPE"] for source in sources]),
        "市场潜力": row.get("市场潜力", ""), "销量合计": row.get("尺码销量总和", ""), "SIZE": size, "SOURCE": line,
        "长度余量": min_margin([source["长度余量"] for source in sources]),
        **{column: row.get(source, "") for column, source in DIMENSIONS.items()},
    }
    if rule_id:
        values.update({"规则ID": rule_id, "匹配尺码": match_size})
    return {
        "make": row["MAKE"], "model": row["MODEL"], "year": row["YEAR"], "years": parse_years(row["YEAR"]),
        "construct": construct, "cab": values["CAB"], "bed": values["BED"], "type": construct,
        "size": size, "values": values, "kind": "pick" if pickup else "nonpick", "sources": sources,
    }


def group_sources(
    rows: list[dict[str, str]], full_rows: list[dict[str, str]], row_index: dict[str, int], line: str,
) -> dict[tuple[str, int], list[tuple[int, dict[str, str]]]]:
    """(压缩类型, 记录序号) -> [(A0 行号, 来源行)]，保持 A1 的顺序（按记录、首年）。

    来源行除 YEAR（被此记录覆盖的年份）外必须与 A0 行一致：页面只按 [行号, YEAR] 从 A0 行还原，不另存来源行字节。"""
    grouped: dict[tuple[str, int], list[tuple[int, dict[str, str]]]] = {}
    missing = [row["DIMENSION-ID"] for row in rows if row["DIMENSION-ID"] not in row_index]
    if missing:
        raise ValueError(f"{line}/{SOURCES_FILE} 有 {len(missing)} 个 DIMENSION-ID 不在 A0 {A0_FILES[line]}（如 {missing[0]}），请重新发布 A1")
    for row in rows:
        index = row_index[row["DIMENSION-ID"]]
        full = full_rows[index]
        changed = [field for field in SOURCE_FIELDS if field in row and row[field] != full.get(field, "")]
        if changed:
            raise ValueError(f"{line}/{SOURCES_FILE} 的 {row['DIMENSION-ID']} 与 A0 行不一致（{', '.join(changed)}），请重新发布 A1")
        pickup = row["压缩类型"] == SOURCE_KINDS[True]
        grouped.setdefault((row["压缩类型"], int(row["记录序号"])), []).append((index, to_source(row, pickup, full)))
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


def read_a0_rows(a0_dir: Path, a1_manifest: dict, line: str) -> tuple[dict, list[dict[str, str]], dict[str, int]]:
    """读 A0 同产线全量表（校验 sha256），并要求与 A1 登记的上游文件一致，保证 DIMENSION-ID 对得上。返回行与 DIMENSION-ID → 行号。"""
    name = A0_FILES[line]
    a0_manifest, rows = read_verified(a0_dir, name)
    upstream = next((item for item in a1_manifest.get("upstream") or [] if item.get("node") == A0_NODE), {})
    expected = next((item["sha256"] for item in upstream.get("files") or [] if item.get("file") == name), None)
    actual = next(item["sha256"] for item in a0_manifest["deliverables"] if item["file"] == name)
    if expected != actual:
        raise ValueError(f"A1 {a1_manifest.get('version')} 不是基于当前 A0 {a0_manifest['version']} 的 {name} 构建，请重新发布 A1")
    row_index: dict[str, int] = {}
    for index, row in enumerate(rows):
        if row["DIMENSION-ID"] in row_index:
            raise ValueError(f"A0 {name} 的 DIMENSION-ID 重复：{row['DIMENSION-ID']}")
        row_index[row["DIMENSION-ID"]] = index
    return a0_manifest, rows, row_index


def write_line_shards(
    out_dir: Path, source_index: int, line: str, full: list[dict], compressed: list[tuple[dict, list[int], list[str]]],
) -> list[dict]:
    """按 类别 + MAKE 写出同一份分片：records 为 A0 行，compressed 为压缩记录（只存 values 与 refs，refs 行号为分片内行号）。

    压缩记录的 make/model/years/kind 与来源行由页面从 values、refs 与分片还原（viewer-data.js expandMatchShard）。
    返回清单 make_groups（非皮卡在前，各类别内 MAKE 按字母序）；压缩记录覆盖的 A0 行不在同一分片时失败。"""
    full_by_shard: dict[tuple[str, str], list[int]] = {}
    for index, record in enumerate(full):
        full_by_shard.setdefault((record["kind"], record["make"]), []).append(index)
    compressed_by_shard: dict[tuple[str, str], list[tuple[dict, list[int], list[str]]]] = {}
    for item in compressed:
        compressed_by_shard.setdefault((item[0]["kind"], item[0]["make"]), []).append(item)
    groups = []
    for kind in KINDS:
        makes = sorted({make for k, make in [*full_by_shard, *compressed_by_shard] if k == kind}, key=lambda make: (make.lower(), make))
        for number, make in enumerate(makes, 1):
            indexes = full_by_shard.get((kind, make), [])
            local = {index: position for position, index in enumerate(indexes)}
            items = []
            for record, row_indexes, years in compressed_by_shard.get((kind, make), []):
                outside = [full[index]["values"].get("DIMENSION-ID", "") for index in row_indexes if index not in local]
                if outside:
                    raise ValueError(f"{line} 压缩记录 {make} {record['model']} {record['year']} 覆盖了其他 MAKE/类别的 A0 行：{outside[0]}")
                items.append({"values": record["values"], "refs": [[local[index], year] for index, year in zip(row_indexes, years)]})
            file_name = f"{DATA_PREFIX}-{source_index:02d}-{slug(line)}-{kind}-{number:03d}-{slug(make)}.json"
            write_json(out_dir / file_name, {
                "name": line, "make": make, "kind": kind,
                "columns": FULL_COLUMNS, "records": [full[index] for index in indexes],
                "compressed_columns": COLUMNS, "compressed": items,
            })
            groups.append({"make": make, "kind": kind, "records_path": file_name,
                           "record_count": len(indexes), "compressed_count": len(items)})
    return groups


def kind_counts(groups: list[dict], field: str = "record_count") -> dict[str, int]:
    return {kind: sum(group[field] for group in groups if group["kind"] == kind) for kind in KINDS}


def build(source_dir: Path, out_dir: Path, a0_dir: Path = A0_SOURCE) -> dict[str, dict[str, int]]:
    """写 size-match-data.json 与分片、vehicle-codes.json；返回各产线 {compressed: 压缩记录数, full: A0 行数}。"""
    for prefix in STALE_PREFIXES:
        for stale in out_dir.glob(f"{prefix}*.json"):
            stale.unlink()
    a1_manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    a0_manifest, sources, counts, vehicle_codes, shapes = None, [], {}, {}, set()
    for source_index, (line, group) in enumerate(LINES.items(), 1):
        a0_manifest, a0_rows, row_index = read_a0_rows(a0_dir, a1_manifest, line)
        full = [full_record(row, line) for row in a0_rows]
        _, source_rows = read_verified(source_dir, f"{line}/{SOURCES_FILE}")
        record_sources = group_sources(source_rows, a0_rows, row_index, line)
        compressed: list[tuple[dict, list[int], list[str]]] = []
        for name, pickup in TABLES:
            _, rows = read_verified(source_dir, f"{line}/{name}")
            if line in CODE_LINES and rows and CODE_COLUMN not in rows[0]:
                raise ValueError(f"{line}/{name} 缺少 {CODE_COLUMN} 列，请先在 all_cars_data 重新运行并发布 A1")
            for number, row in enumerate(rows, 1):
                if line in CODE_LINES:
                    add_vehicle_code(vehicle_codes, row, "pick" if pickup else "nonpick", f"{line}/{name}")
                pairs = record_sources.pop((SOURCE_KINDS[pickup], number), [])
                record = to_record(row, line, pickup, [source for _, source in pairs])
                shapes.update(source["SHAPE"] for source in record["sources"] if source["SHAPE"])
                compressed.append((record, [index for index, _ in pairs], [source["YEAR"] for _, source in pairs]))
        if record_sources:
            raise ValueError(f"{line}/{SOURCES_FILE} 有 {len(record_sources)} 个记录序号不在压缩表中，请重新发布 A1")
        if not compressed or not full:
            raise ValueError(f"{line} 没有数据")
        groups = write_line_shards(out_dir, source_index, line, full, compressed)
        counts[line] = {"compressed": len(compressed), "full": len(full)}
        sources.append({"name": line, "group": group, "label": line if line == group else f"{group} · {line}",
                        "sheet": f"{line}尺码配对", "columns": FULL_COLUMNS, "compressed_columns": COLUMNS,
                        "record_count": len(full), "compressed_count": len(compressed),
                        "kind_counts": kind_counts(groups), "compressed_kind_counts": kind_counts(groups, "compressed_count"),
                        "make_groups": groups})
    unknown = sorted(shapes - set(SHAPE_LABELS))
    if unknown:
        print(f"[size-match-data] SHAPE 没有中文说明（请补 SHAPE_LABELS）：{', '.join(unknown)}")
    # version 为 A1 版本；a0_version：全量行与来源行补充字段（SHAPE、规则ID 等）所依据的 A0 版本，页面据此确认与尺码规则同版本
    origin = {"node": a1_manifest["node"], "version": a1_manifest["version"], "published_at": a1_manifest["published_at"],
              "a0_version": a0_manifest["version"]}
    write_json(out_dir / DATA_MANIFEST, {
        "format_version": 4, "columns": FULL_COLUMNS, "views": VIEWS, "default_view": DEFAULT_VIEW,
        "sources": sources, "origin": origin,
        "shape_labels": {shape: {"label": label, "description": description} for shape, (label, description) in SHAPE_LABELS.items()},
    })
    write_json(out_dir / VEHICLE_CODES_FILE, {
        "format_version": 1, "codes": dict(sorted(vehicle_codes.items())), "origin": origin,
    })
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--a0-dir", type=Path, default=A0_SOURCE)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "public" / "data" / "generated")
    args = parser.parse_args()
    print(json.dumps(build(args.source_dir, args.out_dir, args.a0_dir), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

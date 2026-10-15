#!/usr/bin/env python3
"""把上游 A0.尺码计算/output 发布的尺码规则和店铺货架转成网站参考页数据。

正式接口（A0 2026-10-14 起发布，见 A0 AGENTS.md）：
  <国别>/尺码规则.json   规则表（headers + rules，末列 规则ID）、参数、length_tolerance_mm
  US/店铺货架.json       stores: {店铺: [{匹配尺码, 发货尺码}]}
A0 manifest 未登记这些文件时（更早的 A0 版本），退回兼容模式解析 <国别>/尺码匹配报告.md 的表格：
  ## 尺码规则 / ### 规则表（N 条）          -> 该国规则（表头 + 行）
  ### 店铺货架（匹配尺码 → 发货尺码）        -> 仅 US 报告
两种接口生成的规则行与货架逐项一致（值按 md 单元格规则归一：换行变空格、去首尾空白），仅 file 字段指向实际来源文件。
读取 manifest.json 校验 sha256 后，写出：
  size-rules.json   {source, regions: {US/EU/RU: {file, headers, rows, length_tolerance}}}
  store-groups.json {source, stores: {店铺: [{匹配尺码, 发货尺码}]}}
US/EU/RU 三套规则各自独立读取，不互相推导。
length_tolerance 取报告正文中的“余量长容差 N mm”（长上限 − 车长 的上限，供尺码配对页 hover 计算适配车长）；
RU 规则行自带 余量长上限_mm 时以行值为准，报告未写时为 null。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

from pipeline_paths import configured_path

DEFAULT_SOURCE = configured_path("a0_output_dir")  # configs/pipeline.yaml paths.a0_output_dir
REGIONS = ("US", "EU", "RU")
REPORT_FILES = {region: f"{region}/尺码匹配报告.md" for region in REGIONS}
RULES_FILES = {region: f"{region}/尺码规则.json" for region in REGIONS}
SHELF_FILE = "US/店铺货架.json"
RULES_HEADING = "### 规则表"  # A0 报告“## 尺码规则”下的子节，标题带条数，按前缀匹配
SHELF_HEADING = "### 店铺货架"
CELL_SPLIT = re.compile(r"(?<!\\)\|")
TOLERANCE = re.compile(r"余量长容差\s*\**\s*(\d+(?:\.\d+)?)\s*mm")


def read_verified_text(source_dir: Path, manifest: dict, name: str) -> str:
    expected = next((item["sha256"] for item in manifest["deliverables"] if item["file"] == name), None)
    path = source_dir / name
    if expected is None or not path.is_file():
        raise ValueError(f"上游发布源缺少 {name}")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"{name} 与 manifest.json 的 sha256 不一致，请重新发布上游")
    return data.decode("utf-8-sig")


def _cells(line: str) -> list[str]:
    parts = CELL_SPLIT.split(line.strip())[1:-1]
    return [part.strip().replace("\\|", "|") for part in parts]


def md_table_after(text: str, heading: str, name: str) -> tuple[list[str], list[dict[str, str]]]:
    """取 heading（行首匹配）之后的第一张 md 表格，返回表头与非空行。"""
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith(heading)), None)
    if start is None:
        raise ValueError(f"{name} 缺少“{heading}”一节")
    table = []
    for line in lines[start + 1:]:
        if line.startswith("#"):
            break
        if line.startswith("|"):
            table.append(line)
        elif table:
            break
    if len(table) < 2:
        raise ValueError(f"{name} 的“{heading}”没有表格")
    headers = _cells(table[0])
    rows = [dict(zip(headers, _cells(line))) for line in table[2:]]
    return headers, [row for row in rows if any(row.values())]


def length_tolerance(text: str) -> float | int | None:
    match = TOLERANCE.search(text)
    if not match:
        return None
    value = float(match.group(1))
    return int(value) if value.is_integer() else value


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


def cell_text(value: object) -> str:
    """与 md 单元格同一归一：A0 写 md 时换行变空格，网站解析时去首尾空白。"""
    return str(value).replace("\n", " ").strip()


def uses_json_interface(manifest: dict) -> bool:
    listed = {item["file"] for item in manifest["deliverables"]}
    return SHELF_FILE in listed and all(name in listed for name in RULES_FILES.values())


def from_json(source_dir: Path, manifest: dict) -> tuple[dict, dict[str, list[dict[str, str]]]]:
    regions = {}
    for region, name in RULES_FILES.items():
        payload = json.loads(read_verified_text(source_dir, manifest, name))
        headers = list(payload["headers"])
        rows = [{header: cell_text(rule.get(header, "")) for header in headers} for rule in payload["rules"]]
        rows = [row for row in rows if any(row.values())]
        regions[region] = {"file": name, "headers": headers, "rows": rows, "length_tolerance": payload.get("length_tolerance_mm")}
    shelf = json.loads(read_verified_text(source_dir, manifest, SHELF_FILE))
    stores = {str(store): [{"匹配尺码": cell_text(i["匹配尺码"]), "发货尺码": cell_text(i["发货尺码"])} for i in items]
              for store, items in shelf["stores"].items()}
    return regions, stores


def from_markdown(source_dir: Path, manifest: dict) -> tuple[dict, dict[str, list[dict[str, str]]]]:
    """兼容模式：A0 早于 2026-10-14 的版本没有 JSON 接口，只能解析报告中的 md 表格。"""
    reports = {region: read_verified_text(source_dir, manifest, name) for region, name in REPORT_FILES.items()}
    regions = {}
    for region, text in reports.items():
        headers, rows = md_table_after(text, RULES_HEADING, REPORT_FILES[region])
        regions[region] = {"file": REPORT_FILES[region], "headers": headers, "rows": rows, "length_tolerance": length_tolerance(text)}
    _, shelf = md_table_after(reports["US"], SHELF_HEADING, REPORT_FILES["US"])
    stores: dict[str, list[dict[str, str]]] = {}
    for row in shelf:
        stores.setdefault(row["店铺"], []).append({"匹配尺码": row["匹配尺码"], "发货尺码": row["发货尺码"]})
    return regions, stores


def build(source_dir: Path, out_dir: Path, *, allow_markdown: bool = True) -> dict[str, int]:
    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    source = {"node": manifest["node"], "version": manifest["version"], "published_at": manifest["published_at"]}
    if uses_json_interface(manifest):
        regions, stores = from_json(source_dir, manifest)
        interface = "json"
    elif allow_markdown:
        print(f"[size-rules] 警告：A0 {manifest['version']} 未发布 尺码规则.json/店铺货架.json，兼容模式解析尺码匹配报告.md；请重新发布 A0")
        regions, stores = from_markdown(source_dir, manifest)
        interface = "markdown-legacy"
    else:
        raise ValueError(f"A0 {manifest['version']} 未发布 尺码规则.json/店铺货架.json")
    for region, item in regions.items():
        if not item["rows"]:
            raise ValueError(f"A0 {region} 没有规则行（{item['file']}）")
    if not stores:
        raise ValueError("A0 没有店铺货架")
    write_json(out_dir / "size-rules.json", {"source": source, "regions": regions})
    write_json(out_dir / "store-groups.json", {"source": source, "stores": stores})
    return {**{region: len(item["rows"]) for region, item in regions.items()}, "stores": len(stores), "interface": interface}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parents[1] / "public" / "data" / "generated")
    args = parser.parse_args()
    print(json.dumps(build(args.source_dir, args.out_dir), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""把上游 A0.尺码计算/output 发布的尺码匹配报告中的尺码规则和店铺货架转成网站参考页数据。

A0 不再单独发布规则/货架 CSV，规则全文与店铺货架写在 <国别>/尺码匹配报告.md 的表格中：
  ## 尺码规则                               -> 该国规则（表头 + 行）
  ### 店铺货架（匹配尺码 → 发货尺码）        -> 仅 US 报告
读取 manifest.json 校验 sha256 后，写出：
  size-rules.json   {source, regions: {US/EU/RU: {file, headers, rows}}}
  store-groups.json {source, stores: {店铺: [{匹配尺码, 发货尺码}]}}
US/EU/RU 三套规则各自独立读取，不互相推导。
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
RULES_HEADING = "## 尺码规则"
SHELF_HEADING = "### 店铺货架"
CELL_SPLIT = re.compile(r"(?<!\\)\|")


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


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


def build(source_dir: Path, out_dir: Path) -> dict[str, int]:
    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    source = {"node": manifest["node"], "version": manifest["version"], "published_at": manifest["published_at"]}
    reports = {region: read_verified_text(source_dir, manifest, name) for region, name in REPORT_FILES.items()}
    regions = {}
    for region, text in reports.items():
        headers, rows = md_table_after(text, RULES_HEADING, REPORT_FILES[region])
        if not rows:
            raise ValueError(f"{REPORT_FILES[region]} 没有规则行")
        regions[region] = {"file": REPORT_FILES[region], "headers": headers, "rows": rows}
    _, shelf = md_table_after(reports["US"], SHELF_HEADING, REPORT_FILES["US"])
    stores: dict[str, list[dict[str, str]]] = {}
    for row in shelf:
        stores.setdefault(row["店铺"], []).append({"匹配尺码": row["匹配尺码"], "发货尺码": row["发货尺码"]})
    if not stores:
        raise ValueError(f"{REPORT_FILES['US']} 没有店铺货架")
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

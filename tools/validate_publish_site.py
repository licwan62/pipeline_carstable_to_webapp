from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml


REQUIRED_REFERENCE_FIELDS = ("型号", "长_mm", "宽_mm", "高_mm")


def read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.is_file():
        errors.append(f"missing JSON file: {path}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"invalid JSON file {path}: {error}")
        return {}
    if not isinstance(payload, dict):
        errors.append(f"JSON root must be an object: {path}")
        return {}
    return payload


def resolve_records_path(site_root: Path, manifest_path: Path, records_path: str, errors: list[str]) -> Path | None:
    resolved = (manifest_path.parent / records_path).resolve()
    try:
        resolved.relative_to(site_root)
    except ValueError:
        errors.append(f"source JSON escapes site root: {records_path}")
        return None
    return resolved


def read_source_records(
    site_root: Path,
    manifest_path: Path,
    source: dict[str, Any],
    source_name: str,
    errors: list[str],
) -> list[dict[str, Any]]:
    make_groups = source.get("make_groups")
    if isinstance(make_groups, list):
        records: list[dict[str, Any]] = []
        for group in make_groups:
            if not isinstance(group, dict) or not group.get("records_path"):
                errors.append(f"invalid make shard declaration for {source_name}")
                continue
            split_path = resolve_records_path(site_root, manifest_path, str(group["records_path"]), errors)
            payload = read_json(split_path, errors) if split_path else {}
            if payload.get("name") != source_name:
                errors.append(f"source name mismatch in {group['records_path']}: expected {source_name}")
            if str(payload.get("make") or "") != str(group.get("make") or ""):
                errors.append(f"make mismatch in {group['records_path']}: expected {group.get('make')}")
            group_records = payload.get("records") or []
            if group.get("record_count") is not None and int(group["record_count"]) != len(group_records):
                errors.append(
                    f"record count mismatch for {source_name} / {group.get('make')}: "
                    f"manifest={group['record_count']} actual={len(group_records)}"
                )
            records.extend(group_records)
        return records

    source_payload = source
    if source.get("records_path"):
        split_path = resolve_records_path(site_root, manifest_path, str(source["records_path"]), errors)
        source_payload = read_json(split_path, errors) if split_path else {}
        if source_payload.get("name") != source_name:
            errors.append(f"source name mismatch in {source.get('records_path')}: expected {source_name}")
    return source_payload.get("records") or source.get("records") or []


# 只有 US 区域产线有 CODE（02.代码映射只维护 US）；EU/RU 压缩记录 CODE 为空
CODE_SOURCES = ("US", "HNT", "TM", "TM_拆分")
# 尺码配对页的唯一数据源：A0 全量行 + 引用这些行的 A1 压缩记录（同一份分片，页面切换 压缩表 / 全量表）
MATCH_PAGE = "size-match.html"
MATCH_DATA = "data/generated/size-match-data.json"
MATCH_VIEWS = ("compressed", "full")
# 旧版两套重复数据（压缩表分片内嵌 A0 来源行 + 另一套 A0 全量分片）不得再发布
DUPLICATE_DATA_PREFIXES = ("size-match-code", "size-match-full")


def validate_size_match_data(site_root: Path, errors: list[str]) -> dict[str, int]:
    """size-match-data.json：每个数据源的 MAKE 分片存在、全量行与压缩记录数与清单一致；压缩记录的 refs 都指向本分片的全量行，
    被覆盖年份在该行年份内，且每条压缩记录至少覆盖一行；US 区域产线的压缩记录都带 CODE，vehicle-codes.json 收录其前四位。
    返回 {"full": 全量行数, "compressed": 压缩记录数}。页面没有使用该数据时跳过。"""
    page = site_root / MATCH_PAGE
    if not (page.is_file() and MATCH_DATA in page.read_text(encoding="utf-8")):
        return {}
    manifest_path = site_root / MATCH_DATA
    manifest = read_json(manifest_path, errors)
    vehicle_codes = read_json(site_root / "data" / "generated" / "vehicle-codes.json", errors).get("codes") or {}
    if manifest.get("format_version") != 4:
        errors.append(f"{MATCH_DATA} must be format_version 4 (one shard per line/kind/make holding both views)")
    views = manifest.get("views") or {}
    missing_views = [view for view in MATCH_VIEWS if view not in views]
    if missing_views:
        errors.append(f"{MATCH_DATA} does not declare views: {', '.join(missing_views)}")
    if "CODE" not in ((views.get("compressed") or {}).get("columns") or []):
        errors.append(f"{MATCH_DATA} compressed view does not declare CODE column")
    totals = {"full": 0, "compressed": 0}
    for source in manifest.get("sources") or []:
        name = str(source.get("name") or "")
        full_count = compressed_count = 0
        for group in source.get("make_groups") or []:
            path = resolve_records_path(site_root, manifest_path, str(group.get("records_path") or ""), errors)
            shard = read_json(path, errors) if path else {}
            where = f"{name} / {group.get('kind')} / {group.get('make')}"
            if shard.get("name") != name or str(shard.get("make") or "") != str(group.get("make") or "") or shard.get("kind") != group.get("kind"):
                errors.append(f"shard identity mismatch for {where}: {group.get('records_path')}")
            rows = shard.get("records") or []
            compressed = shard.get("compressed")
            if not isinstance(compressed, list):
                errors.append(f"{where} shard has no compressed view")
                compressed = []
            if int(group.get("record_count", -1)) != len(rows) or int(group.get("compressed_count", -1)) != len(compressed):
                errors.append(f"record count mismatch for {where}")
            for position, item in enumerate(compressed):
                refs = item.get("refs") or []
                values = item.get("values") or {}
                if not refs:
                    errors.append(f"{where} compressed record {position} has no A0 source rows")
                for ref in refs:
                    if not (isinstance(ref, list) and len(ref) == 2 and isinstance(ref[0], int) and 0 <= ref[0] < len(rows)):
                        errors.append(f"{where} compressed record {position} has invalid ref {ref!r}")
                        continue
                    covered = set(_years(str(ref[1])))
                    if not covered or not covered <= set(rows[ref[0]].get("years") or []):
                        errors.append(f"{where} compressed record {position} covers years {ref[1]} outside its A0 row")
                if name in CODE_SOURCES:
                    code = str(values.get("CODE") or "")
                    if not code:
                        errors.append(f"{where} compressed record {position} has no CODE")
                    elif code[:4] not in vehicle_codes:
                        errors.append(f"vehicle-codes.json is missing {name} code prefix {code[:4]}")
            full_count += len(rows)
            compressed_count += len(compressed)
        if not full_count or not compressed_count:
            errors.append(f"{MATCH_DATA} source {name} has no rows in one of its views")
        if source.get("record_count") != full_count or source.get("compressed_count") != compressed_count:
            errors.append(f"{MATCH_DATA} source {name} counts do not match its shards")
        totals["full"] += full_count
        totals["compressed"] += compressed_count
    if not manifest.get("sources"):
        errors.append(f"{MATCH_DATA} has no sources")
    generated = site_root / "data" / "generated"
    duplicates = sorted(path.name for prefix in DUPLICATE_DATA_PREFIXES for path in generated.glob(f"{prefix}*.json"))
    if duplicates:
        errors.append(f"duplicate size-match data must not be published: {', '.join(duplicates[:3])}")
    return totals


def _years(text: str) -> list[int]:
    numbers = [int(part) for part in re.findall(r"\d{4}", text)]
    return numbers if len(numbers) <= 1 else list(range(numbers[0], numbers[-1] + 1))


EVOLUTION_PAGE = "size-match.html"
EVOLUTION_FREE_PAGES = ("size-chart.html", "size-charts.html")
EVOLUTION_HISTORY = MATCH_DATA  # 可视化历史与表格同一份数据（全量行）
ASSET_LINK = re.compile(r"""["'](assets/[\w./-]+\.(?:js|css))(?:\?v=[\w-]+)?["']""")


def validate_size_evolution(site_root: Path, errors: list[str]) -> bool:
    """尺码配对页的车型尺寸演变可视化：开关只在 size-match.html；页面引用的脚本、样式、本地 ECharts 均存在；
    全量分片、尺码规则与店铺货架来自同一 A0 发布版本。没有启用时跳过。"""
    page = site_root / EVOLUTION_PAGE
    text = page.read_text(encoding="utf-8") if page.is_file() else ""
    for other in EVOLUTION_FREE_PAGES:
        other_path = site_root / other
        if other_path.is_file() and "size-evolution" in other_path.read_text(encoding="utf-8"):
            errors.append(f"{other} must not load size-evolution")
    if "size-evolution.js" not in text:
        return False
    if not re.search(r"evolution:\s*\{\s*enabled:\s*true", text):
        errors.append(f"{EVOLUTION_PAGE} loads size-evolution.js without evolution.enabled")
    for required in ("assets/app/size-evolution-data.js", "assets/app/size-evolution.css", "assets/vendor/echarts/echarts.min.js"):
        if required not in text:
            errors.append(f"{EVOLUTION_PAGE} does not reference {required}")
    for relative in sorted(set(ASSET_LINK.findall(text))):
        if not (site_root / relative).is_file():
            errors.append(f"{EVOLUTION_PAGE} references missing asset: {relative}")
    if not (site_root / "assets" / "vendor" / "echarts" / "LICENSE").is_file():
        errors.append("assets/vendor/echarts/LICENSE is missing")
    if not re.search(rf'historyDataPath:\s*"{re.escape(EVOLUTION_HISTORY)}"', text):
        errors.append(f"{EVOLUTION_PAGE} evolution.historyDataPath must be {EVOLUTION_HISTORY}")

    generated = site_root / "data" / "generated"
    # 表格与可视化历史（同一份数据的 A0 版本）、尺码规则、店铺货架必须是同一 A0 版本
    versions = {
        "size-match-data.json a0_version": (read_json(site_root / MATCH_DATA, errors).get("origin") or {}).get("a0_version"),
        "size-rules.json": (read_json(generated / "size-rules.json", errors).get("source") or {}).get("version"),
        "store-groups.json": (read_json(generated / "store-groups.json", errors).get("source") or {}).get("version"),
    }
    if len({version for version in versions.values()}) != 1 or not all(versions.values()):
        errors.append(f"size-match data, rules and store groups come from different A0 versions: {versions}")
    validate_rule_ids(site_root, generated, errors)
    return True


# viewer.js 拆出的模块（数据纯函数 window.SizeViewerData → SIZE 规则 window.SizeViewerRules），须按此顺序先于 viewer.js 加载
VIEWER_MODULES = ["assets/app/viewer-data.js", "assets/app/viewer-rules.js"]


def validate_viewer_data(site_root: Path, errors: list[str]) -> int:
    """加载 viewer.js 的页面必须在它之前按顺序加载 VIEWER_MODULES。返回检查的页面数。"""
    pages = 0
    for page in sorted(site_root.glob("*.html")):
        text = page.read_text(encoding="utf-8")
        viewer = text.find('src="assets/app/viewer.js')
        if viewer < 0:
            continue
        pages += 1
        positions = [text.find(f'src="{module}') for module in VIEWER_MODULES]
        if any(position < 0 for position in positions) or positions != sorted(positions) or positions[-1] > viewer:
            errors.append(f"{page.name} must load {' then '.join(VIEWER_MODULES)} before assets/app/viewer.js")
    for module in VIEWER_MODULES:
        if pages and not (site_root / module).is_file():
            errors.append(f"{module} is missing")
    return pages


def validate_rule_ids(site_root: Path, generated: Path, errors: list[str]) -> None:
    """A0 全量表的 规则ID（命中规则）必须都能在同版本 size-rules.json 对应国别的规则表中找到。"""
    rules = read_json(generated / "size-rules.json", errors).get("regions") or {}
    known = {region: {str(row.get("规则ID") or "") for row in payload.get("rows") or []} - {""} for region, payload in rules.items()}
    manifest_path = site_root / MATCH_DATA
    for source in read_json(manifest_path, errors).get("sources") or []:
        name, region = str(source.get("name") or ""), str(source.get("group") or source.get("name") or "")
        ids = {
            str((record.get("values") or {}).get("规则ID") or "")
            for record in read_source_records(site_root, manifest_path, source, name, errors)
        } - {""}
        unknown = sorted(ids - known.get(region, set()))
        if unknown:
            errors.append(f"{name} 规则ID not found in size-rules.json {region}: {', '.join(unknown[:5])}")


def validate_match_page_views(site_root: Path, errors: list[str]) -> bool:
    """尺码配对页只读一份数据（size-match-data.json），用「视图」控件切换压缩表 / 全量表：页面声明两种 tableModes 与默认视图；
    旧 size-match-code.html 已弃用，不得再发布。页面没有使用该数据时跳过。"""
    page = site_root / MATCH_PAGE
    text = page.read_text(encoding="utf-8") if page.is_file() else ""
    if MATCH_DATA not in text:
        return False
    if not re.search(rf'matchDataPath:\s*"{re.escape(MATCH_DATA)}"', text):
        errors.append(f"{MATCH_PAGE} must use {MATCH_DATA} as matchDataPath")
    modes = re.findall(r'\{\s*key:\s*"(\w+)"', text[text.find("tableModes:"):] if "tableModes:" in text else "")
    if [mode for mode in MATCH_VIEWS if mode not in modes]:
        errors.append(f"{MATCH_PAGE} must declare tableModes for both views: {', '.join(MATCH_VIEWS)}")
    default = re.search(r'defaultTableMode:\s*"(\w+)"', text)
    if not default or default.group(1) not in MATCH_VIEWS:
        errors.append(f"{MATCH_PAGE} must declare defaultTableMode as one of {', '.join(MATCH_VIEWS)}")
    if re.findall(r'(?:matchDataPath|historyDataPath):\s*"([^"]+)"', text).count(MATCH_DATA) != len(re.findall(r'(?:matchDataPath|historyDataPath):', text)):
        errors.append(f"{MATCH_PAGE} must read table and history from the same {MATCH_DATA}")
    if (site_root / "size-match-code.html").exists():
        errors.append("size-match-code.html is deprecated and must not be published")
    return True


def validate_publish_site(site_root: Path) -> dict[str, int]:
    site_root = site_root.resolve()
    config_path = site_root / "config" / "size-chart-view.yaml"
    if not config_path.is_file():
        raise ValueError(f"missing view config: {config_path}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    errors: list[str] = []

    manifest_path = site_root / str((config.get("excel_source") or {}).get("match_data_path") or "data/generated/size-match.json")
    manifest = read_json(manifest_path, errors)
    manifest_sources = {
        str(source.get("name")): source
        for source in manifest.get("sources") or []
        if isinstance(source, dict) and source.get("name")
    }

    total_records = 0
    for configured in config.get("match_sources") or []:
        name = str(configured.get("name") or "")
        source = manifest_sources.get(name)
        if not source:
            errors.append(f"configured source missing from manifest: {name}")
            continue
        required = [column.strip() for column in str(configured.get("columns") or "").split(",") if column.strip()]
        declared = source.get("columns") or manifest.get("columns") or []
        missing_declared = [column for column in required if column not in declared]
        if missing_declared:
            errors.append(f"{name} does not declare required columns: {', '.join(missing_declared)}")

        records = read_source_records(site_root, manifest_path, source, name, errors)
        if not records:
            errors.append(f"source has no records: {name}")
            continue
        if source.get("record_count") is not None and int(source["record_count"]) != len(records):
            errors.append(f"record count mismatch for {name}: manifest={source['record_count']} actual={len(records)}")
        total_records += len(records)
        value_keys = {
            key
            for record in records
            if isinstance(record, dict)
            for key in (record.get("values") or {}).keys()
        }
        missing_values = [column for column in required if column not in value_keys]
        if missing_values:
            errors.append(f"{name} records never provide required fields: {', '.join(missing_values)}")

    reference_path = site_root / str((config.get("size_reference") or {}).get("data_path") or "data/generated/size-ref.json")
    reference = read_json(reference_path, errors)
    reference_rows = reference.get("rows") or []
    if not reference_rows:
        errors.append("size reference has no rows")
    missing_reference = [field for field in REQUIRED_REFERENCE_FIELDS if field not in (reference.get("headers") or [])]
    if missing_reference:
        errors.append(f"size reference is missing required fields: {', '.join(missing_reference)}")

    match_rows = validate_size_match_data(site_root, errors)
    views = validate_match_page_views(site_root, errors)
    evolution = validate_size_evolution(site_root, errors)
    validate_viewer_data(site_root, errors)

    if errors:
        raise ValueError("publish site validation failed:\n- " + "\n- ".join(errors))
    summary = {
        "sources": len(config.get("match_sources") or []),
        "records": total_records,
        "reference_rows": len(reference_rows),
        "match_full_rows": match_rows.get("full", 0),
        "match_compressed_rows": match_rows.get("compressed", 0),
    }
    if evolution:
        summary["evolution"] = 1
    if views:
        summary["match_page_views"] = 1
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a generated pipeline webapp site.")
    parser.add_argument("site_root", type=Path)
    args = parser.parse_args()
    summary = validate_publish_site(args.site_root)
    print(
        f"Validated {summary['sources']} sources, {summary['records']} match records, "
        f"and {summary['reference_rows']} size-reference rows."
        + (" Size evolution visualization assets and versions are consistent." if summary.get("evolution") else "")
    )


if __name__ == "__main__":
    main()

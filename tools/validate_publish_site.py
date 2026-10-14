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


def validate_size_match_code(site_root: Path, errors: list[str]) -> int:
    """尺码配对页的压缩尺码表（size-match-code.json）：清单中每个数据源的 MAKE 分片存在、行数一致、记录带来源行；
    US 区域产线的记录都带 CODE，全局搜索用的 vehicle-codes.json 收录每条记录 CODE 的前四位。"""
    pages = [site_root / "size-match.html", site_root / "size-match-code.html"]
    if not any(page.is_file() and "size-match-code.json" in page.read_text(encoding="utf-8") for page in pages):
        return 0
    manifest_path = site_root / "data" / "generated" / "size-match-code.json"
    manifest = read_json(manifest_path, errors)
    vehicle_codes = read_json(site_root / "data" / "generated" / "vehicle-codes.json", errors).get("codes") or {}
    if "CODE" not in (manifest.get("columns") or []):
        errors.append("size-match-code does not declare CODE column")
    total = 0
    for source in manifest.get("sources") or []:
        name = str(source.get("name") or "")
        records = read_source_records(site_root, manifest_path, source, name, errors)
        if not records:
            errors.append(f"size-match-code source has no records: {name}")
        if source.get("record_count") is not None and int(source["record_count"]) != len(records):
            errors.append(f"size-match-code record count mismatch for {name}")
        if name in CODE_SOURCES and any(not (record.get("values") or {}).get("CODE") for record in records):
            errors.append(f"size-match-code {name} has records without CODE")
        if any(not record.get("sources") for record in records):
            errors.append(f"size-match-code {name} has records without A0 source rows")
        unknown = {code[:4] for record in records if (code := str((record.get("values") or {}).get("CODE") or ""))} - set(vehicle_codes)
        if unknown:
            errors.append(f"vehicle-codes.json is missing {name} code prefixes: {', '.join(sorted(unknown)[:5])}")
        total += len(records)
    if not manifest.get("sources"):
        errors.append("size-match-code has no sources")
    return total


EVOLUTION_PAGE = "size-match.html"
EVOLUTION_FREE_PAGES = ("size-chart.html", "size-charts.html", "size-match-code.html")
EVOLUTION_HISTORY = "data/generated/size-match-full.json"
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
    # 表格（压缩记录的 SHAPE/规则ID 补充所依据的 A0）、可视化历史、尺码规则、店铺货架必须是同一 A0 版本
    versions = {
        "size-match-code.json a0_version": (read_json(generated / "size-match-code.json", errors).get("origin") or {}).get("a0_version"),
        "size-match-full.json": (read_json(generated / "size-match-full.json", errors).get("origin") or {}).get("version"),
        "size-rules.json": (read_json(generated / "size-rules.json", errors).get("source") or {}).get("version"),
        "store-groups.json": (read_json(generated / "store-groups.json", errors).get("source") or {}).get("version"),
    }
    if len({version for version in versions.values()}) != 1 or not all(versions.values()):
        errors.append(f"size-match table, history, rules and store groups come from different A0 versions: {versions}")
    validate_rule_ids(site_root, generated, errors)
    return True


def validate_rule_ids(site_root: Path, generated: Path, errors: list[str]) -> None:
    """A0 全量表的 规则ID（命中规则）必须都能在同版本 size-rules.json 对应国别的规则表中找到。"""
    rules = read_json(generated / "size-rules.json", errors).get("regions") or {}
    known = {region: {str(row.get("规则ID") or "") for row in payload.get("rows") or []} - {""} for region, payload in rules.items()}
    manifest_path = generated / "size-match-full.json"
    for source in read_json(manifest_path, errors).get("sources") or []:
        name, region = str(source.get("name") or ""), str(source.get("group") or source.get("name") or "")
        ids = {
            str((record.get("values") or {}).get("规则ID") or "")
            for record in read_source_records(site_root, manifest_path, source, name, errors)
        } - {""}
        unknown = sorted(ids - known.get(region, set()))
        if unknown:
            errors.append(f"{name} 规则ID not found in size-rules.json {region}: {', '.join(unknown[:5])}")


def validate_merged_match_page(site_root: Path, errors: list[str]) -> bool:
    """尺码配对页只有一张表：A1 压缩尺码表（size-match-code.json），不再有数据视图切换；旧 size-match-code.html 只做跳转。"""
    page = site_root / "size-match.html"
    text = page.read_text(encoding="utf-8") if page.is_file() else ""
    if "size-match-code.json" not in text:
        return False
    if not re.search(r'matchDataPath:\s*"data/generated/size-match-code\.json"', text):
        errors.append("size-match.html must use size-match-code.json as its only table")
    if "datasets:" in text:
        errors.append("size-match.html must not declare switchable data views")
    redirect = site_root / "size-match-code.html"
    if redirect.is_file():
        redirect_text = redirect.read_text(encoding="utf-8")
        if "size-match.html" not in redirect_text or "viewer.js" in redirect_text:
            errors.append("size-match-code.html must only redirect to size-match.html")
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

    code_rows = validate_size_match_code(site_root, errors)
    merged = validate_merged_match_page(site_root, errors)
    evolution = validate_size_evolution(site_root, errors)

    if errors:
        raise ValueError("publish site validation failed:\n- " + "\n- ".join(errors))
    summary = {
        "sources": len(config.get("match_sources") or []),
        "records": total_records,
        "reference_rows": len(reference_rows),
        "code_rows": code_rows,
    }
    if evolution:
        summary["evolution"] = 1
    if merged:
        summary["merged_match_page"] = 1
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

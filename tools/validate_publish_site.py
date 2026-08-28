from __future__ import annotations

import argparse
import json
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

    if errors:
        raise ValueError("publish site validation failed:\n- " + "\n- ".join(errors))
    return {
        "sources": len(config.get("match_sources") or []),
        "records": total_records,
        "reference_rows": len(reference_rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a generated pipeline webapp site.")
    parser.add_argument("site_root", type=Path)
    args = parser.parse_args()
    summary = validate_publish_site(args.site_root)
    print(
        f"Validated {summary['sources']} sources, {summary['records']} match records, "
        f"and {summary['reference_rows']} size-reference rows."
    )


if __name__ == "__main__":
    main()

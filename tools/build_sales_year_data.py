"""Publish verified US annual atoms independently of size-match data."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from build_size_match_data import parse_years, read_verified, slug, write_json
from pipeline_paths import configured_path

DEFAULT_SOURCE = configured_path("sales_output_dir")
SALES_FILE = "原子销量.csv"
US_FILE = "US/全量/全量表.csv"


def number(text: str) -> Decimal | None:
    if not text.strip():
        return None
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"非法销量：{text}") from exc
    if not value.is_finite() or value < 0:
        raise ValueError(f"非法销量（必须非负有限值）：{text}")
    return value


def validate_atoms(rows: list[dict], atoms: list[dict]) -> dict[str, list]:
    dimensions = {}
    for row in rows:
        identity = row["DIMENSION-ID"]
        if identity in dimensions:
            raise ValueError(f"重复尺寸身份：{identity}")
        dimensions[identity] = row
    result = {identity: [] for identity in dimensions}
    seen = set()
    for atom in atoms:
        match = re.fullmatch(r"(.+)\|ATOM_YEAR=(\d{4})", atom["atom_record_id"])
        if not match:
            raise ValueError(f"非法原子年份：{atom['atom_record_id']}")
        identity, year_text = match.groups()
        year = int(year_text)
        if identity not in dimensions:
            raise ValueError(f"孤立原子 ID：{identity}")
        if year not in parse_years(dimensions[identity]["YEAR"]) or not 1886 <= year <= 2100:
            raise ValueError(f"原子年份超出尺寸范围：{atom['atom_record_id']}")
        if (identity, year) in seen:
            raise ValueError(f"重复原子：{atom['atom_record_id']}")
        seen.add((identity, year))
        result[identity].append([year, number(atom["预估销量"])])
    for identity, pairs in result.items():
        if {year for year, _ in pairs} != set(parse_years(dimensions[identity]["YEAR"])):
            raise ValueError(f"原子年份覆盖不完整：{identity}")
        expected = number(dimensions[identity]["尺寸组销量"])
        known = sum((value for _, value in pairs if value is not None), Decimal(0))
        if expected is None or known != expected:
            raise ValueError(f"年度销量与 A0 尺寸组销量不守恒：{identity}，{known} != {expected}")
        pairs.sort()
        result[identity] = [[year, None if value is None else int(value) if value == value.to_integral_value() else float(value)] for year, value in pairs]
    return result


def build(sales_dir: Path, output_dir: Path, a0_dir: Path) -> dict:
    sales_manifest, atoms = read_verified(sales_dir, SALES_FILE)
    a0_manifest, rows = read_verified(a0_dir, US_FILE)
    sales_sha = next(item["sha256"] for item in sales_manifest["deliverables"] if item["file"] == SALES_FILE)
    used = {item["sha256"] for upstream in a0_manifest.get("upstream", []) for item in upstream.get("files", []) if item["file"] == SALES_FILE}
    if used != {sales_sha}:
        raise ValueError("A0 使用的原子销量 SHA256 与本次销量输入不一致，请更新并发布上游 A0")
    records = validate_atoms(rows, atoms)
    groups = defaultdict(list)
    for row in rows:
        groups[("pick" if row["分类"] == "皮卡" else "nonpick", row["MAKE"])].append(row)
    manifest = {
        "format_version": 1, "label": "美国车型预估销量", "unit": "辆",
        "source_aliases": {source: "US" for source in ("US", "HNT", "TM", "TM_拆分")},
        "origin": {"sales_version": sales_manifest["version"], "a0_version": a0_manifest["version"], "sales_sha256": sales_sha,
                   "a0_sha256": next(item["sha256"] for item in a0_manifest["deliverables"] if item["file"] == US_FILE)},
        "atom_count": len(atoms), "record_count": len(records), "make_groups": [],
    }
    # Validation completes before writing any output, including obsolete-shard cleanup.
    output_dir.mkdir(parents=True, exist_ok=True)
    current = set()
    for (kind, make), items in sorted(groups.items()):
        models = defaultdict(list)
        for row in items:
            models[row["MODEL"]].append(row["DIMENSION-ID"])
        payload = {"kind": kind, "make": make, "models": dict(models), "records": {row["DIMENSION-ID"]: records[row["DIMENSION-ID"]] for row in items}}
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
        name = f"sales-year-{kind}-{slug(make)}-{digest}.json"
        current.add(name)
        write_json(output_dir / name, payload)
        manifest["make_groups"].append({"kind": kind, "make": make, "records_path": name, "record_count": len(items)})
    write_json(output_dir / "sales-year-data.json", manifest)
    for old in output_dir.glob("sales-year-*.json"):
        if old.name != "sales-year-data.json" and old.name not in current:
            old.unlink()
    return manifest

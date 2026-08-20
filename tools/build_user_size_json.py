from __future__ import annotations

import argparse
import csv
import json
import os
import urllib.request
import time
import re
from collections import Counter
from pathlib import Path

import yaml

from build_user_size_templates import configured_stores


NON_COLUMNS = ["店铺","CAR","MAKE","MODEL","YEAR","VERSION","CONST","BACKSIZE","CATAGORY","LONG-TYPE","TYPE","SHORT-MODEL","SIZE"]
PICK_COLUMNS = ["店铺","MAKE","MODEL","YEAR","VERSION","CAB","BED","BACKSIZE","SHORT-CAB","TITLE","DESCRIPTION","SIZE"]


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file, delimiter="\t"))


def read_optional_tsv(path: Path) -> list[dict[str, str]]:
    return read_tsv(path) if path.is_file() else []


def compact_table(columns: list[str], rows: list[dict[str, str]]) -> dict:
    return {"columns": columns, "rows": [[row.get(column, "") for column in columns] for row in rows]}


def ai_abbreviations(
    candidates: dict[str, list[str]],
    ai_config: dict,
    examples: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]] | None:
    if not ai_config.get("enabled", False):
        return None
    configured_key = str(ai_config.get("api_key", "")).strip()
    api_key_env = str(ai_config.get("api_key_env", "AI_API_KEY")).strip()
    # Also tolerate a literal key accidentally placed in api_key_env.
    env_name_is_valid = bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", api_key_env))
    api_key = configured_key or (os.environ.get(api_key_env, "").strip() if env_name_is_valid else api_key_env)
    if not api_key:
        counts = ", ".join(f"{kind}={len(values)}" for kind, values in candidates.items())
        print(f"AI abbreviation skipped: no API key configured via api_key or {api_key_env} ({counts}).")
        return None
    limits = {key: int(value) for key, value in ai_config.get("max_length", {}).items()}
    endpoint = str(ai_config["base_url"]).rstrip("/") + "/chat/completions"
    model = str(ai_config["model"])
    batch_size = int(ai_config.get("batch_size", 10))
    retries = int(ai_config.get("retries", 2))
    accepted: dict[str, dict[str, str]] = {kind: {} for kind in candidates}
    for kind, values in candidates.items():
        for start in range(0, len(values), batch_size):
            batch = values[start : start + batch_size]
            prompt = (
                f"Return only a JSON object mapping every input string to its abbreviation. Category={kind}. "
                "Preserve automotive meaning, slash grouping, model identity, and the style of the replacement "
                f"examples. Every result MUST be at most {limits[kind]} characters including spaces and punctuation; "
                "omit secondary Incl: qualifiers when necessary to satisfy the hard limit. Examples: "
                f"{json.dumps(examples[kind], ensure_ascii=False)}. Input: {json.dumps(batch, ensure_ascii=False)}"
            )
            body = json.dumps({
                "model": model,
                "temperature": 0,
                "enable_thinking": bool(ai_config.get("enable_thinking", False)),
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            }).encode("utf-8")
            request = urllib.request.Request(endpoint, data=body, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
            for attempt in range(retries + 1):
                try:
                    with urllib.request.urlopen(request, timeout=int(ai_config.get("timeout_seconds", 120))) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                    result = json.loads(payload["choices"][0]["message"]["content"])
                    accepted[kind].update({source: short.strip() for source, short in result.items() if source in batch and isinstance(short, str) and 0 < len(short.strip()) <= limits[kind]})
                    print(f"AI abbreviation {kind}: batch {start // batch_size + 1}, accepted {len(accepted[kind])}/{len(values)}")
                    break
                except (TimeoutError, OSError, KeyError, ValueError, json.JSONDecodeError):
                    if attempt >= retries:
                        raise
                    time.sleep(2 ** attempt)
    return accepted


def build(case_name: str, compress_root: Path, config: Path, rules_path: Path, ai_config_path: Path, selected_sheets: set[str] | None = None) -> dict:
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    ai_config = yaml.safe_load(ai_config_path.read_text(encoding="utf-8")) or {}
    limits = {key: int(value) for key, value in ai_config.get("max_length", {}).items()}
    sizes = rules["size"]
    model_map = {**rules["model_abbreviations"], **rules.get("ai_cache", {}).get("model", {})}
    cab_map = {**rules["cab_abbreviations"], **rules.get("ai_cache", {}).get("cab", {})}
    type_cache = rules.get("ai_cache", {}).get("type", {})
    rejected = rules.get("ai_rejected", {"model": [], "type": [], "cab": []})
    retry_rejected = bool(ai_config.get("retry_rejected", False))
    type_rows = rules["type_abbreviations"]
    category_rank = {value: index for index, value in enumerate(rules["category_order"])}
    pickup_front = {(row["MAKE"], row["MODEL"]): row for row in rules["pickup_front"]}
    pickup_description = {}
    for row in rules["pickup_front"]:
        pickup_description.setdefault(row["MAKE"], row.get("DESCRIPTION", ""))

    non_pickup: list[dict[str, str]] = []
    pickup: list[dict[str, str]] = []
    stores = configured_stores(config)
    if selected_sheets is not None:
        unknown = selected_sheets - {sheet for _, sheet in stores}
        if unknown:
            raise ValueError(f"Unknown configured sheets: {sorted(unknown)}")
        stores = [(store, sheet) for store, sheet in stores if sheet in selected_sheets]
    for store, input_sheet in stores:
        stem = f"{case_name}_{input_sheet}"
        folder = compress_root / stem / "compress"
        non_rows = read_optional_tsv(folder / f"{stem}_非皮卡高度压缩表.tsv")
        const_counts = Counter(row.get("CAR", "") for row in non_rows)
        distinct_consts: dict[str, set[str]] = {}
        for row in non_rows:
            distinct_consts.setdefault(row.get("CAR", ""), set()).add(row.get("CONST", ""))
        for row in non_rows:
            car, const, version = row.get("CAR", ""), row.get("CONST", ""), row.get("VERSION", "")
            long_type = version.strip() if len(distinct_consts.get(car, set())) == 1 else " ".join(x for x in (const.strip(), version.strip()) if x)
            matches = [item for item in type_rows if item["long"].strip() == long_type.strip() and item["car"].strip() in ("", car.strip())]
            matches.sort(key=lambda item: item["car"].strip() == car.strip(), reverse=True)
            size = sizes.get(row.get("BACKSIZE", ""), {})
            derived = {**row, "店铺": store, "CATAGORY": size.get("category", ""), "LONG-TYPE": long_type, "TYPE": type_cache.get(long_type, matches[0]["short"] if matches else long_type), "SHORT-MODEL": model_map.get(row.get("MODEL", ""), row.get("MODEL", "")), "SIZE": size.get("generic", "")}
            non_pickup.append(derived)

        for row in read_optional_tsv(folder / f"{stem}_皮卡高度压缩表.tsv"):
            front = pickup_front.get((row.get("MAKE", ""), row.get("MODEL", "")), {})
            size = sizes.get(row.get("BACKSIZE", ""), {})
            pickup.append({**row, "店铺": store, "SHORT-CAB": cab_map.get(row.get("CAB", ""), row.get("CAB", "")), "TITLE": front.get("TITLE", f"{row.get('MAKE','')} {row.get('MODEL','')}".strip()), "DESCRIPTION": pickup_description.get(row.get("MAKE", ""), ""), "SIZE": size.get("generic", "")})

    candidates = {
        "model": sorted({row["MODEL"] for row in non_pickup if row["SHORT-MODEL"] == row["MODEL"] and len(row["MODEL"]) > limits.get("model", 12) and (retry_rejected or row["MODEL"] not in rejected.get("model", []))}),
        "type": sorted({row["LONG-TYPE"] for row in non_pickup if row["TYPE"] == row["LONG-TYPE"] and len(row["LONG-TYPE"]) > limits.get("type", 18) and (retry_rejected or row["LONG-TYPE"] not in rejected.get("type", []))}),
        "cab": sorted({row["CAB"] for row in pickup if row["SHORT-CAB"] == row["CAB"] and len(row["CAB"]) > limits.get("cab", 15) and (retry_rejected or row["CAB"] not in rejected.get("cab", []))}),
    }
    examples = {
        "model": dict(list(rules["model_abbreviations"].items())[:30]),
        "type": {item["long"]: item["short"] for item in rules["type_abbreviations"] if not item["car"] and item["short"]} ,
        "cab": rules["cab_abbreviations"],
    }
    enriched = ai_abbreviations(candidates, ai_config, examples)
    if enriched is not None and any(candidates.values()):
        cache = rules.setdefault("ai_cache", {"model": {}, "type": {}, "cab": {}})
        rejected_store = rules.setdefault("ai_rejected", {"model": [], "type": [], "cab": []})
        for kind, values in enriched.items():
            cache.setdefault(kind, {}).update(values)
            rejected_store[kind] = sorted(set(rejected_store.get(kind, [])) | (set(candidates[kind]) - set(values)))
        rules_path.write_text(json.dumps(rules, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        for row in non_pickup:
            row["SHORT-MODEL"] = cache["model"].get(row["MODEL"], row["SHORT-MODEL"])
            row["TYPE"] = cache["type"].get(row["LONG-TYPE"], row["TYPE"])
        for row in pickup:
            row["SHORT-CAB"] = cache["cab"].get(row["CAB"], row["SHORT-CAB"])

    def year_key(value: str) -> tuple[int, str]:
        head = value.split("-", 1)[0].strip()
        return (int(head) if head.isdigit() else 9999, value)
    non_pickup.sort(key=lambda row: (row.get("MAKE", ""), row.get("MODEL", ""), category_rank.get(row.get("CATAGORY", ""), 999), year_key(row.get("YEAR", ""))))
    pickup.sort(key=lambda row: (row.get("TITLE", ""), row.get("MODEL", ""), year_key(row.get("YEAR", "")), row.get("CAB", ""), row.get("BED", "")))
    return {"version": 1, "non_pickup": compact_table(NON_COLUMNS, non_pickup), "pickup": compact_table(PICK_COLUMNS, pickup)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build sorted user-size data directly as compact JSON.")
    parser.add_argument("--case-name", required=True)
    parser.add_argument("--compress-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--ai-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sheet", action="append", help="Only rebuild this configured sheet (repeatable).")
    args = parser.parse_args()
    selected = set(args.sheet) if args.sheet else None
    result = build(args.case_name, args.compress_root, args.config, args.rules, args.ai_config, selected)
    if selected and args.output.is_file():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        selected_stores = {store for store, sheet in configured_stores(args.config) if sheet in selected}
        for table_name in ("non_pickup", "pickup"):
            columns = previous[table_name]["columns"]
            store_index = columns.index("店铺")
            kept = [row for row in previous[table_name]["rows"] if row[store_index] not in selected_stores]
            result[table_name]["rows"] = kept + result[table_name]["rows"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"User-size JSON written: {args.output}" + (f" (updated: {', '.join(args.sheet)})" if args.sheet else ""))


if __name__ == "__main__":
    main()

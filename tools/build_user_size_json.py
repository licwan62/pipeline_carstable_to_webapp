from __future__ import annotations

import argparse
import csv
import json
import os
import urllib.request
import time
import re
from pathlib import Path

import yaml

NON_COLUMNS = ["店铺","CAR","MAKE","MODEL","YEAR","VERSION","CONST","SIZE","SIZE-CODE","CATAGORY","LONG-TYPE","TYPE","SHORT-MODEL"]
PICK_COLUMNS = ["店铺","MAKE","MODEL","YEAR","VERSION","CAB","BED","SIZE","SIZE-CODE","SHORT-CAB","TITLE","DESCRIPTION"]
UNPUBLISHABLE_SIZES = {"", "无可用尺码", "数据不全"}

def _replace_type_terms(value: str, replacements: dict[str, str]) -> str:
    result = value.strip()
    for source, replacement in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = re.escape(source)
        if source[-1:].isalnum():
            pattern = rf"\b{pattern}\b"
        elif source.endswith(":"):
            pattern = rf"{pattern}\s*"
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", result).strip()


def _compact_token(token: str, max_length: int) -> str:
    if len(token) <= max_length:
        return token
    consonants = token[:1] + re.sub(r"[aeiou]", "", token[1:], flags=re.IGNORECASE)
    return consonants[:max_length]


INC_MARKER = "Inc:"


def normalize_inc_marker(value: str) -> str:
    """网站 TYPE 的包含标记统一写作 Inc:（inc:/INC: 等大小写变体一律改写）。"""
    return re.sub(r"(?<![A-Za-z])inc:", INC_MARKER, value, flags=re.IGNORECASE)


def compact_type(value: str, max_length: int, abbreviation_rules: dict) -> str:
    return compact_type_detail(value, max_length, abbreviation_rules)[0]


def compact_type_detail(value: str, max_length: int, abbreviation_rules: dict) -> tuple[str, bool]:
    """Apply JSON-maintained structure abbreviations and a strict length limit.

    Returns (TYPE, lossy)。lossy=True 表示词表缩写后仍超长，走了去 Inc:、删字母或截断，需人工确认。
    """
    structure_terms = abbreviation_rules.get("structure_terms", {})
    qualifier_terms = abbreviation_rules.get("qualifier_terms", {})
    result = _replace_type_terms(value, structure_terms)
    result = _replace_type_terms(result, {"Incl:": qualifier_terms.get("Incl:", "Inc:")})
    if len(result) <= max_length:
        return result, False
    result = _replace_type_terms(result, qualifier_terms)
    if len(result) <= max_length:
        return result, False

    # Keep the configured structure spelling intact. If necessary, remove the
    # inclusion marker before shortening version names.
    without_marker = result.replace(" Inc:", " ")
    if len(without_marker) <= max_length:
        return without_marker, True
    result = without_marker
    structure, separator, suffix = result.partition(" ")
    if not separator:
        return result[:max_length], True

    parts = re.split(r"([/ ])", suffix)
    while len(structure) + 1 + len("".join(parts)) > max_length:
        candidates = [(len(part), index) for index, part in enumerate(parts) if part not in {"/", " "} and len(part) > 2]
        if not candidates:
            break
        _, index = max(candidates)
        parts[index] = _compact_token(parts[index], len(parts[index]) - 1)
    result = structure + " " + "".join(parts)
    return (result if len(result) <= max_length else result[:max_length]), True


TYPE_CONFIRM_COLUMNS = ["LONG-TYPE", "自动TYPE", "确认TYPE", "店铺", "示例"]


def load_type_confirmations(path: Path, max_length: int) -> dict[str, str]:
    """人工确认表：LONG-TYPE -> 确认TYPE（空值表示待确认）。"""
    if not path.is_file():
        return {}
    rows = read_csv(path)
    if rows and not {"LONG-TYPE", "确认TYPE"}.issubset(rows[0]):
        raise ValueError(f"Type confirmation table lacks LONG-TYPE/确认TYPE: {path}")
    confirmed = {row["LONG-TYPE"].strip(): normalize_inc_marker(row["确认TYPE"].strip()) for row in rows if row["LONG-TYPE"].strip() and row["确认TYPE"].strip()}
    too_long = {long: short for long, short in confirmed.items() if len(short) > max_length}
    if too_long:
        raise ValueError(f"确认TYPE 超过 {max_length} 个字符：{too_long}")
    return confirmed


def type_confirm_pending(non_pickup: list[dict[str, str]]) -> list[dict[str, str]]:
    """汇总需人工确认的类型（每个 LONG-TYPE 一行）。"""
    pending: dict[str, dict[str, set[str] | str]] = {}
    for row in non_pickup:
        if not row.get("_TYPE-LOSSY"):
            continue
        item = pending.setdefault(row["LONG-TYPE"], {"自动TYPE": row["TYPE"], "店铺": set(), "示例": set()})
        item["店铺"].add(row["店铺"])  # type: ignore[union-attr]
        item["示例"].add(f"{row.get('CAR', '')} {row.get('YEAR', '')}".strip())  # type: ignore[union-attr]
    return [
        {"LONG-TYPE": long, "自动TYPE": item["自动TYPE"], "确认TYPE": "", "店铺": "|".join(sorted(item["店铺"])), "示例": "|".join(sorted(item["示例"])[:3])}  # type: ignore[arg-type]
        for long, item in sorted(pending.items())
    ]


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def long_type_for_row(row: dict[str, str], multiple_sizes: bool) -> str:
    const = row.get("CONST", "").strip()
    version = row.get("VERSION", "").strip()
    return " ".join(value for value in ((const if multiple_sizes else ""), version) if value)


def expanded_years(value: str) -> tuple[str, ...]:
    text = value.strip()
    match = re.fullmatch(r"(\d{4})(?:-(\d{4}))?", text)
    if not match:
        return (text,)
    start = int(match.group(1))
    end = int(match.group(2) or start)
    return tuple(str(year) for year in range(start, end + 1))


def load_runtime_config(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if path.suffix.casefold() == ".json" else (yaml.safe_load(text) or {})


def configured_stores(config_path: Path) -> list[tuple[str, str]]:
    configured = list((load_runtime_config(config_path).get("input") or {}).get("stores") or [])
    if not configured:
        raise ValueError(f"No input.stores configured in {config_path}")
    stores = [(str(store["store"]), str(store["sheet"])) for store in configured]
    if len({store for store, _ in stores}) != len(stores):
        raise ValueError(f"Configured inputs produce duplicate store names: {stores}")
    return stores


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def read_optional_csv(path: Path) -> list[dict[str, str]]:
    return read_csv(path) if path.is_file() else []


def compact_table(columns: list[str], rows: list[dict[str, str]]) -> dict:
    return {"columns": columns, "rows": [[row.get(column, "") for column in columns] for row in rows]}


def normalized_size(row: dict[str, str], sizes: dict[str, dict]) -> tuple[str, str, dict]:
    """Return canonical SIZE, SIZE-CODE, and size metadata.

    New compressed tables provide SIZE/SIZE-CODE. BACKSIZE remains a read-only
    compatibility fallback for older compressor output.
    SIZE-CODE 取 configs/user-size-rules.json 的 generic（对照表见 configs/size-code.csv）；
    对照表之外的尺码直接用通用尺码名作代码，不可发布的占位尺码保持为空。
    """
    size_value = row.get("SIZE", "").strip() or row.get("BACKSIZE", "").strip()
    metadata = sizes.get(size_value, {})
    size_code = row.get("SIZE-CODE", "").strip() or str(metadata.get("generic", "")).strip()
    if not size_code and size_value not in UNPUBLISHABLE_SIZES:
        size_code = size_value
    return size_value, size_code, metadata


def load_size_code_map(path: Path, category: str = "皮卡") -> dict[str, str]:
    """新通用尺码 -> 尺码代码（A2 输出的 SIZE 已是新通用尺码）。

    只取该分类的行：映射表 2 的非皮卡代码与站点现行代码（configs/size-code.csv）不一致。
    """
    rows = read_csv(path)
    required = {"分类", "新通用尺码", "尺码代码"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"Size-code mapping lacks required columns {sorted(required)}: {path}")
    return {
        row["新通用尺码"].strip(): row["尺码代码"].strip()
        for row in rows
        if row["分类"].strip() == category and row["新通用尺码"].strip() and row["尺码代码"].strip()
    }


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


def build(compress_root: Path, config: Path, rules_path: Path, size_code_map_path: Path, type_abbreviations_path: Path, type_confirm_path: Path, ai_config_path: Path, selected_stores: set[str] | None = None) -> dict:
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    type_abbreviations = json.loads(type_abbreviations_path.read_text(encoding="utf-8"))
    size_code_map = load_size_code_map(size_code_map_path)
    ai_config = yaml.safe_load(ai_config_path.read_text(encoding="utf-8")) or {}
    limits = {key: int(value) for key, value in ai_config.get("max_length", {}).items()}
    type_confirmed = load_type_confirmations(type_confirm_path, limits.get("type", 16))
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
    if selected_stores is not None:
        unknown = selected_stores - {store for store, _ in stores}
        if unknown:
            raise ValueError(f"Unknown configured stores: {sorted(unknown)}")
        stores = [(store, sheet) for store, sheet in stores if store in selected_stores]
    for store, _input_sheet in stores:
        stem = store
        folder = compress_root / stem / "compress"
        non_rows = read_optional_csv(folder / f"{stem}_非皮卡高度压缩表.csv")
        sizes_by_model_year: dict[tuple[str, str, str], set[str]] = {}
        for row in non_rows:
            size_value, _size_code, _size = normalized_size(row, sizes)
            make_model = (row.get("MAKE", "").strip(), row.get("MODEL", "").strip())
            for year in expanded_years(row.get("YEAR", "")):
                sizes_by_model_year.setdefault((*make_model, year), set()).add(size_value)
        for row in non_rows:
            car = row.get("CAR", "")
            make_model = (row.get("MAKE", "").strip(), row.get("MODEL", "").strip())
            multiple_sizes = any(len(sizes_by_model_year.get((*make_model, year), set())) > 1 for year in expanded_years(row.get("YEAR", "")))
            long_type = long_type_for_row(row, multiple_sizes)
            matches = [item for item in type_rows if item["long"].strip() == long_type.strip() and item["car"].strip() in ("", car.strip())]
            matches.sort(key=lambda item: item["car"].strip() == car.strip(), reverse=True)
            size_value, size_code, size = normalized_size(row, sizes)
            mapped_type = type_cache.get(long_type, matches[0]["short"] if matches else long_type)
            if long_type in type_confirmed:
                short_type, lossy = type_confirmed[long_type], False
            else:
                short_type, lossy = compact_type_detail(mapped_type, limits.get("type", 16), type_abbreviations)
            derived = {**row, "店铺": store, "SIZE": size_value, "SIZE-CODE": size_code, "CATAGORY": size.get("category", ""), "LONG-TYPE": long_type, "TYPE": normalize_inc_marker(short_type), "_TYPE-LOSSY": lossy, "SHORT-MODEL": model_map.get(row.get("MODEL", ""), row.get("MODEL", ""))}
            non_pickup.append(derived)

        for row in read_optional_csv(folder / f"{stem}_皮卡高度压缩表.csv"):
            front = pickup_front.get((row.get("MAKE", ""), row.get("MODEL", "")), {})
            size_value, size_code, _size = normalized_size(row, sizes)
            size_code = size_code_map.get(size_value, size_code)
            pickup.append({**row, "店铺": store, "SIZE": size_value, "SIZE-CODE": size_code, "SHORT-CAB": cab_map.get(row.get("CAB", ""), row.get("CAB", "")), "TITLE": front.get("TITLE", f"{row.get('MAKE','')} {row.get('MODEL','')}".strip()), "DESCRIPTION": pickup_description.get(row.get("MAKE", ""), "")})

    candidates = {
        "model": sorted({row["MODEL"] for row in non_pickup if row["SHORT-MODEL"] == row["MODEL"] and len(row["MODEL"]) > limits.get("model", 12) and (retry_rejected or row["MODEL"] not in rejected.get("model", []))}),
        "type": [],
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
            if row["LONG-TYPE"] not in type_confirmed:
                row["TYPE"], row["_TYPE-LOSSY"] = compact_type_detail(cache["type"].get(row["LONG-TYPE"], row["TYPE"]), limits.get("type", 16), type_abbreviations)
                row["TYPE"] = normalize_inc_marker(row["TYPE"])
        for row in pickup:
            row["SHORT-CAB"] = cache["cab"].get(row["CAB"], row["SHORT-CAB"])

    def year_key(value: str) -> tuple[int, str]:
        head = value.split("-", 1)[0].strip()
        return (int(head) if head.isdigit() else 9999, value)
    non_pickup.sort(key=lambda row: (row.get("MAKE", ""), row.get("MODEL", ""), category_rank.get(row.get("CATAGORY", ""), 999), year_key(row.get("YEAR", ""))))
    pickup.sort(key=lambda row: (row.get("TITLE", ""), row.get("MODEL", ""), year_key(row.get("YEAR", "")), row.get("CAB", ""), row.get("BED", "")))
    return {"version": 2, "non_pickup": compact_table(NON_COLUMNS, non_pickup), "pickup": compact_table(PICK_COLUMNS, pickup), "_type_pending": type_confirm_pending(non_pickup)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build sorted user-size data directly as compact JSON.")
    parser.add_argument("--compress-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--size-code-map", type=Path, required=True)
    parser.add_argument("--type-abbreviations", type=Path, required=True)
    parser.add_argument("--type-confirm", type=Path, required=True, help="人工确认表 LONG-TYPE -> 确认TYPE")
    parser.add_argument("--type-pending-output", type=Path, help="写出本次待人工确认的类型清单")
    parser.add_argument("--ai-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--store", action="append", help="Only rebuild this configured store (repeatable).")
    args = parser.parse_args()
    selected = set(args.store) if args.store else None
    result = build(args.compress_root, args.config, args.rules, args.size_code_map, args.type_abbreviations, args.type_confirm, args.ai_config, selected)
    pending = result.pop("_type_pending")
    if args.type_pending_output:
        write_csv(args.type_pending_output, TYPE_CONFIRM_COLUMNS, pending)
    if pending:
        print(f"TYPE 待人工确认：{len(pending)} 个（填写 {args.type_confirm} 的 确认TYPE 列）")
    if selected and args.output.is_file():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        selected_store_names = set(selected)
        for table_name in ("non_pickup", "pickup"):
            columns = previous[table_name]["columns"]
            store_index = columns.index("店铺")
            kept = [row for row in previous[table_name]["rows"] if row[store_index] not in selected_store_names]
            result[table_name]["rows"] = kept + result[table_name]["rows"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"User-size JSON written: {args.output}" + (f" (updated: {', '.join(args.store)})" if args.store else ""))


if __name__ == "__main__":
    main()

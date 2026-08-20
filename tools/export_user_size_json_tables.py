from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

SIZE_FREE_STORES = {"TM-拆分"}
SIZE_COLUMNS = {"BACKSIZE", "SIZE"}

def records(table: dict) -> list[dict[str, str]]:
    columns = table["columns"]
    return [dict(zip(columns, row)) for row in table["rows"]]


def write_tsv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export compact user-size JSON into per-store TSV files.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--store", action="append", help="Only export this store (repeatable).")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    non_rows = records(payload["non_pickup"])
    pick_rows = records(payload["pickup"])
    stores = sorted({row["店铺"] for row in [*non_rows, *pick_rows] if row.get("店铺")})
    if args.store:
        stores = [store for store in stores if store in set(args.store)]
    for store in stores:
        if store in SIZE_FREE_STORES:
            non = [row for row in non_rows if row.get("店铺") == store]
            pick = [row for row in pick_rows if row.get("店铺") == store]
            non_columns = [column for column in payload["non_pickup"]["columns"] if column not in SIZE_COLUMNS]
            pick_columns = [column for column in payload["pickup"]["columns"] if column not in SIZE_COLUMNS]
        else:
            non = [row for row in non_rows if row.get("店铺") == store and row.get("SIZE") not in ("", "无可用尺码") and row.get("BACKSIZE") != "无可用尺码"]
            pick = [row for row in pick_rows if row.get("店铺") == store and row.get("SIZE") not in ("", "无可用尺码") and row.get("BACKSIZE") != "无可用尺码"]
            non_columns = payload["non_pickup"]["columns"]
            pick_columns = payload["pickup"]["columns"]
        write_tsv(args.output_root / store / "non_pickup.tsv", non, non_columns)
        write_tsv(args.output_root / store / "pickup.tsv", pick, pick_columns)
        print(f"{store}: non-pickup={len(non)}, pickup={len(pick)}")


if __name__ == "__main__":
    main()

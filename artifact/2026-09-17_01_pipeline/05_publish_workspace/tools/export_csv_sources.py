from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from export_xlsx_sources import normalize_match_rows, parse_yaml_config, write_match_payloads


ROOT = Path(__file__).resolve().parents[1]
VIEW_CONFIG = ROOT / "config" / "size-chart-view.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export frontend query JSON from normalized CSV sources.")
    parser.add_argument("--pipeline-config", type=Path, required=True)
    args = parser.parse_args()

    pipeline_path = args.pipeline_config.resolve()
    pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
    view = parse_yaml_config(VIEW_CONFIG)
    stores = list((pipeline.get("input") or {}).get("stores") or [])
    if not stores:
        raise ValueError(f"No input.stores configured in {pipeline_path}")

    exported = []
    all_columns: list[str] = []
    for store in stores:
        csv_path = (pipeline_path.parent / str(store["path"])).resolve()
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        columns = [column for column in str(store.get("columns") or "").split(",") if column]
        if not columns:
            columns = ["MODEL", "YEAR", "TYPE", "CAB", "BED", "SIZE"]
        for column in columns:
            if column not in all_columns:
                all_columns.append(column)
        exported.append(
            {
                "name": str(store["store"]),
                "label": str(store.get("label") or store["store"]),
                "sheet": str(store["sheet"]),
                "columns": columns,
                "records": normalize_match_rows(str(store["store"]), rows),
            }
        )

    match_path = ROOT / str((view.get("excel_source") or {})["match_data_path"])
    write_match_payloads(match_path, all_columns, exported)


if __name__ == "__main__":
    main()

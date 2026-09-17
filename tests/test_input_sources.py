from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import openpyxl
import yaml

from run_all import build_variables, scan_cases, selected_step_names
from tools.build_publish_site import configure_csv_sources
from tools.build_user_size_json import configured_stores
from tools.materialize_input_sources import materialize_inputs


def write_config(path: Path, input_dir: Path, artifact_root: Path, public_dir: Path) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "paths": {
                    "input_dir": str(input_dir),
                    "artifact_root": str(artifact_root),
                    "public_dir": str(public_dir),
                    "logs_dir": str(path.parent / "logs"),
                },
                "file_rules": {"input_patterns": ["*.xlsx", "*.csv"]},
                "input": {
                    "case_name": "combined",
                    "header_aliases": {"S8MAKE": "MAKE"},
                    "store": {
                        "store": "{stem}",
                        "label": "{stem}尺码匹配表",
                        "sheet": "{stem}尺码匹配",
                        "header_row": 1,
                        "columns": "MODEL,YEAR,SIZE",
                    },
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


class InputMaterializationTests(unittest.TestCase):
    def test_csv_and_excel_inputs_are_materialized_as_csv_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            input_dir = root / "input"
            input_dir.mkdir()
            (input_dir / "ALL.csv").write_text(
                "MAKE,MODEL,YEAR,确认尺码\nAcura,ADX,2025-2026,YL\n",
                encoding="utf-8-sig",
            )
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.title = "原始数据"
            sheet.append(["MAKE", "MODEL", "YEAR", "确认尺码"])
            sheet.append(["Tesla", "Model Y", "2025", "3XL"])
            workbook.save(input_dir / "TM.xlsx")

            config_path = root / "pipeline.yaml"
            write_config(config_path, input_dir, root / "artifact", root / "public")
            output_dir = root / "artifact" / "batch" / "00_input" / "tables"
            output_config = root / "artifact" / "batch" / "00_input" / "pipeline.generated.json"

            stores = materialize_inputs(input_dir, config_path, output_dir, output_config)

            self.assertEqual([store["file"] for store in stores], ["ALL.csv", "TM.xlsx"])
            self.assertEqual([store["store"] for store in stores], ["ALL", "TM"])
            self.assertEqual([store["path"] for store in stores], ["tables/001-ALL.csv", "tables/002-TM.csv"])
            self.assertFalse(any(output_dir.parent.rglob("*.xlsx")))
            with (output_dir / "001-ALL.csv").open(encoding="utf-8-sig", newline="") as handle:
                self.assertEqual(list(csv.reader(handle))[1][1], "ADX")
            with (output_dir / "002-TM.csv").open(encoding="utf-8-sig", newline="") as handle:
                self.assertEqual(list(csv.reader(handle))[1][1], "Model Y")

            runtime = json.loads(output_config.read_text(encoding="utf-8"))
            self.assertNotIn("match_sources", runtime["input"])
            self.assertEqual([store["store"] for store in runtime["input"]["stores"]], ["ALL", "TM"])
            self.assertEqual(
                configured_stores(output_config),
                [("ALL", "ALL尺码匹配"), ("TM", "TM尺码匹配")],
            )

    def test_header_aliases_are_applied_before_required_field_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            input_dir = root / "input"
            input_dir.mkdir()
            (input_dir / "TM拆.csv").write_text(
                "S8MAKE,MODEL,YEAR,确认尺码\nAcura,RL,1996-1998,3XXXL-0\n",
                encoding="utf-8",
            )
            config_path = root / "pipeline.yaml"
            write_config(config_path, input_dir, root / "artifact", root / "public")
            output_dir = root / "tables"
            materialize_inputs(input_dir, config_path, output_dir, root / "runtime.json")

            with next(output_dir.glob("*.csv")).open(encoding="utf-8-sig", newline="") as handle:
                headers = next(csv.reader(handle))
            self.assertEqual(headers[0], "MAKE")

    def test_missing_required_fields_fail_at_input_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            input_dir = root / "input"
            input_dir.mkdir()
            (input_dir / "broken.csv").write_text(
                "MAKE,MODEL,YEAR\nAcura,ADX,2025\n", encoding="utf-8"
            )
            config_path = root / "pipeline.yaml"
            write_config(config_path, input_dir, root / "artifact", root / "public")
            with self.assertRaisesRegex(ValueError, "最终尺码"):
                materialize_inputs(input_dir, config_path, root / "tables", root / "runtime.json")

    def test_scan_cases_groups_inputs_into_selected_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            input_dir = root / "input"
            input_dir.mkdir()
            (input_dir / "ALL.csv").touch()
            (input_dir / "TM.csv").touch()
            config_path = root / "pipeline.yaml"
            write_config(config_path, input_dir, root / "artifact", root / "public")
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            artifact_dir = root / "artifact" / "2026-09-17_01_pipeline"

            [case] = scan_cases(config, artifact_dir)

            self.assertEqual(case["case_name"], "combined")
            self.assertEqual([path.name for path in case["input_files"]], ["ALL.csv", "TM.csv"])
            self.assertEqual(case["input_tables_dir"], artifact_dir / "00_input" / "tables")
            self.assertEqual(case["pipeline_config"], artifact_dir / "00_input" / "pipeline.generated.json")

    def test_publish_config_keeps_generated_source_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            workspace = root / "workspace"
            (workspace / "config").mkdir(parents=True)
            (workspace / "config" / "size-chart-view.yaml").write_text(
                "size_reference:\n  sheet: ALL尺码\n  data_path: data/generated/size-ref.json\n",
                encoding="utf-8",
            )
            pipeline_config = root / "pipeline.generated.json"
            pipeline_config.write_text(
                json.dumps(
                    {
                        "input": {
                            "stores": [
                                {
                                    "store": "新分析0831",
                                    "label": "新分析0831尺码匹配表",
                                    "sheet": "新分析0831尺码匹配",
                                    "header_row": 2,
                                    "columns": "MODEL,YEAR,SIZE",
                                    "path": "tables/001-新分析0831.csv",
                                }
                            ]
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            configure_csv_sources(workspace, pipeline_config)

            view = yaml.safe_load((workspace / "config" / "size-chart-view.yaml").read_text(encoding="utf-8"))
            self.assertEqual(
                view["match_sources"],
                [
                    {
                        "name": "新分析0831",
                        "label": "新分析0831尺码匹配表",
                        "sheet": "新分析0831尺码匹配",
                        "header_row": 2,
                        "columns": "MODEL,YEAR,SIZE",
                    }
                ],
            )

    def test_old_step_names_map_to_canonical_names(self) -> None:
        config = {
            "steps": {
                "normalize_store_inputs": {"enabled": True},
                "compress_store_fitment": {"enabled": True},
                "build_user_size_json": {"enabled": True},
                "export_store_csv": {"enabled": True},
                "generate_store_html": {"enabled": True},
                "build_public_site": {"enabled": True},
            }
        }
        self.assertEqual(
            selected_step_names(config, from_step="user_size_json", to_step="get_html"),
            {"build_user_size_json", "export_store_csv", "generate_store_html"},
        )

    def test_existing_artifact_uses_legacy_stage_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            artifact_dir = root / "artifact" / "old"
            (artifact_dir / "04_html").mkdir(parents=True)
            config = {
                "paths": {
                    "input_dir": str(root / "input"),
                    "public_dir": str(root / "public"),
                    "logs_dir": str(root / "logs"),
                },
                "variables": {"store_html_dir": "{artifact_dir}/04_store_html"},
            }
            case = {
                "case_name": "combined",
                "input_tables_dir": artifact_dir / "00_input" / "tables",
                "pipeline_config": artifact_dir / "00_input" / "pipeline.generated.json",
                "case_middle": artifact_dir,
                "artifact_dir": artifact_dir,
                "case_public": root / "public",
            }

            variables = build_variables(case, config)

            self.assertEqual(Path(variables["store_html_dir"]), artifact_dir / "04_html")


if __name__ == "__main__":
    unittest.main()

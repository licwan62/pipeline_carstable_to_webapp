from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.validate_publish_site import validate_publish_site


class PublishSiteValidationTests(unittest.TestCase):
    def test_validates_split_source_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "data" / "generated").mkdir(parents=True)
            (root / "config" / "size-chart-view.yaml").write_text(
                """excel_source:
  match_data_path: data/generated/size-match.json
match_sources:
  - name: ALL
    columns: MODEL,L-MM,W-MM,H-MM,SIZE
size_reference:
  data_path: data/generated/size-ref.json
""",
                encoding="utf-8",
            )
            manifest = {
                "format_version": 3,
                "columns": ["MODEL", "L-MM", "W-MM", "H-MM", "SIZE"],
                "sources": [
                    {
                        "name": "ALL",
                        "columns": ["MODEL", "L-MM", "W-MM", "H-MM", "SIZE"],
                        "record_count": 1,
                        "make_groups": [
                            {
                                "make": "Acura",
                                "records_path": "size-match-001-all-001-acura-a1b2c3d4e5f6.json",
                                "record_count": 1,
                            }
                        ],
                    }
                ],
            }
            source = {
                "name": "ALL",
                "make": "Acura",
                "records": [
                    {"values": {"MODEL": "ADX", "L-MM": "4719", "W-MM": "1842", "H-MM": "1621", "SIZE": "YL"}}
                ],
            }
            reference = {
                "headers": ["型号", "长_mm", "宽_mm", "高_mm"],
                "rows": [{"型号": "YL", "长_mm": "5000", "宽_mm": "2000", "高_mm": "1800"}],
            }
            generated = root / "data" / "generated"
            (generated / "size-match.json").write_text(json.dumps(manifest), encoding="utf-8")
            (generated / "size-match-001-all-001-acura-a1b2c3d4e5f6.json").write_text(
                json.dumps(source), encoding="utf-8"
            )
            (generated / "size-ref.json").write_text(json.dumps(reference), encoding="utf-8")

            self.assertEqual(
                validate_publish_site(root),
                {"sources": 1, "records": 1, "reference_rows": 1},
            )


if __name__ == "__main__":
    unittest.main()

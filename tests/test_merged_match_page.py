from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import build_publish_site
from tools.validate_publish_site import validate_merged_match_page

ROOT = Path(__file__).resolve().parents[1]

PAGE = """<!doctype html>
<html><head><link rel="stylesheet" href="assets/app/viewer.css?v=old"></head><body>
  <script>
    window.SIZE_CHART_VIEWER = {
      pageMode: "search",
      sizeRefPath: "data/generated/size-ref.json",
      directories: []
    };
  </script>
  <script src="assets/app/viewer.js?v=old"></script>
</body></html>
"""


def match_page(override: str = build_publish_site.MATCH_PAGE_OVERRIDE) -> str:
    marker = 'sizeRefPath: "data/generated/size-ref.json",\n'
    return PAGE.replace(marker, marker + override)


class MergedMatchPageTests(unittest.TestCase):
    def test_override_uses_compressed_table_for_all_sources(self) -> None:
        override = build_publish_site.MATCH_PAGE_OVERRIDE
        # 唯一表格：A1 压缩尺码表，CODE 在前，含 SHAPE 与长度余量；US 全量、店铺、EU、RU 六个数据源，没有视图切换
        self.assertIn('matchDataPath: "data/generated/size-match-code.json"', override)
        self.assertNotIn("datasets:", override)
        self.assertIn('fieldOrder: ["CODE"', override)
        for column in ('"SHAPE"', '"长度余量"'):
            self.assertIn(column, override)
        for source in ("US", "HNT", "TM", "TM_拆分", "EU", "RU"):
            self.assertIn(f'{{ name: "{source}"', override)

    def test_validator_accepts_single_table_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "size-match.html").write_text(match_page(), encoding="utf-8")
            errors: list[str] = []
            self.assertTrue(validate_merged_match_page(root, errors))
            self.assertEqual(errors, [])

    def test_validator_rejects_switchable_views(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            override = '      datasets: [{ key: "code", matchDataPath: "data/generated/size-match-code.json" }],\n'
            (root / "size-match.html").write_text(match_page(override), encoding="utf-8")
            errors: list[str] = []
            validate_merged_match_page(root, errors)
            self.assertEqual(errors, ["size-match.html must not declare switchable data views"])

    def test_validator_rejects_deprecated_code_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "size-match.html").write_text(match_page(), encoding="utf-8")
            (root / "size-match-code.html").write_text(PAGE, encoding="utf-8")
            errors: list[str] = []
            validate_merged_match_page(root, errors)
            self.assertIn("size-match-code.html is deprecated and must not be published", errors)

    def test_code_page_is_not_in_overrides(self) -> None:
        self.assertFalse((ROOT / "site_overrides" / "size-match-code.html").exists())

    def test_viewer_has_no_view_toggle(self) -> None:
        viewer = (ROOT / "site_overrides" / "assets" / "app" / "viewer.js").read_text(encoding="utf-8")
        self.assertNotIn("config.datasets", viewer)
        self.assertNotIn("data-dataset", viewer)
        # 可视化：压缩记录按来源行（产线 + DIMENSION-ID）对应 A0 全量历史；SHAPE 小字 + 悬停中文说明
        self.assertIn("function evolutionRefs", viewer)
        self.assertIn("evolutionConfig.historyDataPath", viewer)
        self.assertIn("function bindShapeHovers", viewer)


if __name__ == "__main__":
    unittest.main()

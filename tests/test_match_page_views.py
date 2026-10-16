"""尺码配对页设计验收（结构层）：一份数据 size-match-data.json，「视图」控件切换压缩表 / 全量表，可视化历史读同一份数据。

需求编号见 docs/size-match-acceptance.md（R1 两种视图、R2 同一数据源、R3 搜索按字段语义、R6 旧页面弃用）。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import build_publish_site
from tools.validate_publish_site import validate_match_page_views

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


def match_page(override: str = build_publish_site.MATCH_PAGE_OVERRIDE, evolution: str = build_publish_site.EVOLUTION_CONFIG) -> str:
    marker = 'sizeRefPath: "data/generated/size-ref.json",\n'
    return PAGE.replace(marker, marker + override).replace("window.SIZE_CHART_VIEWER = {\n", "window.SIZE_CHART_VIEWER = {\n" + evolution)


def validate(text: str, *, code_page: bool = False) -> list[str]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "size-match.html").write_text(text, encoding="utf-8")
        if code_page:
            (root / "size-match-code.html").write_text(PAGE, encoding="utf-8")
        errors: list[str] = []
        validate_match_page_views(root, errors)
        return errors


class MatchPageViewsTests(unittest.TestCase):
    def test_override_declares_both_views_on_one_data_source(self) -> None:
        override = build_publish_site.MATCH_PAGE_OVERRIDE
        # R1：压缩表与全量表两种视图，默认压缩表；R2：只有一个数据路径
        self.assertIn('matchDataPath: "data/generated/size-match-data.json"', override)
        self.assertIn('{ key: "compressed", label: "压缩表" }', override)
        self.assertIn('{ key: "full", label: "全量表" }', override)
        self.assertIn('defaultTableMode: "compressed"', override)
        self.assertIn('historyDataPath: "data/generated/size-match-data.json"', build_publish_site.EVOLUTION_CONFIG)
        self.assertIn('fieldOrder: ["CODE"', override)
        for column in ('"SHAPE"', '"长度余量"'):
            self.assertIn(column, override)
        for source in ("US", "HNT", "TM", "TM_拆分", "EU", "RU"):
            self.assertIn(f'{{ name: "{source}"', override)

    def test_validator_accepts_built_page(self) -> None:
        self.assertEqual(validate(match_page()), [])

    def test_validator_requires_both_views(self) -> None:
        override = build_publish_site.MATCH_PAGE_OVERRIDE.replace('        { key: "full", label: "全量表" }\n', "")
        self.assertIn("size-match.html must declare tableModes for both views: compressed, full", validate(match_page(override)))

    def test_validator_rejects_separate_history_data(self) -> None:
        evolution = build_publish_site.EVOLUTION_CONFIG.replace("size-match-data.json", "size-match-full.json")
        self.assertIn("size-match.html must read table and history from the same data/generated/size-match-data.json",
                      validate(match_page(evolution=evolution)))

    def test_validator_rejects_deprecated_code_page(self) -> None:
        self.assertIn("size-match-code.html is deprecated and must not be published", validate(match_page(), code_page=True))

    def test_code_page_is_not_in_overrides(self) -> None:
        self.assertFalse((ROOT / "site_overrides" / "size-match-code.html").exists())

    def test_viewer_switches_views_without_refetching(self) -> None:
        viewer = (ROOT / "site_overrides" / "assets" / "app" / "viewer.js").read_text(encoding="utf-8")
        # 视图控件、?view= 直达、分片缓存与视图无关（cacheKey 不含视图），切换只改 searchState.tableMode
        self.assertIn("data-table-mode", viewer)
        self.assertIn('get("view")', viewer)
        self.assertIn("const cacheKey = `${manifestPath}|${source.name}|${shard.records_path || \"inline\"}`;", viewer)
        self.assertIn("function currentView(index)", viewer)
        # 可视化历史永远读全量行；压缩记录按来源行（产线 + DIMENSION-ID）对应历史
        self.assertIn("index.full.records", viewer)
        self.assertIn("function evolutionRefs", viewer)
        self.assertIn("function bindShapeHovers", viewer)
        # R3：全局搜索按字段语义匹配，不再整行子串匹配
        self.assertIn("recordMatchesSearchToken(record, token, shapeLabels)", viewer)
        self.assertNotIn("haystack.includes(token)", viewer)


if __name__ == "__main__":
    unittest.main()

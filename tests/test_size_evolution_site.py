from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools import build_publish_site
from tools.validate_publish_site import validate_size_evolution

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / "site_overrides"

MATCH_PAGE = """<!doctype html>
<html lang="en">
<head>
  <link rel="stylesheet" href="assets/app/viewer.css?v=old">
</head>
<body>
  <div id="app"></div>
  <script>
    window.SIZE_CHART_VIEWER = {
      pageMode: "search",
      directories: []
    };
  </script>
  <script src="assets/app/viewer.js?v=old"></script>
</body>
</html>
"""


def write_site(root: Path, *, rules_version: str = "20261013_12") -> None:
    for relative in build_publish_site.EVOLUTION_ASSETS:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(OVERRIDES / relative, target)
    for name in ("viewer.js", "viewer.css"):
        (root / "assets" / "app" / name).write_text("", encoding="utf-8")
    (root / "size-match.html").write_text(MATCH_PAGE, encoding="utf-8")
    (root / "size-chart.html").write_text(MATCH_PAGE, encoding="utf-8")
    generated = root / "data" / "generated"
    generated.mkdir(parents=True)
    origin = {"node": "size-calculation", "version": "20261013_12"}
    # 一份数据（A0 全量行 + A1 压缩记录）：version 为 A1 版本，a0_version 为全量行所依据的 A0 版本
    data_origin = {"node": "size-compression", "version": "20261013_08", "a0_version": "20261013_12"}
    (generated / "size-match-data.json").write_text(json.dumps({"origin": data_origin}), encoding="utf-8")
    (generated / "size-rules.json").write_text(json.dumps({"source": {**origin, "version": rules_version}}), encoding="utf-8")
    (generated / "store-groups.json").write_text(json.dumps({"source": origin}), encoding="utf-8")


class SizeEvolutionSiteTests(unittest.TestCase):
    def test_overrides_contain_visualization_sources(self) -> None:
        for relative in [*build_publish_site.EVOLUTION_ASSETS, "assets/app/viewer.js", "assets/app/viewer.css"]:
            self.assertTrue((OVERRIDES / relative).is_file(), relative)
        viewer = (OVERRIDES / "assets" / "app" / "viewer.js").read_text(encoding="utf-8")
        # 可视化由页面开关启用，viewer 仍保留现有检索、复制、SIZE hover 等实现
        self.assertIn("config.evolution", viewer)
        for existing in ("function copyResultRow", "function bindSizeReferenceHovers", "function renderResultsOutline", "function sizeRuleFor"):
            self.assertIn(existing, viewer)

    def test_injects_only_size_match_page_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_site(root)
            build_publish_site.add_size_evolution(root)
            build_publish_site.add_size_evolution(root)
            build_publish_site.stamp_asset_versions(root)
            page = (root / "size-match.html").read_text(encoding="utf-8")
            version = build_publish_site.ASSET_VERSION
            self.assertEqual(page.count("size-evolution.js"), 1)
            self.assertIn("enabled: true", page)
            self.assertIn(f"assets/vendor/echarts/echarts.min.js?v={version}", page)
            # 可视化历史读表格同一份数据（size-match-data.json 的全量行），不另发一套全量分片
            self.assertIn('historyDataPath: "data/generated/size-match-data.json"', page)
            self.assertIn(f"assets/app/viewer.js?v={version}", page)
            # 可视化脚本在 viewer.js 之前加载
            self.assertLess(page.index("size-evolution.js"), page.index("assets/app/viewer.js"))
            self.assertNotIn("size-evolution", (root / "size-chart.html").read_text(encoding="utf-8"))
            errors: list[str] = []
            self.assertTrue(validate_size_evolution(root, errors))
            self.assertEqual(errors, [])

    def test_missing_override_assets_fail_build(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_site(root)
            (root / "assets" / "vendor" / "echarts" / "echarts.min.js").unlink()
            with self.assertRaises(FileNotFoundError):
                build_publish_site.add_size_evolution(root)

    def test_validator_rejects_mixed_a0_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_site(root, rules_version="20261010_01")
            build_publish_site.add_size_evolution(root)
            errors: list[str] = []
            validate_size_evolution(root, errors)
            self.assertTrue(any("different A0 versions" in error for error in errors))

    def test_validator_rejects_evolution_on_other_pages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_site(root)
            build_publish_site.add_size_evolution(root)
            shutil.copy2(root / "size-match.html", root / "size-chart.html")
            errors: list[str] = []
            validate_size_evolution(root, errors)
            self.assertIn("size-chart.html must not load size-evolution", errors)


if __name__ == "__main__":
    unittest.main()

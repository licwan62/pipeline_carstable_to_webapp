"""viewer.js 拆出的模块（viewer-data.js 数据纯函数 → viewer-rules.js SIZE 规则）必须在每个加载 viewer.js 的页面中按顺序先于 viewer.js 加载。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import build_publish_site as site
from tools.validate_publish_site import validate_viewer_data

PAGE = '<html><body>\n  <script src="assets/app/viewer.js?v=old"></script>\n</body></html>\n'


def make_site(root: Path, with_asset: bool = True) -> Path:
    (root / "assets" / "app").mkdir(parents=True)
    if with_asset:
        for asset in site.VIEWER_MODULES:
            (root / asset).write_text("//", encoding="utf-8")
    for name in ("size-match.html", "size-chart.html"):
        (root / name).write_text(PAGE, encoding="utf-8")
    (root / "index.html").write_text("<html><body>home</body></html>", encoding="utf-8")
    return root


def test_injects_before_viewer_once_and_validator_accepts(tmp_path):
    root = make_site(tmp_path)
    site.add_viewer_module_scripts(root)
    site.add_viewer_module_scripts(root)
    text = (root / "size-match.html").read_text(encoding="utf-8")
    assert text.count("viewer-data.js") == 1 and text.count("viewer-rules.js") == 1
    assert text.index("viewer-data.js") < text.index("viewer-rules.js") < text.index("viewer.js")
    assert "  <script src=\"assets/app/viewer-data.js" in text, "沿用 viewer.js 标签的缩进"
    assert "  <script src=\"assets/app/viewer-rules.js" in text
    assert "viewer-data.js" not in (root / "index.html").read_text(encoding="utf-8")
    errors: list[str] = []
    assert validate_viewer_data(root, errors) == 2
    assert errors == []


def test_page_with_only_viewer_data_gets_rules_module_in_order(tmp_path):
    """旧页面已加载 viewer-data.js 时只补 viewer-rules.js，仍在 viewer.js 之前、viewer-data.js 之后。"""
    root = make_site(tmp_path)
    old = PAGE.replace('  <script src="assets/app/viewer.js', '  <script src="assets/app/viewer-data.js?v=old"></script>\n  <script src="assets/app/viewer.js')
    (root / "size-match.html").write_text(old, encoding="utf-8")
    site.add_viewer_data_script(root)  # 旧名仍可用
    text = (root / "size-match.html").read_text(encoding="utf-8")
    assert text.count("viewer-data.js") == 1
    assert text.index("viewer-data.js") < text.index("viewer-rules.js") < text.index("viewer.js")


def test_validator_rejects_missing_or_misordered_modules(tmp_path):
    root = make_site(tmp_path)
    (root / "size-chart.html").write_text(PAGE.replace("</body>", '  <script src="assets/app/viewer-data.js"></script>\n</body>'), encoding="utf-8")
    swapped = PAGE.replace(
        '  <script src="assets/app/viewer.js',
        '  <script src="assets/app/viewer-rules.js"></script>\n  <script src="assets/app/viewer-data.js"></script>\n  <script src="assets/app/viewer.js',
    )
    (root / "size-charts.html").write_text(swapped, encoding="utf-8")
    errors: list[str] = []
    validate_viewer_data(root, errors)
    assert {name for name in ("size-match.html", "size-chart.html", "size-charts.html") if any(name in e for e in errors)} == {
        "size-match.html", "size-chart.html", "size-charts.html"}
    (root / site.VIEWER_RULES_ASSET).unlink()
    errors = []
    validate_viewer_data(root, errors)
    assert f"{site.VIEWER_RULES_ASSET} is missing" in errors


@pytest.mark.parametrize("asset", [site.VIEWER_DATA_ASSET, site.VIEWER_RULES_ASSET])
def test_missing_asset_fails_build(tmp_path, asset):
    root = make_site(tmp_path)
    (root / asset).unlink()
    with pytest.raises(FileNotFoundError):
        site.add_viewer_module_scripts(root)


def test_overrides_ship_viewer_modules():
    overrides = Path(site.__file__).resolve().parents[1] / "site_overrides"
    for asset in site.VIEWER_MODULES:
        assert (overrides / asset).is_file()

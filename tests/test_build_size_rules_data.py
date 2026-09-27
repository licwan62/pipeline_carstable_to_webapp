import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_size_rules_data as mod  # noqa: E402

import hashlib


def report(region, rules, shelf=""):
    """最小化的 A0 尺码匹配报告：规则表在“## 尺码规则”下，US 另有店铺货架表。"""
    return (
        f"# {region} 尺码匹配报告\n\n## 匹配概况\n\n| 指标 | 数值 |\n| --- | --- |\n| 车型数 | 1 |\n\n"
        + shelf
        + f"\n## 尺码规则\n\n来源：`data/{region}/规则/x.csv`（1 条）。\n\n{rules}"
    )


def make_source(tmp_path, tamper=False):
    shelf = "### 店铺货架（匹配尺码 → 发货尺码）\n\n| 店铺 | 匹配尺码 | 发货尺码 |\n| --- | --- | --- |\n| HNT | 2M | 2M |\n"
    files = {
        "US/尺码匹配报告.md": report("US", "| 尺码 | 分类 | 备注 |\n| --- | --- | --- |\n| 2M | 两厢车 | a\\|b |\n", shelf),
        "EU/尺码匹配报告.md": report("EU", "| 尺码 | 分类 |\n| --- | --- |\n| 2M | 两厢车 |\n"),
        "RU/尺码匹配报告.md": report("RU", "| 亚马逊尺码 | OZON尺码 |\n| --- | --- |\n| 2M | 2XS |\n"),
    }
    deliverables = []
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(text.encode())
        deliverables.append({"file": name, "sha256": hashlib.sha256(text.encode()).hexdigest()})
    if tamper:
        (tmp_path / "US/尺码匹配报告.md").write_text(files["US/尺码匹配报告.md"].replace("HNT", "TM"), encoding="utf-8")
    manifest = {"node": "size-calculation", "version": "20260921_08", "published_at": "2026-09-21T00:00:00", "deliverables": deliverables}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_build_writes_three_independent_regions_and_stores(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    make_source(src)
    counts = mod.build(src, out)
    rules = json.loads((out / "size-rules.json").read_text(encoding="utf-8"))
    groups = json.loads((out / "store-groups.json").read_text(encoding="utf-8"))
    assert counts == {"US": 1, "EU": 1, "RU": 1, "stores": 1}
    assert rules["regions"]["RU"]["headers"] == ["亚马逊尺码", "OZON尺码"]
    assert groups["stores"]["HNT"] == [{"匹配尺码": "2M", "发货尺码": "2M"}]
    assert rules["regions"]["US"]["rows"] == [{"尺码": "2M", "分类": "两厢车", "备注": "a|b"}]


def test_build_rejects_hash_mismatch(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_source(src, tamper=True)
    with pytest.raises(ValueError, match="sha256"):
        mod.build(src, tmp_path / "out")

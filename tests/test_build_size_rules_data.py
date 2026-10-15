import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_size_rules_data as mod  # noqa: E402

import hashlib


def report(region, rules, shelf="", tolerance=""):
    """最小化的 A0 尺码匹配报告：规则表在“## 尺码规则”的“### 规则表（N 条）”子节，其后是参数表；US 另有店铺货架表。"""
    return (
        f"# {region} 尺码匹配报告\n\n## 匹配概况\n\n| 指标 | 数值 |\n| --- | --- |\n| 车型数 | 1 |\n\n"
        + shelf
        + f"\n## 尺码规则\n\n来源：`data/{region}/规则/x.csv`。\n\n### 计算量\n\n- 说明\n\n{tolerance}### 规则表（1 条）\n\n{rules}"
        + "\n### 参数\n\n| 参数 | 值 |\n| --- | --- |\n| 余量 | 550 |\n"
    )


def make_source(tmp_path, tamper=False):
    shelf = "### 店铺货架（匹配尺码 → 发货尺码）\n\n| 店铺 | 匹配尺码 | 发货尺码 |\n| --- | --- | --- |\n| HNT | 2M | 2M |\n"
    files = {
        "US/尺码匹配报告.md": report(
            "US", "| 尺码 | 分类 | 备注 |\n| --- | --- | --- |\n| 2M | 两厢车 | a\\|b |\n", shelf,
            "### 选码\n\n3. 且 `长上限 − 长` ≤ 余量长容差 **550 mm**；\n\n",
        ),
        "EU/尺码匹配报告.md": report("EU", "| 尺码 | 分类 |\n| --- | --- |\n| 2M | 两厢车 |\n"),
        "RU/尺码匹配报告.md": report(
            "RU", "| 亚马逊尺码 | OZON尺码 |\n| --- | --- |\n| 2M | 2XS |\n", "",
            "- 规则表没有该列时统一用参数 余量长容差 635 mm。\n\n",
        ),
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
    assert counts == {"US": 1, "EU": 1, "RU": 1, "stores": 1, "interface": "markdown-legacy"}
    assert rules["regions"]["RU"]["headers"] == ["亚马逊尺码", "OZON尺码"]
    assert groups["stores"]["HNT"] == [{"匹配尺码": "2M", "发货尺码": "2M"}]
    assert rules["regions"]["US"]["rows"] == [{"尺码": "2M", "分类": "两厢车", "备注": "a|b"}]
    assert [rules["regions"][r]["length_tolerance"] for r in ("US", "EU", "RU")] == [550, None, 635]


def test_build_rejects_hash_mismatch(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_source(src, tamper=True)
    with pytest.raises(ValueError, match="sha256"):
        mod.build(src, tmp_path / "out")


def add_json_interface(src, *, eu_tolerance=None):
    """A0 2026-10-14 起的机器接口：<国别>/尺码规则.json 与 US/店铺货架.json（内容与 make_source 的 md 表格同源）。"""
    payloads = {
        "US/尺码规则.json": {"headers": ["尺码", "分类", "备注"], "rules": [{"尺码": "2M", "分类": "两厢车", "备注": "a|b"}], "length_tolerance_mm": 550},
        "EU/尺码规则.json": {"headers": ["尺码", "分类"], "rules": [{"尺码": "2M", "分类": "两厢车"}], "length_tolerance_mm": eu_tolerance},
        "RU/尺码规则.json": {"headers": ["亚马逊尺码", "OZON尺码"], "rules": [{"亚马逊尺码": " 2M ", "OZON尺码": "2XS"}], "length_tolerance_mm": 635},
        "US/店铺货架.json": {"stores": {"HNT": [{"匹配尺码": "2M", "发货尺码": "2M"}]}},
    }
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    for name, payload in payloads.items():
        data = json.dumps(payload, ensure_ascii=False).encode()
        (src / name).write_bytes(data)
        manifest["deliverables"].append({"file": name, "sha256": hashlib.sha256(data).hexdigest()})
    (src / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_json_interface_matches_markdown_interface(tmp_path):
    md_src, json_src = tmp_path / "md", tmp_path / "json"
    md_src.mkdir()
    json_src.mkdir()
    make_source(md_src)
    make_source(json_src)
    add_json_interface(json_src)
    assert mod.build(json_src, tmp_path / "out_json")["interface"] == "json"
    mod.build(md_src, tmp_path / "out_md")
    from_json = json.loads((tmp_path / "out_json" / "size-rules.json").read_text(encoding="utf-8"))
    from_md = json.loads((tmp_path / "out_md" / "size-rules.json").read_text(encoding="utf-8"))
    assert {r: v.pop("file") for r, v in from_json["regions"].items()} == {r: f"{r}/尺码规则.json" for r in ("US", "EU", "RU")}
    for value in from_md["regions"].values():
        value.pop("file")
    assert from_json == from_md
    assert (tmp_path / "out_json" / "store-groups.json").read_bytes() == (tmp_path / "out_md" / "store-groups.json").read_bytes()


def test_json_interface_is_verified_and_strict_mode_rejects_markdown(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_source(src)
    with pytest.raises(ValueError, match="未发布"):
        mod.build(src, tmp_path / "out", allow_markdown=False)
    add_json_interface(src)
    (src / "US/店铺货架.json").write_bytes(b'{"stores": {}}')
    with pytest.raises(ValueError, match="sha256"):
        mod.build(src, tmp_path / "out")

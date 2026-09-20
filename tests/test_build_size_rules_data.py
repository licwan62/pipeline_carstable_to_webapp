import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_size_rules_data as mod  # noqa: E402

import hashlib


def make_source(tmp_path, tamper=False):
    files = {
        "尺码匹配规则.csv": "尺码,分类\n2M,两厢车\n",
        "尺码匹配规则_EU.csv": "尺码,分类\n2M,两厢车\n",
        "尺码匹配规则_RU.csv": "亚马逊尺码,OZON尺码\n2M,2XS\n",
        "店铺货架.csv": "店铺,匹配尺码,发货尺码\nHNT,2M,2M\n",
    }
    deliverables = []
    for name, text in files.items():
        (tmp_path / name).write_bytes(text.encode())
        deliverables.append({"file": name, "sha256": hashlib.sha256(text.encode()).hexdigest()})
    if tamper:
        (tmp_path / "店铺货架.csv").write_text("店铺,匹配尺码,发货尺码\nHNT,3L,3L\n", encoding="utf-8")
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


def test_build_rejects_hash_mismatch(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_source(src, tamper=True)
    with pytest.raises(ValueError, match="sha256"):
        mod.build(src, tmp_path / "out")

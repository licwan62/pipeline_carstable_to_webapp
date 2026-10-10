import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_size_match_data as mod  # noqa: E402

HEADER = "MAKE,MODEL,结构,CAB,BED,YEAR,分类,自动尺码,自动长度余量,DIMENSION-CODE,DIMENSION-ID\n"


def write_source(folder, files):
    folder.mkdir()
    deliverables = []
    for name, text in files.items():
        data = text.encode()
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
        deliverables.append({"file": name, "sha256": hashlib.sha256(data).hexdigest()})
    (folder / "manifest.json").write_text(
        json.dumps({"node": "n", "version": "v", "published_at": "t", "deliverables": deliverables}), encoding="utf-8")


def test_us_stores_and_eu_sources(tmp_path):
    regions = {
        "US": HEADER + "Acura,ADX,SUV,,,2025-2026,越野车,YL,131,C1,Acura ADX 2025-2026 US\n",
        "EU": HEADER + "Citroen,GS,Hatch,,,1970-1977,两厢车,2M,53,C2,Citroen GS 1970-1977 EU\n"
              + "Citroen,C35,Chassis Cab,,,1974-1992,皮卡,PK-X,10,C4,Citroen C35 1974-1992 EU\n",
        "RU": HEADER + "Ru,X,SUV,,,2020,越野车,YM,1,C3,Ru X 2020 RU\n",
    }
    store = HEADER + "Acura,ADX,SUV,,,2025-2026,越野车,YM,131,C1,Acura ADX 2025-2026 US\n"
    write_source(tmp_path / "a0", {**{mod.REGION_FILES[r]: text for r, text in regions.items()},
                                   **{name: store for name in mod.STORES.values()}})
    counts = mod.build(tmp_path / "a0", tmp_path / "out")
    assert counts == {"US": 1, "HNT": 1, "TM": 1, "TM_拆分": 1, "EU": 2, "RU": 1}
    manifest = json.loads((tmp_path / "out" / "size-match-full.json").read_text(encoding="utf-8"))
    assert [(s["name"], s["group"]) for s in manifest["sources"]] == [
        ("US", "US"), ("HNT", "US"), ("TM", "US"), ("TM_拆分", "US"), ("EU", "EU"), ("RU", "RU")]
    shard = json.loads((tmp_path / "out" / manifest["sources"][1]["make_groups"][0]["records_path"]).read_text(encoding="utf-8"))
    assert shard["records"][0]["values"]["SIZE"] == "YM" and shard["records"][0]["years"] == [2025, 2026]
    # 分类为皮卡的（EU Chassis Cab 也算）归皮卡分片，与非皮卡分开检索
    eu = manifest["sources"][4]
    assert [(g["kind"], g["make"]) for g in eu["make_groups"]] == [("nonpick", "Citroen"), ("pick", "Citroen")]
    assert eu["kind_counts"] == {"nonpick": 1, "pick": 1}
    pick = json.loads((tmp_path / "out" / eu["make_groups"][1]["records_path"]).read_text(encoding="utf-8"))
    assert pick["kind"] == "pick" and [r["kind"] for r in pick["records"]] == ["pick"]
    # A0 已取消 DIMENSION-CODE，尺码配对不再有 CODE 列（代号见压缩代号页）
    assert "CODE" not in manifest["columns"] and "CODE" not in shard["records"][0]["values"]


def test_renamed_sales_column_fills_sales_total():
    record = mod.to_record({"MAKE": "Acura", "MODEL": "ADX", "YEAR": "2025", "尺寸组销量": "131"}, "US")
    assert record["values"]["销量合计"] == "131"

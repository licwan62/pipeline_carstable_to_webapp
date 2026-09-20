import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_size_match_data as mod  # noqa: E402

HEADER = "MAKE,MODEL,结构,CAB,BED,YEAR,自动尺码,自动长度余量,DIMENSION-CODE,DIMENSION-ID\n"


def write_source(folder, files):
    folder.mkdir()
    deliverables = []
    for name, text in files.items():
        data = text.encode()
        (folder / name).write_bytes(data)
        deliverables.append({"file": name, "sha256": hashlib.sha256(data).hexdigest()})
    (folder / "manifest.json").write_text(
        json.dumps({"node": "n", "version": "v", "published_at": "t", "deliverables": deliverables}), encoding="utf-8")


def test_us_stores_and_eu_sources(tmp_path):
    summary = HEADER + "Acura,ADX,SUV,,,2025-2026,YL,131,C1,Acura ADX 2025-2026 US\nCitroen,GS,Hatch,,,1970-1977,2M,53,C2,Citroen GS 1970-1977 EU\nRu,X,SUV,,,2020,YM,1,C3,Ru X 2020 RU\n"
    store = HEADER + "Acura,ADX,SUV,,,2025-2026,YM,131,C1,Acura ADX 2025-2026 US\n"
    write_source(tmp_path / "a1", {"全量表_汇总.csv": summary})
    write_source(tmp_path / "a0", {name: store for name in mod.STORES.values()})
    counts = mod.build(tmp_path / "a1", tmp_path / "out", tmp_path / "a0")
    assert counts == {"US": 1, "HNT": 1, "TM": 1, "TM_拆分": 1, "EU": 1, "RU": 1}
    manifest = json.loads((tmp_path / "out" / "size-match-full.json").read_text(encoding="utf-8"))
    assert [(s["name"], s["group"]) for s in manifest["sources"]] == [
        ("US", "US"), ("HNT", "US"), ("TM", "US"), ("TM_拆分", "US"), ("EU", "EU"), ("RU", "RU")]
    shard = json.loads((tmp_path / "out" / manifest["sources"][1]["make_groups"][0]["records_path"]).read_text(encoding="utf-8"))
    assert shard["records"][0]["values"]["SIZE"] == "YM" and shard["records"][0]["years"] == [2025, 2026]
    assert shard["records"][0]["values"]["CODE"] == "C1"

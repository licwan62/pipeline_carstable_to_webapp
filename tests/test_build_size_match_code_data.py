import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_size_match_code_data as mod  # noqa: E402

DIMS = "最大长-MM,最大长年份,最小长-MM,最小长年份,最大宽-MM,最大宽年份,最小宽-MM,最小宽年份,最大高-MM,最大高年份,最小高-MM,最小高年份"
NONPICK = (f"CODE,CAR,MAKE,MODEL,YEAR,VERSION,CONST,BACKSIZE,尺码销量总和,{DIMS}\n"
           "25112526,Acura ADX,Acura,ADX,2025-2026,,SUV,YL,40266,4719,2026,4700,2025,1842,2025-2026,1842,2025-2026,1621,2025-2026,1621,2025-2026\n")
PICK = (f"CODE,CAR,MAKE,MODEL,YEAR,VERSION,CAB,BED,BACKSIZE,尺码销量总和,{DIMS}\n"
        "14160206,CadillacEscalade EXT,Cadillac,Escalade EXT,2002-2006,,Crew,5.3,PK-M,49173,"
        "5621,2002-2006,5621,2002-2006,2004,2002-2006,2004,2002-2006,1897,2002-2006,1897,2002-2006\n")
SOURCES = ("压缩类型,记录序号,DIMENSION-ID,MAKE,MODEL,版本,结构,CAB,BED,YEAR,L-MM,W-MM,H-MM\n"
           "非皮卡,1,Acura ADX SUV 2025 US,Acura,ADX,,SUV,,,2025,4700,1842,1621\n"
           "非皮卡,1,Acura ADX SUV 2026 US,Acura,ADX,,SUV,,,2026,4719,1842,1621\n"
           "皮卡,1,Cadillac Escalade EXT Pickup 2002-2006 Crew US,Cadillac,Escalade EXT,,Pickup,Crew,5.3,2002-2006,5621,2004,1897\n")


def write_a2(folder: Path, nonpick: str = NONPICK, sources: str = SOURCES) -> None:
    deliverables = []
    for line in mod.LINES:
        for name, text in [*((name, PICK if pickup else nonpick) for name, pickup in mod.TABLES), (mod.SOURCES_FILE, sources)]:
            data = text.encode()
            path = folder / line / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            deliverables.append({"file": f"{line}/{name}", "sha256": hashlib.sha256(data).hexdigest()})
    (folder / "manifest.json").write_text(
        json.dumps({"node": "size-compression", "version": "v", "published_at": "t", "deliverables": deliverables}), encoding="utf-8")


def test_builds_size_match_format_sources_with_codes(tmp_path):
    write_a2(tmp_path / "a2")
    counts = mod.build(tmp_path / "a2", tmp_path / "out")
    assert counts == {line: 2 for line in mod.LINES}
    manifest = json.loads((tmp_path / "out" / "size-match-code.json").read_text(encoding="utf-8"))
    assert manifest["format_version"] == 3 and manifest["columns"][0] == "CODE"
    assert [(s["name"], s["group"]) for s in manifest["sources"]] == [(line, "US") for line in mod.LINES]
    assert manifest["origin"]["node"] == "size-compression"
    hnt = manifest["sources"][1]
    # 非皮卡与皮卡分开检索：分片按 类别 + MAKE，非皮卡在前
    assert [(g["kind"], g["make"]) for g in hnt["make_groups"]] == [("nonpick", "Acura"), ("pick", "Cadillac")]
    assert hnt["kind_counts"] == {"nonpick": 1, "pick": 1}
    acura = json.loads((tmp_path / "out" / hnt["make_groups"][0]["records_path"]).read_text(encoding="utf-8"))
    record = acura["records"][0]
    assert acura["name"] == "HNT" and record["years"] == [2025, 2026]
    assert {k: record["values"][k] for k in ("CODE", "TYPE", "销量合计", "SIZE")} == {"CODE": "25112526", "TYPE": "SUV", "销量合计": "40266", "SIZE": "YL"}
    pickup = json.loads((tmp_path / "out" / hnt["make_groups"][1]["records_path"]).read_text(encoding="utf-8"))["records"][0]
    assert (pickup["type"], pickup["cab"], pickup["bed"], pickup["size"], pickup["kind"]) == ("Pickup", "Crew", "5.3", "PK-M", "pick")
    assert record["kind"] == "nonpick"
    # 长宽高为来源最大值；sources 为该记录覆盖的 A0 行（按 压缩类型 + 记录序号 对应）
    assert {k: record["values"][k] for k in ("L-MM", "W-MM", "H-MM")} == {"L-MM": "4719", "W-MM": "1842", "H-MM": "1621"}
    assert [(s["YEAR"], s["L-MM"], s["TYPE"]) for s in record["sources"]] == [("2025", "4700", "SUV"), ("2026", "4719", "SUV")]
    assert [(s["YEAR"], s["TYPE"], s["CAB"], s["L-MM"]) for s in pickup["sources"]] == [("2002-2006", "Pickup", "Crew", "5621")]
    assert manifest["columns"][-4:] == ["L-MM", "W-MM", "H-MM", "SIZE"]


def test_rejects_sources_for_unknown_records(tmp_path):
    write_a2(tmp_path / "a2", sources=SOURCES + "非皮卡,2,x,Acura,ADX,,SUV,,,2024,4600,1800,1600\n")
    with pytest.raises(ValueError, match="记录序号"):
        mod.build(tmp_path / "a2", tmp_path / "out")


def test_rejects_tables_without_code(tmp_path):
    write_a2(tmp_path / "a2", nonpick=NONPICK.replace("CODE,", "").replace("25112526,", ""))
    with pytest.raises(ValueError, match="CODE"):
        mod.build(tmp_path / "a2", tmp_path / "out")


def test_rejects_sha_mismatch(tmp_path):
    write_a2(tmp_path / "a2")
    (tmp_path / "a2" / "US" / mod.TABLES[1][0]).write_text(PICK + "x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sha256"):
        mod.build(tmp_path / "a2", tmp_path / "out")

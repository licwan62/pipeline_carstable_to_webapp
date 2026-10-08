import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_size_match_code_data as mod  # noqa: E402

NONPICK = "CODE,CAR,MAKE,MODEL,YEAR,VERSION,CONST,BACKSIZE,尺码销量总和\n25112526,Acura ADX,Acura,ADX,2025-2026,,SUV,YL,40266\n"
PICK = "CODE,CAR,MAKE,MODEL,YEAR,VERSION,CAB,BED,BACKSIZE,尺码销量总和\n14160206,CadillacEscalade EXT,Cadillac,Escalade EXT,2002-2006,,Crew,5.3,PK-M,49173\n"


def write_a2(folder: Path, nonpick: str = NONPICK) -> None:
    deliverables = []
    for line in mod.LINES:
        for (name, pickup) in mod.TABLES:
            data = (PICK if pickup else nonpick).encode()
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
    assert [g["make"] for g in hnt["make_groups"]] == ["Acura", "Cadillac"]
    acura = json.loads((tmp_path / "out" / hnt["make_groups"][0]["records_path"]).read_text(encoding="utf-8"))
    record = acura["records"][0]
    assert acura["name"] == "HNT" and record["years"] == [2025, 2026]
    assert {k: record["values"][k] for k in ("CODE", "TYPE", "销量合计", "SIZE")} == {"CODE": "25112526", "TYPE": "SUV", "销量合计": "40266", "SIZE": "YL"}
    pickup = json.loads((tmp_path / "out" / hnt["make_groups"][1]["records_path"]).read_text(encoding="utf-8"))["records"][0]
    assert (pickup["type"], pickup["cab"], pickup["bed"], pickup["size"]) == ("Pickup", "Crew", "5.3", "PK-M")


def test_rejects_tables_without_code(tmp_path):
    write_a2(tmp_path / "a2", nonpick=NONPICK.replace("CODE,", "").replace("25112526,", ""))
    with pytest.raises(ValueError, match="CODE"):
        mod.build(tmp_path / "a2", tmp_path / "out")


def test_rejects_sha_mismatch(tmp_path):
    write_a2(tmp_path / "a2")
    (tmp_path / "a2" / "US" / mod.TABLES[1][0]).write_text(PICK + "x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sha256"):
        mod.build(tmp_path / "a2", tmp_path / "out")

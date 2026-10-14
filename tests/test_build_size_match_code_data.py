import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_size_match_code_data as mod  # noqa: E402

DIMS = "最大长-MM,最大长年份,最小长-MM,最小长年份,最大宽-MM,最大宽年份,最小宽-MM,最小宽年份,最大高-MM,最大高年份,最小高-MM,最小高年份"
ADX = "Acura ADX,Acura,ADX,2025-2026,,SUV,YL,40266,4719,2026,4700,2025,1842,2025-2026,1842,2025-2026,1621,2025-2026,1621,2025-2026"
NONPICK = f"CODE,CAR,MAKE,MODEL,YEAR,VERSION,CONST,BACKSIZE,尺码销量总和,{DIMS}\n25112526,{ADX}\n"
# EU/RU 产线没有 CODE；RU 的尺码列是 亚马逊尺码
NONPICK_EU = f"CAR,MAKE,MODEL,YEAR,VERSION,CONST,BACKSIZE,尺码销量总和,{DIMS}\n{ADX}\n"
NONPICK_RU = NONPICK_EU.replace("BACKSIZE", "亚马逊尺码")
PICK = (f"CODE,CAR,MAKE,MODEL,YEAR,VERSION,CAB,BED,BACKSIZE,尺码销量总和,{DIMS}\n"
        "14160206,CadillacEscalade EXT,Cadillac,Escalade EXT,2002-2006,,Crew,5.3,PK-M,49173,"
        "5621,2002-2006,5621,2002-2006,2004,2002-2006,2004,2002-2006,1897,2002-2006,1897,2002-2006\n")
SOURCES = ("压缩类型,记录序号,DIMENSION-ID,MAKE,MODEL,版本,结构,CAB,BED,YEAR,L-MM,W-MM,H-MM\n"
           "非皮卡,1,Acura ADX SUV 2025 US,Acura,ADX,,SUV,,,2025,4700,1842,1621\n"
           "非皮卡,1,Acura ADX SUV 2026 US,Acura,ADX,,SUV,,,2026,4719,1842,1621\n"
           "皮卡,1,Cadillac Escalade EXT Pickup 2002-2006 Crew US,Cadillac,Escalade EXT,,Pickup,Crew,5.3,2002-2006,5621,2004,1897\n")
# A0 全量表（按 DIMENSION-ID 补 SHAPE、长度余量、规则ID、匹配尺码）
A0_ROWS = ("DIMENSION-ID,SHAPE,自动长度余量,规则ID,匹配尺码\n"
           "Acura ADX SUV 2025 US,SLOPED_CROSSOVER,150,Rb55fc98664,YL\n"
           "Acura ADX SUV 2026 US,BOXY_SUV,131,Rb55fc98664,YL\n"
           "Cadillac Escalade EXT Pickup 2002-2006 Crew US,PICKUP,79,R0706433775,PK-M\n")
NONPICK_BY_LINE = {"EU": NONPICK_EU, "RU": NONPICK_RU}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_inputs(root: Path, nonpick: str = NONPICK, sources: str = SOURCES, a0_rows: str = A0_ROWS) -> tuple[Path, Path]:
    a0, a1 = root / "a0", root / "a1"
    a0_deliverables = []
    for name in dict.fromkeys(mod.A0_FILES.values()):
        data = a0_rows.encode()
        (a0 / name).parent.mkdir(parents=True, exist_ok=True)
        (a0 / name).write_bytes(data)
        a0_deliverables.append({"file": name, "sha256": sha(data)})
    (a0 / "manifest.json").write_text(json.dumps(
        {"node": "size-calculation", "version": "a0v", "published_at": "t", "deliverables": a0_deliverables}), encoding="utf-8")
    deliverables = []
    for line in mod.LINES:
        line_nonpick = NONPICK_BY_LINE.get(line, nonpick)
        for name, text in [*((name, PICK if pickup else line_nonpick) for name, pickup in mod.TABLES), (mod.SOURCES_FILE, sources)]:
            data = text.encode()
            path = a1 / line / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            deliverables.append({"file": f"{line}/{name}", "sha256": sha(data)})
    upstream = [{"node": "size-calculation", "version": "a0v", "files": a0_deliverables}]
    (a1 / "manifest.json").write_text(json.dumps(
        {"node": "size-compression", "version": "v", "published_at": "t", "deliverables": deliverables, "upstream": upstream}),
        encoding="utf-8")
    return a1, a0


def build(tmp_path, **kwargs):
    a1, a0 = write_inputs(tmp_path, **kwargs)
    return mod.build(a1, tmp_path / "out", a0)


def read(tmp_path, name):
    return json.loads((tmp_path / "out" / name).read_text(encoding="utf-8"))


def first_record(tmp_path, source_index):
    manifest = read(tmp_path, "size-match-code.json")
    return read(tmp_path, manifest["sources"][source_index]["make_groups"][0]["records_path"])["records"][0]


def test_builds_size_match_format_sources_with_codes(tmp_path):
    counts = build(tmp_path)
    assert counts == {line: 2 for line in mod.LINES}
    manifest = read(tmp_path, "size-match-code.json")
    assert manifest["format_version"] == 3 and manifest["columns"][0] == "CODE"
    assert [(s["name"], s["group"]) for s in manifest["sources"]] == list(mod.LINES.items())
    assert [s["label"] for s in manifest["sources"]] == ["US", "US · HNT", "US · TM", "US · TM_拆分", "EU", "RU"]
    assert manifest["origin"] == {"node": "size-compression", "version": "v", "published_at": "t", "a0_version": "a0v"}
    hnt = manifest["sources"][1]
    # 非皮卡与皮卡分开检索：分片按 类别 + MAKE，非皮卡在前
    assert [(g["kind"], g["make"]) for g in hnt["make_groups"]] == [("nonpick", "Acura"), ("pick", "Cadillac")]
    assert hnt["kind_counts"] == {"nonpick": 1, "pick": 1}
    acura = read(tmp_path, hnt["make_groups"][0]["records_path"])
    record = acura["records"][0]
    assert acura["name"] == "HNT" and record["years"] == [2025, 2026]
    assert {k: record["values"][k] for k in ("CODE", "TYPE", "销量合计", "SIZE")} == {"CODE": "25112526", "TYPE": "SUV", "销量合计": "40266", "SIZE": "YL"}
    pickup = read(tmp_path, hnt["make_groups"][1]["records_path"])["records"][0]
    assert (pickup["type"], pickup["cab"], pickup["bed"], pickup["size"], pickup["kind"]) == ("Pickup", "Crew", "5.3", "PK-M", "pick")
    assert record["kind"] == "nonpick"
    # 长宽高为来源最大值；sources 为该记录覆盖的 A0 行（按 压缩类型 + 记录序号 对应）
    assert {k: record["values"][k] for k in ("L-MM", "W-MM", "H-MM")} == {"L-MM": "4719", "W-MM": "1842", "H-MM": "1621"}
    assert [(s["YEAR"], s["L-MM"], s["TYPE"]) for s in record["sources"]] == [("2025", "4700", "SUV"), ("2026", "4719", "SUV")]
    assert [(s["YEAR"], s["TYPE"], s["CAB"], s["L-MM"]) for s in pickup["sources"]] == [("2002-2006", "Pickup", "Crew", "5621")]
    assert manifest["columns"][-5:] == ["L-MM", "W-MM", "H-MM", "长度余量", "SIZE"]


def test_enriches_records_from_a0_full_table(tmp_path):
    build(tmp_path)
    record = first_record(tmp_path, 0)
    # 来源行带 A0 同行的 SHAPE / 长度余量；记录 SHAPE 去重合并，长度余量取最小（最长的车决定余量）
    assert [(s["SHAPE"], s["长度余量"]) for s in record["sources"]] == [("SLOPED_CROSSOVER", "150"), ("BOXY_SUV", "131")]
    assert record["values"]["SHAPE"] == "SLOPED_CROSSOVER / BOXY_SUV"
    assert record["values"]["长度余量"] == "131"
    # 来源行命中同一条规则时记录带规则ID 与匹配尺码（SIZE 悬停显示命中规则）
    assert (record["values"]["规则ID"], record["values"]["匹配尺码"]) == ("Rb55fc98664", "YL")
    manifest = read(tmp_path, "size-match-code.json")
    assert manifest["columns"].index("SHAPE") == manifest["columns"].index("TYPE") + 1
    assert manifest["shape_labels"]["SLOPED_CROSSOVER"]["label"] == "溜背跨界 SUV"


def test_mixed_rules_leave_record_without_rule_id(tmp_path):
    build(tmp_path, a0_rows=A0_ROWS.replace("150,Rb55fc98664", "150,Rother"))
    assert "规则ID" not in first_record(tmp_path, 0)["values"]


def test_eu_and_ru_lines_have_no_code(tmp_path):
    build(tmp_path)
    for index in (4, 5):
        record = first_record(tmp_path, index)
        assert (record["values"]["CODE"], record["size"]) == ("", "YL")


def test_writes_vehicle_codes_for_global_search(tmp_path):
    build(tmp_path)
    payload = read(tmp_path, mod.VEHICLE_CODES_FILE)
    # CODE 前四位 = MAKE_CODE + MODEL_CODE，页面据此把 8 位代码解析为 MAKE + MODEL + 年份区间
    assert payload["codes"] == {
        "1416": {"make": "Cadillac", "model": "Escalade EXT", "kinds": ["pick"]},
        "2511": {"make": "Acura", "model": "ADX", "kinds": ["nonpick"]},
    }
    assert payload["origin"]["node"] == "size-compression"


def test_rejects_code_prefix_shared_by_two_models(tmp_path):
    row = NONPICK.splitlines()[1].replace("25112526,Acura ADX,Acura,ADX", "25112426,Acura RDX,Acura,RDX")
    with pytest.raises(ValueError, match="2511"):
        build(tmp_path, nonpick=f"{NONPICK}{row}\n")


def test_rejects_sources_for_unknown_records(tmp_path):
    with pytest.raises(ValueError, match="记录序号"):
        build(tmp_path, sources=SOURCES + "非皮卡,2,x,Acura,ADX,,SUV,,,2024,4600,1800,1600\n",
              a0_rows=A0_ROWS + "x,BOXY_SUV,1,R1,YL\n")


def test_rejects_sources_missing_from_a0(tmp_path):
    with pytest.raises(ValueError, match="DIMENSION-ID"):
        build(tmp_path, a0_rows=A0_ROWS.replace("Acura ADX SUV 2025 US", "Acura ADX SUV 2024 US"))


def test_rejects_a1_built_on_other_a0(tmp_path):
    a1, a0 = write_inputs(tmp_path)
    manifest = json.loads((a1 / "manifest.json").read_text(encoding="utf-8"))
    manifest["upstream"][0]["files"][0]["sha256"] = "0" * 64
    (a1 / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="重新发布 A1"):
        mod.build(a1, tmp_path / "out", a0)


def test_rejects_tables_without_code(tmp_path):
    with pytest.raises(ValueError, match="CODE"):
        build(tmp_path, nonpick=NONPICK_EU)


def test_rejects_sha_mismatch(tmp_path):
    a1, a0 = write_inputs(tmp_path)
    (a1 / "US" / mod.TABLES[1][0]).write_text(PICK + "x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sha256"):
        mod.build(a1, tmp_path / "out", a0)

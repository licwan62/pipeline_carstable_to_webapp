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
# A0 全量表：全量表视图的行，也是压缩记录 refs 指向的行（按 DIMENSION-ID 补 SHAPE、长度余量、规则ID、匹配尺码）；
# 另有一行没有尺码、不在任何压缩记录里的 Acura 行，只出现在全量表视图
A0_HEADER = "DIMENSION-ID,MAKE,MODEL,版本,结构,CAB,BED,YEAR,分类,L-MM,W-MM,H-MM,SHAPE,自动尺码,自动长度余量,规则ID,匹配尺码\n"
A0_ROWS = (A0_HEADER
           + "Acura ADX SUV 2024 US,Acura,ADX,,SUV,,,2024,越野车,4690,1842,1621,BOXY_SUV,,,,\n"
           + "Acura ADX SUV 2025 US,Acura,ADX,,SUV,,,2025,越野车,4700,1842,1621,SLOPED_CROSSOVER,YL,150,Rb55fc98664,YL\n"
           + "Acura ADX SUV 2026 US,Acura,ADX,,SUV,,,2026,越野车,4719,1842,1621,BOXY_SUV,YL,131,Rb55fc98664,YL\n"
           + "Cadillac Escalade EXT Pickup 2002-2006 Crew US,Cadillac,Escalade EXT,,Pickup,Crew,5.3,2002-2006,皮卡,5621,2004,1897,PICKUP,PK-M,79,R0706433775,PK-M\n")
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


def first_shard(tmp_path, source_index, kind="nonpick"):
    manifest = read(tmp_path, mod.DATA_MANIFEST)
    group = next(g for g in manifest["sources"][source_index]["make_groups"] if g["kind"] == kind)
    return read(tmp_path, group["records_path"])


def expand_sources(shard, item):
    """与 viewer-data.js expandMatchShard 相同的还原：refs → 本分片 A0 行（YEAR 换成被覆盖年份）。"""
    pickup = shard["kind"] == "pick"
    return [mod.to_source({**shard["records"][index]["values"], "YEAR": year}, pickup, shard["records"][index]["values"])
            for index, year in item["refs"]]


def test_one_data_source_holds_both_views(tmp_path):
    counts = build(tmp_path)
    assert counts == {line: {"compressed": 2, "full": 4} for line in mod.LINES}
    manifest = read(tmp_path, mod.DATA_MANIFEST)
    assert manifest["format_version"] == 4 and manifest["default_view"] == "compressed"
    assert manifest["views"]["compressed"]["columns"][0] == "CODE" and "CODE" not in manifest["views"]["full"]["columns"]
    assert [(s["name"], s["group"]) for s in manifest["sources"]] == list(mod.LINES.items())
    assert [s["label"] for s in manifest["sources"]] == ["US", "US · HNT", "US · TM", "US · TM_拆分", "EU", "RU"]
    assert manifest["origin"] == {"node": "size-compression", "version": "v", "published_at": "t", "a0_version": "a0v"}
    hnt = manifest["sources"][1]
    # 非皮卡与皮卡分开检索：分片按 类别 + MAKE，非皮卡在前；每个分片同时有全量行与压缩记录
    assert [(g["kind"], g["make"], g["record_count"], g["compressed_count"]) for g in hnt["make_groups"]] == [
        ("nonpick", "Acura", 3, 1), ("pick", "Cadillac", 1, 1)]
    assert (hnt["kind_counts"], hnt["compressed_kind_counts"]) == ({"nonpick": 3, "pick": 1}, {"nonpick": 1, "pick": 1})
    # 只有一套数据文件：不再生成 size-match-code* / size-match-full*
    names = sorted(path.name for path in (tmp_path / "out").iterdir())
    assert not [name for name in names if name.startswith(("size-match-code", "size-match-full"))]
    assert all(name.startswith(mod.DATA_PREFIX) or name == mod.VEHICLE_CODES_FILE for name in names)


def test_compressed_records_reference_full_rows_instead_of_copying(tmp_path):
    build(tmp_path)
    acura = first_shard(tmp_path, 1)
    assert [row["values"]["DIMENSION-ID"] for row in acura["records"]] == [
        "Acura ADX SUV 2024 US", "Acura ADX SUV 2025 US", "Acura ADX SUV 2026 US"]
    (item,) = acura["compressed"]
    assert set(item) == {"values", "refs"}, "压缩记录只存聚合值与引用，不内嵌 A0 来源行"
    assert item["refs"] == [[1, "2025"], [2, "2026"]]
    values = item["values"]
    assert {k: values[k] for k in ("CODE", "TYPE", "销量合计", "SIZE", "L-MM", "W-MM", "H-MM")} == {
        "CODE": "25112526", "TYPE": "SUV", "销量合计": "40266", "SIZE": "YL", "L-MM": "4719", "W-MM": "1842", "H-MM": "1621"}
    # 还原出的来源行与旧版内嵌的 sources 相同（字段见 to_source）
    assert [(s["YEAR"], s["L-MM"], s["TYPE"], s["SHAPE"], s["长度余量"]) for s in expand_sources(acura, item)] == [
        ("2025", "4700", "SUV", "SLOPED_CROSSOVER", "150"), ("2026", "4719", "SUV", "BOXY_SUV", "131")]
    pickup = first_shard(tmp_path, 1, "pick")
    assert pickup["compressed"][0]["refs"] == [[0, "2002-2006"]]
    assert [(s["TYPE"], s["CAB"], s["L-MM"]) for s in expand_sources(pickup, pickup["compressed"][0])] == [("Pickup", "Crew", "5621")]
    # 全量行就是 A0 行（全量表视图），SIZE 为 A0 自动尺码
    assert [(row["year"], row["size"], row["kind"]) for row in acura["records"]] == [("2024", "", "nonpick"), ("2025", "YL", "nonpick"), ("2026", "YL", "nonpick")]


def test_enriches_records_from_a0_full_table(tmp_path):
    build(tmp_path)
    values = first_shard(tmp_path, 0)["compressed"][0]["values"]
    # 记录 SHAPE 去重合并，长度余量取最小（最长的车决定余量）；来源行命中同一条规则时记录带规则ID 与匹配尺码
    assert values["SHAPE"] == "SLOPED_CROSSOVER / BOXY_SUV"
    assert values["长度余量"] == "131"
    assert (values["规则ID"], values["匹配尺码"]) == ("Rb55fc98664", "YL")
    manifest = read(tmp_path, mod.DATA_MANIFEST)
    columns = manifest["views"]["compressed"]["columns"]
    assert columns.index("SHAPE") == columns.index("TYPE") + 1
    assert columns[-5:] == ["L-MM", "W-MM", "H-MM", "长度余量", "SIZE"]
    assert manifest["shape_labels"]["SLOPED_CROSSOVER"]["label"] == "溜背跨界 SUV"


def test_mixed_rules_leave_record_without_rule_id(tmp_path):
    build(tmp_path, a0_rows=A0_ROWS.replace("150,Rb55fc98664", "150,Rother"))
    assert "规则ID" not in first_shard(tmp_path, 0)["compressed"][0]["values"]


def test_eu_and_ru_lines_have_no_code(tmp_path):
    build(tmp_path)
    for index in (4, 5):
        values = first_shard(tmp_path, index)["compressed"][0]["values"]
        assert (values["CODE"], values["SIZE"]) == ("", "YL")


def test_writes_vehicle_codes_for_global_search(tmp_path):
    build(tmp_path)
    payload = read(tmp_path, mod.VEHICLE_CODES_FILE)
    # CODE 前四位 = MAKE_CODE + MODEL_CODE，页面据此把 8 位代码解析为 MAKE + MODEL + 年份区间
    assert payload["codes"] == {
        "1416": {"make": "Cadillac", "model": "Escalade EXT", "kinds": ["pick"]},
        "2511": {"make": "Acura", "model": "ADX", "kinds": ["nonpick"]},
    }
    assert payload["origin"]["node"] == "size-compression"


def test_removes_stale_duplicate_data(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for name in ("size-match-code.json", "size-match-full-01-us-nonpick-001-acura.json", "size-match-data-99-old.json"):
        (out / name).write_text("{}", encoding="utf-8")
    build(tmp_path)
    assert not (out / "size-match-code.json").exists() and not (out / "size-match-data-99-old.json").exists()
    assert not list(out.glob("size-match-full*"))


def test_rejects_code_prefix_shared_by_two_models(tmp_path):
    row = NONPICK.splitlines()[1].replace("25112526,Acura ADX,Acura,ADX", "25112426,Acura RDX,Acura,RDX")
    with pytest.raises(ValueError, match="2511"):
        build(tmp_path, nonpick=f"{NONPICK}{row}\n")


def test_rejects_sources_for_unknown_records(tmp_path):
    with pytest.raises(ValueError, match="记录序号"):
        build(tmp_path, sources=SOURCES + "非皮卡,2,Acura ADX SUV 2024 US,Acura,ADX,,SUV,,,2024,4690,1842,1621\n")


def test_rejects_sources_missing_from_a0(tmp_path):
    with pytest.raises(ValueError, match="DIMENSION-ID"):
        build(tmp_path, a0_rows=A0_ROWS.replace("Acura ADX SUV 2025 US", "Acura ADX SUV 2023 US"))


def test_rejects_sources_that_differ_from_a0_rows(tmp_path):
    # 来源行只按 [行号, 年份] 引用 A0 行，A1 与 A0 字段不一致时无法无损还原，必须失败
    with pytest.raises(ValueError, match="L-MM"):
        build(tmp_path, sources=SOURCES.replace("2025,4700,1842", "2025,4705,1842"))


def test_rejects_sources_in_other_make_shard(tmp_path):
    sources = SOURCES + "非皮卡,1,Cadillac Escalade EXT Pickup 2002-2006 Crew US,Cadillac,Escalade EXT,,Pickup,Crew,5.3,2002-2006,5621,2004,1897\n"
    with pytest.raises(ValueError, match="其他 MAKE/类别"):
        build(tmp_path, sources=sources)


def test_rejects_duplicate_dimension_ids(tmp_path):
    with pytest.raises(ValueError, match="重复"):
        build(tmp_path, a0_rows=A0_ROWS + A0_ROWS.splitlines()[2] + "\n")


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


def validated_site(tmp_path):
    """把构建结果放进站点目录，供 validate_size_match_data 检查（size-match.html 引用该数据时才检查）。"""
    from validate_publish_site import MATCH_DATA, validate_size_match_data
    site = tmp_path / "site"
    a1, a0 = write_inputs(tmp_path)
    mod.build(a1, site / "data" / "generated", a0)
    (site / "size-match.html").write_text(f'matchDataPath: "{MATCH_DATA}"', encoding="utf-8")
    return site, validate_size_match_data


def test_validator_accepts_built_data(tmp_path):
    site, validate = validated_site(tmp_path)
    errors: list[str] = []
    assert validate(site, errors) == {"full": 24, "compressed": 12}
    assert errors == []


def test_validator_rejects_broken_refs_and_duplicate_data(tmp_path):
    site, validate = validated_site(tmp_path)
    generated = site / "data" / "generated"
    shard_path = next(generated.glob(f"{mod.DATA_PREFIX}-01-us-nonpick-*.json"))
    shard = json.loads(shard_path.read_text(encoding="utf-8"))
    shard["compressed"][0]["refs"] = [[9, "2025"], [0, "2025"]]
    shard_path.write_text(json.dumps(shard), encoding="utf-8")
    (generated / "size-match-full.json").write_text("{}", encoding="utf-8")
    errors: list[str] = []
    validate(site, errors)
    assert any("invalid ref [9, '2025']" in error for error in errors)
    assert any("covers years 2025 outside its A0 row" in error for error in errors)
    assert any("duplicate size-match data must not be published" in error for error in errors)

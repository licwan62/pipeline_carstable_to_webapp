from __future__ import annotations

from pathlib import Path

import yaml

from tools.build_user_size_json import compact_type, expanded_years, long_type_for_row


ROOT = Path(__file__).resolve().parents[1]
TYPE_RULES = yaml.safe_load((ROOT / "configs/type-structure-abbreviations.json").read_text(encoding="utf-8"))


def test_website_loads_us_and_us_store_lines_only():
    config = yaml.safe_load((ROOT / "configs/pipeline.yaml").read_text(encoding="utf-8"))
    assert config["input"]["lines"] == ["US", "HNT", "TM", "TM_拆分"]
    assert "DIMENSION-CODE" not in config["input"]["store"]["columns"].split(",")


def test_long_type_keeps_only_requested_parts():
    row = {"CONST": "Sedan", "VERSION": "Incl: AMG"}
    assert long_type_for_row(row, show_const=True, show_version=True) == "Sedan Incl: AMG"
    assert long_type_for_row(row, show_const=False, show_version=True) == "Incl: AMG"
    assert long_type_for_row(row, show_const=False, show_version=False) == ""


def _parts(rows):
    from tools.build_user_size_json import type_parts_needed

    rows = [{"MAKE": "M", "MODEL": "X", **row} for row in rows]
    return type_parts_needed(rows, [row["SIZE"] for row in rows])


def test_version_dropped_when_row_is_the_only_size_for_its_years():
    # Plymouth Fury 1956-1972：合并行覆盖全部版本，只有 Wagon 与其年份重叠且尺码不同
    parts = _parts([
        {"YEAR": "1956-1972", "CONST": "Convertible/Coupe/Hardtop/Sedan", "VERSION": "Incl: Belvedere Fury/Sport Fury", "SIZE": "4L-0"},
        {"YEAR": "1962-1964", "CONST": "Wagon", "VERSION": "", "SIZE": "无可用尺码"},
        {"YEAR": "1973-1974", "CONST": "Coupe", "VERSION": "", "SIZE": "4XL-0"},
    ])
    assert parts == [(True, False), (True, False), (False, False)]


def test_base_row_needs_no_version_list_when_rivals_are_specific_versions():
    # SL-Class：基础行 Incl: 列表 vs AMG 裸版本行，AMG 以外自然归入基础行
    parts = _parts([
        {"YEAR": "2003-2010", "CONST": "Convertible", "VERSION": "Incl: SL500/SL600", "SIZE": "4L-0"},
        {"YEAR": "2003-2010", "CONST": "Convertible", "VERSION": "AMG", "SIZE": "4XL-0"},
    ])
    assert parts == [(False, False), (False, True)]


def test_version_kept_when_two_base_rows_overlap_on_structure():
    parts = _parts([
        {"YEAR": "2000", "CONST": "SUV", "VERSION": "Incl: 2dr", "SIZE": "YL"},
        {"YEAR": "2000", "CONST": "SUV/Wagon", "VERSION": "Incl: 4dr", "SIZE": "YXL"},
    ])
    assert parts == [(True, True), (True, True)]


def test_specific_version_list_is_always_shown():
    assert _parts([{"YEAR": "2018", "CONST": "Coupe", "VERSION": "GT3", "SIZE": "3L"}]) == [(False, True)]


def test_same_size_rows_do_not_need_type():
    parts = _parts([
        {"YEAR": "2000-2005", "CONST": "Sedan", "VERSION": "", "SIZE": "3L"},
        {"YEAR": "2003-2008", "CONST": "Wagon", "VERSION": "Incl: GT", "SIZE": "3L"},
    ])
    assert parts == [(False, False), (False, False)]


def test_year_ranges_are_expanded_for_overlapping_model_year_checks():
    assert expanded_years("2000-2002") == ("2000", "2001", "2002")


def test_shared_standard_and_special_versions_use_compact_include_label():
    assert compact_type("Incl: Panel/SS", 16, TYPE_RULES) == "Inc:Panel/SS"


def test_body_type_is_abbreviated_even_when_followed_by_version():
    assert compact_type("Convertible AMG", 16, TYPE_RULES) == "Conv AMG"


def test_complex_type_keeps_structure_and_versions_under_17_characters():
    result = compact_type("Convertible/Coupe Incl: LeMans/Tempest", 16, TYPE_RULES)
    assert result == "Conv/Cpe LM/Tmp"
    assert len(result) < 17
    assert not result.startswith("Cv/Cp")


def test_manual_confirmation_fixes_mpv_sedan_duplicate():
    from tools.build_user_size_json import load_type_confirmations

    confirmed = load_type_confirmations(ROOT / "configs/type-manual-confirm.csv", 16)
    assert confirmed["MPV Incl: Sedona/Sedona LWB"] == "MPV/Sdn LWB"


def test_lossy_compaction_is_flagged_for_manual_confirmation():
    from tools.build_user_size_json import compact_type_detail

    assert compact_type_detail("Convertible AMG", 16, TYPE_RULES) == ("Conv AMG", False)
    _, lossy = compact_type_detail("SUV Incl: 2dr/2dr 2WD/2dr 4WD/4dr 2WD", 16, TYPE_RULES)
    assert lossy


def test_confirmed_type_must_fit_length_limit(tmp_path):
    import pytest
    from tools.build_user_size_json import load_type_confirmations

    table = tmp_path / "confirm.csv"
    table.write_text("LONG-TYPE,确认TYPE\nA,12345678901234567\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_type_confirmations(table, 16)


def test_pickup_size_code_uses_new_generic_size_mapping():
    from tools.build_user_size_json import load_size_code_map

    config = yaml.safe_load((ROOT / "configs/pipeline.yaml").read_text(encoding="utf-8"))
    mapping = load_size_code_map((ROOT / config["paths"]["size_code_map_file"]).resolve())
    assert mapping == {"PK-S": "P0", "PK-M": "P1", "PK-L": "P2", "PK-XL": "P3", "PK-XXL-645": "P4", "PK-XXL-680": "P5"}


def test_inc_marker_is_unified_to_capitalized_form():
    from tools.build_user_size_json import normalize_inc_marker

    assert normalize_inc_marker("SUV inc:2WD/4WD") == "SUV Inc:2WD/4WD"
    assert normalize_inc_marker("INC:AMG") == "Inc:AMG"
    assert normalize_inc_marker("Zinc:X") == "Zinc:X"


def test_confirmation_table_uses_capitalized_inc_marker():
    text = (ROOT / "configs/type-manual-confirm.csv").read_text(encoding="utf-8-sig")
    confirmed = [line.split(",")[2] for line in text.splitlines()[1:]]
    assert not [value for value in confirmed if "inc:" in value]

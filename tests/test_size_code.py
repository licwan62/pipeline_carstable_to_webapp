from __future__ import annotations

import csv
import json
from pathlib import Path

from build_user_size_json import normalized_size

ROOT = Path(__file__).resolve().parents[1]
SIZES = json.loads((ROOT / "configs" / "user-size-rules.json").read_text(encoding="utf-8"))["size"]


def code(size: str) -> str:
    return normalized_size({"BACKSIZE": size}, SIZES)[1]


def test_rules_follow_size_code_table():
    with (ROOT / "configs" / "size-code.csv").open(encoding="utf-8-sig", newline="") as handle:
        table = {row["通用尺码"]: row["尺码代码"] for row in csv.DictReader(handle)}
    assert {size: code(size) for size in table} == table


def test_4x_shares_codes_with_4x_0():
    assert [code(s) for s in ("4S", "4M", "4L", "4XL", "4XXL")] == [code(f"{s}-0") for s in ("4S", "4M", "4L", "4XL", "4XXL")]


def test_renamed_2xxl_sizes_share_5_series_codes():
    assert (code("2XXL-510"), code("2XXL-530")) == (code("5L"), code("5XL")) == ("V2", "V3")


def test_sizes_outside_table_use_size_name_and_placeholders_stay_empty():
    assert code("2L+") == "2L+"
    assert code("CHALLENGER") == "CHALLENGER"
    assert code("无可用尺码") == ""
    assert code("数据不全") == ""

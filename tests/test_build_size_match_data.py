import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_size_match_data as mod  # noqa: E402


def test_full_record_fields_and_kind():
    row = {"MAKE": "Citroen", "MODEL": "C35", "结构": "Chassis Cab", "YEAR": "1974-1977", "分类": "皮卡", "自动尺码": "PK-X",
           "自动长度余量": "10", "DIMENSION-ID": "Citroen C35 1974-1977 EU"}
    record = mod.to_record(row, "EU")
    # 分类为皮卡的（EU Chassis Cab 也算）归皮卡分片，与非皮卡分开检索
    assert record["kind"] == "pick" and mod.to_record({**row, "分类": "两厢车"}, "EU")["kind"] == "nonpick"
    assert record["years"] == [1974, 1975, 1976, 1977]
    assert {k: record["values"][k] for k in ("SIZE", "TYPE", "长度余量", "SOURCE")} == {
        "SIZE": "PK-X", "TYPE": "Chassis Cab", "长度余量": "10", "SOURCE": "EU"}
    # 全量表视图没有 CODE 列（代号属于 A1 压缩记录）
    assert "CODE" not in mod.COLUMNS and "CODE" not in record["values"]


def test_renamed_sales_column_fills_sales_total():
    record = mod.to_record({"MAKE": "Acura", "MODEL": "ADX", "YEAR": "2025", "尺寸组销量": "131"}, "US")
    assert record["values"]["销量合计"] == "131"


def test_shape_column_and_rule_identity_fields_pass_through():
    # SHAPE（03 COVER_SHAPE）作为表格列紧跟 TYPE；规则ID / 匹配尺码 保留在 values，供可视化追溯命中规则
    assert mod.COLUMNS.index("SHAPE") == mod.COLUMNS.index("TYPE") + 1
    row = {"MAKE": "Acura", "MODEL": "ADX", "YEAR": "2025", "结构": "SUV", "SHAPE": "SUV-C", "自动尺码": "YM",
           "匹配尺码": "YL", "规则ID": "R0123456789"}
    values = mod.to_record(row, "HNT")["values"]
    assert (values["SHAPE"], values["匹配尺码"], values["规则ID"], values["SIZE"]) == ("SUV-C", "YL", "R0123456789", "YM")

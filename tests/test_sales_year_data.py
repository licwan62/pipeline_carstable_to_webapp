import copy
import hashlib
import json

import pytest

from tools.build_sales_year_data import build, validate_atoms
from tools.upstream_pin import pin_upstream, verify_pinned, UpstreamPinError
from tools.validate_publish_site import validate_sales_year_data


def sample():
    rows = [{"DIMENSION-ID": "test US", "YEAR": "2025-2027", "尺寸组销量": "7", "MAKE": "Test", "MODEL": "One", "分类": "越野车"}]
    atoms = [{"atom_record_id": f"test US|ATOM_YEAR={year}", "预估销量": value} for year, value in [(2025, "7"), (2026, "0"), (2027, "")]]
    return rows, atoms


def test_annual_values_preserve_zero_and_null():
    rows, atoms = sample()
    assert validate_atoms(rows, atoms) == {"test US": [[2025, 7], [2026, 0], [2027, None]]}


@pytest.mark.parametrize("case, message", [("duplicate", "重复原子"), ("year", "范围"), ("invalid", "非法原子年份"), ("orphan", "孤立"), ("negative", "非负"), ("nan", "非负"), ("sum", "不守恒"), ("coverage", "覆盖")])
def test_reject_invalid_atoms(case, message):
    rows, atoms = sample()
    if case == "duplicate": atoms.append(copy.deepcopy(atoms[0]))
    if case == "year": atoms[0]["atom_record_id"] = "test US|ATOM_YEAR=2024"
    if case == "invalid": atoms[0]["atom_record_id"] = "test US|ATOM_YEAR=invalid"
    if case == "orphan": atoms[0]["atom_record_id"] = "unknown|ATOM_YEAR=2025"
    if case == "negative": atoms[0]["预估销量"] = "-1"
    if case == "nan": atoms[0]["预估销量"] = "NaN"
    if case == "sum": atoms[0]["预估销量"] = "8"
    if case == "coverage": atoms.pop()
    with pytest.raises(ValueError, match=message): validate_atoms(rows, atoms)


def source(root, name, text, version):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    manifest = {"node": version, "version": version, "deliverables": [{"file": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_verified_build_and_mismatched_provenance_leave_output_intact(tmp_path):
    sales, a0, out = [tmp_path / name for name in ("sales", "a0", "out")]
    sm = source(sales, "原子销量.csv", "atom_record_id,预估销量\ntest US|ATOM_YEAR=2025,7\ntest US|ATOM_YEAR=2026,0\ntest US|ATOM_YEAR=2027,\n", "sales-v")
    am = source(a0, "US/全量/全量表.csv", "DIMENSION-ID,MAKE,MODEL,YEAR,分类,尺寸组销量\ntest US,Test,One,2025-2027,越野车,7\n", "a0-v")
    am["upstream"] = [{"files": sm["deliverables"]}]
    (a0 / "manifest.json").write_text(json.dumps(am), encoding="utf-8")
    result = build(sales, out, a0)
    assert result["atom_count"] == 3
    assert result["source_aliases"]["TM"] == "US"
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    am["upstream"][0]["files"][0]["sha256"] = "wrong"
    (a0 / "manifest.json").write_text(json.dumps(am), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA256"): build(sales, out, a0)
    assert before == {p.name: p.read_bytes() for p in out.iterdir()}


def test_resume_checks_pinned_sales_manifest(tmp_path):
    sales = tmp_path / "sales"
    source(sales, "atoms.csv", "a,b\n", "v")
    context = pin_upstream({"sales_output_dir": sales}, tmp_path / "work")
    verify_pinned(context)
    pinned = tmp_path / "work/upstream/sales_output_dir/manifest.json"
    pinned.write_text("{}", encoding="utf-8")
    with pytest.raises(UpstreamPinError, match="manifest"): verify_pinned(context)


def test_site_validation_rejects_corrupt_annual_shard(tmp_path):
    generated = tmp_path / "data/generated"
    generated.mkdir(parents=True)
    (tmp_path / "size-match.html").write_text('salesDataPath: "data/generated/sales-year-data.json"', encoding="utf-8")
    def write(name, body):
        (generated / name).write_text(json.dumps(body), encoding="utf-8")
    write("size-match-data.json", {"origin": {"a0_version": "v"}})
    write("sales-year-data.json", {
        "format_version": 1, "origin": {"a0_version": "v", "sales_version": "s", "sales_sha256": "a" * 64, "a0_sha256": "b" * 64},
        "source_aliases": {key: "US" for key in ("US", "HNT", "TM", "TM_拆分")}, "record_count": 1, "atom_count": 1,
        "make_groups": [{"make": "Test", "kind": "nonpick", "records_path": "annual.json", "record_count": 1}],
    })
    shard = {"make": "Test", "kind": "nonpick", "models": {"One": ["a"]}, "records": {"a": [[2025, 0]]}}
    write("annual.json", shard)
    errors = []
    validate_sales_year_data(tmp_path, errors)
    assert not errors
    shard["records"]["a"] = [[2025, -1]]
    write("annual.json", shard)
    validate_sales_year_data(tmp_path, errors)
    assert any("year/value" in error for error in errors)

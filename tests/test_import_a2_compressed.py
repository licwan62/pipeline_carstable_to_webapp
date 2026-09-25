from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import import_a2_compressed as importer

FULL_HEADER = "MAKE,MODEL,版本,结构,YEAR,自动尺码,DIMENSION-ID\n"
NON_HEADER = "CAR,MAKE,MODEL,YEAR,VERSION,CONST,BACKSIZE\n"
PICK_HEADER = "CAR,MAKE,MODEL,YEAR,VERSION,CAB,BED,BACKSIZE\n"


def publish(output_dir: Path, node: str, files: dict[str, str]) -> None:
    output_dir.mkdir(parents=True)
    deliverables = []
    for name, text in files.items():
        (output_dir / name).write_text(text, encoding="utf-8-sig")
        deliverables.append({"file": name, "sha256": hashlib.sha256((output_dir / name).read_bytes()).hexdigest()})
    manifest = {"node": node, "version": "20260925_01", "artifact": f"{node}/artifacts/x", "deliverables": deliverables}
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def setup(tmp_path: Path, lines=("US", "HNT", "EU"), config_lines=None) -> dict[str, Path]:
    a1, a2 = tmp_path / "a1", tmp_path / "a2"
    publish(a1, "full-generation", {f"全量生成_{line}.csv": FULL_HEADER + f"Ford,Focus,,Sedan,2020,M,Ford Focus 2020 {line}\n" for line in lines})
    a2_files = {}
    for line in lines:
        a2_files[f"压缩尺码表_{line}.csv"] = NON_HEADER
        a2_files[f"压缩尺码表_{line}_有损.csv"] = NON_HEADER + f"Ford Focus,Ford,Focus,2020,,Sedan,{line}-M\n"
        a2_files[f"压缩尺码表_{line}_皮卡.csv"] = PICK_HEADER
        a2_files[f"压缩尺码表_{line}_皮卡_有损.csv"] = PICK_HEADER
    publish(a2, "size-compression", a2_files)
    config = tmp_path / "pipeline.yaml"
    input_block = {"source": "all_cars_data", "store": {"store": "{stem}", "label": "{stem}尺码匹配表", "sheet": "{stem}尺码匹配"},
                   "required_fields": ["品牌", "前台车型", "年份区间", "最终尺码"]}
    if config_lines:
        input_block["lines"] = list(config_lines)
    config.write_text(json.dumps({"input": input_block, "columns": {
        "品牌": ["MAKE"], "前台车型": ["MODEL"], "年份区间": ["YEAR"], "最终尺码": ["自动尺码"]}}, ensure_ascii=False), encoding="utf-8")
    return {"a1": a1, "a2": a2, "config": config, "tables": tmp_path / "run" / "00_input" / "tables",
            "runtime": tmp_path / "run" / "00_input" / "pipeline.generated.json", "compressed": tmp_path / "run" / "01"}


def run(paths: dict[str, Path]) -> list[dict]:
    return importer.import_lines(paths["a1"], paths["a2"], paths["config"], paths["tables"], paths["runtime"], paths["compressed"])


def test_imports_every_a2_line_in_manifest_order(tmp_path: Path):
    paths = setup(tmp_path)
    stores = run(paths)
    assert [store["store"] for store in stores] == ["US", "HNT", "EU"]
    assert stores[1]["label"] == "HNT尺码匹配表" and stores[1]["path"] == "tables/002-HNT.csv"
    high = paths["compressed"] / "HNT" / "compress" / "HNT_非皮卡高度压缩表.csv"
    assert "HNT-M" in high.read_text(encoding="utf-8-sig")
    assert (paths["compressed"] / "HNT" / "compress" / "HNT_皮卡高度压缩表.csv").is_file()
    runtime = json.loads(paths["runtime"].read_text(encoding="utf-8"))
    assert [store["store"] for store in runtime["input"]["stores"]] == ["US", "HNT", "EU"]
    assert runtime["sources"]["compressed"]["node"] == "size-compression"
    assert (paths["tables"] / "003-EU.csv").is_file()


def test_configured_lines_select_and_order(tmp_path: Path):
    paths = setup(tmp_path, config_lines=["EU", "US"])
    assert [store["store"] for store in run(paths)] == ["EU", "US"]


def test_unknown_configured_line_fails(tmp_path: Path):
    paths = setup(tmp_path, config_lines=["US", "TM"])
    with pytest.raises(importer.SourceImportError, match="TM"):
        run(paths)


def test_sha_mismatch_fails_before_writing(tmp_path: Path):
    paths = setup(tmp_path)
    (paths["a2"] / "压缩尺码表_EU_有损.csv").write_text(NON_HEADER, encoding="utf-8-sig")
    with pytest.raises(importer.SourceImportError, match="sha256"):
        run(paths)
    assert not paths["runtime"].exists() and not paths["compressed"].exists()

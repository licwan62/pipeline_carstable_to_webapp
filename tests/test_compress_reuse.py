from __future__ import annotations

import json
from pathlib import Path

import yaml

from compress_configured_sheets import FINGERPRINT_NAME, expected_output, find_history, input_fingerprint

PROFILE = {"columns": {"a": ["A"]}, "defaults": {}}


def make_batch(root: Path, name: str, content: str, *, marker: bool) -> Path:
    batch = root / name
    (batch / "00_input" / "tables").mkdir(parents=True)
    (batch / "00_input" / "tables" / "001-S.csv").write_text(content, encoding="utf-8")
    (batch / "00_input" / "pipeline.generated.json").write_text(json.dumps(PROFILE), encoding="utf-8")
    produced = expected_output(batch / "01_compressed_fitment", "S")
    produced.parent.mkdir(parents=True)
    produced.write_text("x", encoding="utf-8")
    if marker:
        digest = input_fingerprint(batch / "00_input" / "tables" / "001-S.csv", PROFILE)
        (batch / "01_compressed_fitment" / "S" / FINGERPRINT_NAME).write_text(digest, encoding="utf-8")
    return batch


def test_history_reused_only_when_hash_unchanged(tmp_path: Path) -> None:
    make_batch(tmp_path, "2026-01-01_01_pipeline", "A\n1\n", marker=False)  # 老批次无指纹，靠快照回算
    make_batch(tmp_path, "2026-01-01_02_pipeline", "A\n2\n", marker=True)
    current = tmp_path / "2026-01-01_03_pipeline" / "01_compressed_fitment"
    current.mkdir(parents=True)
    store = {"store": "S", "path": "tables/001-S.csv"}
    source = tmp_path / "in.csv"

    source.write_text("A\n1\n", encoding="utf-8")
    assert find_history(current, store, input_fingerprint(source, PROFILE)).parts[-3] == "2026-01-01_01_pipeline"
    source.write_text("A\n3\n", encoding="utf-8")
    assert find_history(current, store, input_fingerprint(source, PROFILE)) is None
    source.write_text("A\n2\n", encoding="utf-8")
    assert find_history(current, store, input_fingerprint(source, PROFILE)).parts[-3] == "2026-01-01_02_pipeline"

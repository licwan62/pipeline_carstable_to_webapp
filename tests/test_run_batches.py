"""运行上下文与批次：上游固定、v3 批次恢复规则、站点字节去重与恢复、语义名迁移。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

from tools import pipeline_core, site_batch, upstream_pin


def write_upstream(root: Path, node: str, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    deliverables = []
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())  # 按字节写，避免 Windows 文本模式换行转换改变 sha256
        deliverables.append({"file": name, "sha256": hashlib.sha256(text.encode()).hexdigest(), "artifact_file": f"{node}/artifacts/x/{name}"})
    (root / "manifest.json").write_text(json.dumps({"node": node, "version": "20261014_01", "deliverables": deliverables}), encoding="utf-8")
    return root


# ---- 上游固定：构建途中上游变化不产生混合版本 ----

def test_pinned_inputs_survive_upstream_change_during_build(tmp_path):
    a0 = write_upstream(tmp_path / "A0", "size-calculation", {"US/全量/全量表.csv": "v1\n"})
    context = upstream_pin.pin_upstream({"a0_output_dir": a0}, tmp_path / "work")
    pinned = Path(context["sources"]["a0_output_dir"]["pinned_dir"])
    (a0 / "US" / "全量" / "全量表.csv").write_text("v2 published mid-build\n", encoding="utf-8")
    upstream_pin.verify_pinned(upstream_pin.load_context(tmp_path / "work"))
    assert (pinned / "US" / "全量" / "全量表.csv").read_text(encoding="utf-8") == "v1\n"
    assert json.loads((pinned / "manifest.json").read_text(encoding="utf-8"))["version"] == "20261014_01"


def test_pin_fails_before_any_step_when_file_differs_from_manifest(tmp_path):
    a0 = write_upstream(tmp_path / "A0", "size-calculation", {"a.csv": "v1\n"})
    (a0 / "a.csv").write_text("half-written\n", encoding="utf-8")
    with pytest.raises(upstream_pin.UpstreamPinError, match="sha256"):
        upstream_pin.pin_upstream({"a0_output_dir": a0}, tmp_path / "work")


def test_pin_fails_when_upstream_republishes_while_pinning(tmp_path, monkeypatch):
    a0 = write_upstream(tmp_path / "A0", "size-calculation", {"a.csv": "v1\n", "b.csv": "v1\n"})
    real = upstream_pin.sha256_bytes

    def republish_midway(data: bytes) -> str:
        manifest = json.loads((a0 / "manifest.json").read_text(encoding="utf-8"))
        manifest["version"] = "20261014_02"
        (a0 / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return real(data)

    monkeypatch.setattr(upstream_pin, "sha256_bytes", republish_midway)
    with pytest.raises(upstream_pin.UpstreamPinError, match="重新发布"):
        upstream_pin.pin_upstream({"a0_output_dir": a0}, tmp_path / "work")


def test_run_all_pin_failure_keeps_public_and_records_failed_batch(tmp_path, monkeypatch):
    from tools import run_all

    a0 = write_upstream(tmp_path / "A0", "size-calculation", {"a.csv": "v1\n"})
    a1 = write_upstream(tmp_path / "A1", "size-compression", {"US/压缩尺码表.csv": "v1\n"})
    (a1 / "US" / "压缩尺码表.csv").write_text("changed after manifest\n", encoding="utf-8")
    public = tmp_path / "public"
    public.mkdir()
    (public / "index.html").write_text("previous", encoding="utf-8")
    marker = tmp_path / "step-ran.txt"
    config = {
        "repos": {"pipeline": str(tmp_path)},
        "paths": {
            "a0_output_dir": str(a0), "compressed_output_dir": str(a1), "sales_output_dir": str(a0), "input_dir": str(tmp_path / "input"),
            "artifact_root": str(tmp_path / "artifact"), "public_dir": str(public), "logs_dir": str(tmp_path / "logs"),
            "work_root": str(tmp_path / "work"),
        },
        "input": {"source": "all_cars_data"},
        "steps": {"build_public_site": {"repo": "pipeline", "command": ["{python}", "-c", f"open(r'{marker}', 'w').write('x')"]}},
    }
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["run_all.py", "--config", str(config_path)])
    assert run_all.main() == 1
    assert not marker.exists()
    assert (public / "index.html").read_text(encoding="utf-8") == "previous"
    [batch] = list((tmp_path / "artifact").iterdir())
    manifest = json.loads((batch / "artifact.json").read_text(encoding="utf-8"))
    assert manifest["version"] == 3 and manifest["status"] == "failed"
    assert manifest["steps"]["build_public_site"]["status"] == "pending"
    assert "sha256" in manifest["error"]


# ---- 恢复规则 ----

def make_v3(root: Path, name: str, status: str) -> Path:
    batch = root / name
    batch.mkdir(parents=True)
    (batch / "artifact.json").write_text(json.dumps({"version": 3, "status": status, "work_dir": f"work/{name}"}), encoding="utf-8")
    return batch


def test_only_incomplete_v3_batches_can_resume(tmp_path):
    assert site_batch.can_resume(make_v3(tmp_path, "2026-10-14_01_pipeline", "failed"))[0]
    assert site_batch.can_resume(make_v3(tmp_path, "2026-10-14_02_pipeline", "partial"))[0]
    ok, reason = site_batch.can_resume(make_v3(tmp_path, "2026-10-14_03_pipeline", "complete"))
    assert not ok and "创建新批次" in reason
    legacy = tmp_path / "2026-10-13_08_pipeline"
    legacy.mkdir()
    (legacy / "artifact.json").write_text(json.dumps({"version": 2, "layout": "store-pipeline-v2", "status": "partial"}), encoding="utf-8")
    ok, reason = site_batch.can_resume(legacy)
    assert not ok and "旧批次" in reason
    assert site_batch.describe_batch(legacy)["format"] == 2


# ---- 站点字节去重与恢复 ----

def make_site(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_store_site_references_existing_bytes_and_restores(tmp_path):
    artifact = tmp_path / "artifact"
    first = site_batch.SiteBatch.create(artifact / "2026-10-14_01_pipeline", work_dir=tmp_path / "work" / "a", config_path=tmp_path / "c.yaml", steps=["s"], root=tmp_path)
    site1 = make_site(tmp_path / "site1", {"index.html": "home", "data/generated/a.json": "A", "assets/app/v.js": "js"})
    summary1 = first.store_site(site1)
    assert summary1["stored_new_files"] == 3

    second = site_batch.SiteBatch.create(artifact / "2026-10-14_02_pipeline", work_dir=tmp_path / "work" / "b", config_path=tmp_path / "c.yaml", steps=["s"], root=tmp_path)
    site2 = make_site(tmp_path / "site2", {"index.html": "home", "data/generated/a.json": "A2", "assets/app/v.js": "js"})
    summary2 = second.store_site(site2)
    assert summary2 == {"files": 3, "bytes": 8, "stored_new_files": 1, "stored_new_bytes": 2, "referenced_files": 2}
    assert not (second.dir / "site" / "index.html").exists()
    assert site_batch.site_references(second.dir) == {"2026-10-14_01_pipeline"}

    restored = tmp_path / "restored"
    assert site_batch.restore_site(second.dir, restored, root=tmp_path) == 3
    assert {p.relative_to(restored).as_posix(): p.read_text(encoding="utf-8") for p in restored.rglob("*") if p.is_file()} == {
        "index.html": "home", "data/generated/a.json": "A2", "assets/app/v.js": "js"
    }


def test_store_site_rejects_public_that_differs_from_validated_build(tmp_path):
    batch = site_batch.SiteBatch.create(tmp_path / "artifact" / "b", work_dir=tmp_path / "w", config_path=tmp_path / "c.yaml", steps=[], root=tmp_path)
    public = make_site(tmp_path / "public", {"index.html": "tampered"})
    expected = [{"path": "index.html", "sha256": hashlib.sha256(b"built").hexdigest(), "bytes": 5}]
    with pytest.raises(RuntimeError, match="不一致"):
        batch.store_site(public, expected)


def test_create_marks_batch_bytes_binary_for_git(tmp_path):
    batch_dir = tmp_path / "artifact" / "2026-10-15_01_pipeline"
    site_batch.SiteBatch.create(batch_dir, work_dir=tmp_path / "w", config_path=tmp_path / "c.yaml", steps=[], root=tmp_path)
    assert (batch_dir / ".gitattributes").read_bytes() == b"* -text\n"


def test_create_refuses_to_overwrite_existing_batch(tmp_path):
    existing = tmp_path / "artifact" / "2026-10-14_01_pipeline"
    existing.mkdir(parents=True)
    (existing / "artifact.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError):
        site_batch.SiteBatch.create(existing, work_dir=tmp_path / "w", config_path=tmp_path / "c.yaml", steps=[], root=tmp_path)


# ---- 语义名迁移 ----

def test_legacy_a2_key_and_step_name_are_migrated_with_warning():
    warnings: list[str] = []
    config = {
        "paths": {"a2_output_dir": "../all_cars_data/A1.压缩尺寸信息/output"},
        "steps": {"import_a2_compressed": {"enabled": True}, "build_user_size_json": {"enabled": True}},
    }
    pipeline_core.normalize_config(config, warn=warnings.append)
    assert config["paths"]["compressed_output_dir"] == "../all_cars_data/A1.压缩尺寸信息/output"
    assert list(config["steps"]) == ["import_compressed_tables", "build_user_size_json"]
    assert len(warnings) == 2
    assert pipeline_core.selected_step_names(config, from_step="import_a2_compressed", to_step=None) == {"import_compressed_tables", "build_user_size_json"}


def test_conflicting_old_and_new_names_fail():
    with pytest.raises(ValueError, match="不一致"):
        pipeline_core.normalize_config({"paths": {"a2_output_dir": "x", "compressed_output_dir": "y"}}, warn=lambda m: None)
    with pytest.raises(ValueError, match="只保留"):
        pipeline_core.normalize_config({"paths": {}, "steps": {"import_a2_compressed": {}, "import_compressed_tables": {}}}, warn=lambda m: None)


def test_import_cli_rejects_conflicting_legacy_argument(tmp_path):
    import import_compressed_tables

    with pytest.raises(SystemExit) as exit_info:
        import_compressed_tables.main([
            "--a0-output", str(tmp_path), "--a2-output", str(tmp_path / "old"), "--compressed-output", str(tmp_path / "new"),
            "--config", str(tmp_path / "c.yaml"), "--output-dir", str(tmp_path / "o"), "--output-config", str(tmp_path / "o.json"),
            "--compressed-root", str(tmp_path / "r"),
        ])
    assert exit_info.value.code == 2


def test_size_code_map_prefers_published_a0_file_and_snapshots_legacy_fallback(tmp_path):
    from tools import run_all

    pinned = tmp_path / "pinned"
    (pinned / "US").mkdir(parents=True)
    (pinned / "US" / "新旧尺码对应.csv").write_bytes("模式,分类,尺码,新通用尺码,尺码代码\n".encode())
    legacy = tmp_path / "legacy.csv"
    legacy.write_bytes("模式,分类,尺码,新通用尺码,尺码代码\n通用,皮卡,P1,P1,P1\n".encode())
    config = {"paths": {"size_code_map_file": str(legacy)}}

    batch = site_batch.SiteBatch.create(tmp_path / "artifact" / "b1", work_dir=tmp_path / "w1", config_path=tmp_path / "c", steps=[], root=tmp_path)
    published = {"sources": {"a0_output_dir": {"version": "v", "pinned_dir": str(pinned), "files": [{"file": "US/新旧尺码对应.csv"}]}}}
    assert run_all.resolve_size_code_map(config, published, batch, resuming=False) == pinned / "US" / "新旧尺码对应.csv"
    assert batch.manifest["size_code_map"]["interface"] == "a0_output"

    batch2 = site_batch.SiteBatch.create(tmp_path / "artifact" / "b2", work_dir=tmp_path / "w2", config_path=tmp_path / "c", steps=[], root=tmp_path)
    older = {"sources": {"a0_output_dir": {"version": "v", "pinned_dir": str(pinned), "files": []}}}
    assert run_all.resolve_size_code_map(config, older, batch2, resuming=False) == legacy
    assert batch2.manifest["size_code_map"]["interface"] == "legacy_a0_data"
    assert (batch2.dir / "extra" / "upstream_size_code_map.csv").read_bytes() == legacy.read_bytes()
    legacy.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="改动"):
        run_all.resolve_size_code_map(config, older, batch2, resuming=True)

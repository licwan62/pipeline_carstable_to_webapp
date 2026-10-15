"""网站批次归档：默认预演；保护当前发布来源、保留批次与递归引用；复制校验后才删除；可查找与恢复。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import archive_artifacts as arch
from tools import site_batch


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode())


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setattr(arch, "has_uncommitted", lambda batch, root: False)
    artifact = tmp_path / "artifact"
    public = tmp_path / "public"
    # 旧批次（v2）：两个都有 05_site_workspace
    for name in ("2026-09-17_01_pipeline", "2026-09-18_01_pipeline"):
        write(artifact / name / "artifact.json", json.dumps({"version": 2, "status": "complete", "steps": ["build_public_site"]}))
        write(artifact / name / "05_site_workspace" / "_site" / "index.html", f"old {name}")
    # v3 批次 A 保存全部字节，批次 B 只存变化并引用 A
    a = site_batch.SiteBatch.create(artifact / "2026-10-14_01_pipeline", work_dir=tmp_path / "work" / "x", config_path=tmp_path / "c", steps=[], root=tmp_path)
    site_a = tmp_path / "site_a"
    write(site_a / "index.html", "home")
    write(site_a / "data.json", "A")
    a.store_site(site_a)
    a.set_publish("public", status="promoted")
    a.finish("complete")
    b = site_batch.SiteBatch.create(artifact / "2026-10-14_02_pipeline", work_dir=tmp_path / "work" / "y", config_path=tmp_path / "c", steps=[], root=tmp_path)
    site_b = tmp_path / "site_b"
    write(site_b / "index.html", "home")
    write(site_b / "data.json", "B")
    b.store_site(site_b)
    b.set_publish("public", status="promoted")
    b.finish("complete")
    # 当前 public = 批次 B 的站点（另带一份纯运行元数据日志）
    write(public / "index.html", "home")
    write(public / "data.json", "B")
    write(public / "data" / "source" / "html" / "US" / "output_generation.log", "Generated at: now")
    return {"root": tmp_path, "artifact": artifact, "public": public}


def test_plan_protects_publish_source_and_its_references(repo):
    result = arch.plan(repo["artifact"], repo["public"], keep=0, root=repo["root"])
    assert result["publish_source"].name == "2026-10-14_02_pipeline"
    assert set(result["protected"]) == {"2026-10-14_02_pipeline", "2026-10-14_01_pipeline"}
    assert "引用" in result["protected"]["2026-10-14_01_pipeline"]
    assert [b.name for b in result["candidates"]] == ["2026-09-17_01_pipeline", "2026-09-18_01_pipeline"]


def test_dry_run_moves_nothing(repo, monkeypatch):
    monkeypatch.setattr(arch, "ROOT", repo["root"])
    before = sorted(p.name for p in repo["artifact"].iterdir())
    assert arch.main(["--keep", "1", "--artifact-root", str(repo["artifact"]), "--public", str(repo["public"]), "--dest", str(repo["root"] / "nas")]) == 0
    assert sorted(p.name for p in repo["artifact"].iterdir()) == before
    assert not (repo["root"] / "nas").exists()


def test_execute_copies_verifies_indexes_and_restores(repo):
    plan = arch.plan(repo["artifact"], repo["public"], keep=1, root=repo["root"])
    dest = repo["root"] / "nas"
    records = arch.archive(plan["candidates"], dest, 1, repo["artifact"], root=repo["root"])
    assert [r["batch"] for r in records] == ["2026-09-17_01_pipeline", "2026-09-18_01_pipeline"]
    assert not (repo["artifact"] / "2026-09-17_01_pipeline").exists()
    assert (dest / "2026-09-17_01_pipeline" / "05_site_workspace" / "_site" / "index.html").read_text() == "old 2026-09-17_01_pipeline"
    index = json.loads((repo["root"] / arch.INDEX_NAME).read_text(encoding="utf-8"))
    assert index["archives"][0]["batches"][0]["sha256"]
    assert (dest / arch.DEST_INDEX_NAME).is_file()
    assert arch.find("2026-09-18_01_pipeline", root=repo["root"])["archive_path"] == str(dest / "2026-09-18_01_pipeline")

    restored = arch.restore("2026-09-17_01_pipeline", repo["artifact"], root=repo["root"])
    assert (restored / "artifact.json").is_file()
    with pytest.raises(FileExistsError):
        arch.restore("2026-09-17_01_pipeline", repo["artifact"], root=repo["root"])


def test_archive_refuses_existing_destination(repo):
    plan = arch.plan(repo["artifact"], repo["public"], keep=1, root=repo["root"])
    dest = repo["root"] / "nas"
    (dest / "2026-09-17_01_pipeline").mkdir(parents=True)
    with pytest.raises(FileExistsError):
        arch.archive(plan["candidates"], dest, 1, repo["artifact"], root=repo["root"])
    assert (repo["artifact"] / "2026-09-17_01_pipeline").is_dir()


def test_legacy_publish_source_is_inferred_when_no_v3_batch_matches(repo):
    write(repo["public"] / "index.html", "edited by hand")
    result = arch.plan(repo["artifact"], repo["public"], keep=0, root=repo["root"])
    assert result["publish_source"].name == "2026-10-14_02_pipeline"
    assert "推定" in result["protected"]["2026-10-14_02_pipeline"]

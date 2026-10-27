"""站点构建的发布可靠性：先在 work 中构建并校验，成功才切换 public；失败保持旧 public 字节不变。

用最小的假外部站点骨架（publish_tables_to_webapp 的 build_site/export 工具）驱动真实的
build_publish_site.main → build_staged_site → apply_site_overrides → promote_site 流程；
上游数据生成器与完整校验用可控替身，以便在各阶段注入失败。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from tools import build_publish_site as site
from tools import site_promote

# 纯运行元数据：店铺 HTML 生成日志带时间戳与本机路径，比较站点内容时排除
RUN_METADATA = {"output_generation.log"}

FAKE_BUILD_SITE = '''
import shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "_site"
if SITE.exists():
    shutil.rmtree(SITE)
for d in ["assets", "config", "data/generated", "data/source/html"]:
    if (ROOT / d).exists():
        shutil.copytree(ROOT / d, SITE / d, dirs_exist_ok=True)
for page in (ROOT / "pages" / "level-1").glob("*.html"):
    shutil.copy2(page, SITE / page.name)
'''

FAKE_EXPORT = '''
import json
import yaml
def parse_yaml_config(path):
    return yaml.safe_load(open(path, encoding="utf-8"))
def normalize_match_rows(source, rows):
    return rows
def write_match_payloads(path, columns, sources):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"columns": columns, "sources": sources}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
'''

MATCH_PAGE = """<!doctype html>
<html><head>
  <link rel="stylesheet" href="assets/app/viewer.css?v=old">
</head><body>
  <script>
    window.SIZE_CHART_VIEWER = {
      matchDataPath: "data/generated/size-match-data.json",
    };
  </script>
  <script src="assets/app/viewer.js?v=old"></script>
</body></html>
"""


def tree_hashes(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in RUN_METADATA
    }


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    repo = tmp_path / "publish_repo"
    (repo / "tools").mkdir(parents=True)
    (repo / "tools" / "build_site.py").write_text(FAKE_BUILD_SITE, encoding="utf-8")
    (repo / "tools" / "export_xlsx_sources.py").write_text(FAKE_EXPORT, encoding="utf-8")
    (repo / "tools" / "validate_generated_data.py").write_text("def validate_generated_data(root):\n    pass\n", encoding="utf-8")
    (repo / "assets" / "app").mkdir(parents=True)
    (repo / "assets" / "app" / "base.js").write_text("// skeleton\n", encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "size-chart-view.yaml").write_text("excel_source:\n  match_data_path: data/generated/size-match.json\n", encoding="utf-8")
    (repo / "pages" / "level-1").mkdir(parents=True)
    (repo / "pages" / "level-1" / "index.html").write_text("<html><body>home</body></html>\n", encoding="utf-8")
    (repo / "pages" / "level-1" / "size-match.html").write_text(MATCH_PAGE, encoding="utf-8")
    (repo / "data" / "generated").mkdir(parents=True)
    (repo / "data" / "generated" / "size-ref.json").write_text('{"rows": []}\n', encoding="utf-8")
    (repo / "data" / "generated" / "size-match-001-stale-0123456789ab.json").write_text("{}", encoding="utf-8")
    (repo / "README.md").write_text("skeleton\n", encoding="utf-8")

    html = tmp_path / "html" / "US" / "nonpick"
    html.mkdir(parents=True)
    (html / "output_001.html").write_text("<html>chart</html>\n", encoding="utf-8")
    (html / "output_generation.log").write_text("Generated at: now\n", encoding="utf-8")

    inputs = tmp_path / "inputs"
    (inputs / "tables").mkdir(parents=True)
    (inputs / "tables" / "001-US.csv").write_text("MODEL,YEAR,自动尺码\nCivic,2020,3L\n", encoding="utf-8")
    (inputs / "pipeline.generated.json").write_text(
        json.dumps({"input": {"stores": [{"store": "US", "sheet": "US", "path": "tables/001-US.csv"}]}}), encoding="utf-8"
    )

    def fake_rules(a0_dir: Path, out: Path) -> None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "size-rules.json").write_text(json.dumps({"a0": a0_dir.name}), encoding="utf-8")

    def fake_code(compressed_dir: Path, out: Path, a0_dir: Path) -> None:
        (out / "size-match-data.json").write_text(json.dumps({"a1": compressed_dir.name, "a0": a0_dir.name}), encoding="utf-8")

    calls: list[Path] = []

    def fake_validate(root: Path) -> dict:
        calls.append(root)
        if not (root / "index.html").is_file() or not (root / "data" / "generated" / "size-match-data.json").is_file():
            raise ValueError("publish site validation failed")
        return {"ok": 1}

    monkeypatch.setattr(site, "build_sales_year_data", lambda *args: None)
    monkeypatch.setattr(site, "build_size_rules_data", fake_rules)
    monkeypatch.setattr(site, "build_size_match_code_data", fake_code)
    monkeypatch.setattr(site, "validate_publish_site", fake_validate)
    monkeypatch.setattr(site, "run_size_match_acceptance", lambda root, compressed_dir=None: None)

    public = tmp_path / "public"
    public.mkdir()
    (public / "index.html").write_text("<html><body>previous release</body></html>\n", encoding="utf-8")
    (public / "data" / "generated").mkdir(parents=True)
    (public / "data" / "generated" / "size-match-data.json").write_text('{"old": true}', encoding="utf-8")
    (public / "assets" / "app").mkdir(parents=True)
    (public / "assets" / "app" / "viewer.js").write_text("// hand-edited in public, must not leak into builds\n", encoding="utf-8")

    a0 = tmp_path / "pinned" / "a0"
    a1 = tmp_path / "pinned" / "a1"
    a0.mkdir(parents=True)
    a1.mkdir(parents=True)
    return {"repo": repo, "html": tmp_path / "html", "config": inputs / "pipeline.generated.json", "public": public,
            "work": tmp_path / "work", "a0": a0, "a1": a1, "calls": calls, "tmp": tmp_path}


def run_build(env: dict, monkeypatch: pytest.MonkeyPatch, *, public: Path | None = None, workspace: Path | None = None) -> None:
    argv = [
        "build_publish_site.py", "--publish-repo", str(env["repo"]), "--html-root", str(env["html"]),
        "--pipeline-config", str(env["config"]), "--workspace", str(workspace or env["work"] / "ws"),
        "--site-output", str(public or env["public"]), "--a0-dir", str(env["a0"]), "--compressed-dir", str(env["a1"]),
        "--site-manifest", str(env["work"] / "site_manifest.json"),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    site.main()


def leftovers(public: Path) -> list[str]:
    return sorted(p.name for p in public.parent.iterdir() if p.name.startswith(f".{public.name}."))


@pytest.mark.parametrize("stage", ["generated_data", "page_overlay", "full_validation", "size_match_acceptance", "sales_data"])
def test_failure_in_any_stage_keeps_previous_public_bytes(env, monkeypatch, stage):
    before = tree_hashes(env["public"])

    def boom(*args, **kwargs):
        raise RuntimeError(f"injected failure: {stage}")

    target = {"generated_data": "build_size_match_code_data", "page_overlay": "add_size_evolution", "full_validation": "validate_publish_site",
              "size_match_acceptance": "run_size_match_acceptance", "sales_data": "build_sales_year_data"}[stage]
    monkeypatch.setattr(site, target, boom)
    with pytest.raises(RuntimeError, match="injected failure"):
        run_build(env, monkeypatch)
    assert tree_hashes(env["public"]) == before
    assert leftovers(env["public"]) == []
    assert (env["work"] / "ws").is_dir(), "失败时保留工作目录供诊断"


def test_empty_and_existing_public_produce_identical_site(env, monkeypatch):
    run_build(env, monkeypatch, workspace=env["work"] / "ws1")
    with_existing = tree_hashes(env["public"])
    fresh = env["tmp"] / "fresh_public"  # 不存在的目录 = 空 public
    run_build(env, monkeypatch, public=fresh, workspace=env["work"] / "ws2")
    assert tree_hashes(fresh) == with_existing
    assert "assets/app/viewer.js" in with_existing
    built_viewer = (env["public"] / "assets" / "app" / "viewer.js").read_text(encoding="utf-8")
    assert "hand-edited in public" not in built_viewer, "构建不得回读旧 public 的前端文件"
    assert not any(name.startswith("data/generated/size-match-001-stale") for name in with_existing), "外部骨架的旧生成分片不得混入"
    assert "data/generated/size-ref.json" in with_existing


def test_success_switches_public_and_validates_live(env, monkeypatch):
    run_build(env, monkeypatch)
    listed = json.loads((env["work"] / "site_manifest.json").read_text(encoding="utf-8"))["files"]
    assert {f["path"]: f["sha256"] for f in listed if Path(f["path"]).name not in RUN_METADATA} == tree_hashes(env["public"])
    assert env["calls"][-1] == env["public"].resolve(), "切换后对新 public 再做一次站点校验"
    assert json.loads((env["public"] / "data" / "generated" / "size-match-data.json").read_text(encoding="utf-8")) == {"a1": "a1", "a0": "a0"}
    assert leftovers(env["public"]) == []


def test_validation_failure_after_switch_restores_previous_public(env, monkeypatch):
    before = tree_hashes(env["public"])
    real_validate = site.validate_publish_site
    seen: list[Path] = []

    def staged_ok_live_fails(root: Path) -> dict:
        seen.append(root)
        if len(seen) >= 2:
            raise ValueError("live validation failed")
        return real_validate(root)

    monkeypatch.setattr(site, "validate_publish_site", staged_ok_live_fails)
    with pytest.raises(ValueError, match="live validation failed"):
        run_build(env, monkeypatch)
    assert tree_hashes(env["public"]) == before
    assert leftovers(env["public"]) == []


def test_rename_blocked_falls_back_to_mirror_and_rolls_back(tmp_path, monkeypatch):
    live = tmp_path / "public"
    live.mkdir()
    (live / "a.txt").write_text("old", encoding="utf-8")
    (live / "gone.txt").write_text("old-only", encoding="utf-8")
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "a.txt").write_text("new", encoding="utf-8")

    def locked(source: Path, target: Path, attempts: int = 20) -> None:
        raise PermissionError("directory is watched")

    monkeypatch.setattr(site_promote, "rename_with_retry", locked)
    before = tree_hashes(live)
    with pytest.raises(ValueError):
        site_promote.promote_site(staged, live, lambda root: (_ for _ in ()).throw(ValueError("bad site")), log=lambda m: None)
    assert tree_hashes(live) == before
    assert leftovers(live) == []

    method = site_promote.promote_site(staged, live, lambda root: None, log=lambda m: None)
    assert method == "mirror"
    assert (live / "a.txt").read_text(encoding="utf-8") == "new"
    assert not (live / "gone.txt").exists()
    assert leftovers(live) == []

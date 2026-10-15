"""网站流水线批次（artifact/<YYYY-MM-DD_NN_pipeline>/）的 v3 清单、去重存储与恢复。

与 all_cars_data 的 ``lib/artifact_batch.RunBatch`` 同一原则（每份字节只存一次；已发布输入记引用，已提交配置记
sha256 + Git commit，只有无法引用的才复制），但不复用其代码：RunBatch 假设仓库根是 all_cars_data、节点目录与
``pipeline.json``，跨仓库复用需要 sys.path 注入和根路径适配，收益只有几十行。评估结论见 docs/pipeline.md。

批次目录（v3）::

    artifact.json        清单：状态、各步骤状态、上游引用、仓库 commit、配置哈希、站点文件统计、public/NAS 发布状态
    site_files.json      最终站点文件清单 [{path, sha256, bytes, stored_in}]；stored_in 为保存这份字节的批次文件
    site/<path>          本批次新出现的站点字节（与已有 v3 批次相同的文件只记引用，不复制）
    upstream/<key>/...gz 无法引用的上游文件快照（上游 artifact 文件缺失或字节不一致时）
    config/<path>        未提交或已修改的配置快照
    external/<repo>.diff.gz、external/<repo>/untracked/...gz   外部工具仓库未提交改动快照
    extra/*.gz           中间大表（gzip）与人工核对清单

中间工作文件在 ``work/<批次>/``（不纳入 Git），成功后删除，失败时保留供诊断。

只有未完成（running/failed/partial）的 v3 批次允许 ``--from-step`` 恢复；完成批次重跑必须创建新批次。
v1/v2 旧批次只读识别（``describe_batch``），不改写。

    python tools/site_batch.py show <批次>
    python tools/site_batch.py restore <批次> --dest <空目录> [--validate]
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "artifact.json"
SITE_FILES = "site_files.json"
FORMAT_VERSION = 3
LAYOUT = "site-batch-v3"
# 批次内文件按 sha256 登记，Git 必须原样保存字节：仓库 core.autocrlf=true 会把 CRLF 存成 LF、检出时再改写换行，
# 导致换机检出后 restore 校验失败。每个 v3 批次自带此文件（不影响旧批次）。
BATCH_GITATTRIBUTES = b"* -text\n"
INCOMPLETE = {"running", "failed", "partial"}
# 外部仓库未跟踪文件快照跳过的目录（备份、缓存、依赖，不参与构建）
SKIP_UNTRACKED_DIRS = {"bak", ".bak", "__pycache__", "node_modules", ".pytest_cache"}


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path, root: Path = ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def read_manifest(batch_dir: Path) -> dict[str, Any]:
    path = batch_dir / MANIFEST
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def describe_batch(batch_dir: Path) -> dict[str, Any]:
    """只读识别批次格式：v3 返回清单；旧批次返回推断的格式、状态与是否带完整站点工作区。"""
    manifest = read_manifest(batch_dir)
    version = manifest.get("version")
    if version == FORMAT_VERSION:
        return {"format": 3, "status": manifest.get("status"), "manifest": manifest}
    return {
        "format": version or 1,
        "status": manifest.get("status", "unknown"),
        "layout": manifest.get("layout"),
        "has_site_workspace": (batch_dir / "05_site_workspace" / "_site").is_dir() or (batch_dir / "05_publish_workspace").is_dir(),
        "manifest": manifest,
    }


def can_resume(batch_dir: Path) -> tuple[bool, str]:
    info = describe_batch(batch_dir)
    if info["format"] != FORMAT_VERSION:
        return False, f"{batch_dir.name} 是 v{info['format']} 旧批次，只读保留，不支持恢复；请不带 --artifact 重新运行以创建新批次"
    if info["status"] not in INCOMPLETE:
        return False, f"{batch_dir.name} 已完成（{info['status']}），完成批次不可恢复执行；请不带 --artifact 重新运行以创建新批次"
    return True, ""


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def gzip_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, target.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as dst:
        shutil.copyfileobj(src, dst)


class SiteBatch:
    """v3 批次清单的读写；每次修改立即落盘，失败运行也留下完整诊断。"""

    def __init__(self, batch_dir: Path, *, root: Path = ROOT) -> None:
        self.dir = batch_dir.resolve()
        self.root = root.resolve()
        self.manifest = read_manifest(self.dir)

    @classmethod
    def create(cls, batch_dir: Path, *, work_dir: Path, config_path: Path, steps: list[str], root: Path = ROOT) -> "SiteBatch":
        if batch_dir.exists() and any(batch_dir.iterdir()):
            raise FileExistsError(f"批次目录已存在且非空，不覆盖：{batch_dir}")
        batch = cls(batch_dir, root=root)
        batch_dir.mkdir(parents=True, exist_ok=True)
        (batch_dir / ".gitattributes").write_bytes(BATCH_GITATTRIBUTES)
        stamp = now()
        batch.manifest = {
            "version": FORMAT_VERSION,
            "layout": LAYOUT,
            "batch": batch_dir.name,
            "created_at": stamp,
            "updated_at": stamp,
            "status": "running",
            "work_dir": rel(work_dir, root),
            "config": rel(config_path, root),
            "steps": {name: {"status": "pending"} for name in steps},
            "publish": {"public": {"status": "not_run"}, "nas": {"status": "not_run"}},
        }
        batch.save()
        return batch

    def save(self) -> None:
        self.manifest["updated_at"] = now()
        write_json(self.dir / MANIFEST, self.manifest)

    # ---- 步骤与状态 ----
    def step(self, name: str, status: str, **extra: Any) -> None:
        record = self.manifest.setdefault("steps", {}).setdefault(name, {})
        record["status"] = status
        record["started_at" if status == "running" else "finished_at"] = now()
        if status != "failed":
            record.pop("error", None)
        record.update(extra)
        self.save()

    def finish(self, status: str, error: str | None = None) -> None:
        self.manifest["status"] = status
        if error:
            self.manifest["error"] = error[-4000:]
        else:
            self.manifest.pop("error", None)
        self.save()

    def set_publish(self, target: str, **record: Any) -> None:
        self.manifest.setdefault("publish", {})[target] = {**record, "recorded_at": now()}
        self.save()

    # ---- 输入记录 ----
    def record_upstream(self, context: dict[str, Any]) -> None:
        """上游文件：上游仓库中 artifact_file 存在且字节一致时只记引用，否则把固定副本 gzip 进批次。"""
        upstream: dict[str, Any] = {"pinned_at": context.get("pinned_at"), "sources": {}}
        for key, source in context["sources"].items():
            repo_root = Path(source["repo_root"]) if source.get("repo_root") else None
            files = []
            for item in source["files"]:
                entry = dict(item)
                artifact_file = item.get("artifact_file")
                candidate = repo_root / artifact_file if repo_root and artifact_file else None
                if candidate and candidate.is_file() and sha256_file(candidate) == item["sha256"]:
                    entry["stored"] = "reference"
                else:
                    target = self.dir / "upstream" / key / (item["file"] + ".gz")
                    gzip_copy(Path(source["pinned_dir"]) / item["file"], target)
                    entry["stored"] = "snapshot"
                    entry["snapshot"] = rel(target, self.root)
                files.append(entry)
            manifest_copy = self.dir / "upstream" / key / "manifest.json"
            manifest_copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(source["pinned_dir"]) / "manifest.json", manifest_copy)
            upstream["sources"][key] = {
                **{k: source.get(k) for k in ("node", "path", "version", "artifact", "published_at", "manifest_sha256", "repo_commit", "repo_output_dirty")},
                "repo": Path(source["repo_root"]).name if source.get("repo_root") else None,
                "output_dir": source.get("output_dir"),
                "manifest_copy": rel(manifest_copy, self.root),
                "files": files,
            }
        self.manifest["upstream"] = upstream
        self.save()

    def record_repo(self, name: str, path: Path, *, used_paths: list[str] | None = None, required: bool = True) -> None:
        """记录仓库 commit；有未提交改动时保存 diff 与未跟踪小文件快照。"""
        state = repo_state(path, used_paths)
        if state["commit"] is None:
            self.manifest.setdefault("repos", {})[name] = {"path": str(path), "available": False, "required": required}
            self.save()
            return
        record: dict[str, Any] = {"path": str(path.resolve()), "commit": state["commit"], "dirty": state["dirty"], "required": required}
        if used_paths:
            record["used_paths"] = used_paths
        if state["dirty"]:
            diff = run_git(path, "diff", "--binary", "HEAD", "--", *(used_paths or ["."]))
            if diff:
                target = self.dir / "external" / f"{name}.diff.gz"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(gzip.compress(diff, mtime=0))
                record["diff"] = rel(target, self.root)
                record["diff_sha256"] = hashlib.sha256(diff).hexdigest()
            untracked = []
            listing = run_git(path, "ls-files", "--others", "--exclude-standard", "-z", "--", *(used_paths or ["."])) or b""
            for item in filter(None, listing.decode("utf-8").split("\0")):
                source = path / item
                if set(Path(item).parts) & SKIP_UNTRACKED_DIRS or not source.is_file() or source.stat().st_size > 5_000_000:
                    continue
                target = self.dir / "external" / name / "untracked" / (item + ".gz")
                gzip_copy(source, target)
                untracked.append({"path": item, "sha256": sha256_file(source), "snapshot": rel(target, self.root)})
            record["untracked"] = untracked
        self.manifest.setdefault("repos", {})[name] = record
        self.save()

    def record_configs(self, paths: list[Path]) -> None:
        """配置文件 sha256；未提交或有改动的复制到 config/。"""
        entries = []
        for path in paths:
            if not path.is_file():
                continue
            entry: dict[str, Any] = {"path": rel(path, self.root), "sha256": sha256_file(path)}
            status = run_git(path.parent, "status", "--porcelain", "--", path.name)
            tracked = run_git(path.parent, "ls-files", "--error-unmatch", "--", path.name) is not None
            entry["committed"] = bool(tracked and not (status or b"").strip())
            if not entry["committed"]:
                target = self.dir / "config" / entry["path"].replace(":", "")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                entry["snapshot"] = rel(target, self.root)
            entries.append(entry)
        self.manifest["configs"] = entries
        self.save()

    def add_extra(self, source: Path, name: str | None = None, *, compress: bool = True) -> None:
        if not source.is_file():
            return
        target = self.dir / "extra" / ((name or source.name) + (".gz" if compress else ""))
        if compress:
            gzip_copy(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        self.manifest.setdefault("extra", []).append({"file": rel(target, self.root), "source": source.name, "sha256": sha256_file(source)})
        self.save()

    # ---- 站点文件 ----
    def store_site(self, site_root: Path, expected: list[dict[str, Any]] | None = None, *, artifact_root: Path | None = None) -> dict[str, int]:
        """把最终站点登记到 site_files.json：已有 v3 批次存过的字节只记引用，新字节复制到 site/。

        expected 为构建步骤写出的已校验站点清单；给出时要求 site_root 的文件集与 sha256 完全一致。
        """
        known = existing_site_bytes(artifact_root or self.dir.parent, exclude=self.dir, root=self.root)
        files = []
        stored_new = stored_bytes = 0
        for path in sorted(p for p in site_root.rglob("*") if p.is_file()):
            relative = path.relative_to(site_root).as_posix()
            digest = sha256_file(path)
            size = path.stat().st_size
            stored_in = known.get(digest)
            if stored_in is None:
                target = self.dir / "site" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                stored_in = rel(target, self.root)
                known[digest] = stored_in
                stored_new += 1
                stored_bytes += size
            files.append({"path": relative, "sha256": digest, "bytes": size, "stored_in": stored_in})
        if expected is not None:
            want = {(f["path"], f["sha256"]) for f in expected}
            got = {(f["path"], f["sha256"]) for f in files}
            if want != got:
                diff = sorted(want ^ got)[:10]
                raise RuntimeError(f"public 与已校验的构建清单不一致（{len(want ^ got)} 项，如 {diff}）")
        write_json(self.dir / SITE_FILES, files)
        summary = {"files": len(files), "bytes": sum(f["bytes"] for f in files), "stored_new_files": stored_new, "stored_new_bytes": stored_bytes,
                   "referenced_files": len(files) - stored_new}
        self.manifest["site"] = {"list": SITE_FILES, **summary}
        self.save()
        return summary


def run_git(path: Path, *args: str) -> bytes | None:
    try:
        return subprocess.run(["git", "-C", str(path), "-c", "core.quotepath=off", *args], capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None


def repo_state(path: Path, paths: list[str] | None = None) -> dict[str, Any]:
    head = run_git(path, "rev-parse", "HEAD")
    if head is None:
        return {"commit": None, "dirty": None}
    status = run_git(path, "status", "--porcelain", "--", *(paths or ["."])) or b""
    return {"commit": head.decode().strip(), "dirty": bool(status.strip())}


def existing_site_bytes(artifact_root: Path, exclude: Path | None = None, root: Path = ROOT) -> dict[str, str]:
    """已有 v3 批次中保存站点字节的位置：sha256 -> stored_in（仓库相对路径，文件须存在）。"""
    known: dict[str, str] = {}
    if not artifact_root.is_dir():
        return known
    for batch in sorted(artifact_root.iterdir()):
        if not batch.is_dir() or (exclude is not None and batch.resolve() == exclude.resolve()):
            continue
        listing = batch / SITE_FILES
        if not listing.is_file():
            continue
        for item in json.loads(listing.read_text(encoding="utf-8")):
            if item["sha256"] not in known and (root / item["stored_in"]).is_file():
                known[item["sha256"]] = item["stored_in"]
    return known


def site_references(batch_dir: Path) -> set[str]:
    """该批次 site_files.json 引用的其他批次名（递归保护用）。"""
    listing = batch_dir / SITE_FILES
    if not listing.is_file():
        return set()
    names = set()
    for item in json.loads(listing.read_text(encoding="utf-8")):
        parts = Path(item["stored_in"]).parts
        if len(parts) >= 2 and parts[1] != batch_dir.name:
            names.add(parts[1])
    return names


def restore_site(batch_dir: Path, dest: Path, *, root: Path = ROOT) -> int:
    """按 site_files.json 把完整站点恢复到 dest（须不存在或为空），逐文件校验 sha256。"""
    listing = batch_dir / SITE_FILES
    if not listing.is_file():
        raise FileNotFoundError(f"{batch_dir.name} 没有 {SITE_FILES}（旧批次请从 05_site_workspace/_site 读取）")
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"恢复目标非空：{dest}")
    files = json.loads(listing.read_text(encoding="utf-8"))
    for item in files:
        source = root / item["stored_in"]
        if not source.is_file():
            raise FileNotFoundError(f"{item['path']} 的保存位置不存在：{item['stored_in']}（批次可能已归档，请先恢复归档）")
        target = dest / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if sha256_file(target) != item["sha256"]:
            raise RuntimeError(f"{item['path']} 恢复后 sha256 不一致")
    return len(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect or restore website pipeline batches.")
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show")
    show.add_argument("batch")
    restore = sub.add_parser("restore")
    restore.add_argument("batch")
    restore.add_argument("--dest", type=Path, required=True)
    restore.add_argument("--validate", action="store_true", help="恢复后运行 validate_publish_site")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    batch_dir = Path(args.batch) if Path(args.batch).is_absolute() else ROOT / "artifact" / args.batch
    if args.command == "show":
        print(json.dumps(describe_batch(batch_dir), ensure_ascii=False, indent=2))
        return 0
    count = restore_site(batch_dir, args.dest.resolve())
    print(f"Restored {count} files from {batch_dir.name} -> {args.dest}")
    if args.validate:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from validate_publish_site import validate_publish_site

        print(validate_publish_site(args.dest.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

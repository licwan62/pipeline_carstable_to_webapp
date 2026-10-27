"""运行开始时固定 all_cars_data 已发布交付物（A0 全量与报告、A1 压缩表、年度原子销量），供本次运行的所有步骤读取。

每个来源（上游节点 output/）按 manifest.json 复制全部交付物到 ``<work>/upstream/<key>/``，复制时逐文件校验 sha256；
复制完成后再读一次上游 manifest，若期间上游重新发布（manifest 变化）或任一文件与 manifest 不一致则失败，
此时尚未修改 public。之后各步骤只读固定副本，不在不同步骤重新选择上游版本，避免产生混合版本。

返回/写出的运行上下文（``run_context.json``）记录每个来源的节点、版本、来源 artifact、仓库 commit 与各文件
sha256、artifact_file（上游仓库内保存这份字节的不可变批次文件），供批次清单记引用。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

CONTEXT_FILE = "run_context.json"


class UpstreamPinError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_info(path: Path) -> dict[str, Any]:
    """path 所在 Git 仓库的根、HEAD 与工作区是否有未提交改动（只看 path 子树）。"""
    try:
        root = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
        head = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain", "--", "."], capture_output=True, text=True, encoding="utf-8", check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return {"repo_root": None, "commit": None, "dirty": None}
    return {"repo_root": str(Path(root).resolve()), "commit": head, "dirty": bool(dirty)}


def pin_source(key: str, output_dir: Path, dest_root: Path) -> dict[str, Any]:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.is_file():
        raise UpstreamPinError(f"上游发布缺少 manifest.json：{output_dir}")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    dest = dest_root / key
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    files = []
    for item in manifest.get("deliverables", []):
        name = item["file"]
        source = output_dir / name
        if not source.is_file():
            raise UpstreamPinError(f"{manifest.get('node')} 发布中缺少 {name}")
        data = source.read_bytes()
        digest = sha256_bytes(data)
        if digest != item["sha256"]:
            raise UpstreamPinError(f"{manifest.get('node')}/{name} 与 manifest.json 的 sha256 不一致（上游正在发布或文件被改动），未修改 public")
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        files.append({"file": name, "sha256": digest, "bytes": len(data), "artifact_file": item.get("artifact_file")})
    if manifest_path.read_bytes() != manifest_bytes:
        raise UpstreamPinError(f"{manifest.get('node')} 在固定输入期间重新发布，请稍后重跑")
    (dest / "manifest.json").write_bytes(manifest_bytes)
    git = git_info(output_dir)
    return {
        "key": key,
        "output_dir": str(output_dir.resolve()),
        "pinned_dir": str(dest.resolve()),
        "node": manifest.get("node"),
        "path": manifest.get("path"),
        "version": manifest.get("version"),
        "artifact": manifest.get("artifact"),
        "published_at": manifest.get("published_at"),
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "repo_root": git["repo_root"],
        "repo_commit": git["commit"],
        "repo_output_dirty": git["dirty"],
        "files": files,
    }


def pin_upstream(sources: dict[str, Path], work_dir: Path) -> dict[str, Any]:
    """固定各来源到 work_dir/upstream/<key>/，写出并返回 work_dir/run_context.json。"""
    dest_root = work_dir / "upstream"
    context = {
        "pinned_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "sources": {key: pin_source(key, Path(path).resolve(), dest_root) for key, path in sources.items()},
    }
    write_context(work_dir, context)
    return context


def write_context(work_dir: Path, context: dict[str, Any]) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / CONTEXT_FILE).write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_context(work_dir: Path) -> dict[str, Any] | None:
    path = work_dir / CONTEXT_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def verify_pinned(context: dict[str, Any]) -> None:
    """恢复执行前确认固定副本完整未被改动。"""
    for source in context["sources"].values():
        pinned = Path(source["pinned_dir"])
        manifest = pinned / "manifest.json"
        if not manifest.is_file() or sha256_bytes(manifest.read_bytes()) != source["manifest_sha256"]:
            raise UpstreamPinError(f"固定输入 manifest {manifest} 缺失或已改动，无法恢复执行")
        for item in source["files"]:
            path = pinned / item["file"]
            if not path.is_file() or sha256_bytes(path.read_bytes()) != item["sha256"]:
                raise UpstreamPinError(f"固定输入 {path} 缺失或已改动，无法恢复执行；请重新运行创建新批次")

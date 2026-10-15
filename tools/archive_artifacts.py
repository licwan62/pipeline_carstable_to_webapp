"""把较旧的网站批次（artifact/<批次>/）归档到仓库外，保留最近 N 个；默认只预演（dry-run）。

    python tools/archive_artifacts.py --keep 5                                    # 预演：列出将归档/受保护的批次
    python tools/archive_artifacts.py --keep 5 --dest "\\\\NAS8824B4\\Public\\PQData\\bak\\pipeline_carstable_to_webapp\\artifact" --execute
    python tools/archive_artifacts.py --find 2026-09-25_02_pipeline
    python tools/archive_artifacts.py --restore 2026-09-25_02_pipeline            # 从归档位置复制回 artifact/ 并校验

受保护（不移动）：
- 当前发布来源：内容与当前 public 一致的批次（v3 比对 site_files.json；旧批次比对 05_site_workspace/_site，
  排除 output_generation.log 等纯运行元数据）；
- 最近 N 个批次；未完成且工作目录仍在的 v3 批次（可恢复执行）；
- 受保护批次 site_files.json 递归引用的批次（保证恢复完整站点所需字节都在本地）；
- 含未提交（未跟踪或已修改）文件的批次。

执行时逐批次复制到目标、逐文件校验 sha256，全部一致才删除本地；目标已存在则拒绝。每次归档追加到仓库根目录
``artifact_archive.json``（批次 → 归档路径、文件数、字节数、各文件 sha256），目标根目录同步写 ``ARCHIVE_INDEX.json``。
归档后在仓库提交本地删除与索引。旧批次只读识别，不改写其内容。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from site_batch import FORMAT_VERSION, INCOMPLETE, SITE_FILES, describe_batch, sha256_file, site_references  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INDEX_NAME = "artifact_archive.json"
DEST_INDEX_NAME = "ARCHIVE_INDEX.json"
RUN_METADATA = {"output_generation.log"}


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): sha256_file(p)
        for p in root.rglob("*")
        if p.is_file() and p.name not in RUN_METADATA
    }


def batch_site_hashes(batch: Path) -> dict[str, str] | None:
    listing = batch / SITE_FILES
    if listing.is_file():
        return {i["path"]: i["sha256"] for i in json.loads(listing.read_text(encoding="utf-8")) if Path(i["path"]).name not in RUN_METADATA}
    for legacy in (batch / "05_site_workspace" / "_site", batch / "05_publish_workspace" / "_site"):
        if legacy.is_dir():
            return tree_hashes(legacy)
    return None


def publish_source(batches: list[Path], public: Path) -> Path | None:
    """内容与当前 public 一致的最新批次。"""
    if not public.is_dir():
        return None
    current = tree_hashes(public)
    for batch in reversed(batches):
        hashes = batch_site_hashes(batch)
        if hashes is not None and hashes == current:
            return batch
    return None


def inferred_publish_source(batches: list[Path]) -> Path | None:
    """旧流程先复制 _site 再在 public 上叠加页面，旧批次不含最终站点字节，只能推定：最近一个跑过 build_public_site 的批次。"""
    for batch in reversed(batches):
        manifest = describe_batch(batch)["manifest"]
        steps = manifest.get("steps") or []
        names = [k for k, v in steps.items() if v.get("status") == "succeeded"] if isinstance(steps, dict) else steps
        if "build_public_site" in names or (manifest.get("publish") or {}).get("public", {}).get("status") == "promoted":
            return batch
    return None


def has_uncommitted(batch: Path, root: Path) -> bool:
    try:
        out = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", str(batch)], capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return False
    return bool(out.strip())


def plan(artifact_root: Path, public: Path, keep: int, root: Path = ROOT, work_root: Path | None = None) -> dict:
    batches = sorted(p for p in artifact_root.iterdir() if p.is_dir())
    protected: dict[str, str] = {}
    source = publish_source(batches, public)
    if source is not None:
        protected[source.name] = "当前发布来源（内容与 public 一致）"
    else:
        source = inferred_publish_source(batches)
        if source is not None:
            protected[source.name] = "推定当前发布来源（旧批次不含最终站点字节，取最近一次构建 public 的批次）"
    for batch in batches[-keep:] if keep > 0 else []:
        protected.setdefault(batch.name, f"最近 {keep} 个")
    work_root = work_root or root / "work"
    for batch in batches:
        info = describe_batch(batch)
        if info["format"] == FORMAT_VERSION and info["status"] in INCOMPLETE and (work_root / batch.name).is_dir():
            protected.setdefault(batch.name, "未完成批次，可恢复执行")
    pending = list(protected)
    while pending:
        name = pending.pop()
        for ref in site_references(artifact_root / name):
            if ref not in protected:
                protected[ref] = f"被 {name} 的站点文件引用"
                pending.append(ref)
    candidates, skipped = [], {}
    for batch in batches:
        if batch.name in protected:
            continue
        if has_uncommitted(batch, root):
            skipped[batch.name] = "含未提交文件"
            continue
        candidates.append(batch)
    return {"batches": batches, "protected": protected, "skipped": skipped, "candidates": candidates, "publish_source": source}


def dir_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def archive(candidates: list[Path], dest: Path, keep: int, artifact_root: Path, root: Path = ROOT) -> list[dict]:
    records = []
    for batch in candidates:
        resolved = batch.resolve()
        if resolved.parent != artifact_root.resolve():
            raise RuntimeError(f"拒绝归档 artifact 根目录以外的路径：{resolved}")
        target = dest / batch.name
        if target.exists():
            raise FileExistsError(f"归档目标已存在，拒绝覆盖：{target}")
        files = sorted(p for p in batch.rglob("*") if p.is_file())
        hashes = {p.relative_to(batch).as_posix(): sha256_file(p) for p in files}
        total = sum(p.stat().st_size for p in files)
        shutil.copytree(batch, target)
        bad = [name for name, digest in hashes.items() if not (target / name).is_file() or sha256_file(target / name) != digest]
        if bad:
            raise RuntimeError(f"{batch.name} 归档校验失败（{bad[:5]}），本地未删除")
        shutil.rmtree(resolved)
        records.append({"batch": batch.name, "archive_path": str(target), "files": len(files), "bytes": total, "sha256": hashes})
        print(f"归档 {batch.name} -> {target}（{len(files)} 个文件，已校验并删除本地）")
    if records:
        entry = {"archived_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "dest": str(dest), "keep": keep, "batches": records}
        for index in (root / INDEX_NAME, dest / DEST_INDEX_NAME):
            data = json.loads(index.read_text(encoding="utf-8")) if index.is_file() else {"schema_version": 1, "archives": []}
            data["archives"].append(entry)
            index.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return records


def find(name: str, root: Path = ROOT) -> dict | None:
    index = root / INDEX_NAME
    if not index.is_file():
        return None
    for entry in reversed(json.loads(index.read_text(encoding="utf-8"))["archives"]):
        for record in entry["batches"]:
            if record["batch"] == name:
                return record
    return None


def restore(name: str, artifact_root: Path, root: Path = ROOT) -> Path:
    record = find(name, root)
    if record is None:
        raise KeyError(f"{INDEX_NAME} 中没有 {name}")
    source, target = Path(record["archive_path"]), artifact_root / name
    if target.exists():
        raise FileExistsError(f"{target} 已存在")
    shutil.copytree(source, target)
    bad = [n for n, d in record["sha256"].items() if not (target / n).is_file() or sha256_file(target / n) != d]
    if bad:
        shutil.rmtree(target)
        raise RuntimeError(f"恢复校验失败（{bad[:5]}），已撤销")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", type=int, default=5)
    parser.add_argument("--dest", type=Path, default=ROOT / ".bak" / "artifact")
    parser.add_argument("--artifact-root", type=Path, default=ROOT / "artifact")
    parser.add_argument("--public", type=Path, default=ROOT / "public")
    parser.add_argument("--execute", action="store_true", help="实际复制、校验并删除本地（默认只预演）")
    parser.add_argument("--find", metavar="BATCH")
    parser.add_argument("--restore", metavar="BATCH")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if args.find:
        print(json.dumps(find(args.find) or {}, ensure_ascii=False, indent=1)[:4000])
        return 0
    if args.restore:
        print(f"已恢复：{restore(args.restore, args.artifact_root)}")
        return 0
    result = plan(args.artifact_root, args.public, args.keep)
    print(f"批次 {len(result['batches'])} 个；当前发布来源：{result['publish_source'].name if result['publish_source'] else '未找到（未保护任何来源，请检查 public）'}")
    for name, reason in result["protected"].items():
        print(f"  保护 {name}：{reason}")
    for name, reason in result["skipped"].items():
        print(f"  跳过 {name}：{reason}")
    total = sum(dir_bytes(b) for b in result["candidates"])
    for batch in result["candidates"]:
        print(f"  {'归档' if args.execute else '[dry-run] 归档'} {batch.name} -> {args.dest / batch.name}")
    print(f"{'将' if not args.execute else ''}归档 {len(result['candidates'])} 个批次，{total / 1e6:.1f} MB")
    if result["publish_source"] is None and args.execute:
        print("未找到当前发布来源，拒绝执行", file=sys.stderr)
        return 2
    if args.execute:
        archive(result["candidates"], args.dest, args.keep, args.artifact_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

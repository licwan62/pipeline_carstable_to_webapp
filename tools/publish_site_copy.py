"""把本流水线构建的站点文件发布到多个项目共同维护的部署目录（NAS 站点）。

部署目录不归任何一个项目独占：
- 每个发布方在 ``_publishers/<发布方>.json`` 记录自己拥有的文件及 SHA-256，只新增、更新、删除这些文件；
  其他发布方的文件一律不动。构建结果与其他发布方已登记的路径冲突时整体拒绝，不覆盖。
- ``_publishers/registry.json`` 每个发布方一项（入口导航、发布时间），各自只改写自己的键。
  站点页面通过 ``assets/app/site-common.js`` 读取它，显示其他项目登记的入口。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


PUBLISHER = "pipeline_carstable_to_webapp"
STATE_DIR = "_publishers"
REGISTRY = "registry.json"
RETRY_DELAYS = (1, 2, 4, 8, 15)
# SMB 瞬时网络错误：找不到网络路径、意外的网络错误、网络名不再可用、信号灯超时。
TRANSIENT_WINERRORS = {53, 59, 64, 121}


def transient(error: OSError) -> bool:
    return isinstance(error, PermissionError) or getattr(error, "winerror", None) in TRANSIENT_WINERRORS


def with_retry(action, delays: tuple[float, ...] = RETRY_DELAYS):
    """NAS（SMB）上的文件被同步/Web 服务占用或网络短暂中断时，按退避重试。"""
    for delay in (*delays, None):
        try:
            return action()
        except OSError as error:
            if delay is None or not transient(error):
                raise
            time.sleep(delay)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def site_files(root: Path) -> dict[str, Path]:
    """站点相对路径（POSIX）→ 文件；登记目录与中断留下的临时文件不属于站点内容。"""
    if not root.is_dir():
        return {}
    files = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_file() and relative.split("/")[0] != STATE_DIR and not path.name.endswith(".publishing"):
            files[relative] = path
    return files


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.publishing")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with_retry(lambda: os.replace(temporary, path))


def other_claims(destination: Path, publisher: str) -> dict[str, str]:
    claims = {}
    for state in sorted((destination / STATE_DIR).glob("*.json")):
        if state.name == REGISTRY or state.stem == publisher:
            continue
        for relative in read_json(state, {}).get("files", {}):
            claims[relative] = state.stem
    return claims


def update_registry(destination: Path, publisher: str, entry: dict) -> None:
    """只改写本发布方的键；写入前确认文件未被其他发布方同时改动，否则重新合并。"""
    path = destination / STATE_DIR / REGISTRY
    for _ in range(5):
        before = path.read_bytes() if path.is_file() else b""
        registry = json.loads(before) if before else {}
        registry.setdefault("publishers", {})[publisher] = entry
        if (path.read_bytes() if path.is_file() else b"") != before:
            continue
        write_json(path, registry)
        return
    raise RuntimeError("registry.json 持续被其他发布方改写，请稍后重试")


def copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.publishing")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def publish_order(relative: str) -> tuple:
    # 先写数据与资源，最后写页面，避免新页面引用尚未到位的文件。
    return (relative.endswith(".html"), relative.endswith(".json"), relative)


def publish_owned(source: Path, destination: Path, publisher: str = PUBLISHER, nav: list | None = None) -> dict:
    source = source.resolve()
    if not (source / "index.html").is_file():
        raise FileNotFoundError(f"source site has no index.html: {source}")
    destination = destination.absolute()
    if not destination.name or destination.parent == destination:
        raise ValueError(f"refusing unsafe destination: {destination}")
    if source == destination.resolve():
        raise ValueError("source and destination must be different")
    destination.mkdir(parents=True, exist_ok=True)

    state_path = destination / STATE_DIR / f"{publisher}.json"
    previous = read_json(state_path, None)
    claims = other_claims(destination, publisher)
    files = site_files(source)
    if previous is None:
        # 首次按共同维护方式发布：此前本流水线整站替换部署目录，其他发布方未登记的现有文件都来自本流水线。
        owned_before = {relative: None for relative in site_files(destination) if relative not in claims}
    else:
        owned_before = previous.get("files", {})

    conflicts = sorted(relative for relative in files if relative in claims)
    unowned = sorted(relative for relative in files if relative not in owned_before and relative not in claims and (destination / relative).exists())
    if conflicts or unowned:
        details = [f"{relative}（属于 {claims[relative]}）" for relative in conflicts] + [f"{relative}（未登记）" for relative in unowned]
        raise ValueError("与站点上其他内容冲突，未做任何改动：" + "；".join(details[:20]))

    owned, copied, removed = {}, 0, 0
    for relative in sorted(files, key=publish_order):
        digest = sha256(files[relative])
        owned[relative] = digest
        target = destination / relative
        if owned_before.get(relative) == digest and target.is_file():
            continue
        # 首次登记（或上次中断）时没有记录的摘要：现有文件内容已一致则不再复制。
        if relative in owned_before and owned_before[relative] is None and with_retry(lambda: target.is_file()
                and target.stat().st_size == files[relative].stat().st_size and sha256(target) == digest):
            continue
        with_retry(lambda: copy_file(files[relative], target))
        copied += 1

    for relative in sorted(set(owned_before) - set(files) - set(claims), reverse=True):
        target = destination / relative
        if with_retry(target.is_file):
            with_retry(target.unlink)
            removed += 1
        parent = target.parent
        while parent != destination and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    published_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    write_json(state_path, {"publisher": publisher, "published_at": published_at, "files": owned})
    update_registry(destination, publisher, {"published_at": published_at, "nav": nav or []})
    return {"files": len(owned), "copied": copied, "removed": removed}


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish this pipeline's site files into a co-maintained deployment directory.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--publisher", default=PUBLISHER)
    parser.add_argument(
        "--best-effort",
        action="store_true",
        help="Report deployment errors as warnings without failing the pipeline.",
    )
    parser.add_argument("--status-file", type=Path, help="写出 NAS 发布结果 JSON（status: published/failed），供批次清单单独记录")
    args = parser.parse_args()

    def write_status(**record) -> None:
        if args.status_file:
            args.status_file.parent.mkdir(parents=True, exist_ok=True)
            record.update(destination=str(args.destination), publisher=args.publisher)
            args.status_file.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    try:
        result = publish_owned(args.source, args.destination, args.publisher)
    except Exception as error:
        message = f"NAS publish failed: {error}"
        write_status(status="failed", error=str(error))
        if args.best_effort:
            print(f"WARNING: {message}", file=sys.stderr)
            return 0
        print(f"ERROR: {message}", file=sys.stderr)
        return 1

    write_status(status="published", result=result)
    print(f"Published site: {args.source.absolute()} -> {args.destination.absolute()} {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

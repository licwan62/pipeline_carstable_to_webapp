from __future__ import annotations

import argparse
import shutil
import sys
import time
import uuid
from pathlib import Path


RENAME_RETRY_DELAYS = (1, 2, 4, 8, 15)


def rename_with_retry(source: Path, target: Path, delays: tuple[float, ...] = RENAME_RETRY_DELAYS) -> None:
    """NAS（SMB）上目录刚被重命名或仍被同步/Web 服务占用时会短暂拒绝访问，按退避重试。"""
    for delay in (*delays, None):
        try:
            source.rename(target)
            return
        except PermissionError:
            if delay is None:
                raise
            time.sleep(delay)


def replace_directory(source: Path, destination: Path) -> None:
    source = source.resolve()
    if not (source / "index.html").is_file():
        raise FileNotFoundError(f"source site has no index.html: {source}")

    destination = destination.absolute()
    if not destination.name or destination.parent == destination:
        raise ValueError(f"refusing unsafe destination: {destination}")
    if source == destination:
        raise ValueError("source and destination must be different")

    destination.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    staging = destination.parent / f".{destination.name}.deploy-{token}"
    backup = destination.parent / f".{destination.name}.backup-{token}"
    moved_existing = False

    try:
        shutil.copytree(source, staging)
        if not (staging / "index.html").is_file():
            raise FileNotFoundError(f"staged site has no index.html: {staging}")
        if destination.exists():
            rename_with_retry(destination, backup)
            moved_existing = True
        rename_with_retry(staging, destination)
    except Exception:
        if moved_existing and backup.exists() and not destination.exists():
            rename_with_retry(backup, destination)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    if backup.exists():
        shutil.rmtree(backup)


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy a complete static site to a deployment directory.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument(
        "--best-effort",
        action="store_true",
        help="Report deployment errors as warnings without failing the pipeline.",
    )
    args = parser.parse_args()

    try:
        replace_directory(args.source, args.destination)
    except Exception as error:
        message = f"NAS publish failed: {error}"
        if args.best_effort:
            print(f"WARNING: {message}", file=sys.stderr)
            return 0
        print(f"ERROR: {message}", file=sys.stderr)
        return 1

    print(f"Published site: {args.source.absolute()} -> {args.destination.absolute()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

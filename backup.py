from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parent.resolve()
BACKUP_DIR_NAME = "bak"
SOURCE_DIR_NAMES = ("data", "configs")
MANIFEST_NAME = "manifest.json"
INCOMPLETE_MARKER_NAME = ".incomplete"
BUFFER_SIZE = 1024 * 1024


def rename_with_retry(source: Path, target: Path, attempts: int = 20) -> None:
    for attempt in range(attempts):
        try:
            source.rename(target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.1)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(BUFFER_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def source_inventory(source_dir: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        inventory.append(
            {
                "path": path.relative_to(source_dir).as_posix(),
                "size": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    return inventory


def validate_backup_name(name: str) -> str:
    if not name or name in {".", ".."} or Path(name).name != name:
        raise ValueError("存档名只能是单个目录名，不能包含路径分隔符。")
    return name


def next_backup_name(backup_root: Path, preferred: str | None = None) -> str:
    if preferred is not None:
        name = validate_backup_name(preferred)
        if (backup_root / name).exists():
            raise FileExistsError(f"存档已存在: {backup_root / name}")
        return name

    base = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    name = base
    counter = 1
    while (backup_root / name).exists():
        name = f"{base}_{counter:02d}"
        counter += 1
    return name


def detect_project_name(root: Path) -> str | None:
    input_dir = root / "data" / "input"
    if not input_dir.is_dir():
        return None
    input_files = sorted(
        path for path in input_dir.glob("*.xlsx") if not path.name.startswith("~$")
    )
    if len(input_files) == 1:
        return input_files[0].stem
    return None


def create_backup(root: Path = ROOT, name: str | None = None) -> Path:
    root = root.resolve()
    backup_root = root / BACKUP_DIR_NAME
    sources = [root / source_name for source_name in SOURCE_DIR_NAMES]
    missing = [source for source in sources if not source.is_dir()]
    if missing:
        missing_text = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"缺少待存档目录: {missing_text}")

    backup_root.mkdir(parents=True, exist_ok=True)
    if name is None:
        project_name = detect_project_name(root)
        if project_name and not (backup_root / project_name).exists():
            name = project_name
        elif project_name:
            name = f"{project_name}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_name = next_backup_name(backup_root, name)
    destination = backup_root / backup_name

    try:
        destination.mkdir()
        (destination / INCOMPLETE_MARKER_NAME).write_text("creating\n", encoding="utf-8")
        source_entries: list[dict[str, Any]] = []
        for source in sources:
            copied_source = destination / source.name
            shutil.copytree(source, copied_source, copy_function=shutil.copy2)
            files = source_inventory(copied_source)
            source_entries.append(
                {
                    "path": source.name,
                    "file_count": len(files),
                    "total_bytes": sum(item["size"] for item in files),
                    "files": files,
                }
            )

        manifest = {
            "version": 1,
            "name": backup_name,
            "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "sources": source_entries,
        }
        (destination / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (destination / INCOMPLETE_MARKER_NAME).unlink()
    except Exception:
        if destination.exists():
            shutil.rmtree(destination)
        raise

    return destination


def load_manifest(backup_dir: Path) -> dict[str, Any]:
    if (backup_dir / INCOMPLETE_MARKER_NAME).exists():
        raise ValueError(f"存档尚未创建完成: {backup_dir}")
    manifest_path = backup_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"存档缺少 {MANIFEST_NAME}: {backup_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise ValueError(f"不支持的存档版本: {manifest.get('version')}")
    return manifest


def get_backup_dir(root: Path, name: str) -> Path:
    backup_dir = root.resolve() / BACKUP_DIR_NAME / validate_backup_name(name)
    if not backup_dir.is_dir():
        raise FileNotFoundError(f"存档不存在: {backup_dir}")
    return backup_dir


def verify_backup(backup_dir: Path) -> list[str]:
    manifest = load_manifest(backup_dir)
    errors: list[str] = []

    for source in manifest.get("sources", []):
        source_name = source["path"]
        source_dir = backup_dir / source_name
        if not source_dir.is_dir():
            errors.append(f"缺少目录: {source_name}")
            continue

        expected = {item["path"]: item for item in source.get("files", [])}
        actual_paths = {
            path.relative_to(source_dir).as_posix()
            for path in source_dir.rglob("*")
            if path.is_file()
        }
        for relative_path in sorted(expected.keys() - actual_paths):
            errors.append(f"缺少文件: {source_name}/{relative_path}")
        for relative_path in sorted(actual_paths - expected.keys()):
            errors.append(f"多出文件: {source_name}/{relative_path}")
        for relative_path in sorted(expected.keys() & actual_paths):
            path = source_dir / Path(relative_path)
            item = expected[relative_path]
            if path.stat().st_size != item["size"]:
                errors.append(f"大小不符: {source_name}/{relative_path}")
            elif file_sha256(path) != item["sha256"]:
                errors.append(f"校验失败: {source_name}/{relative_path}")

    return errors


def list_backups(root: Path = ROOT) -> list[dict[str, Any]]:
    backup_root = root.resolve() / BACKUP_DIR_NAME
    if not backup_root.is_dir():
        return []

    backups: list[dict[str, Any]] = []
    for backup_dir in sorted(backup_root.iterdir(), reverse=True):
        if not backup_dir.is_dir() or backup_dir.name.startswith("."):
            continue
        try:
            manifest = load_manifest(backup_dir)
            backups.append(manifest)
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            backups.append({"name": backup_dir.name, "invalid": True})
    return backups


def restore_backup(root: Path, name: str, *, force: bool = False) -> tuple[Path, Path]:
    if not force:
        raise PermissionError("恢复会替换当前 data 和 configs；请确认后加 --force。")

    root = root.resolve()
    backup_dir = get_backup_dir(root, name)
    errors = verify_backup(backup_dir)
    if errors:
        details = "\n".join(f"- {error}" for error in errors[:20])
        raise ValueError(f"存档校验失败，未执行恢复:\n{details}")

    safety_name = "pre_restore_" + dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safety_backup = create_backup(root, safety_name)
    operation_id = uuid.uuid4().hex
    staging = root / f".restore-stage-{operation_id}"
    rollback = root / f".restore-rollback-{operation_id}"

    try:
        for source_name in SOURCE_DIR_NAMES:
            shutil.copytree(backup_dir / source_name, staging / source_name, copy_function=shutil.copy2)

        rollback.mkdir()
        for source_name in SOURCE_DIR_NAMES:
            current = root / source_name
            if current.exists():
                rename_with_retry(current, rollback / source_name)
            rename_with_retry(staging / source_name, current)
    except Exception:
        for source_name in SOURCE_DIR_NAMES:
            current = root / source_name
            old = rollback / source_name
            if old.exists():
                if current.exists():
                    shutil.rmtree(current)
                rename_with_retry(old, current)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if rollback.exists():
            shutil.rmtree(rollback)

    return backup_dir, safety_backup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="存档或恢复项目的 data 和 configs 目录。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="创建一个完整存档。")
    create_parser.add_argument("--name", help="自定义项目存档名；默认使用 input 中的 xlsx 文件名。")
    create_parser.add_argument(
        "--clean-workspace",
        "--clean",
        "--no-keep-workspace",
        action="store_true",
        help="存档校验成功后清空 input、middle 和 output 工作区。",
    )

    subparsers.add_parser("list", help="列出已有存档。")

    verify_parser = subparsers.add_parser("verify", help="校验存档内容是否完整。")
    verify_parser.add_argument("name", help="要校验的存档名。")

    restore_parser = subparsers.add_parser("restore", help="恢复一个存档。")
    restore_parser.add_argument("name", help="要恢复的存档名。")
    restore_parser.add_argument("--force", action="store_true", help="确认替换当前 data 和 configs。")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        arguments = ["create"]
    args = build_parser().parse_args(arguments)

    try:
        if args.command == "create":
            destination = create_backup(name=args.name)
            print(f"存档完成: {destination}")
            errors = verify_backup(destination)
            if errors:
                raise ValueError("新存档校验失败，工作区未清理。")
            if args.clean_workspace:
                from cleanup import clean_workspace

                removed = clean_workspace(ROOT)
                print(f"工作区已清理: {len(removed)} 个项目")
            return 0

        if args.command == "list":
            backups = list_backups()
            if not backups:
                print("暂无存档。")
                return 0
            for manifest in backups:
                if manifest.get("invalid"):
                    print(f"{manifest['name']}  [无效存档]")
                    continue
                file_count = sum(source["file_count"] for source in manifest["sources"])
                total_bytes = sum(source["total_bytes"] for source in manifest["sources"])
                size_mb = total_bytes / 1024 / 1024
                print(f"{manifest['name']}  {manifest['created_at']}  {file_count} files  {size_mb:.2f} MiB")
            return 0

        backup_dir = get_backup_dir(ROOT, args.name)
        if args.command == "verify":
            errors = verify_backup(backup_dir)
            if errors:
                print("存档校验失败:")
                for error in errors:
                    print(f"- {error}")
                return 1
            print(f"存档完整: {backup_dir}")
            return 0

        if args.command == "restore":
            restored, safety = restore_backup(ROOT, args.name, force=args.force)
            print(f"恢复完成: {restored}")
            print(f"恢复前的内容已安全存档: {safety}")
            return 0
    except (FileNotFoundError, FileExistsError, PermissionError, ValueError, OSError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())

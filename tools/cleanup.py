from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_DIRS = (
    Path("input"),
    Path("public"),
)
PRESERVED_NAMES = {".gitkeep", ".尺码匹配表放在此处"}


def workspace_items(root: Path = ROOT) -> list[Path]:
    project_root = root.resolve()
    items: list[Path] = []
    for relative_dir in WORKSPACE_DIRS:
        directory = project_root / relative_dir
        if not directory.is_dir():
            continue
        items.extend(path for path in directory.iterdir() if path.name not in PRESERVED_NAMES)
    return items


def clean_workspace(root: Path = ROOT, *, dry_run: bool = False) -> list[Path]:
    removed = workspace_items(root)
    for path in removed:
        print(f"[clean] {path}")
        if dry_run:
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="清空 input 和 public；所有历史 artifact 批次保持不变。"
    )
    parser.add_argument("--force", action="store_true", help="确认删除工作区文件。")
    parser.add_argument("--dry-run", action="store_true", help="只显示将删除的内容。")
    args = parser.parse_args(argv)

    if not args.force and not args.dry_run:
        print("错误: 清理会删除当前工作区文件；请先存档，并在确认后加 --force。", file=sys.stderr)
        return 1

    removed = clean_workspace(dry_run=args.dry_run)
    action = "将清理" if args.dry_run else "已清理"
    print(f"{action} {len(removed)} 个工作区项目；历史 artifact 批次保持不变。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

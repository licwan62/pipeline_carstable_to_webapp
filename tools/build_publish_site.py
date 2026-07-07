from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


SKELETON_DIRS = ["assets", "config", "data/generated", "pages"]
SKELETON_FILES = ["README.md", ".nojekyll"]


def copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        return
    shutil.copytree(source, target, dirs_exist_ok=True)


def copy_file(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a webapp site in a local workspace without modifying the publish repo.")
    parser.add_argument("--publish-repo", type=Path, required=True)
    parser.add_argument("--html-root", type=Path, required=True)
    parser.add_argument("--xlsx-source", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--site-output", type=Path, required=True)
    args = parser.parse_args()

    publish_repo = args.publish_repo.resolve()
    html_root = args.html_root.resolve()
    xlsx_source = args.xlsx_source.resolve()
    workspace = args.workspace.resolve()
    site_output = args.site_output.resolve()

    if not publish_repo.exists():
        raise FileNotFoundError(f"Publish repo does not exist: {publish_repo}")
    if not html_root.exists():
        raise FileNotFoundError(f"HTML root does not exist: {html_root}")
    if not xlsx_source.exists():
        raise FileNotFoundError(f"XLSX source does not exist: {xlsx_source}")

    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)

    for relative in SKELETON_DIRS:
        copy_tree(publish_repo / relative, workspace / relative)
    for relative in SKELETON_FILES:
        copy_file(publish_repo / relative, workspace / relative)

    copy_file(publish_repo / "tools" / "build_site.py", workspace / "tools" / "build_site.py")
    copy_file(publish_repo / "tools" / "export_xlsx_sources.py", workspace / "tools" / "export_xlsx_sources.py")
    copy_tree(html_root, workspace / "data" / "source" / "html")

    export_command = [
        sys.executable,
        str(workspace / "tools" / "export_xlsx_sources.py"),
        "--xlsx-source",
        str(xlsx_source),
    ]
    print(f"[export_xlsx_sources] {' '.join(export_command)}")
    subprocess.run(export_command, cwd=workspace, check=True)

    command = [sys.executable, str(workspace / "tools" / "build_site.py")]
    print(f"[build_site] {' '.join(command)}")
    subprocess.run(command, cwd=workspace, check=True)

    built_site = workspace / "_site"
    if not built_site.exists():
        raise FileNotFoundError(f"build_site.py did not produce: {built_site}")

    if site_output.exists():
        shutil.rmtree(site_output)
    shutil.copytree(built_site, site_output)
    print(f"Built site: {site_output}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "_site"

PRIMARY_PAGES = [
    "index.html",
    "size-chart.html",
    "size-match.html",
    "size-charts.html",
    "size-ref.html",
]


def copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        return
    shutil.copytree(source, target, dirs_exist_ok=True)


def copy_file(source: Path, target: Path) -> None:
    if source.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def discover_chart_directories() -> list[dict[str, object]]:
    html_root = ROOT / "data" / "source" / "html"
    if not html_root.exists():
        return []

    directories: list[dict[str, object]] = []
    for directory in sorted(path for path in html_root.rglob("*") if path.is_dir()):
        files = sorted(path.name for path in directory.glob("output_*.html"))
        if not files:
            continue
        name = directory.relative_to(html_root).as_posix()
        directories.append({"name": name, "files": files})
    return directories


def inject_chart_directories(page_path: Path, directories: list[dict[str, object]]) -> None:
    if not page_path.exists():
        return
    text = page_path.read_text(encoding="utf-8")
    start_marker = "      directories: "
    end_marker = "\n    };"
    start = text.find(start_marker)
    if start == -1:
        return
    end = text.find(end_marker, start)
    if end == -1:
        return

    json_text = json.dumps(directories, ensure_ascii=False, indent=8)
    replacement = start_marker + json_text
    page_path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


def main() -> None:
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)

    copy_tree(ROOT / "assets", SITE / "assets")
    copy_tree(ROOT / "config", SITE / "config")
    copy_tree(ROOT / "data" / "generated", SITE / "data" / "generated")
    copy_tree(ROOT / "data" / "source" / "html", SITE / "data" / "source" / "html")

    for page in PRIMARY_PAGES:
        copy_file(ROOT / "pages" / "level-1" / page, SITE / page)

    chart_directories = discover_chart_directories()
    for page in ["size-chart.html", "size-match.html", "size-charts.html"]:
        inject_chart_directories(SITE / page, chart_directories)

    copy_file(ROOT / "README.md", SITE / "README.md")
    copy_file(ROOT / ".nojekyll", SITE / ".nojekyll")


if __name__ == "__main__":
    main()

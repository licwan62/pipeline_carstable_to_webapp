from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import openpyxl
import yaml


SKELETON_DIRS = ["assets", "config", "data/generated", "pages"]
SKELETON_FILES = ["README.md", ".nojekyll"]
MATCH_COLUMNS = "MODEL,版本,YEAR,TYPE,CAB,BED,销量合计,L-MM,W-MM,H-MM,长度余量,SIZE"


class IndentedSafeDumper(yaml.SafeDumper):
    """Keep sequence items indented for the publish repo's small YAML parser."""

    def increase_indent(self, flow: bool = False, indentless: bool = False):
        return super().increase_indent(flow, indentless=False)


def copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        return
    shutil.copytree(source, target, dirs_exist_ok=True)


def copy_file(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def store_name(sheet_name: str) -> str:
    if sheet_name.startswith(("全尺码", "ALL尺码")):
        return "ALL"
    name = sheet_name
    for suffix in ("尺码匹配表", "尺码匹配"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name or sheet_name


def configure_excel_sources(
    workspace: Path,
    pipeline_config: Path,
    xlsx_source: Path,
    html_style_config: Path | None = None,
) -> bool:
    """Materialize publish sources from the pipeline's configured input sheets."""
    view_path = workspace / "config" / "size-chart-view.yaml"
    with pipeline_config.open("r", encoding="utf-8") as handle:
        pipeline = yaml.safe_load(handle) or {}
    with view_path.open("r", encoding="utf-8") as handle:
        view = yaml.safe_load(handle) or {}

    input_config = pipeline.get("input") or {}
    configured_sources = list(input_config.get("match_sources") or [])
    if not configured_sources:
        configured_sources = [
            {
                "name": store_name(str(sheet)),
                "label": str(sheet),
                "sheet": str(sheet),
                "header_row": 1,
                "columns": MATCH_COLUMNS,
            }
            for sheet in input_config.get("sheets") or []
        ]
    if not configured_sources:
        raise ValueError("Pipeline config must define input.match_sources or input.sheets")

    normalized_sources = []
    for source in configured_sources:
        if not isinstance(source, dict):
            raise ValueError(f"Invalid input.match_sources entry: {source!r}")
        missing_fields = [field for field in ("name", "sheet") if not source.get(field)]
        if missing_fields:
            raise ValueError(f"input.match_sources entry is missing {missing_fields}: {source!r}")
        normalized_sources.append(
            {
                "name": str(source["name"]),
                "label": str(source.get("label") or source["name"]),
                "sheet": str(source["sheet"]),
                "header_row": int(source.get("header_row", 1)),
                "columns": str(source.get("columns") or MATCH_COLUMNS),
            }
        )

    configured_sheets = [source["sheet"] for source in normalized_sources]
    workbook = openpyxl.load_workbook(xlsx_source, read_only=True, data_only=True)
    workbook_sheets = set(workbook.sheetnames)
    workbook.close()

    missing = [sheet for sheet in configured_sheets if sheet not in workbook_sheets]
    if missing:
        raise KeyError(f"Configured input worksheets do not exist: {missing}")

    view["match_sources"] = normalized_sources

    if html_style_config:
        with html_style_config.open("r", encoding="utf-8") as handle:
            html_style = yaml.safe_load(handle) or {}
        view["size_colors"] = {
            "a": html_style.get("size_a_background", "#1777c8"),
            "c": html_style.get("size_c_background", "#d62828"),
            "h": html_style.get("size_h_background", "#00a6a6"),
            "s": html_style.get("size_s_background", "#f28c28"),
            "other": html_style.get("size_other_background", html_style.get("size_badge_background", "#6b7280")),
            "text": html_style.get("size_badge_text_color", "#ffffff"),
        }

    reference_candidates = ["全尺码", "ALL尺码"]
    reference_sheet = next((name for name in reference_candidates if name in workbook_sheets), None)
    if reference_sheet is not None:
        view.setdefault("size_reference", {})["sheet"] = reference_sheet

    with view_path.open("w", encoding="utf-8", newline="\n") as handle:
        yaml.dump(
            view,
            handle,
            Dumper=IndentedSafeDumper,
            allow_unicode=True,
            sort_keys=False,
        )
    print(
        f"[configure_publish] match sheets={configured_sheets}; "
        f"size reference={reference_sheet or 'reuse existing generated data'}"
    )
    return reference_sheet is not None


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a webapp site in a local workspace without modifying the publish repo.")
    parser.add_argument("--publish-repo", type=Path, required=True)
    parser.add_argument("--html-root", type=Path, required=True)
    parser.add_argument("--xlsx-source", type=Path, required=True)
    parser.add_argument("--pipeline-config", type=Path, required=True)
    parser.add_argument("--html-style-config", type=Path)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--site-output", type=Path, required=True)
    args = parser.parse_args()

    publish_repo = args.publish_repo.resolve()
    html_root = args.html_root.resolve()
    xlsx_source = args.xlsx_source.resolve()
    pipeline_config = args.pipeline_config.resolve()
    html_style_config = args.html_style_config.resolve() if args.html_style_config else None
    workspace = args.workspace.resolve()
    site_output = args.site_output.resolve()

    if not publish_repo.exists():
        raise FileNotFoundError(f"Publish repo does not exist: {publish_repo}")
    if not html_root.exists():
        raise FileNotFoundError(f"HTML root does not exist: {html_root}")
    if not xlsx_source.exists():
        raise FileNotFoundError(f"XLSX source does not exist: {xlsx_source}")
    if not pipeline_config.exists():
        raise FileNotFoundError(f"Pipeline config does not exist: {pipeline_config}")
    if html_style_config and not html_style_config.exists():
        raise FileNotFoundError(f"HTML style config does not exist: {html_style_config}")

    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)

    for relative in SKELETON_DIRS:
        copy_tree(publish_repo / relative, workspace / relative)
    for relative in SKELETON_FILES:
        copy_file(publish_repo / relative, workspace / relative)

    copy_file(publish_repo / "tools" / "build_site.py", workspace / "tools" / "build_site.py")
    copy_file(publish_repo / "tools" / "export_xlsx_sources.py", workspace / "tools" / "export_xlsx_sources.py")
    copy_file(publish_repo / "tools" / "validate_generated_data.py", workspace / "tools" / "validate_generated_data.py")
    copy_tree(html_root, workspace / "data" / "source" / "html")
    exports_size_reference = configure_excel_sources(
        workspace, pipeline_config, xlsx_source, html_style_config
    )

    export_command = [
        sys.executable,
        str(workspace / "tools" / "export_xlsx_sources.py"),
        "--xlsx-source",
        str(xlsx_source),
    ]
    if not exports_size_reference:
        export_command.append("--skip-size-reference")
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

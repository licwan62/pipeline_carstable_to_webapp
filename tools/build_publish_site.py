from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_size_match_code_data import DEFAULT_SOURCE as SIZE_MATCH_CODE_SOURCE, build as build_size_match_code_data  # noqa: E402
from build_size_match_data import DEFAULT_SOURCE as SIZE_MATCH_SOURCE, build as build_size_match_data  # noqa: E402
from build_size_rules_data import DEFAULT_SOURCE, build as build_size_rules_data  # noqa: E402


SKELETON_DIRS = ["assets", "config", "data/generated", "pages"]
SKELETON_FILES = ["README.md", ".nojekyll"]
MATCH_COLUMNS = "MODEL,版本,YEAR,TYPE,CAB,BED,销量合计,L-MM,W-MM,H-MM,长度余量,SIZE"
PRESERVED_FRONTEND_FILES = [
    "assets/app/viewer.js",
    "assets/app/viewer.css",
    "size-match.html",
    "size-ref.html",
    "store-groups.html",
    "assets/app/site-common.js",
    "assets/app/size-ref.js",
    "assets/app/store-groups.js",
]


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


def preserve_frontend_overrides(site_output: Path, workspace: Path) -> None:
    """Keep reviewed match-view UI customizations when rebuilding generated data."""
    for relative in PRESERVED_FRONTEND_FILES:
        source = site_output / relative
        if source.is_file():
            copy_file(source, workspace / relative)


def configure_csv_sources(
    workspace: Path,
    pipeline_config: Path,
    html_style_config: Path | None = None,
) -> None:
    """Configure publish metadata for normalized CSV sources."""
    view_path = workspace / "config" / "size-chart-view.yaml"
    with pipeline_config.open("r", encoding="utf-8") as handle:
        pipeline = yaml.safe_load(handle) or {}
    with view_path.open("r", encoding="utf-8") as handle:
        view = yaml.safe_load(handle) or {}

    input_config = pipeline.get("input") or {}
    configured_stores = list(input_config.get("stores") or [])
    if not configured_stores:
        raise ValueError("Pipeline config must define input.stores")

    normalized_sources = []
    for store in configured_stores:
        if not isinstance(store, dict):
            raise ValueError(f"Invalid input.stores entry: {store!r}")
        missing_fields = [field for field in ("store", "sheet") if not store.get(field)]
        if missing_fields:
            raise ValueError(f"input.stores entry is missing {missing_fields}: {store!r}")
        normalized_sources.append(
            {
                "name": str(store["store"]),
                "label": str(store.get("label") or store["store"]),
                "sheet": str(store["sheet"]),
                "header_row": int(store.get("header_row", 1)),
                "columns": str(store.get("columns") or MATCH_COLUMNS),
            }
        )

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

    with view_path.open("w", encoding="utf-8", newline="\n") as handle:
        yaml.dump(
            view,
            handle,
            Dumper=IndentedSafeDumper,
            allow_unicode=True,
            sort_keys=False,
        )
    print(
        f"[configure_publish] stores="
        f"{[source['name'] for source in normalized_sources]}; reuse existing size reference"
    )


# 尺码配对页（size-match.html）只有一张表：A1 压缩尺码表（CODE 代号在前，点 MAKE 展开来源车型各年份），
# US 全量、US 店铺、EU、RU 六个数据源；SHAPE、长度余量、规则ID 由 A0 全量表按 DIMENSION-ID 补齐。
# 车型可视化的历史仍读 A0 全量分片（evolution.historyDataPath），旧 size-match-code.html 只做跳转。
MATCH_PAGE_OVERRIDE = """      matchDataPath: "data/generated/size-match-code.json",
      fieldOrder: ["CODE", "MODEL", "版本", "TYPE", "SHAPE", "YEAR", "CAB", "BED", "销量合计", "L-MM", "W-MM", "H-MM", "长度余量", "SIZE"],
      searchPlaceholder: "Search code, make, model, type, shape, size, year...",
      matchSources: [
        { name: "US", label: "US 全量", group: "US" },
        { name: "HNT", label: "US · HNT", group: "US" },
        { name: "TM", label: "US · TM", group: "US" },
        { name: "TM_拆分", label: "US · TM_拆分", group: "US" },
        { name: "EU", label: "EU", group: "EU" },
        { name: "RU", label: "RU", group: "RU" }
      ],
"""


# 前端资源版本：改动 viewer.js/css、site-common.js、size-evolution*、vendor 资源后递增，构建时统一写入所有页面，避免浏览器沿用旧缓存。
ASSET_VERSION = "20261013-5"
# assets/app/*.js|css 与 assets/vendor/<库>/*.js|css（ECharts 由页面配置 evolution.echartsPath 懒加载，路径同样带 ?v=）
ASSET_REFERENCE = re.compile(r"(assets/(?:app|vendor/[\w.-]+)/[\w.-]+\.(?:js|css))\?v=[\w-]+")

# 尺码配对页的车型尺寸演变可视化：只注入 size-match.html（viewer.js 按 evolution.enabled 启用，size-chart 不启用）；
# 表格是压缩记录，弹窗历史读 A0 全量分片 historyDataPath
EVOLUTION_PAGE = "size-match.html"
EVOLUTION_STYLE = f'  <link rel="stylesheet" href="assets/app/size-evolution.css?v={ASSET_VERSION}">\n'
EVOLUTION_SCRIPTS = (
    f'  <script src="assets/app/size-evolution-data.js?v={ASSET_VERSION}"></script>\n'
    f'  <script src="assets/app/size-evolution.js?v={ASSET_VERSION}"></script>\n'
)
EVOLUTION_CONFIG = f"""      evolution: {{
        enabled: true,
        echartsPath: "assets/vendor/echarts/echarts.min.js?v={ASSET_VERSION}",
        historyDataPath: "data/generated/size-match-full.json"
      }},
"""
EVOLUTION_ASSETS = [
    "assets/app/size-evolution-data.js",
    "assets/app/size-evolution.js",
    "assets/app/size-evolution.css",
    "assets/vendor/echarts/echarts.min.js",
    "assets/vendor/echarts/LICENSE",
]


def add_site_common_script(site_output: Path) -> None:
    """每个根目录页面都加载 site-common.js，以显示其他项目在 _publishers/registry.json 登记的入口。"""
    for page in site_output.glob("*.html"):
        text = page.read_text(encoding="utf-8")
        if "assets/app/site-common.js" in text or "</body>" not in text:
            continue
        tag = f'  <script src="assets/app/site-common.js?v={ASSET_VERSION}"></script>' + chr(10)
        end = text.rindex("</body>")
        page.write_text(text[:end] + tag + text[end:], encoding="utf-8")


def add_size_evolution(site_output: Path) -> None:
    """尺码配对页加载可视化样式、脚本并打开 evolution 开关；其他页面不加载（viewer.js 无开关时不显示入口）。"""
    missing = [relative for relative in EVOLUTION_ASSETS if not (site_output / relative).is_file()]
    if missing:
        raise FileNotFoundError(f"site_overrides 缺少可视化资源：{', '.join(missing)}")
    page = site_output / EVOLUTION_PAGE
    text = page.read_text(encoding="utf-8")
    if "size-evolution.js" in text:
        return
    config_marker = "    window.SIZE_CHART_VIEWER = {\n"
    style_marker = '  <link rel="stylesheet" href="assets/app/viewer.css'
    script_marker = '  <script src="assets/app/viewer.js'
    for marker in (config_marker, style_marker, script_marker):
        if marker not in text:
            raise ValueError(f"{EVOLUTION_PAGE} 缺少 {marker.strip()}，无法注入可视化")
    text = text.replace(config_marker, config_marker + EVOLUTION_CONFIG, 1)
    style_end = text.index("\n", text.index(style_marker)) + 1
    text = text[:style_end] + EVOLUTION_STYLE + text[style_end:]
    script_start = text.index(script_marker)
    text = text[:script_start] + EVOLUTION_SCRIPTS + text[script_start:]
    page.write_text(text, encoding="utf-8")


def stamp_asset_versions(site_output: Path) -> None:
    for page in site_output.glob("*.html"):
        text = page.read_text(encoding="utf-8")
        stamped = ASSET_REFERENCE.sub(lambda match: f"{match.group(1)}?v={ASSET_VERSION}", text)
        if stamped != text:
            page.write_text(stamped, encoding="utf-8")


def apply_site_overrides(site_output: Path) -> None:
    """构建完成后叠加项目自有页面和上游发布数据（build_site.py 会重建这些文件）。"""
    copy_tree(Path(__file__).resolve().parents[1] / "site_overrides", site_output)
    generated = site_output / "data" / "generated"
    build_size_rules_data(DEFAULT_SOURCE, generated)
    build_size_match_data(SIZE_MATCH_SOURCE, generated)
    build_size_match_code_data(SIZE_MATCH_CODE_SOURCE, generated, SIZE_MATCH_SOURCE)
    match_page = site_output / "size-match.html"
    text = match_page.read_text(encoding="utf-8")
    if "matchDataPath:" not in text:
        marker = 'sizeRefPath: "data/generated/size-ref.json",' + chr(10)
        if marker not in text:
            raise ValueError("size-match.html 缺少 sizeRefPath，无法注入 US/EU 数据源配置")
        match_page.write_text(text.replace(marker, marker + MATCH_PAGE_OVERRIDE, 1), encoding="utf-8")
    add_site_common_script(site_output)
    add_size_evolution(site_output)
    stamp_asset_versions(site_output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a webapp site in a local workspace without modifying the publish repo.")
    parser.add_argument("--publish-repo", type=Path, required=True)
    parser.add_argument("--html-root", type=Path, required=True)
    parser.add_argument("--pipeline-config", type=Path, required=True)
    parser.add_argument("--html-style-config", type=Path)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--site-output", type=Path, required=True)
    args = parser.parse_args()

    publish_repo = args.publish_repo.resolve()
    html_root = args.html_root.resolve()
    pipeline_config = args.pipeline_config.resolve()
    html_style_config = args.html_style_config.resolve() if args.html_style_config else None
    workspace = args.workspace.resolve()
    site_output = args.site_output.resolve()

    if not publish_repo.exists():
        raise FileNotFoundError(f"Publish repo does not exist: {publish_repo}")
    if not html_root.exists():
        raise FileNotFoundError(f"HTML root does not exist: {html_root}")
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
    copy_file(Path(__file__).with_name("export_csv_sources.py"), workspace / "tools" / "export_csv_sources.py")
    copy_file(publish_repo / "tools" / "validate_generated_data.py", workspace / "tools" / "validate_generated_data.py")
    copy_tree(html_root, workspace / "data" / "source" / "html")
    configure_csv_sources(workspace, pipeline_config, html_style_config)
    preserve_frontend_overrides(site_output, workspace)

    export_command = [
        sys.executable,
        str(workspace / "tools" / "export_csv_sources.py"),
        "--pipeline-config",
        str(pipeline_config),
    ]
    print(f"[export_csv_sources] {' '.join(export_command)}")
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
    apply_site_overrides(site_output)
    print(f"Built site: {site_output}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_size_match_code_data import DEFAULT_SOURCE as SIZE_MATCH_CODE_SOURCE, build as build_size_match_code_data  # noqa: E402
from build_size_match_data import DEFAULT_SOURCE as SIZE_MATCH_SOURCE  # noqa: E402
from build_size_rules_data import build as build_size_rules_data  # noqa: E402
from build_sales_year_data import DEFAULT_SOURCE as SALES_SOURCE, build as build_sales_year_data
from site_promote import promote_site  # noqa: E402
from validate_publish_site import validate_publish_site  # noqa: E402


# 外部站点骨架（publish_tables_to_webapp）只复制构建需要的源文件与资源：
# - data/generated 中的 size-match*.json 由本流水线每次重新生成，不复制，避免旧分片混入；
# - size-ref.json（旧尺码参考，35 行，本流水线不生成）是页面 sizeRefPath 的静态来源，按白名单单独复制。
# 当前 public 不再参与构建（原先从 public 回读的 8 个前端文件与 site_overrides/构建结果逐字节一致，见 docs/pipeline.md）。
SKELETON_DIRS = ["assets", "config", "pages"]
SKELETON_DATA_FILES = ["data/generated/size-ref.json"]
SKELETON_FILES = ["README.md", ".nojekyll"]
SKELETON_TOOLS = ["build_site.py", "export_xlsx_sources.py", "validate_generated_data.py"]
MATCH_COLUMNS = "MODEL,版本,YEAR,TYPE,CAB,BED,销量合计,L-MM,W-MM,H-MM,长度余量,SIZE"
STAGED_SITE = "_site"


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


# 尺码配对页（size-match.html）：一份数据 size-match-data.json（A0 全量行 + 引用这些行的 A1 压缩记录），
# 「视图」控件切换 压缩表（CODE 在前，点 CODE 展开来源车型各年份）/ 全量表（A0 逐行），默认压缩表，?view=full 直接打开全量表；
# US 全量、US 店铺、EU、RU 六个数据源；车型可视化历史读同一份数据的全量行（evolution.historyDataPath 与 matchDataPath 相同）。
# 旧 size-match-code.html 已弃用；验收要求见 docs/size-match-acceptance.md。
MATCH_DATA_PATH = "data/generated/size-match-data.json"
MATCH_PAGE_OVERRIDE = f"""      matchDataPath: "{MATCH_DATA_PATH}",
      tableModes: [
        {{ key: "compressed", label: "压缩表" }},
        {{ key: "full", label: "全量表" }}
      ],
      defaultTableMode: "compressed",
      fieldOrder: ["CODE", "MODEL", "版本", "TYPE", "SHAPE", "YEAR", "CAB", "BED", "销量合计", "L-MM", "W-MM", "H-MM", "长度余量", "SIZE"],
      searchPlaceholder: "Search code, make, model, type, shape, size, year...",
      matchSources: [
        {{ name: "US", label: "US 全量", group: "US" }},
        {{ name: "HNT", label: "US · HNT", group: "US" }},
        {{ name: "TM", label: "US · TM", group: "US" }},
        {{ name: "TM_拆分", label: "US · TM_拆分", group: "US" }},
        {{ name: "EU", label: "EU", group: "EU" }},
        {{ name: "RU", label: "RU", group: "RU" }}
      ],
"""


# 前端资源版本：改动 viewer.js/css、site-common.js、size-evolution*、vendor 资源后递增，构建时统一写入所有页面，避免浏览器沿用旧缓存。
ASSET_VERSION = "20261026-1"
# assets/app/*.js|css 与 assets/vendor/<库>/*.js|css（ECharts 由页面配置 evolution.echartsPath 懒加载，路径同样带 ?v=）
ASSET_REFERENCE = re.compile(r"(assets/(?:app|vendor/[\w.-]+)/[\w.-]+\.(?:js|css))\?v=[\w-]+")

# 尺码配对页的车型尺寸演变可视化：只注入 size-match.html（viewer.js 按 evolution.enabled 启用，size-chart 不启用）；
# 弹窗历史读同一份数据的全量行（historyDataPath = matchDataPath）
EVOLUTION_PAGE = "size-match.html"
EVOLUTION_STYLE = f'  <link rel="stylesheet" href="assets/app/size-evolution.css?v={ASSET_VERSION}">\n'
EVOLUTION_SCRIPTS = (
    f'  <script src="assets/app/size-evolution-data.js?v={ASSET_VERSION}"></script>\n'
    f'  <script src="assets/app/size-evolution.js?v={ASSET_VERSION}"></script>\n'
)
EVOLUTION_CONFIG = f"""      evolution: {{
        enabled: true,
        echartsPath: "assets/vendor/echarts/echarts.min.js?v={ASSET_VERSION}",
        historyDataPath: "{MATCH_DATA_PATH}",
        salesDataPath: "data/generated/sales-year-data.json"
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


# viewer.js 拆出的模块，凡加载 viewer.js 的页面都必须按此顺序在它之前加载：
# viewer-data.js（数据纯函数，window.SizeViewerData）→ viewer-rules.js（SIZE 规则索引与悬停 HTML，window.SizeViewerRules，依赖前者）
VIEWER_SCRIPT = '<script src="assets/app/viewer.js'
VIEWER_DATA_ASSET = "assets/app/viewer-data.js"
VIEWER_RULES_ASSET = "assets/app/viewer-rules.js"
VIEWER_MODULES = [VIEWER_DATA_ASSET, VIEWER_RULES_ASSET]


def add_viewer_module_scripts(site_output: Path) -> None:
    """在每个加载 viewer.js 的根目录页面中，于 viewer.js 之前按顺序插入尚未加载的 VIEWER_MODULES（幂等）。"""
    missing = [asset for asset in VIEWER_MODULES if not (site_output / asset).is_file()]
    if missing:
        raise FileNotFoundError(f"site_overrides 缺少 {', '.join(missing)}")
    for page in site_output.glob("*.html"):
        text = page.read_text(encoding="utf-8")
        modules = [asset for asset in VIEWER_MODULES if asset not in text]
        if VIEWER_SCRIPT not in text or not modules:
            continue
        start = text.index(VIEWER_SCRIPT)
        line_start = text.rfind(chr(10), 0, start) + 1
        indent = text[line_start:start]
        tags = "".join(f'<script src="{asset}?v={ASSET_VERSION}"></script>' + chr(10) + indent for asset in modules)
        page.write_text(text[:start] + tags + text[start:], encoding="utf-8")


add_viewer_data_script = add_viewer_module_scripts  # 旧名（只注入 viewer-data.js 时的函数名）


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


def apply_site_overrides(site_output: Path, a0_dir: Path | None = None, compressed_dir: Path | None = None, sales_dir: Path | None = None) -> None:
    """构建完成后叠加项目自有页面和上游发布数据（build_site.py 会重建这些文件）。

    a0_dir/compressed_dir 为本次运行固定的上游副本（run_all 在运行开始固定）；缺省时读 configs 中的上游 output。
    """
    a0_dir = a0_dir or SIZE_MATCH_SOURCE
    compressed_dir = compressed_dir or SIZE_MATCH_CODE_SOURCE
    copy_tree(Path(__file__).resolve().parents[1] / "site_overrides", site_output)
    generated = site_output / "data" / "generated"
    rules = build_size_rules_data(a0_dir, generated)
    print(f"[size-rules] {rules}")
    build_size_match_code_data(compressed_dir, generated, a0_dir)
    build_sales_year_data(sales_dir or SALES_SOURCE, generated, a0_dir)
    match_page = site_output / "size-match.html"
    text = match_page.read_text(encoding="utf-8")
    if "matchDataPath:" not in text:
        marker = 'sizeRefPath: "data/generated/size-ref.json",' + chr(10)
        if marker not in text:
            raise ValueError("size-match.html 缺少 sizeRefPath，无法注入 US/EU 数据源配置")
        match_page.write_text(text.replace(marker, marker + MATCH_PAGE_OVERRIDE, 1), encoding="utf-8")
    add_site_common_script(site_output)
    add_viewer_module_scripts(site_output)
    add_size_evolution(site_output)
    stamp_asset_versions(site_output)


def prepare_workspace(publish_repo: Path, html_root: Path, workspace: Path) -> None:
    """在 workspace 中放置外部站点骨架（白名单）、本仓库导出工具与店铺 HTML；不读取当前 public。"""
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    for relative in SKELETON_DIRS:
        copy_tree(publish_repo / relative, workspace / relative)
    for relative in [*SKELETON_DATA_FILES, *SKELETON_FILES]:
        copy_file(publish_repo / relative, workspace / relative)
    for name in SKELETON_TOOLS:
        copy_file(publish_repo / "tools" / name, workspace / "tools" / name)
    copy_file(Path(__file__).with_name("export_csv_sources.py"), workspace / "tools" / "export_csv_sources.py")
    copy_tree(html_root, workspace / "data" / "source" / "html")


def site_file_list(site_root: Path) -> list[dict[str, object]]:
    files = []
    for path in sorted(p for p in site_root.rglob("*") if p.is_file()):
        data = path.read_bytes()
        files.append({"path": path.relative_to(site_root).as_posix(), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    return files


# 尺码配对页数据层验收（docs/size-match-acceptance.md）：用页面自己的 viewer-data.js 检查临时站点的数据——两种视图、同一数据源、
# 压缩来源与 A1 逐条一致、搜索场景不出现上下文之外的车型。切换 public 之前运行，失败即不发布。
SIZE_MATCH_ACCEPTANCE = Path(__file__).resolve().parents[1] / "tests" / "acceptance" / "size_match_data.cjs"


def run_size_match_acceptance(site: Path, compressed_dir: Path | None = None) -> None:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("尺码配对数据验收需要 Node.js（node 不在 PATH）")
    command = [node, str(SIZE_MATCH_ACCEPTANCE), "--site", str(site), "--a1", str(compressed_dir or SIZE_MATCH_CODE_SOURCE)]
    print(f"[size-match acceptance] {' '.join(command)}")
    # Node 输出 UTF-8；经本进程按 stdout 编码转发（run_all 以本地编码读管道，直接继承管道会出现乱码与编码错误）
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    encoding = sys.stdout.encoding or "utf-8"
    print((completed.stdout + completed.stderr).encode(encoding, errors="replace").decode(encoding), end="", flush=True)
    if completed.returncode:
        raise RuntimeError(f"尺码配对数据验收未通过（退出码 {completed.returncode}），见上方 FAIL 项；public 未改动")
    annual = subprocess.run(
        [node, str(SIZE_MATCH_ACCEPTANCE.with_name("sales_year_data.cjs")), "--site", str(site)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    print((annual.stdout + annual.stderr).encode(encoding, errors="replace").decode(encoding), end="", flush=True)
    if annual.returncode:
        raise RuntimeError("年度销量数据验收未通过；public 未改动")


def build_staged_site(
    publish_repo: Path,
    html_root: Path,
    pipeline_config: Path,
    html_style_config: Path | None,
    workspace: Path,
    a0_dir: Path | None = None,
    compressed_dir: Path | None = None,
    sales_dir: Path | None = None,
) -> Path:
    """在 workspace 内完成导出、骨架构建、页面叠加、配对与规则数据、资源版本与完整校验，返回已校验的临时站点。"""
    prepare_workspace(publish_repo, html_root, workspace)
    configure_csv_sources(workspace, pipeline_config, html_style_config)

    export_command = [sys.executable, str(workspace / "tools" / "export_csv_sources.py"), "--pipeline-config", str(pipeline_config)]
    print(f"[export_csv_sources] {' '.join(export_command)}")
    subprocess.run(export_command, cwd=workspace, check=True)

    command = [sys.executable, str(workspace / "tools" / "build_site.py")]
    print(f"[build_site] {' '.join(command)}")
    subprocess.run(command, cwd=workspace, check=True)

    staged = workspace / STAGED_SITE
    if not staged.exists():
        raise FileNotFoundError(f"build_site.py did not produce: {staged}")
    apply_site_overrides(staged, a0_dir, compressed_dir, sales_dir)
    summary = validate_publish_site(staged)
    print(f"[validate] staged site: {summary}")
    run_size_match_acceptance(staged, compressed_dir)
    return staged


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the webapp site in a work directory, validate it, then switch it into --site-output."
    )
    parser.add_argument("--publish-repo", type=Path, required=True)
    parser.add_argument("--html-root", type=Path, required=True)
    parser.add_argument("--pipeline-config", type=Path, required=True)
    parser.add_argument("--html-style-config", type=Path)
    parser.add_argument("--workspace", type=Path, required=True, help="构建工作目录（work/<运行号>/05_site_workspace），每次重建")
    parser.add_argument("--site-output", type=Path, required=True)
    parser.add_argument("--a0-dir", type=Path, help="本次运行固定的 A0 output 副本（缺省读 configs 的 a0_output_dir）")
    parser.add_argument("--compressed-dir", type=Path, help="本次运行固定的 A1 压缩表 output 副本（缺省读 configs）")
    parser.add_argument("--sales-dir", type=Path, help="本次运行固定的销量 output 副本")
    parser.add_argument("--site-manifest", type=Path, help="写出已校验站点的文件清单与 sha256（JSON）")
    parser.add_argument("--no-promote", action="store_true", help="只构建并校验临时站点，不切换 --site-output")
    args = parser.parse_args()

    publish_repo = args.publish_repo.resolve()
    html_root = args.html_root.resolve()
    pipeline_config = args.pipeline_config.resolve()
    html_style_config = args.html_style_config.resolve() if args.html_style_config else None
    workspace = args.workspace.resolve()
    site_output = args.site_output.resolve()

    for label, path in (("Publish repo", publish_repo), ("HTML root", html_root), ("Pipeline config", pipeline_config)):
        if not path.exists():
            raise FileNotFoundError(f"{label} does not exist: {path}")
    if html_style_config and not html_style_config.exists():
        raise FileNotFoundError(f"HTML style config does not exist: {html_style_config}")
    if workspace == site_output or site_output in workspace.parents:
        raise ValueError(f"--workspace 不能位于 --site-output 内：{workspace}")

    staged = build_staged_site(
        publish_repo, html_root, pipeline_config, html_style_config, workspace,
        args.a0_dir.resolve() if args.a0_dir else None,
        args.compressed_dir.resolve() if args.compressed_dir else None,
        args.sales_dir.resolve() if args.sales_dir else None,
    )
    files = site_file_list(staged)
    if args.site_manifest:
        args.site_manifest.parent.mkdir(parents=True, exist_ok=True)
        args.site_manifest.write_text(json.dumps({"files": files}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if args.no_promote:
        print(f"Built and validated staged site (not promoted): {staged}")
        return
    method = promote_site(staged, site_output, validate_publish_site)
    print(f"Built site: {site_output} ({len(files)} files, switched by {method})")


if __name__ == "__main__":
    main()

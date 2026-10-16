#!/usr/bin/env python3
"""尺码配对页验收：按 docs/size-match-acceptance.md 的需求逐项检查一个已构建站点，输出通过/失败清单与报告。

三层，任一失败即退出码 1：
1. 结构：validate_publish_site（页面声明两种视图、同一数据源、数据分片与引用完整、无重复数据族等）；
2. 数据：tests/acceptance/size_match_data.cjs（用站点自己的 viewer-data.js 展开数据：两种视图、压缩来源与 A1 逐条一致、搜索场景）；
3. 浏览器：tests/acceptance/size_match_browser.cjs（Playwright 无头 Chromium 打开页面：视图切换、搜索、列筛选、来源展开、无报错）。

    python tools/acceptance_size_match.py                 # 验收 public/（A1 默认读 configs 的 compressed_output_dir）
    python tools/acceptance_size_match.py --site <目录> --a1 <A1 output>
    python tools/acceptance_size_match.py --no-browser    # 只跑结构与数据层（构建时自动运行的就是数据层）

报告写入 logs/acceptance/size-match-<时间>.md 与同名 .json。
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_size_match_code_data import DEFAULT_SOURCE as A1_SOURCE  # noqa: E402
from validate_publish_site import validate_publish_site  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "tests" / "acceptance"
PLAYWRIGHT_MISSING = 3


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


def serve(site: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def run_node(script: str, arguments: list[str], out: Path) -> tuple[int, list[dict]]:
    node = shutil.which("node")
    if not node:
        return 127, [{"id": script, "requirement": "-", "title": "需要 Node.js", "status": "fail", "detail": "node 不在 PATH"}]
    completed = subprocess.run([node, str(ACCEPTANCE / script), *arguments, "--out", str(out)], text=True, encoding="utf-8")
    results = json.loads(out.read_text(encoding="utf-8"))["results"] if out.is_file() else []
    return completed.returncode, results


def structure_layer(site: Path) -> list[dict]:
    try:
        summary = validate_publish_site(site)
    except ValueError as error:
        return [{"id": "V1", "requirement": "R1/R2", "title": "站点结构校验（validate_publish_site）", "status": "fail", "detail": str(error)}]
    detail = f"压缩 {summary.get('match_compressed_rows', 0)} 条 · 全量 {summary.get('match_full_rows', 0)} 行"
    ok = bool(summary.get("match_page_views")) and summary.get("match_compressed_rows", 0) > 0
    return [{"id": "V1", "requirement": "R1/R2", "title": "站点结构校验（validate_publish_site）",
             "status": "pass" if ok else "fail", "detail": detail if ok else f"页面没有使用 size-match-data 两种视图：{summary}"}]


def write_report(report_dir: Path, site: Path, layers: dict[str, list[dict]], notes: list[str]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    payload = {"site": str(site), "generated_at": datetime.now().isoformat(timespec="seconds"), "layers": layers, "notes": notes}
    (report_dir / f"size-match-{stamp}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# 尺码配对页验收 {stamp}", "", f"站点：`{site}`", "", "需求见 docs/size-match-acceptance.md。", ""]
    for layer, results in layers.items():
        lines += [f"## {layer}", "", "| 结果 | 编号 | 需求 | 检查 | 说明 |", "| --- | --- | --- | --- | --- |"]
        for item in results:
            mark = {"pass": "通过", "fail": "**失败**", "skip": "未运行"}[item["status"]]
            detail = str(item.get("detail", "")).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {mark} | {item['id']} | {item['requirement']} | {item['title']} | {detail} |")
        lines.append("")
    lines += [f"- {note}" for note in notes]
    path = report_dir / f"size-match-{stamp}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", type=Path, default=ROOT / "public", help="已构建的站点目录（默认 public/）")
    parser.add_argument("--a1", type=Path, default=A1_SOURCE, help="与站点数据同版本的 A1 output（压缩来源对照）")
    parser.add_argument("--no-browser", action="store_true", help="跳过浏览器层")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "logs" / "acceptance")
    args = parser.parse_args()
    site = args.site.resolve()

    layers: dict[str, list[dict]] = {}
    notes: list[str] = []
    print("== 结构层")
    layers["结构层"] = structure_layer(site)
    with tempfile.TemporaryDirectory() as directory:
        print("== 数据层")
        _, layers["数据层"] = run_node("size_match_data.cjs", ["--site", str(site), "--a1", str(args.a1.resolve())], Path(directory) / "data.json")
        if args.no_browser:
            notes.append("浏览器层已按 --no-browser 跳过；完整验收需要运行浏览器层。")
        else:
            print("== 浏览器层")
            server, url = serve(site)
            try:
                code, results = run_node("size_match_browser.cjs", ["--url", url, "--site", str(site)], Path(directory) / "browser.json")
            finally:
                server.shutdown()
            if code == PLAYWRIGHT_MISSING:
                results = [{"id": "B*", "requirement": "-", "title": "浏览器层", "status": "skip",
                            "detail": "找不到 Playwright，设置 SIZE_MATCH_PLAYWRIGHT 后重跑"}]
            elif not results:
                results = [{"id": "B*", "requirement": "-", "title": "浏览器层", "status": "fail", "detail": f"脚本异常退出（{code}）"}]
            layers["浏览器层"] = results

    all_results = [item for results in layers.values() for item in results]
    failed = [item for item in all_results if item["status"] != "pass"]
    for layer, results in layers.items():
        if layer == "结构层":
            for item in results:
                print(f"{'PASS' if item['status'] == 'pass' else 'FAIL'} {item['id']} {item['title']} — {item['detail']}")
    report = write_report(args.report_dir, site, layers, notes)
    print(f"\n验收{'通过' if not failed else '未通过'}：{len(all_results) - len(failed)}/{len(all_results)} 项通过；报告 {report}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())

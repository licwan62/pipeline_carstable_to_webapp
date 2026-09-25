#!/usr/bin/env python3
"""从 all_cars_data 的已发布交付物导入网站流水线的产线输入（替代原 normalize_store_inputs + compress_store_fitment）。

每条产线（US、HNT、TM、TM_拆分、EU、RU，取自 A2 manifest 的交付物，或 input.lines 指定）：
  - A1.全量生成/output/全量生成_<产线>.csv  -> <output-dir>/NNN-<店铺>.csv（表头规范化同 materialize_input_sources）
  - A2.压缩尺寸信息/output/压缩尺码表_<产线>_有损.csv      -> <compressed-root>/<店铺>/compress/<店铺>_非皮卡高度压缩表.csv
  - A2.压缩尺寸信息/output/压缩尺码表_<产线>_皮卡_有损.csv -> <compressed-root>/<店铺>/compress/<店铺>_皮卡高度压缩表.csv
所有读取的文件先按对应节点 output/manifest.json 校验 sha256；店铺名/标签按 input.store 模板以产线名为 {stem} 生成。
运行时配置（含 input.stores 与来源版本）写入 --output-config，供下游步骤读取。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from materialize_input_sources import build_store, csv_rows, load_config, safe_sheet_name, write_csv_rows  # noqa: E402

LINE_PATTERN = re.compile(r"^压缩尺码表_(.+)_有损\.csv$")


class SourceImportError(ValueError):
    pass


def load_manifest(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "manifest.json"
    if not path.is_file():
        raise SourceImportError(f"上游发布缺少 manifest.json：{output_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


def verified(output_dir: Path, manifest: dict[str, Any], name: str) -> Path:
    expected = next((item["sha256"] for item in manifest["deliverables"] if item["file"] == name), None)
    path = output_dir / name
    if expected is None or not path.is_file():
        raise SourceImportError(f"{manifest.get('node')} 发布中缺少 {name}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SourceImportError(f"{name} 与 {manifest.get('node')} 的 manifest.json sha256 不一致，请重新发布上游")
    return path


def manifest_lines(manifest: dict[str, Any]) -> list[str]:
    """A2 交付物中的产线，保持 manifest 顺序（非皮卡有损表 压缩尺码表_<产线>_有损.csv）。"""
    lines = []
    for item in manifest["deliverables"]:
        match = LINE_PATTERN.match(item["file"])
        if match and not match.group(1).endswith("_皮卡"):
            lines.append(match.group(1))
    return lines


def source_record(manifest: dict[str, Any]) -> dict[str, Any]:
    return {key: manifest.get(key) for key in ("node", "version", "artifact", "published_at")}


def import_lines(
    a1_output: Path,
    a2_output: Path,
    config_path: Path,
    output_dir: Path,
    output_config: Path,
    compressed_root: Path,
) -> list[dict[str, Any]]:
    config = load_config(config_path)
    a1_manifest, a2_manifest = load_manifest(a1_output), load_manifest(a2_output)
    available = manifest_lines(a2_manifest)
    configured = [str(line) for line in (config.get("input") or {}).get("lines") or []]
    unknown = sorted(set(configured) - set(available))
    if unknown:
        raise SourceImportError(f"input.lines 中的产线不在 A2 发布中：{unknown}（可用：{available}）")
    lines = configured or available
    if not lines:
        raise SourceImportError("A2 发布中没有可导入的产线")

    plans = []
    for line in lines:
        store = build_store(Path(f"{line}.csv"), config)
        plans.append(
            {
                "line": line,
                "store": store,
                "table": verified(a1_output, a1_manifest, f"全量生成_{line}.csv"),
                "non_pickup": verified(a2_output, a2_manifest, f"压缩尺码表_{line}_有损.csv"),
                "pickup": verified(a2_output, a2_manifest, f"压缩尺码表_{line}_皮卡_有损.csv"),
            }
        )
    names = [plan["store"]["store"] for plan in plans]
    if len(names) != len(set(names)):
        raise SourceImportError(f"产线生成的店铺名重复：{names}")

    output_dir.mkdir(parents=True, exist_ok=True)
    stores = []
    for index, plan in enumerate(plans, start=1):
        store, name = plan["store"], plan["store"]["store"]
        table_path = output_dir / f"{index:03d}-{safe_sheet_name(name)}.csv"
        row_count = write_csv_rows(csv_rows(plan["table"], config), table_path, config, plan["table"])
        store["file"] = plan["table"].name
        store["path"] = table_path.relative_to(output_config.parent).as_posix()
        store["line"] = plan["line"]
        folder = compressed_root / name / "compress"
        if folder.parent.exists():
            shutil.rmtree(folder.parent)
        folder.mkdir(parents=True)
        shutil.copy2(plan["non_pickup"], folder / f"{name}_非皮卡高度压缩表.csv")
        shutil.copy2(plan["pickup"], folder / f"{name}_皮卡高度压缩表.csv")
        stores.append(store)
        print(f"[line] {plan['line']} -> {name}: {table_path.name} ({row_count} rows), {folder}")

    runtime_config = dict(config)
    runtime_input = dict(runtime_config.get("input") or {})
    runtime_input.pop("sheets", None)
    runtime_input.pop("match_sources", None)
    runtime_input["stores"] = stores
    runtime_config["input"] = runtime_input
    runtime_config["sources"] = {"full_tables": source_record(a1_manifest), "compressed": source_record(a2_manifest)}
    output_config.parent.mkdir(parents=True, exist_ok=True)
    output_config.write_text(json.dumps(runtime_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Imported {len(stores)} line(s) from A1 {a1_manifest.get('version')} / A2 {a2_manifest.get('version')}; "
        f"runtime config: {output_config}"
    )
    return stores


def main() -> int:
    parser = argparse.ArgumentParser(description="Import A1 full tables and A2 compressed tables per product line.")
    parser.add_argument("--a1-output", type=Path, required=True)
    parser.add_argument("--a2-output", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-config", type=Path, required=True)
    parser.add_argument("--compressed-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        import_lines(
            args.a1_output.resolve(), args.a2_output.resolve(), args.config.resolve(),
            args.output_dir.resolve(), args.output_config.resolve(), args.compressed_root.resolve(),
        )
    except SourceImportError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

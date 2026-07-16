from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import pandas as pd


DATASETS = ("ALL尺码匹配", "TM尺码匹配", "HNT尺码匹配")
TABLE_SUFFIXES = (
    "非皮卡无损压缩表.tsv",
    "非皮卡高度压缩表.tsv",
    "皮卡无损压缩.tsv",
    "皮卡高度压缩表.tsv",
    "原子事实表.tsv",
    "压缩log.tsv",
)


def dataset_dir(root: Path, dataset: str) -> Path:
    matches = sorted(
        path for path in root.iterdir() if path.is_dir() and path.name.endswith(f"_{dataset}")
    )
    if not matches:
        raise FileNotFoundError(f"{root} 缺少 {dataset} 压缩目录")
    if len(matches) > 1:
        raise ValueError(f"{root} 存在多份 {dataset} 压缩目录")
    return matches[0]


def table_path(project_dir: Path, suffix: str) -> Path:
    prefix = project_dir.name
    return project_dir / "compress" / f"{prefix}_{suffix}"


def read_tsv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t", dtype=str, encoding="utf-8-sig", keep_default_na=False)


def merge_tables(base_path: Path, incremental_path: Path, output_path: Path) -> tuple[int, int, int]:
    base_exists = base_path.is_file()
    incremental_exists = incremental_path.is_file()
    if not base_exists and not incremental_exists:
        return 0, 0, 0
    base = read_tsv(base_path) if base_exists else pd.DataFrame()
    incremental = read_tsv(incremental_path) if incremental_exists else pd.DataFrame()
    if not base.empty and not incremental.empty and list(base.columns) != list(incremental.columns):
        raise ValueError(f"增量压缩表字段与原项目不一致: {incremental_path}")
    existing = {
        tuple(str(value) for value in row)
        for row in base.itertuples(index=False, name=None)
    }
    appended_indexes: list[int] = []
    for index, row in incremental.iterrows():
        signature = tuple(str(row[column]) for column in incremental.columns)
        if signature in existing:
            continue
        existing.add(signature)
        appended_indexes.append(index)
    additions = incremental.loc[appended_indexes]
    merged = pd.concat([base, additions], ignore_index=True, sort=False).reset_index(drop=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output_path, sep="\t", index=False, encoding="utf-8-sig")
    return len(base), len(incremental), len(merged)


def merge_compress_outputs(base_root: Path, incremental_root: Path) -> dict[str, dict[str, tuple[int, int, int]]]:
    summary: dict[str, dict[str, tuple[int, int, int]]] = {}
    for dataset in DATASETS:
        base_project = dataset_dir(base_root, dataset)
        incremental_project = dataset_dir(incremental_root, dataset)
        dataset_summary: dict[str, tuple[int, int, int]] = {}
        for suffix in TABLE_SUFFIXES:
            base_path = table_path(base_project, suffix)
            incremental_path = table_path(incremental_project, suffix)
            dataset_summary[suffix] = merge_tables(base_path, incremental_path, base_path)

        stale_xlsx = base_project / f"{base_project.name}_output.xlsx"
        if stale_xlsx.exists():
            stale_xlsx.unlink()
        stale_check = base_project / "check"
        if stale_check.exists():
            shutil.rmtree(stale_check)
        summary[dataset] = dataset_summary
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把增量压缩结果合入原项目 01_compress，不重新全量压缩。")
    parser.add_argument("--base-root", type=Path, required=True)
    parser.add_argument("--incremental-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = merge_compress_outputs(args.base_root.resolve(), args.incremental_root.resolve())
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"增量压缩结果合并失败: {exc}", file=sys.stderr)
        return 1

    for dataset, tables in summary.items():
        atom_counts = tables["原子事实表.tsv"]
        non_pickup_counts = tables["非皮卡高度压缩表.tsv"]
        pickup_counts = tables["皮卡高度压缩表.tsv"]
        print(
            f"[{dataset}] 原子 {atom_counts[0]}+{atom_counts[1]}->{atom_counts[2]} | "
            f"非皮卡 {non_pickup_counts[0]}+{non_pickup_counts[1]}->{non_pickup_counts[2]} | "
            f"皮卡 {pickup_counts[0]}+{pickup_counts[1]}->{pickup_counts[2]}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

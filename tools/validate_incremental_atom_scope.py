from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


DATASETS = ("ALL尺码匹配", "TM尺码匹配", "HNT尺码匹配")
SCOPE_COLUMNS = ("MAKE", "MODEL", "BACKSIZE")


def normalize(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).replace("\u00a0", " ").replace("\u200b", "").strip()


def read_tsv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t", dtype=str, encoding="utf-8-sig", keep_default_na=False)


def dataset_for_path(path: Path) -> str | None:
    text = str(path)
    return next((dataset for dataset in DATASETS if dataset in text), None)


def atom_scope_keys(atom_frame: pd.DataFrame) -> set[tuple[str, str, str]]:
    missing = [column for column in SCOPE_COLUMNS if column not in atom_frame.columns]
    if missing:
        raise ValueError(f"原子事实表缺少组合键列: {', '.join(missing)}")
    return {
        tuple(normalize(row[column]) for column in SCOPE_COLUMNS)
        for _, row in atom_frame.iterrows()
    }


def filter_atoms_by_scope(atom_frame: pd.DataFrame, keys: set[tuple[str, str, str]]) -> pd.DataFrame:
    mask = atom_frame.apply(
        lambda row: tuple(normalize(row[column]) for column in SCOPE_COLUMNS) in keys,
        axis=1,
    )
    return atom_frame.loc[mask].copy().reset_index(drop=True)


def atom_files_by_dataset(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in sorted(root.rglob("*_原子事实表.tsv")):
        dataset = dataset_for_path(path)
        if not dataset:
            continue
        if dataset in result:
            raise ValueError(f"{root} 中存在多份 {dataset} 原子事实表")
        result[dataset] = path
    missing = [dataset for dataset in DATASETS if dataset not in result]
    if missing:
        raise FileNotFoundError(f"{root} 缺少原子事实表: {', '.join(missing)}")
    return result


def validate_incremental_scope(
    *,
    incremental_root: Path,
    full_root: Path,
    compress_repo: Path,
) -> tuple[int, int, list[str]]:
    sys.path.insert(0, str(compress_repo.resolve()))
    from check_atom import build_atom_check  # type: ignore[import-not-found]

    incremental_atoms = atom_files_by_dataset(incremental_root)
    full_atoms = atom_files_by_dataset(full_root)
    scoped_count = 0
    overlap_count = 0
    errors: list[str] = []

    for dataset in DATASETS:
        incremental_frame = read_tsv(incremental_atoms[dataset])
        full_frame = read_tsv(full_atoms[dataset])
        keys = atom_scope_keys(incremental_frame)
        scoped_frame = filter_atoms_by_scope(full_frame, keys)
        incremental_signatures = {
            tuple(normalize(value) for value in row)
            for row in incremental_frame.astype(str).itertuples(index=False, name=None)
        }
        scoped_signatures = [
            tuple(normalize(value) for value in row)
            for row in scoped_frame.astype(str).itertuples(index=False, name=None)
        ]
        dataset_overlap = sum(signature not in incremental_signatures for signature in scoped_signatures)
        scoped_count += len(scoped_frame)
        overlap_count += dataset_overlap
        print(
            f"[{dataset}] 新增原子={len(incremental_frame)}，"
            f"组合键作用域={len(scoped_frame)}，历史重叠原子={dataset_overlap}"
        )

        full_atom_path = full_atoms[dataset]
        prefix = full_atom_path.stem.removesuffix("_原子事实表")
        compress_dir = full_atom_path.parent
        output_dir = full_atom_path.parent.parent / "check_incremental"
        output_dir.mkdir(parents=True, exist_ok=True)

        for atom_type, table_suffix in (
            ("非皮卡", "非皮卡高度压缩表"),
            ("皮卡", "皮卡高度压缩表"),
        ):
            type_atoms = scoped_frame[
                scoped_frame["压缩类型"].map(normalize) == atom_type
            ].copy()
            if type_atoms.empty:
                continue
            compress_path = compress_dir / f"{prefix}_{table_suffix}.tsv"
            if not compress_path.is_file():
                errors.append(f"缺少压缩表: {compress_path}")
                continue
            result = build_atom_check(type_atoms, read_tsv(compress_path))
            output_path = output_dir / f"{prefix}_{atom_type}增量原子检查.tsv"
            result.to_csv(output_path, sep="\t", index=False, encoding="utf-8-sig")
            failed = result[result["检查结果"].map(normalize) != "OK"]
            for _, row in failed.head(50).iterrows():
                errors.append(
                    f"{dataset}/{atom_type}: {normalize(row['检查结果'])} - "
                    f"{normalize(row['MAKE'])} {normalize(row['MODEL'])} "
                    f"{normalize(row['YEAR'])} {normalize(row['BACKSIZE'])}"
                )

    return scoped_count, overlap_count, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="只核验新增车型+尺码组合键，以及完整项目中与其重叠的历史原子。"
    )
    parser.add_argument("--incremental-root", type=Path, required=True)
    parser.add_argument("--full-root", type=Path, required=True)
    parser.add_argument("--compress-repo", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        scoped_count, overlap_count, errors = validate_incremental_scope(
            incremental_root=args.incremental_root.resolve(),
            full_root=args.full_root.resolve(),
            compress_repo=args.compress_repo.resolve(),
        )
    except (FileNotFoundError, ValueError, KeyError, OSError) as exc:
        print(f"增量原子核验失败: {exc}", file=sys.stderr)
        return 1

    if errors:
        print(f"增量原子核验失败，共 {len(errors)} 个问题：")
        for error in errors[:50]:
            print(f"- {error}")
        return 1
    print(f"增量原子核验通过：作用域 {scoped_count} 条，其中历史重叠 {overlap_count} 条。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

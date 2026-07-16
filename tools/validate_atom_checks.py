from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path


OK_RESULT = "OK"


def validate_atom_checks(root: Path) -> tuple[int, list[str]]:
    errors: list[str] = []
    atom_paths = sorted(root.rglob("*_原子事实表.tsv"))
    if not atom_paths:
        return 0, [f"没有找到原子事实表: {root}"]

    expected_checks: set[Path] = set()
    for atom_path in atom_paths:
        with atom_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            if "压缩类型" not in (reader.fieldnames or []):
                errors.append(f"{atom_path}: 缺少 压缩类型 列")
                continue
            types = {(row.get("压缩类型") or "").strip() for row in reader}
            types.discard("")
        if not types:
            errors.append(f"{atom_path}: 原子事实表没有数据行")
            continue
        prefix = atom_path.stem.removesuffix("_原子事实表")
        check_dir = atom_path.parent.parent / "check"
        for atom_type in types:
            expected_checks.add(check_dir / f"{prefix}_{atom_type}原子检查.tsv")

    for expected in sorted(expected_checks):
        if not expected.is_file():
            errors.append(f"缺少原子检查表: {expected}")

    check_paths = sorted(root.rglob("*原子检查.tsv"))
    if not check_paths:
        errors.append(f"没有找到原子检查表: {root}")
        return 0, errors

    checked_rows = 0
    for path in check_paths:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            if "检查结果" not in (reader.fieldnames or []):
                errors.append(f"{path}: 缺少 检查结果 列")
                continue

            results: Counter[str] = Counter()
            for line_number, row in enumerate(reader, start=2):
                checked_rows += 1
                result = (row.get("检查结果") or "").strip()
                results[result] += 1
                if result != OK_RESULT:
                    make = (row.get("MAKE") or "").strip()
                    model = (row.get("MODEL") or "").strip()
                    year = (row.get("YEAR") or "").strip()
                    errors.append(
                        f"{path}:{line_number}: {result or 'EMPTY'} - {make} {model} {year}"
                    )
            if not results:
                errors.append(f"{path}: 检查表没有数据行")

    if checked_rows == 0 and not errors:
        errors.append(f"原子检查表没有数据行: {root}")
    return checked_rows, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="确认所有原子检查结果均为 OK。")
    parser.add_argument("--root", type=Path, required=True, help="包含原子检查 TSV 的输出根目录。")
    args = parser.parse_args(argv)

    checked_rows, errors = validate_atom_checks(args.root.resolve())
    if errors:
        print(f"原子核验失败，共检查 {checked_rows} 行：")
        for error in errors[:50]:
            print(f"- {error}")
        if len(errors) > 50:
            print(f"- 其余 {len(errors) - 50} 个错误已省略")
        return 1

    print(f"原子核验通过：{checked_rows} 行全部为 OK。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

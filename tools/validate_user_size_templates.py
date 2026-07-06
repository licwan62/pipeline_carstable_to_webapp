from __future__ import annotations

import argparse
from pathlib import Path

from openpyxl import load_workbook


REQUIRED_SHEETS = ["非皮卡压缩表", "皮卡压缩表"]


def validate_workbook(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"模板不存在: {path}"]

    workbook = load_workbook(path, read_only=True, data_only=True)
    for sheet_name in REQUIRED_SHEETS:
        if sheet_name not in workbook.sheetnames:
            errors.append(f"{path}: 缺少工作表 {sheet_name}")
            continue

        sheet = workbook[sheet_name]
        header = [str(cell.value).strip() if cell.value is not None else "" for cell in sheet[1]]
        if "SIZE" not in header:
            errors.append(f"{path} / {sheet_name}: 缺少 SIZE 列")
            continue

    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate user-size middle workbooks before HTML generation.")
    parser.add_argument("workbooks", nargs="+", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    errors: list[str] = []
    for workbook in args.workbooks:
        errors.extend(validate_workbook(workbook))

    if errors:
        print("用户尺码模板未填写完整，暂不生成 HTML：")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    print("用户尺码模板校验通过。")


if __name__ == "__main__":
    main()

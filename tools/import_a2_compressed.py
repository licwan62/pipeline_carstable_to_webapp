"""兼容入口：import_a2_compressed.py 已更名为 import_compressed_tables.py（2026-10-14）。

旧命令与 ``import import_a2_compressed`` 继续可用；请改用新文件名与 --compressed-output 参数。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from import_compressed_tables import *  # noqa: E402,F401,F403
from import_compressed_tables import import_lines, main as _main  # noqa: E402,F401


def main(argv: list[str] | None = None) -> int:
    print("[import] tools/import_a2_compressed.py 已更名为 tools/import_compressed_tables.py，请更新调用方", file=sys.stderr)
    return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main())

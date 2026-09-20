import sys
from pathlib import Path

# 脚本集中在 tools/，测试直接按模块名导入（run_all、backup、cleanup 等）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

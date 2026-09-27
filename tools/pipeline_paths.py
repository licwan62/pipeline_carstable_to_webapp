"""按 configs/pipeline.yaml 的 paths 解析目录，供不经 run_all.py 直接调用的工具使用。

与 run_all.py 相同：存在 configs/pipeline.local.yaml（本机覆盖，可 include pipeline.yaml）时优先使用；
相对路径以本仓库根目录为基准。
"""

from __future__ import annotations

from pathlib import Path

from materialize_input_sources import load_config

ROOT = Path(__file__).resolve().parents[1]


def pipeline_config() -> dict:
    local = ROOT / "configs" / "pipeline.local.yaml"
    return load_config(local if local.is_file() else ROOT / "configs" / "pipeline.yaml")


def configured_path(key: str) -> Path:
    value = (pipeline_config().get("paths") or {}).get(key)
    if not value:
        raise KeyError(f"configs/pipeline.yaml 缺少 paths.{key}")
    path = Path(value)
    return (path if path.is_absolute() else ROOT / path).resolve()

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


# 语义名 -> 旧名（与 pipeline_core.PATH_KEY_ALIASES 相反方向）
LEGACY_KEYS = {"compressed_output_dir": "a2_output_dir"}


def configured_path(key: str) -> Path:
    paths = pipeline_config().get("paths") or {}
    new_key = {old: new for new, old in LEGACY_KEYS.items()}.get(key, key)
    old_key = LEGACY_KEYS.get(new_key)
    value = paths.get(new_key)
    legacy = paths.get(old_key) if old_key else None
    if value and legacy and str(value) != str(legacy):
        raise ValueError(f"paths.{old_key}（旧名）与 paths.{new_key} 不一致，请只保留 {new_key}")
    value = value or legacy
    if not value:
        raise KeyError(f"configs/pipeline.yaml 缺少 paths.{new_key}")
    path = Path(value)
    return (path if path.is_absolute() else ROOT / path).resolve()

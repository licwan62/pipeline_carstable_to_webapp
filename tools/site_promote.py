"""把已校验的临时站点切换为当前发布目录（public/），失败时恢复上一版。

Windows 上没有“替换非空目录”的单次原子操作，这里的切换是多步的，不声称原子：

1. 重命名切换（首选）：``public`` → ``.public.prev-<时间>``，再把临时站点重命名为 ``public``，然后对新 ``public`` 运行
   校验；任一步失败即删掉不完整的新目录并把上一版改回 ``public``。两次重命名之间存在 public 不存在的极短窗口。
2. 镜像切换（回退）：资源管理器、杀毒、同步盘等可能拒绝重命名被监视的目录（PermissionError），此时先完整复制
   上一版到 ``.public.prev-<时间>``，再就地镜像新站点，校验失败或镜像中断时从副本镜像回去。

成功后删除上一版副本；回滚本身也失败时保留副本并在异常中给出路径，供人工恢复。
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable


def rename_with_retry(source: Path, target: Path, attempts: int = 20) -> None:
    for attempt in range(attempts):
        try:
            source.rename(target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.1)


def mirror_directory(source: Path, target: Path) -> None:
    """Make target match source while keeping target's root directory in place."""
    target.mkdir(parents=True, exist_ok=True)
    source_items = {path.relative_to(source): path for path in source.rglob("*")}

    for relative, path in sorted(source_items.items(), key=lambda item: len(item[0].parts)):
        destination = target / relative
        if path.is_dir():
            if destination.exists() and not destination.is_dir():
                destination.unlink()
            destination.mkdir(parents=True, exist_ok=True)

    for relative, path in source_items.items():
        if not path.is_file():
            continue
        destination = target / relative
        if destination.exists() and destination.is_dir():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)

    for path in sorted(target.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.relative_to(target) in source_items:
            continue
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink()


def _backup_path(live: Path) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return live.parent / f".{live.name}.prev-{stamp}"


def _remove_tree(path: Path, live: Path) -> None:
    """只删除 live 同级、名称带 .prev-/.next- 的副本或 live 本身，防止误删。"""
    resolved = path.resolve()
    allowed = resolved == live.resolve() or resolved.name.startswith((f".{live.name}.prev-", f".{live.name}.next-"))
    if resolved.parent != live.resolve().parent or not allowed:
        raise RuntimeError(f"拒绝删除意外路径：{resolved}")
    shutil.rmtree(resolved)


def _discard_sibling(staged: Path, live: Path) -> None:
    """跨盘复制出的 .next- 临时副本在失败后删除；原 work 内的临时站点保留供诊断。"""
    if staged.exists() and staged.name.startswith(f".{live.name}.next-"):
        _remove_tree(staged, live)


def promote_site(staged: Path, live: Path, validate: Callable[[Path], Any], *, log: Callable[[str], None] = print) -> str:
    """把 staged 切换为 live 并对 live 运行 validate；返回所用方式（rename/mirror）。失败时 live 恢复为上一版并抛出。"""
    staged, live = staged.resolve(), live.resolve()
    if not staged.is_dir():
        raise FileNotFoundError(f"临时站点不存在：{staged}")
    live.parent.mkdir(parents=True, exist_ok=True)
    if os.stat(staged).st_dev != os.stat(live.parent).st_dev:
        # 跨盘符不能重命名：先在 live 同级复制一份，再走同盘重命名（在移开上一版之前完成，缩短无站点窗口）
        sibling = live.parent / f".{live.name}.next-{dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        shutil.copytree(staged, sibling)
        shutil.rmtree(staged)
        staged = sibling
    backup = _backup_path(live)
    had_live = live.exists()
    try:
        if had_live:
            rename_with_retry(live, backup)
    except PermissionError as error:
        log(f"[promote] 无法重命名 {live}（{error}），改用镜像切换")
        return _promote_by_mirror(staged, live, validate, backup, log)
    try:
        rename_with_retry(staged, live)
        validate(live)
    except BaseException as error:
        try:
            if live.exists():
                _remove_tree(live, live)
            if had_live:
                rename_with_retry(backup, live)
        except Exception as rollback_error:
            raise RuntimeError(f"站点切换失败（{error}），自动回滚也失败（{rollback_error}）；上一版保存在 {backup}") from error
        _discard_sibling(staged, live)
        log(f"[promote] 切换失败，已恢复上一版：{error}")
        raise
    if had_live:
        _remove_tree(backup, live)
    return "rename"


def _promote_by_mirror(staged: Path, live: Path, validate: Callable[[Path], Any], backup: Path, log: Callable[[str], None]) -> str:
    shutil.copytree(live, backup)
    try:
        mirror_directory(staged, live)
        validate(live)
    except BaseException as error:
        try:
            mirror_directory(backup, live)
        except Exception as rollback_error:
            raise RuntimeError(f"站点镜像切换失败（{error}），自动回滚也失败（{rollback_error}）；上一版保存在 {backup}") from error
        _remove_tree(backup, live)
        _discard_sibling(staged, live)
        log(f"[promote] 镜像切换失败，已恢复上一版：{error}")
        raise
    _remove_tree(backup, live)
    shutil.rmtree(staged)
    return "mirror"

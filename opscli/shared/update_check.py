"""PyPI 版本更新检查模块，仅 CLI 模式生效。

在 CLI 入口 main() 回调中调用 check_and_notify()，
检查 PyPI 最新版本与本地版本差异，有新版本时输出提示到 stderr。

缓存机制：查询结果缓存到 ~/.config/opscli/pypi_version_cache.json，
24 小时内不重复请求 PyPI，减少网络开销。
"""

from __future__ import annotations

import json
import time

import httpx
from rich.console import Console

from opscli.config import CONFIG_DIR
from opscli.version import get_version

# PyPI JSON API 地址，返回包的完整元数据
_PYPI_JSON_URL = "https://pypi.org/pypi/aukeys-opscli/json"

# 缓存文件路径，与 CONFIG_DIR 一致
_CACHE_FILE = CONFIG_DIR / "pypi_version_cache.json"

# 缓存有效期（秒），24 小时
_CACHE_TTL = 86400


def _parse_version(version_str: str) -> tuple[int, ...]:
    """将版本字符串解析为整数元组，供比较使用。

    支持标准语义化版本号（如 "0.0.72"），忽略 "v" 前缀，
    最多解析三段（major.minor.patch），不足补零。

    与 opscli/skills/sync/updater.py 的 parse() 同源逻辑，
    此处独立存在避免 shared 反向依赖 skills 模块。
    """
    normalized = version_str.strip()
    if normalized.startswith("v"):
        normalized = normalized[1:]
    parts = normalized.split(".")
    ints = [int(part) if part.isdigit() else 0 for part in parts[:3]]
    # 不足三段的补零，如 "1.2" → (1, 2, 0)
    while len(ints) < 3:
        ints.append(0)
    return tuple(ints)


def is_newer_available(current: str, latest: str) -> bool:
    """判断 latest 是否比 current 版本号更高。"""
    return _parse_version(current) < _parse_version(latest)


def _read_cache() -> dict | None:
    """读取本地缓存，返回 {"latest_version": str, "checked_at": float} 或 None。

    缓存过期、文件不存在、JSON 解析失败等异常情况均返回 None（静默降级）。
    """
    if not _CACHE_FILE.exists():
        return None
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        # 校验必要字段存在且类型正确
        if (
            isinstance(data, dict)
            and "latest_version" in data
            and "checked_at" in data
            and isinstance(data["checked_at"], (int, float))
        ):
            # 检查缓存是否在有效期内
            if time.time() - data["checked_at"] < _CACHE_TTL:
                return data
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        pass
    return None


def _write_cache(latest_version: str) -> None:
    """将 PyPI 最新版本号写入本地缓存文件。"""
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(
        json.dumps({
            "latest_version": latest_version,
            "checked_at": time.time(),
        }),
        encoding="utf-8",
    )


def _fetch_latest_version() -> str | None:
    """从 PyPI JSON API 获取最新版本号。

    Returns:
        最新版本号字符串，请求失败或解析失败时返回 None。
    """
    try:
        response = httpx.get(_PYPI_JSON_URL, timeout=5)
        response.raise_for_status()
        data = response.json()
        return data.get("info", {}).get("version")
    except Exception:
        return None


def _print_update_hint(current: str, latest: str) -> None:
    """输出更新提示到 stderr，不干扰 stdout 的正常输出。"""
    console = Console(stderr=True)
    console.print()
    console.print(
        f"[yellow]opscli 有新版本可用，建议更新最新版本: v{current} → v{latest}[/yellow]"
    )
    console.print("[dim]请运行以下命令一键更新（升级 CLI 并自动同步 Skills）：[/dim]")
    console.print("[cyan]  opscli self-update[/cyan]")
    console.print()


def check_and_notify() -> None:
    """检查是否有新版本可用，有则输出提示到 stderr。

    全流程静默：任何异常（网络、文件、解析）均不抛出，
    不影响 CLI 命令的正常执行。仅从 CLI 入口调用，
    MCP 模式天然不经过此处（独立进程入口）。
    """
    try:
        current = get_version()

        # 优先从缓存读取，避免每次都请求 PyPI
        cached = _read_cache()
        if cached:
            # 缓存有效：基于缓存数据判断，不重复请求
            if is_newer_available(current, cached["latest_version"]):
                _print_update_hint(current, cached["latest_version"])
            return

        # 缓存过期或不存在，请求 PyPI 刷新
        latest = _fetch_latest_version()
        if latest is None:
            return

        _write_cache(latest)

        if is_newer_available(current, latest):
            _print_update_hint(current, latest)
    except Exception:
        # 兜底：任何未预期的异常静默吞掉，不影响正常命令执行
        pass

"""用户级元数据缓存。

为 CLI 与 MCP 提供按用户隔离、带 TTL 与并发文件锁的全量元数据缓存，
避免每次取数都向后端拉全量 query-metadata。

两层缓存：
    L1 进程内内存（服务 MCP 长驻进程高频读）
    L2 磁盘 JSON（服务 CLI 短生命进程跨调用复用）

身份无关：只接收 (base_dir, user_email, fetch_fn)，身份由调用方注入，
避免 query 反向依赖 mcp（铁律2）。
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from opscli.config import CONFIG_DIR
from opscli.shared.file_lock import file_lock

_CACHE_VERSION = 1
_DEFAULT_TTL_SECONDS = 3600  # 默认 1 小时，可经调用方覆盖


@dataclass
class MetadataCacheResult:
    """缓存读取结果。

    Attributes:
        payload: 全量元数据 {"datasets": [...], "fields": [...], "select_columns": [...]}
        stale: True 表示后端拉取失败、回退到过期缓存
        fetched_at: 该 payload 的抓取时间（UTC）
        from_cache: True=命中缓存(L1/L2)，False=本次新抓取
    """

    payload: dict[str, Any]
    stale: bool
    fetched_at: datetime
    from_cache: bool


class MetadataCache:
    """按 base_dir 隔离的元数据缓存实例。线程安全。"""

    def __init__(self, base_dir: Path | None = None, ttl_seconds: int = _DEFAULT_TTL_SECONDS):
        # base_dir 为 None 时用默认 CONFIG_DIR（CLI/stdio 共享）；
        # MCP 多用户场景传入隔离目录。
        self._base = Path(base_dir) if base_dir else CONFIG_DIR
        self._dir = self._base / "metadata"
        self._ttl = ttl_seconds
        self._mem: dict[str, dict[str, Any]] = {}  # email_hash -> 信封
        self._lock = threading.Lock()
        # 按 email_hash 的进程内刷新锁：防同进程多线程重复拉取（配合跨进程 file_lock 构成双层锁）
        self._refresh_locks: dict[str, threading.Lock] = {}
        self._refresh_locks_guard = threading.Lock()

    @staticmethod
    def _email_hash(email: str) -> str:
        """按 email 生成 16 位十六进制缓存键（同机多账号隔离）。"""
        return hashlib.sha256(email.encode("utf-8")).hexdigest()[:16]

    def _envelope(self, email: str, payload: dict[str, Any]) -> dict[str, Any]:
        """构造磁盘/内存信封。"""
        return {
            "cache_version": _CACHE_VERSION,
            "user_email": email,
            "metadata_version": payload.get("metadata_version", ""),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "ttl_seconds": self._ttl,
            "payload": payload,
        }

    def _is_fresh(self, env: dict[str, Any], email: str) -> bool:
        """命中判定：email 一致且未超 TTL。"""
        # 换账号即失效（对齐 CredentialStore email 变更清 tokens 的约定）
        if env.get("user_email") != email:
            return False
        try:
            fetched = datetime.fromisoformat(env["fetched_at"])
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            return False
        age = (datetime.now(timezone.utc) - fetched).total_seconds()
        return age < env.get("ttl_seconds", self._ttl)

    def _cache_file(self, h: str) -> Path:
        """按 email 哈希定位缓存文件。"""
        return self._dir / f"{h}.json"

    def _lock_file(self, h: str) -> Path:
        """按 email 哈希定位锁文件（与缓存文件同目录）。"""
        return self._dir / f".lock_{h}"

    def _read_disk(self, h: str) -> dict[str, Any] | None:
        """读取磁盘信封；文件缺失或损坏返回 None。"""
        f = self._cache_file(h)
        if not f.exists():
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            # 损坏或读失败：视为无缓存，交由上层重新拉取
            return None

    def _write_disk(self, h: str, env: dict[str, Any]) -> None:
        """原子写信封：临时文件 + os.replace（照搬 updater 原子替换约定）。"""
        self._dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(env, fh, ensure_ascii=False)
            os.replace(tmp, self._cache_file(h))  # 同目录 rename，原子
        except BaseException:
            # 失败时清理临时文件，避免残留
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _refresh_lock(self, h: str) -> threading.Lock:
        """获取/创建某用户的进程内刷新锁（防同进程多线程重复拉取）。"""
        with self._refresh_locks_guard:
            if h not in self._refresh_locks:
                self._refresh_locks[h] = threading.Lock()
            return self._refresh_locks[h]

    def _result(self, env: dict[str, Any], *, stale: bool, from_cache: bool) -> MetadataCacheResult:
        """把信封投影为对外结果对象。"""
        fetched = datetime.fromisoformat(env["fetched_at"])
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        return MetadataCacheResult(
            payload=env["payload"], stale=stale, fetched_at=fetched, from_cache=from_cache
        )

    def get(self, user_email: str, fetch_fn: Callable[[], dict[str, Any]]) -> MetadataCacheResult:
        """读取用户全量元数据，未命中/过期时经 fetch_fn 拉取并缓存。

        Args:
            user_email: 当前用户邮箱（缓存隔离维度）。
            fetch_fn: 无参回调，返回后端全量 payload。

        Returns:
            MetadataCacheResult。
        """
        h = self._email_hash(user_email)

        # L1 内存
        with self._lock:
            env = self._mem.get(h)
        if env and self._is_fresh(env, user_email):
            return self._result(env, stale=False, from_cache=True)

        # L2 磁盘
        env = self._read_disk(h)
        if env and self._is_fresh(env, user_email):
            with self._lock:
                self._mem[h] = env
            return self._result(env, stale=False, from_cache=True)

        # miss/过期 → 双层锁（进程内刷新锁 + 跨进程 file_lock）刷新，防惊群
        with self._refresh_lock(h), file_lock(self._lock_file(h)):
            # 双重检查：可能有别的线程/进程刚刷完
            env2 = self._read_disk(h)
            if env2 and self._is_fresh(env2, user_email):
                with self._lock:
                    self._mem[h] = env2
                return self._result(env2, stale=False, from_cache=True)

            try:
                payload = fetch_fn()
            except Exception:
                # 后端拉取失败：有过期缓存则回退并标 stale，否则原样抛出
                stale_env = env2 or env
                if stale_env is not None:
                    return self._result(stale_env, stale=True, from_cache=True)
                raise

            new_env = self._envelope(user_email, payload)
            self._write_disk(h, new_env)
            with self._lock:
                self._mem[h] = new_env
            return self._result(new_env, stale=False, from_cache=False)

    def invalidate(self, user_email: str | None = None) -> None:
        """失效缓存。user_email=None 清全部用户；否则只清该用户。"""
        if user_email is None:
            with self._lock:
                self._mem.clear()
            if self._dir.exists():
                for f in self._dir.glob("*.json"):
                    try:
                        f.unlink()
                    except OSError:
                        pass
            return
        h = self._email_hash(user_email)
        with self._lock:
            self._mem.pop(h, None)
        try:
            self._cache_file(h).unlink()
        except OSError:
            pass


# 模块级缓存池：按 base_dir 隔离不同用户/客户端
_caches: dict[str | None, MetadataCache] = {}
_pool_lock = threading.Lock()


def get_metadata_cache(
    base_dir: Path | None = None, ttl_seconds: int = _DEFAULT_TTL_SECONDS
) -> MetadataCache:
    """获取池化的 MetadataCache（懒加载，按 base_dir 隔离）。"""
    key = str(base_dir) if base_dir else None
    if key not in _caches:
        with _pool_lock:
            if key not in _caches:
                _caches[key] = MetadataCache(base_dir=base_dir, ttl_seconds=ttl_seconds)
    return _caches[key]


def invalidate_metadata_cache(
    base_dir: Path | None = None, user_email: str | None = None
) -> None:
    """失效指定 base_dir 的缓存（登录/登出时调用）。

    必须通过 get_metadata_cache 拿到（必要时新建）实例再失效：
    CLI auth login/logout 是短生命进程，本进程从未实例化过缓存池，
    若只查已有池条目会静默 no-op，无法清除别的进程（如 MCP 服务）
    写在磁盘上的缓存，破坏"登录/登出强制失效"保证。
    """
    get_metadata_cache(base_dir).invalidate(user_email)

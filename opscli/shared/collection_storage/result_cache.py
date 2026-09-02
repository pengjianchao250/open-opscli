"""共享采集结果缓存合同。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Literal


CacheMode = Literal["prefer_cache", "live"]
ENV_RESULT_CACHE_ENABLED = "OPSCLI_COLLECTION_RESULT_CACHE_ENABLED"
ENV_RESULT_CACHE_TTL_SECONDS = "OPSCLI_COLLECTION_RESULT_CACHE_TTL_SECONDS"
DEFAULT_RESULT_CACHE_TTL_SECONDS = 86400

_cache_hit_context: ContextVar[bool] = ContextVar(
    "collection_result_cache_hit",
    default=False,
)


@dataclass(frozen=True)
class CachedCollectionResult:
    """一次从共享 MySQL 恢复的完整采集结果。"""

    source_job_id: str
    scenario: str
    site: str
    row_count: int
    completed_at: str | None
    persistence_completed_at: str | None
    result_metadata: dict[str, Any]
    datasets: tuple[dict[str, Any], ...]


def build_cache_key(source_system: str, request: dict[str, Any]) -> str:
    """对来源和规范化业务请求计算稳定 SHA-256 缓存键。"""
    payload = {
        "source_system": str(source_system or "").strip().lower(),
        "request": request,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def attach_cache_metadata(
    request_params: dict[str, Any],
    *,
    cache_key: str | None,
    cache_scope: str | None,
    result_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """把内部缓存索引附加到既有 request_params JSON。"""
    payload = dict(request_params)
    if cache_key and cache_scope:
        payload["_cache"] = {
            "version": 1,
            "cache_key": cache_key,
            "cache_scope": cache_scope,
            "result": dict(result_metadata or {}),
        }
    return payload


def safe_result_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """提取重建公开结果所需的低敏字段。"""
    export = payload.get("export")
    safe_export = None
    if isinstance(export, dict):
        safe_export = {
            key: export.get(key)
            for key in ("filename", "url", "format", "mime_type")
            if export.get(key) is not None
        }
    warnings = payload.get("warnings")
    safe_warnings = []
    if isinstance(warnings, list):
        for warning in warnings:
            if not isinstance(warning, dict):
                continue
            item = {
                key: warning.get(key)
                for key in ("stage", "message")
                if warning.get(key) is not None
            }
            if item:
                safe_warnings.append(item)
    return {
        "row_count": int(payload.get("row_count") or 0),
        "export": safe_export,
        "warnings": safe_warnings,
    }


def dataset_records(cached: CachedCollectionResult) -> list[dict[str, Any]]:
    """返回首个 Dataset 的对象记录，作为原服务主结果行。"""
    if not cached.datasets:
        return []
    records = cached.datasets[0].get("records")
    if not isinstance(records, list):
        return []
    return [
        dict(record["payload"])
        for record in records
        if isinstance(record, dict) and isinstance(record.get("payload"), dict)
    ]


async def find_cached_result(
    repository: Any,
    *,
    source_system: str,
    data_environment: str,
    scenario: str,
    site: str,
    cache_key: str,
    cache_scope: str,
    cache_mode: CacheMode = "prefer_cache",
    include_datasets: bool = True,
) -> CachedCollectionResult | None:
    """按内部开关查询缓存；任何读异常都回退实时请求。"""
    if cache_mode == "live" or not result_cache_enabled():
        return None
    try:
        return await asyncio.to_thread(
            repository.find_cached_result,
            source_system=source_system,
            data_environment=data_environment,
            scenario=scenario,
            site=site,
            cache_key=cache_key,
            cache_scope=cache_scope,
            ttl_seconds=result_cache_ttl_seconds(),
            include_datasets=include_datasets,
        )
    except Exception:
        return None


def result_cache_enabled() -> bool:
    """读取内部结果缓存开关，默认启用。"""
    value = os.environ.get(ENV_RESULT_CACHE_ENABLED, "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def result_cache_ttl_seconds() -> int:
    """读取缓存新鲜度秒数，非法值回退一天。"""
    try:
        value = int(
            os.environ.get(
                ENV_RESULT_CACHE_TTL_SECONDS,
                str(DEFAULT_RESULT_CACHE_TTL_SECONDS),
            )
        )
    except ValueError:
        return DEFAULT_RESULT_CACHE_TTL_SECONDS
    return value if value > 0 else DEFAULT_RESULT_CACHE_TTL_SECONDS


def reset_cache_hit_state() -> Token[bool]:
    """为一次工具调用初始化缓存命中状态。"""
    return _cache_hit_context.set(False)


def restore_cache_hit_state(token: Token[bool]) -> None:
    """恢复外层缓存命中上下文。"""
    _cache_hit_context.reset(token)


def mark_cache_hit() -> None:
    """标记当前工具调用从共享结果缓存返回。"""
    _cache_hit_context.set(True)


def was_cache_hit() -> bool:
    """返回当前工具调用是否命中共享结果缓存。"""
    return _cache_hit_context.get()

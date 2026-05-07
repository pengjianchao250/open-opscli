"""ChatGPT / OpenAI MCP 连接器兼容工具模块。

为兼容 OpenAI Company Knowledge、Deep Research 和 MCP Connectors 而实现的
两个标准工具：

    search — 在本地数据集和字段索引中搜索
    fetch  — 获取指定数据集/字段的详细信息

官方规范：
    https://platform.openai.com/docs/mcp
    https://developers.openai.com/apps-sdk/build/mcp-server

工具签名（Company Knowledge 标准）：
    search(query: str) -> {"results": [{"id": str, "title": str, "url": str}]}
    fetch(id: str)     -> {"id": str, "title": str, "text": str, "url": str, "metadata": dict}

响应格式：
    FastMCP 自动将返回值序列化为 JSON 并放入 content[0].text 中，
    与 OpenAI 要求的 MCP content array 格式完全兼容。
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import ToolAnnotations

from .helpers import _err, _ok, _query_manager


# ── 共享辅助 ─────────────────────────────────────────────────────


def _build_url(resource_type: str, resource_id: str) -> str:
    """构造 opscli 内部 URL 标识（用于 citation）。"""
    return f"opscli://{resource_type}/{resource_id}"


# ── search ───────────────────────────────────────────────────────


async def search(query: str) -> dict:
    """在本地数据集和字段索引中搜索，返回匹配结果列表。

    Company Knowledge / Deep Research 标准工具。
    仅搜索本地缓存的 metadata，不需要后端认证。

    Args:
        query: 搜索关键词（自然语言或字段名/数据集名）

    Returns:
        {"results": [{"id": str, "title": str, "url": str}, ...]}
    """
    try:
        results: list[dict[str, str]] = []
        mgr = _query_manager()

        # 1. 搜索数据集
        try:
            datasets = mgr.list_datasets()
            for ds in datasets:
                score = _score_dataset_match(ds, query)
                if score > 0:
                    alias = ds.get("dataset_alias", "")
                    name = ds.get("dataset_name", alias)
                    results.append({
                        "id": f"dataset:{alias}",
                        "title": name or alias,
                        "url": _build_url("dataset", alias),
                    })
        except Exception:
            pass

        # 2. 搜索字段
        try:
            fields = mgr.list_fields()
            for f in fields:
                score = _score_field_match(f, query)
                if score > 0:
                    field_name = f.get("field_name", "")
                    dataset = f.get("dataset_alias", "")
                    verbose = f.get("verbose_name", field_name)
                    g_alias = f.get("global_alias", field_name)
                    field_id = f"{dataset}.{field_name}" if dataset else field_name
                    results.append({
                        "id": f"field:{field_id}",
                        "title": verbose or g_alias or field_name,
                        "url": _build_url("field", field_id),
                    })
        except Exception:
            pass

        # 去重（同一资源可能被数据集和字段同时命中）
        seen = set()
        unique_results = []
        for r in results:
            if r["id"] not in seen:
                seen.add(r["id"])
                unique_results.append(r)

        return {"results": unique_results[:20]}
    except Exception as exc:
        return {"results": []}


def _tokenize_query(query: str) -> list[str]:
    """将查询字符串拆分为独立 token，支持空格和逗号分隔。

    返回去重后的非空 token 列表（全小写）。
    """
    tokens = []
    for part in query.replace(",", " ").replace("，", " ").split():
        t = part.strip().lower()
        if t and t not in tokens:
            tokens.append(t)
    return tokens


def _score_dataset_match(ds: dict, query: str) -> int:
    """计算数据集与查询关键词的匹配分数。

    支持多词查询：先用整句匹配，再按 token 逐词匹配并累加分数。
    """
    q = query.lower()
    alias = (ds.get("dataset_alias") or "").lower()
    name = (ds.get("dataset_name") or "").lower()
    desc = (ds.get("description") or "").lower()

    # 整句精确/子串匹配（高优先级）
    if alias == q:
        return 120
    if name == q:
        return 100
    if q in alias:
        return 60
    if q in name:
        return 45
    if q in desc:
        return 10

    # 多 token 逐词匹配：每个 token 独立计分后累加
    tokens = _tokenize_query(query)
    if len(tokens) <= 1:
        return 0

    total = 0
    for token in tokens:
        if token in alias:
            total += 30
        elif token in name:
            total += 22
        elif token in desc:
            total += 5
    return total


def _score_field_match(f: dict, query: str) -> int:
    """计算字段与查询关键词的匹配分数。

    支持多词查询：先用整句匹配，再按 token 逐词匹配并累加分数。
    """
    q = query.lower()
    field_name = (f.get("field_name") or "").lower()
    verbose = (f.get("verbose_name") or "").lower()
    g_alias = (f.get("global_alias") or "").lower()
    dataset = (f.get("dataset_alias") or "").lower()
    desc = (f.get("description") or "").lower()

    # 整句精确/子串匹配（高优先级）
    if field_name == q:
        return 120
    if verbose == q:
        return 100
    if g_alias == q:
        return 90
    if q in field_name:
        return 60
    if q in verbose:
        return 45
    if dataset == q:
        return 40
    if q in g_alias:
        return 35
    if q in desc:
        return 10

    # 多 token 逐词匹配：每个 token 独立计分后累加
    tokens = _tokenize_query(query)
    if len(tokens) <= 1:
        return 0

    total = 0
    for token in tokens:
        if token == field_name:
            total += 60
        elif token == verbose:
            total += 50
        elif token in field_name:
            total += 30
        elif token in verbose:
            total += 22
        elif token in g_alias:
            total += 17
        elif token in desc:
            total += 5
    return total


# ── fetch ────────────────────────────────────────────────────────


async def fetch(id: str) -> dict:
    """获取指定数据集/字段的详细信息。

    Company Knowledge / Deep Research 标准工具。

    Args:
        id: 资源唯一标识（由 search 工具返回的 id 字段）
            格式: dataset:{alias} 或 field:{dataset.field_name}

    Returns:
        {"id": str, "title": str, "text": str, "url": str, "metadata": dict}
    """
    try:
        # 解析 id 格式
        if ":" in id:
            resource_type, resource_id = id.split(":", 1)
        elif id.startswith("opscli://"):
            parts = id.replace("opscli://", "").split("/", 1)
            resource_type = parts[0] if len(parts) > 0 else ""
            resource_id = parts[1] if len(parts) > 1 else ""
        else:
            resource_type = "dataset"
            resource_id = id

        handler = _FETCH_HANDLERS.get(resource_type)
        if not handler:
            return {
                "id": id,
                "title": "未知资源",
                "text": f"不支持的资源类型: {resource_type}",
                "url": id,
                "metadata": {"error": "unsupported_resource_type"},
            }

        return handler(resource_id)
    except Exception as exc:
        return {
            "id": id,
            "title": "获取失败",
            "text": str(exc),
            "url": id,
            "metadata": {"error": str(exc)},
        }


def _fetch_dataset(alias: str) -> dict:
    """获取数据集详细信息。"""
    mgr = _query_manager()
    meta = mgr.metadata(dataset_alias=alias)
    meta_dict = meta.to_dict()

    dimensions = meta_dict.get("dimensions", [])
    metrics = meta_dict.get("metrics", [])

    text_parts = [f"数据集: {alias}"]
    if dimensions:
        dim_names = [f"{d['name']} ({d.get('verbose_name', '')})" for d in dimensions[:10]]
        text_parts.append(f"维度字段 ({len(dimensions)}个): {', '.join(dim_names)}")
        if len(dimensions) > 10:
            text_parts[-1] += f" 等共{len(dimensions)}个"
    if metrics:
        met_names = [f"{m['name']} ({m.get('verbose_name', '')})" for m in metrics[:10]]
        text_parts.append(f"指标字段 ({len(metrics)}个): {', '.join(met_names)}")
        if len(metrics) > 10:
            text_parts[-1] += f" 等共{len(metrics)}个"

    return {
        "id": f"dataset:{alias}",
        "title": meta_dict.get("dataset_name", alias),
        "text": "\n".join(text_parts),
        "url": _build_url("dataset", alias),
        "metadata": {
            "type": "dataset",
            "table_id": meta_dict.get("table_id"),
            "dataset_type": meta_dict.get("dataset_type"),
            "dataset_category": meta_dict.get("dataset_category"),
            "main_dttm_col": meta_dict.get("main_dttm_col"),
            "dimensions_count": len(dimensions),
            "metrics_count": len(metrics),
        },
    }


def _fetch_field(field_id: str) -> dict:
    """获取字段详细信息。"""
    if "." in field_id:
        dataset_alias, field_name = field_id.split(".", 1)
    else:
        dataset_alias = None
        field_name = field_id

    mgr = _query_manager()
    meta = mgr.metadata(dataset_alias=dataset_alias)
    meta_dict = meta.to_dict()

    all_fields = meta_dict.get("dimensions", []) + meta_dict.get("metrics", [])
    field_info = None
    for f in all_fields:
        if f.get("name") == field_name or f.get("global_alias") == field_name:
            field_info = f
            break

    if not field_info:
        return {
            "id": f"field:{field_id}",
            "title": f"字段未找到: {field_name}",
            "text": f"在数据集 {dataset_alias or '未知'} 中未找到字段 {field_name}",
            "url": _build_url("field", field_id),
            "metadata": {"type": "field", "error": "not_found"},
        }

    text = f"字段: {field_info.get('verbose_name', field_name)} ({field_name})"
    if dataset_alias:
        text += f"\n所属数据集: {dataset_alias}"
    text += f"\n字段类型: {field_info.get('field_type', 'unknown')}"
    if field_info.get("aggregation"):
        text += f"\n可用聚合: {field_info.get('aggregation')}"

    return {
        "id": f"field:{field_id}",
        "title": field_info.get("verbose_name", field_name),
        "text": text,
        "url": _build_url("field", field_id),
        "metadata": {
            "type": "field",
            "dataset_alias": dataset_alias,
            **{k: v for k, v in field_info.items() if not k.startswith("_")},
        },
    }


_FETCH_HANDLERS: dict[str, Any] = {
    "dataset": _fetch_dataset,
    "field": _fetch_field,
}


# ── 工具注册 ─────────────────────────────────────────────────────

_SEARCH_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    openWorldHint=False,
    destructiveHint=False,
)

_FETCH_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    openWorldHint=False,
    destructiveHint=False,
)


def register(mcp) -> None:
    """向指定 MCP 实例注册 ChatGPT / OpenAI 兼容的 search 和 fetch 工具。"""

    @mcp.tool(
        name="search",
        title="Search knowledge",
        description="在本地数据集和字段索引中搜索，返回匹配的数据集和字段列表。",
        annotations=_SEARCH_ANNOTATIONS,
    )
    async def _search(query: str) -> dict:
        return await search(query)

    @mcp.tool(
        name="fetch",
        title="Fetch document",
        description="获取指定数据集或字段的详细信息（由 search 返回的 id 标识）。",
        annotations=_FETCH_ANNOTATIONS,
    )
    async def _fetch(id: str) -> dict:
        return await fetch(id)

"""卖家精灵类目节点解析。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from opscli.seller_sprite.api.payloads import csv, market_id, month_name
from opscli.seller_sprite.domain.exceptions import SellerSpriteConfigError


NODE_PATH_RE = re.compile(r"^\d+(?::\d+)*$")
CATEGORY_KEYS = ("nodeIdPaths", "nodeIdPath", "node", "category")


@dataclass(frozen=True)
class CategoryNode:
    id: str
    node_id_path: str
    label: str
    label_path: str
    has_children: bool


class SellerSpriteCategoryResolver:
    """通过卖家精灵类目接口解析类目文本。"""

    def __init__(self, client) -> None:
        self.client = client
        self._cache: dict[str, list[CategoryNode]] = {}

    async def resolve_params(
        self,
        *,
        params: dict[str, Any],
        scenario: str,
        site: str,
        period: str,
    ) -> dict[str, Any]:
        key = _category_key(params)
        if scenario == "market-research" and key == "category":
            return params
        if not key:
            return params

        values = csv(params.get(key))
        if not values:
            return params

        table = month_name(params.get("month") or period)
        market = market_id(params.get("market") or params.get("site") or site)
        resolved = [await self.resolve(value, market=market, table=table) for value in values]

        next_params = dict(params)
        if scenario == "market-research":
            next_params[key] = ",".join(resolved)
        else:
            next_params[key] = resolved
        return next_params

    async def resolve(self, value: str, *, market: Any, table: str) -> str:
        text = str(value or "").strip()
        if not text or NODE_PATH_RE.fullmatch(text):
            return text
        return await self._resolve_label(text, market=market, table=table)

    async def _resolve_label(self, value: str, *, market: Any, table: str) -> str:
        matches = await self._nodes(market=market, table=table, node_label_path=value)
        exact_matches = _exact_matches(value, matches)
        if len(exact_matches) == 1:
            return exact_matches[0].node_id_path
        if len(matches) != 1:
            _raise_match_error(value, matches, scope="全部类目")
        return matches[0].node_id_path

    async def _nodes(
        self,
        *,
        market: Any,
        table: str,
        node_id_path: str = "",
        node_label_path: str = "",
    ) -> list[CategoryNode]:
        cache_key = f"{market}:{table}:{node_id_path}:{node_label_path}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        payload = await self.client.category_nodes(
            market_id=market,
            table=table,
            node_id_path=node_id_path or None,
            node_label_path=node_label_path or None,
        )
        nodes = _parse_nodes(payload, parent_path=node_id_path)
        self._cache[cache_key] = nodes
        return nodes


def _category_key(params: dict[str, Any]) -> str | None:
    for key in CATEGORY_KEYS:
        if params.get(key):
            return key
    return None


def _parse_nodes(payload: dict[str, Any], *, parent_path: str) -> list[CategoryNode]:
    raw_items = payload.get("items")
    if raw_items is None and isinstance(payload.get("data"), dict):
        raw_items = payload["data"].get("items")
    if not isinstance(raw_items, list):
        return []
    return [_parse_node(item, parent_path=parent_path) for item in raw_items if isinstance(item, dict)]


def _parse_node(item: dict[str, Any], *, parent_path: str) -> CategoryNode:
    node_id = str(item.get("id") or item.get("nodeId") or "").strip()
    node_id_path = str(item.get("nodeIdPath") or item.get("nodeIdPaths") or "").strip()
    if not node_id_path:
        node_id_path = f"{parent_path}:{node_id}" if parent_path and node_id else node_id
    label = _label(item)
    label_path = str(item.get("label") or item.get("nodeLabelPathLocale") or item.get("nodeLabelPath") or "").strip()
    if not label_path:
        label_path = label
    children = item.get("children")
    has_children = bool(children) or item.get("hasChildren") is True or item.get("leaf") is False
    return CategoryNode(
        id=node_id,
        node_id_path=node_id_path,
        label=label,
        label_path=label_path,
        has_children=has_children,
    )


def _label(item: dict[str, Any]) -> str:
    for key in ("label", "nodeLabelLocale", "nodeLabel", "alias"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _exact_matches(value: str, matches: list[CategoryNode]) -> list[CategoryNode]:
    normalized = _normalize_category_text(value)
    if not normalized:
        return []
    return [
        node
        for node in matches
        if normalized
        in {
            _normalize_category_text(node.label_path),
            _normalize_category_text(node.label),
        }
    ]


def _normalize_category_text(value: str) -> str:
    text = str(value or "").strip().replace("：", ":")
    text = re.sub(r"\s*:\s*", ":", text)
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def _raise_match_error(value: str, matches: list[CategoryNode], *, scope: str) -> None:
    if not matches:
        raise SellerSpriteConfigError(f"未匹配到卖家精灵类目：{value}（范围：{scope}）")
    candidates = [
        {
            "nodeIdPath": node.node_id_path,
            "labelPath": node.label_path,
        }
        for node in matches[:10]
    ]
    raise SellerSpriteConfigError(
        f"卖家精灵类目存在多个匹配：{value}。请补充完整类目路径或 nodeIdPath。候选：{candidates}"
    )

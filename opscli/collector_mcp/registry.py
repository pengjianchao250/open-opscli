"""统一数据采集服务静态 Tool Bundle 注册表。"""

from __future__ import annotations

import os
from collections.abc import Iterable

from opscli.collector_mcp.profile import CollectorServiceProfile, CollectorToolBundle


def _build_seller_sprite_bundle() -> CollectorToolBundle:
    """延迟构造 SellerSprite Bundle，导入阶段不启动业务资源。"""
    from opscli.seller_sprite.mcp_bundle import build_bundle

    return build_bundle()


def _build_keepa_bundle() -> CollectorToolBundle:
    """延迟构造 Keepa Bundle，导入阶段不启动业务资源。"""
    from opscli.keepa.mcp_bundle import build_bundle

    return build_bundle()


_BUNDLE_FACTORIES = {
    "seller_sprite": _build_seller_sprite_bundle,
    "keepa": _build_keepa_bundle,
}


def resolve_bundles(profile: CollectorServiceProfile) -> tuple[CollectorToolBundle, ...]:
    """按 Profile 稳定顺序解析并校验显式 Bundle。"""
    bundles: list[CollectorToolBundle] = []
    seen_ids: set[str] = set()
    seen_prefixes: set[str] = set()
    for bundle_id in profile.bundles:
        factory = _BUNDLE_FACTORIES.get(bundle_id)
        if factory is None:
            raise ValueError(f"Collector Bundle 未在静态注册表声明：{bundle_id}")
        bundle = factory()
        if bundle.bundle_id != bundle_id:
            raise ValueError(
                f"Collector Bundle ID 不一致：配置为 {bundle_id}，实际为 {bundle.bundle_id}"
            )
        if bundle.bundle_id in seen_ids:
            raise ValueError(f"Collector Bundle ID 重复：{bundle.bundle_id}")
        if not bundle.tool_prefix or bundle.tool_prefix in seen_prefixes:
            raise ValueError(f"Collector Tool 前缀无效或重复：{bundle.tool_prefix}")
        missing_env = [name for name in bundle.required_env if not os.getenv(name)]
        if missing_env:
            raise ValueError(
                f"Collector Bundle {bundle.bundle_id} 缺少配置：{', '.join(missing_env)}"
            )
        seen_ids.add(bundle.bundle_id)
        seen_prefixes.add(bundle.tool_prefix)
        bundles.append(bundle)
    return tuple(bundles)


def validate_bundle_tools(
    catalog: Iterable[dict],
    bundles: tuple[CollectorToolBundle, ...],
    *,
    public_tools: frozenset[str],
) -> None:
    """校验实际工具均属于公共白名单或已启用 Bundle 前缀。"""
    prefixes = tuple(bundle.tool_prefix for bundle in bundles)
    for item in catalog:
        name = str(item.get("name") or "")
        if name in public_tools:
            continue
        if not any(name.startswith(prefix) for prefix in prefixes):
            raise ValueError(f"Collector Tool 未归属已启用 Bundle：{name}")

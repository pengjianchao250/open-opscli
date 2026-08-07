"""统一数据采集服务 Profile 与 Tool Bundle 契约。"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, AsyncContextManager


BundleRegister = Callable[[Any], None]
BundleLifespan = Callable[[], AsyncContextManager[None]]
BundleHealthCheck = Callable[[], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class CollectorToolBundle:
    """声明单个数据采集模块的公开工具和运行生命周期。"""

    bundle_id: str
    tool_prefix: str
    register: BundleRegister
    lifespan: BundleLifespan
    health_check: BundleHealthCheck
    required_env: tuple[str, ...] = ()
    single_worker_required: bool = False


@dataclass(frozen=True)
class CollectorServiceProfile:
    """声明一次数据采集服务部署允许启用的 Bundle。"""

    profile_id: str
    service_id: str
    display_name: str
    bundles: tuple[str, ...]
    critical_bundles: tuple[str, ...]
    single_worker_required: bool = True


_PROFILES = {
    "production": CollectorServiceProfile(
        profile_id="production",
        service_id="collector",
        display_name="数据采集服务",
        bundles=("seller_sprite", "keepa"),
        critical_bundles=("seller_sprite", "keepa"),
    ),
}


def load_profile(environ: dict[str, str] | None = None) -> CollectorServiceProfile:
    """读取并校验版本控制内的 Collector Profile 及 Bundle 子集。"""
    values = os.environ if environ is None else environ
    profile_name = values.get("OPSCLI_COLLECTOR_PROFILE", "production").strip() or "production"
    profile = _PROFILES.get(profile_name)
    if profile is None:
        raise ValueError(f"未知 Collector Profile：{profile_name}")

    configured = values.get("OPSCLI_COLLECTOR_BUNDLES")
    if configured is None:
        enabled = profile.bundles
    else:
        enabled = tuple(item.strip() for item in configured.split(",") if item.strip())
        if not enabled:
            raise ValueError("OPSCLI_COLLECTOR_BUNDLES 不能为空")
        if len(enabled) != len(set(enabled)):
            raise ValueError("OPSCLI_COLLECTOR_BUNDLES 包含重复 Bundle")
        disallowed = sorted(set(enabled) - set(profile.bundles))
        if disallowed:
            raise ValueError(f"Profile 不允许启用 Bundle：{', '.join(disallowed)}")

    missing_critical = sorted(set(profile.critical_bundles) - set(enabled))
    if missing_critical:
        raise ValueError(f"缺少关键 Bundle：{', '.join(missing_critical)}")
    return CollectorServiceProfile(
        profile_id=profile.profile_id,
        service_id=profile.service_id,
        display_name=profile.display_name,
        bundles=enabled,
        critical_bundles=profile.critical_bundles,
        single_worker_required=profile.single_worker_required,
    )

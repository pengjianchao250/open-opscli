"""统一数据采集服务 Profile 与注册表测试。"""

import pytest

from opscli.collector_mcp.profile import load_profile
from opscli.collector_mcp.registry import resolve_bundles, validate_bundle_tools


def test_default_profile_only_enables_seller_sprite():
    profile = load_profile({})

    assert profile.display_name == "数据采集服务"
    assert profile.bundles == ("seller_sprite",)
    assert profile.critical_bundles == ("seller_sprite",)
    assert profile.single_worker_required is True


def test_profile_rejects_unknown_bundle_override():
    with pytest.raises(ValueError, match="不允许启用 Bundle"):
        load_profile(
            {
                "OPSCLI_COLLECTOR_PROFILE": "production",
                "OPSCLI_COLLECTOR_BUNDLES": "seller_sprite,unknown",
            }
        )


def test_profile_rejects_missing_critical_bundle():
    with pytest.raises(ValueError, match="不能为空"):
        load_profile(
            {
                "OPSCLI_COLLECTOR_PROFILE": "production",
                "OPSCLI_COLLECTOR_BUNDLES": "",
            }
        )


def test_registry_resolves_static_seller_sprite_bundle():
    bundles = resolve_bundles(load_profile({}))

    assert [bundle.bundle_id for bundle in bundles] == ["seller_sprite"]
    assert bundles[0].tool_prefix == "seller_sprite_"
    assert bundles[0].single_worker_required is True


def test_registry_rejects_tool_outside_public_and_bundle_prefixes():
    bundles = resolve_bundles(load_profile({}))

    with pytest.raises(ValueError, match="未归属"):
        validate_bundle_tools(
            [{"name": "debug_delete_all"}],
            bundles,
            public_tools=frozenset(),
        )

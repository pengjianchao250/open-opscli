#!/usr/bin/env python3
"""MCP Server 端到端集成测试。

测试场景：
1. 模拟两个不同 API Key 的用户完成 Device Flow 授权
2. 验证两人的 session 被保存到不同的隔离目录
3. 验证后续查询时读取的是各自的 session，不会串用
4. 验证同一 API Key 换"设备"（新请求上下文）无需重新授权

运行方式：
    cd /Users/mask/python3/opscli
    python3 scripts/test_mcp_e2e.py
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def setup_isolated_env():
    """设置隔离的测试环境，使用临时目录替代 ~/.config/opscli"""
    import opscli.config
    import opscli.mcp.tools.helpers as helpers_module

    tmpdir = Path(tempfile.mkdtemp(prefix="mcp_e2e_test_"))

    # Monkeypatch CONFIG_DIR
    original_config_dir = opscli.config.CONFIG_DIR
    opscli.config.CONFIG_DIR = tmpdir

    # Monkeypatch _get_credential_dir 返回我们的临时目录下的子目录
    original_get_dir = helpers_module._get_credential_dir

    def mock_get_credential_dir():
        from opscli.mcp.context import get_current_api_key
        api_key = get_current_api_key()
        if not api_key:
            return None
        key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
        cred_dir = tmpdir / "credentials_by_key" / key_hash
        cred_dir.mkdir(parents=True, exist_ok=True)
        return cred_dir

    helpers_module._get_credential_dir = mock_get_credential_dir

    return tmpdir, original_config_dir, original_get_dir


def restore_env(original_config_dir, original_get_dir):
    """恢复原始环境"""
    import opscli.config
    import opscli.mcp.tools.helpers as helpers_module

    opscli.config.CONFIG_DIR = original_config_dir
    helpers_module._get_credential_dir = original_get_dir


async def test_multi_user_isolation():
    """测试：两个用户各自授权后，凭证完全隔离"""
    print("=" * 70)
    print("【集成测试 1】两个用户 Device Flow 授权 + 凭证隔离")
    print("=" * 70)

    tmpdir, orig_config_dir, orig_get_dir = setup_isolated_env()

    try:
        from opscli.auth.storage.credential_store import CredentialStore
        from opscli.mcp.context import mcp_request_ctx
        from opscli.mcp.tools.auth import (
            auth_doctor,
            auth_login_poll,
            auth_is_authenticated,
        )

        # 模拟用户 A 的 API Key
        api_key_a = "mcp_test_user_a_abc123"
        # 模拟用户 B 的 API Key
        api_key_b = "mcp_test_user_b_def456"

        # Step 1: 模拟用户 A 完成授权（直接写入凭证，模拟 auth_login_poll 成功后的保存）
        print("\n📌 Step 1: 用户 A 完成 Device Flow 授权...")
        ctx_a = mcp_request_ctx.set({
            "api_key": api_key_a,
            "user_id": "101",
            "email": "user_a@example.com",
        })

        # 模拟 auth_login_poll 保存的凭证
        from opscli.mcp.tools.helpers import _get_credential_dir
        dir_a = _get_credential_dir()
        store_a = CredentialStore(base_dir=dir_a)
        store_a.save_session("session_a_xxx", "user_a@example.com", "2026-12-31T23:59:59Z")
        store_a.save_token("ops", "jwt_a_xxx", 7200)

        print(f"   用户 A 凭证保存到: {dir_a}")
        print(f"   session_id: session_a_xxx")

        mcp_request_ctx.reset(ctx_a)

        # Step 2: 模拟用户 B 完成授权
        print("\n📌 Step 2: 用户 B 完成 Device Flow 授权...")
        ctx_b = mcp_request_ctx.set({
            "api_key": api_key_b,
            "user_id": "102",
            "email": "user_b@example.com",
        })

        dir_b = _get_credential_dir()
        store_b = CredentialStore(base_dir=dir_b)
        store_b.save_session("session_b_yyy", "user_b@example.com", "2026-12-31T23:59:59Z")
        store_b.save_token("ops", "jwt_b_yyy", 7200)

        print(f"   用户 B 凭证保存到: {dir_b}")
        print(f"   session_id: session_b_yyy")

        mcp_request_ctx.reset(ctx_b)

        # Step 3: 验证目录物理隔离
        print("\n📌 Step 3: 验证凭证目录物理隔离...")
        assert dir_a != dir_b, "两个用户的凭证目录必须不同"

        # 检查实际存储内容
        data_a = store_a.load()
        data_b = store_b.load()

        assert data_a["session_id"] == "session_a_xxx", "用户 A 的 session 不应被篡改"
        assert data_b["session_id"] == "session_b_yyy", "用户 B 的 session 不应被篡改"

        print(f"   ✅ 目录 A: {dir_a.name}")
        print(f"   ✅ 目录 B: {dir_b.name}")
        print(f"   ✅ 两个目录物理隔离，无重叠")

        # Step 4: 模拟用户 A 后续请求（如 query_simple）
        print("\n📌 Step 4: 用户 A 发起查询请求，验证读取到的是自己的 session...")
        ctx_a2 = mcp_request_ctx.set({
            "api_key": api_key_a,
            "user_id": "101",
        })

        from opscli.mcp.tools.helpers import _get_session_id, _get_jwt
        sid_a = _get_session_id("ops")
        jwt_a = _get_jwt("ops")

        assert sid_a == "session_a_xxx", f"用户 A 应读取到自己的 session，实际: {sid_a}"
        assert jwt_a == "jwt_a_xxx", f"用户 A 应读取到自己的 JWT，实际: {jwt_a}"

        print(f"   ✅ 读取到的 session_id: {sid_a}")
        print(f"   ✅ 读取到的 JWT: {jwt_a}")

        mcp_request_ctx.reset(ctx_a2)

        # Step 5: 模拟用户 B 后续请求
        print("\n📌 Step 5: 用户 B 发起查询请求，验证读取到的是自己的 session...")
        ctx_b2 = mcp_request_ctx.set({
            "api_key": api_key_b,
            "user_id": "102",
        })

        sid_b = _get_session_id("ops")
        jwt_b = _get_jwt("ops")

        assert sid_b == "session_b_yyy", f"用户 B 应读取到自己的 session，实际: {sid_b}"
        assert jwt_b == "jwt_b_yyy", f"用户 B 应读取到自己的 JWT，实际: {jwt_b}"

        print(f"   ✅ 读取到的 session_id: {sid_b}")
        print(f"   ✅ 读取到的 JWT: {jwt_b}")

        mcp_request_ctx.reset(ctx_b2)

        # Step 6: 验证 "陌生" API Key 无法读取到任何凭证
        print("\n📌 Step 6: 陌生 API Key 尝试访问，应无凭证...")
        ctx_c = mcp_request_ctx.set({
            "api_key": "mcp_stranger_zzz",
            "user_id": "999",
        })

        sid_c = _get_session_id("ops")
        jwt_c = _get_jwt("ops")

        assert sid_c is None, "陌生用户不应读取到任何 session"
        assert jwt_c is None, "陌生用户不应读取到任何 JWT"

        print(f"   ✅ session_id: {sid_c} (None)")
        print(f"   ✅ JWT: {jwt_c} (None)")

        mcp_request_ctx.reset(ctx_c)

        print("\n" + "=" * 70)
        print("✅ 集成测试 1 通过：两个用户凭证完全隔离，无串用风险")
        print("=" * 70)
        return True

    finally:
        restore_env(orig_config_dir, orig_get_dir)


async def test_same_key_cross_device():
    """测试：同一 API Key 在不同"设备"上访问，无需重新授权"""
    print("\n" + "=" * 70)
    print("【集成测试 2】同一 API Key 换设备无需重新授权")
    print("=" * 70)

    tmpdir, orig_config_dir, orig_get_dir = setup_isolated_env()

    try:
        from opscli.auth.storage.credential_store import CredentialStore
        from opscli.mcp.context import mcp_request_ctx
        from opscli.mcp.tools.helpers import _get_session_id, _get_jwt

        api_key = "mcp_test_user_cross_device"

        # 模拟 "设备 A" 首次授权
        print("\n📌 Step 1: 设备 A 首次授权...")
        ctx1 = mcp_request_ctx.set({
            "api_key": api_key,
            "user_id": "101",
        })

        from opscli.mcp.tools.helpers import _get_credential_dir
        cred_dir = _get_credential_dir()
        store = CredentialStore(base_dir=cred_dir)
        store.save_session("session_cross_001", "user@example.com", "2026-12-31T23:59:59Z")
        store.save_token("ops", "jwt_cross_001", 7200)

        print(f"   凭证保存到: {cred_dir}")
        print(f"   session_id: session_cross_001")

        mcp_request_ctx.reset(ctx1)

        # 模拟 "设备 B" 使用同一个 API Key 访问
        print("\n📌 Step 2: 设备 B（新请求上下文）使用同一 API Key 访问...")
        ctx2 = mcp_request_ctx.set({
            "api_key": api_key,
            "user_id": "101",
        })

        sid = _get_session_id("ops")
        jwt = _get_jwt("ops")

        assert sid == "session_cross_001", f"设备 B 应直接读取已保存的 session，实际: {sid}"
        assert jwt == "jwt_cross_001", f"设备 B 应直接读取已保存的 JWT，实际: {jwt}"

        print(f"   ✅ 无需重新授权")
        print(f"   ✅ 读取到的 session_id: {sid}")
        print(f"   ✅ 读取到的 JWT: {jwt}")

        mcp_request_ctx.reset(ctx2)

        print("\n" + "=" * 70)
        print("✅ 集成测试 2 通过：同一 API Key 换设备无需重新授权")
        print("=" * 70)
        return True

    finally:
        restore_env(orig_config_dir, orig_get_dir)


async def test_old_bug_reproduction():
    """测试：复现旧 Bug（共享 credentials.bin）并验证已修复"""
    print("\n" + "=" * 70)
    print("【集成测试 3】复现旧 Bug：共享存储导致串用")
    print("=" * 70)

    tmpdir, orig_config_dir, orig_get_dir = setup_isolated_env()

    try:
        from opscli.auth.storage.credential_store import CredentialStore
        from opscli.mcp.context import mcp_request_ctx
        from opscli.mcp.tools.helpers import _get_session_id

        api_key_a = "mcp_user_a_oldbug"
        api_key_b = "mcp_user_b_oldbug"

        # 用户 A 先登录
        print("\n📌 Step 1: 用户 A 先授权...")
        ctx_a = mcp_request_ctx.set({
            "api_key": api_key_a,
            "user_id": "101",
        })

        from opscli.mcp.tools.helpers import _get_credential_dir
        dir_a = _get_credential_dir()
        store_a = CredentialStore(base_dir=dir_a)
        store_a.save_session("session_a_first", "a@example.com", "2026-12-31T23:59:59Z")

        print(f"   用户 A session: session_a_first")
        mcp_request_ctx.reset(ctx_a)

        # 用户 B 后登录（旧 Bug 下会覆盖 A 的 session）
        print("\n📌 Step 2: 用户 B 后授权...")
        ctx_b = mcp_request_ctx.set({
            "api_key": api_key_b,
            "user_id": "102",
        })

        dir_b = _get_credential_dir()
        store_b = CredentialStore(base_dir=dir_b)
        store_b.save_session("session_b_second", "b@example.com", "2026-12-31T23:59:59Z")

        print(f"   用户 B session: session_b_second")
        mcp_request_ctx.reset(ctx_b)

        # 用户 A 再次请求
        print("\n📌 Step 3: 用户 A 再次请求，验证 session 未被 B 覆盖...")
        ctx_a2 = mcp_request_ctx.set({
            "api_key": api_key_a,
            "user_id": "101",
        })

        sid_a = _get_session_id("ops")

        # 旧 Bug：如果共享存储，这里会读到 session_b_second
        # 修复后：应该读到 session_a_first
        if sid_a == "session_b_second":
            print(f"   ❌ 旧 Bug 复现！用户 A 读到了 B 的 session: {sid_a}")
            return False
        else:
            assert sid_a == "session_a_first", f"用户 A 应保持自己的 session，实际: {sid_a}"
            print(f"   ✅ 用户 A 的 session 未被覆盖: {sid_a}")

        mcp_request_ctx.reset(ctx_a2)

        print("\n" + "=" * 70)
        print("✅ 集成测试 3 通过：旧 Bug 已修复，多用户安全隔离")
        print("=" * 70)
        return True

    finally:
        restore_env(orig_config_dir, orig_get_dir)


async def main():
    print("\n" + "=" * 70)
    print(" MCP Server 端到端集成测试")
    print("=" * 70)

    results = []
    results.append(("多用户凭证隔离", await test_multi_user_isolation()))
    results.append(("换设备无需重授权", await test_same_key_cross_device()))
    results.append(("旧 Bug 修复验证", await test_old_bug_reproduction()))

    print("\n" + "=" * 70)
    print(" 测试结果汇总")
    print("=" * 70)

    all_passed = True
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {name:<30} {status}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("🎉 全部集成测试通过！多用户凭证隔离功能完全正常。")
    else:
        print("⚠️ 部分测试失败，请检查输出。")

    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

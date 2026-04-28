"""MCP 凭证读取性能基准测试。

对比三种读取方式的延迟：
1. 明文 JSON 读取（旧 SessionStore 方式，已删除，手动模拟）
2. AES-256-GCM 解密读取（CredentialStore 直接读取）
3. 内存缓存读取（McpCredentialCache，推荐方式）

运行：python tests/benchmark_credential_read.py
"""

import json
import time
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from opscli.auth.storage.credential_store import CredentialStore
from opscli.auth.storage.crypto import Crypto
from opscli.mcp.credential_cache import McpCredentialCache


def benchmark_plain_json(data: dict, iterations: int = 1000):
    """模拟旧的明文 JSON 读取方式。"""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "mcp_sessions.json"
        path.write_text(json.dumps(data), encoding="utf-8")

        def _read():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)

        # warmup
        for _ in range(10):
            _read()

        start = time.perf_counter()
        for _ in range(iterations):
            _read()
        elapsed = time.perf_counter() - start
        return elapsed / iterations * 1000  # ms


def benchmark_encrypted_store(store: CredentialStore, iterations: int = 1000):
    """AES-256-GCM 加密文件读取。"""
    # warmup
    for _ in range(10):
        store.load()

    start = time.perf_counter()
    for _ in range(iterations):
        store.load()
    elapsed = time.perf_counter() - start
    return elapsed / iterations * 1000  # ms


def benchmark_memory_cache(cache: McpCredentialCache, iterations: int = 1000):
    """内存缓存读取（首次加载后）。"""
    # 确保缓存已加载
    cache.invalidate()

    # warmup
    for _ in range(10):
        cache.get_session_id()
        cache.get_jwt("ops")

    start = time.perf_counter()
    for _ in range(iterations):
        cache.get_session_id()
        cache.get_jwt("ops")
    elapsed = time.perf_counter() - start
    return elapsed / iterations * 1000  # ms


def main():
    # 准备测试数据
    test_data = {
        "session_id": "sess-bench-123",
        "email": "bench@example.com",
        "session_expires_at": "2099-01-01T00:00:00+00:00",
        "tokens": {
            "ops": {
                "jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyIiwiZXhwIjoxNzc3MjgwMDAwfQ.fake",
                "expires_at": (datetime.now(timezone.utc).isoformat()),
                "saved_at": int(time.time()),
            }
        },
    }

    # 初始化 CredentialStore（禁用 Keychain，避免干扰）
    import opscli.auth.storage.credential_store as cs_mod
    orig_keyring = cs_mod._KEYRING_AVAILABLE
    cs_mod._KEYRING_AVAILABLE = False

    try:
        with tempfile.TemporaryDirectory() as td:
            store = CredentialStore(base_dir=Path(td))
            store.save_session(
                test_data["session_id"],
                test_data["email"],
                test_data["session_expires_at"],
            )
            for system, td_info in test_data["tokens"].items():
                store.save_token(system, td_info["jwt"], expires_in=7200)

            cache = McpCredentialCache(base_dir=Path(td))

            iterations = 1000

            t_plain = benchmark_plain_json(test_data, iterations)
            t_encrypted = benchmark_encrypted_store(store, iterations)
            t_memory = benchmark_memory_cache(cache, iterations)

            print("=" * 60)
            print("MCP 凭证读取性能基准测试")
            print("=" * 60)
            print(f"迭代次数: {iterations}")
            print()
            print(f"{'方式':<30} {'单次延迟':>12} {'相对倍数':>10}")
            print("-" * 60)
            print(f"{'1. 明文 JSON（旧 SessionStore）':<30} {t_plain:>10.3f} ms {t_plain/t_plain:>8.1f}x")
            print(f"{'2. AES-256-GCM 解密（CredentialStore）':<30} {t_encrypted:>10.3f} ms {t_encrypted/t_plain:>8.1f}x")
            print(f"{'3. 内存缓存（McpCredentialCache）':<30} {t_memory:>10.3f} ms {t_memory/t_plain:>8.1f}x")
            print("=" * 60)
            print()
            print("结论：")
            if t_memory < t_plain * 2:
                print("  ✅ 内存缓存延迟与明文 JSON 持平，满足高频 Tool 调用需求")
            else:
                print("  ⚠️ 内存缓存延迟显著高于明文 JSON，建议优化")

            if t_encrypted > t_plain * 5:
                print(f"  ⚠️ AES 解密开销为明文的 {t_encrypted/t_plain:.1f} 倍，必须通过内存缓存规避")
            else:
                print(f"  ✅ AES 解密开销可控（{t_encrypted/t_plain:.1f}x），但高频场景仍需缓存")

    finally:
        cs_mod._KEYRING_AVAILABLE = orig_keyring


if __name__ == "__main__":
    main()

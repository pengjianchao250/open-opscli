"""显式授权端到端（e2e）测试。

以真实 `opscli` 子进程（python -m opscli.cli）执行 `auth me`，打通全链路：
argv 预解析 → 显式凭证上下文 → AuthClient 注入 → 真实 HTTP。

用本地 mock HTTP 服务替代后端，通过 OPSCLI_OPS_SYSTEM_URL 环境变量指向它，
覆盖两种凭证模式：
1. 直接给 ops JWT：/api/v1/auth/me 应收到 Bearer <显式 JWT>
2. 仅给 session_id：先 POST /api/v1/auth/cli-token 换取 JWT，再带换取的 JWT 调 /me
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class _MockBackendHandler(BaseHTTPRequestHandler):
    """模拟 ops 后端：记录收到的 Authorization，并按路径返回固定响应。"""

    # 类级列表：收集各次请求的 (method, path, authorization) 供断言
    records: list[tuple[str, str, str]] = []

    def log_message(self, format, *args):  # 静默 http.server 默认日志
        pass

    def _respond(self, code: int, body: dict):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        auth = self.headers.get("Authorization", "")
        type(self).records.append(("GET", self.path, auth))
        if self.path.endswith("/api/v1/auth/me"):
            self._respond(200, {"data": {"email": "e2e@example.com", "auth_seen": auth}})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        _ = self.rfile.read(length)  # 读掉请求体
        auth = self.headers.get("Authorization", "")
        type(self).records.append(("POST", self.path, auth))
        # ops 与 polaris 的 token 换取端点路径不同，返回可区分的 JWT
        if self.path.endswith("/api/v1/auth/cli-token"):
            # ops：session 换取 JWT
            self._respond(200, {"jwt": "exchanged-ops-jwt", "expires_in": 3600})
        elif self.path.endswith("/api/auth/cli-token"):
            # polaris：session 换取 JWT
            self._respond(200, {"jwt": "exchanged-polaris-jwt", "expires_in": 3600})
        else:
            self._respond(404, {"error": "not found"})


@pytest.fixture
def mock_backend():
    """启动本地 mock 后端，yield 其 base_url，测试结束自动关闭。"""
    _MockBackendHandler.records = []
    server = HTTPServer(("127.0.0.1", 0), _MockBackendHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _run_opscli(
    args: list[str], base_url: str, *, polaris_url: str | None = None
) -> subprocess.CompletedProcess:
    """以子进程运行 opscli，环境变量将系统地址指向 mock 后端。

    Args:
        args:        opscli 子命令参数
        base_url:    ops 系统地址（同时用于 get_ops_system_url / 内置 ops 系统）
        polaris_url: polaris 系统地址；提供时启用 polaris 并指向该地址，
                     否则关闭 polaris，避免触及未 mock 的 polaris 端点
    """
    import os

    env = os.environ.copy()
    # 覆盖 ops 系统地址：get_builtin_systems / get_ops_system_url 均读此变量
    env["OPSCLI_OPS_SYSTEM_URL"] = base_url
    env["OPSCLI_OPS_URL"] = f"{base_url}/api"
    if polaris_url is not None:
        env["OPSCLI_POLARIS_ENABLED"] = "true"
        env["OPSCLI_POLARIS_SYSTEM_URL"] = polaris_url
    else:
        env["OPSCLI_POLARIS_ENABLED"] = "false"
    return subprocess.run(
        [sys.executable, "-m", "opscli.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_e2e_auth_me_with_direct_ops_jwt(mock_backend):
    """直接提供 ops JWT：/me 应收到 Bearer <显式 JWT>，输出含用户邮箱。"""
    result = _run_opscli(
        ["auth", "me", "--ops-jwt-token=direct-jwt", "--session-id=sid-1"],
        mock_backend,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    info = json.loads(result.stdout)
    assert info["data"]["email"] == "e2e@example.com"
    # /me 收到的是显式 JWT，且未走 token 换取
    me_calls = [r for r in _MockBackendHandler.records if r[1].endswith("/auth/me")]
    assert me_calls and me_calls[-1][2] == "Bearer direct-jwt"
    assert not any(r[1].endswith("/cli-token") for r in _MockBackendHandler.records)


def test_e2e_auth_me_session_only_triggers_exchange(mock_backend):
    """仅提供 session_id：应先换取 JWT，再带换取的 JWT 调 /me。"""
    result = _run_opscli(
        ["auth", "me", "--session-id=sid-2"],
        mock_backend,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    info = json.loads(result.stdout)
    assert info["data"]["email"] == "e2e@example.com"
    # 发生了 token 换取
    assert any(r[1].endswith("/cli-token") for r in _MockBackendHandler.records)
    # /me 带的是换取回来的 JWT
    me_calls = [r for r in _MockBackendHandler.records if r[1].endswith("/auth/me")]
    assert me_calls and me_calls[-1][2] == "Bearer exchanged-ops-jwt"


def test_e2e_missing_session_id_is_rejected(mock_backend):
    """提供 JWT 但缺 --session-id：进程应以非零码退出并给出中文错误。"""
    result = _run_opscli(
        ["auth", "me", "--ops-jwt-token=direct-jwt"],
        mock_backend,
    )
    assert result.returncode != 0
    assert "必须同时提供 --session-id" in (result.stdout + result.stderr)


# ── polaris 双 JWT 端到端 ─────────────────────────────────
# 用 `auth token get -s <system>`：其 stdout 为纯 JWT，最适合断言 per-alias 路由。


def test_e2e_polaris_direct_jwt(mock_backend):
    """直接提供 polaris JWT：token get -s polaris 应原样输出该 JWT，不发网络换取。"""
    result = _run_opscli(
        ["auth", "token", "get", "-s", "polaris",
         "--polaris-jwt-token=direct-polaris", "--session-id=sid-p"],
        mock_backend,
        polaris_url=mock_backend,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert result.stdout.strip() == "direct-polaris"
    # 直接给 JWT 时不应触发任何 token 换取
    assert not any(r[1].endswith("/cli-token") for r in _MockBackendHandler.records)


def test_e2e_dual_jwt_routes_per_system(mock_backend):
    """同时提供 ops 与 polaris 两个 JWT：按 -s 别名各自返回对应系统的 JWT。"""
    common = ["--ops-jwt-token=OO", "--polaris-jwt-token=PP", "--session-id=sid-d"]

    ops_result = _run_opscli(
        ["auth", "token", "get", "-s", "ops", *common],
        mock_backend,
        polaris_url=mock_backend,
    )
    assert ops_result.returncode == 0, ops_result.stderr
    assert ops_result.stdout.strip() == "OO"

    pol_result = _run_opscli(
        ["auth", "token", "get", "-s", "polaris", *common],
        mock_backend,
        polaris_url=mock_backend,
    )
    assert pol_result.returncode == 0, pol_result.stderr
    assert pol_result.stdout.strip() == "PP"


def test_e2e_polaris_session_exchange(mock_backend):
    """仅提供 session_id：token get -s polaris 应走 polaris 端点换取并输出换取的 JWT。"""
    result = _run_opscli(
        ["auth", "token", "get", "-s", "polaris", "--session-id=sid-pe"],
        mock_backend,
        polaris_url=mock_backend,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert result.stdout.strip() == "exchanged-polaris-jwt"
    # 换取走的是 polaris 专属端点（/api/auth/cli-token，区别于 ops 的 /api/v1/auth/cli-token）
    pol_token_calls = [
        r for r in _MockBackendHandler.records if r[1].endswith("/api/auth/cli-token")
    ]
    assert pol_token_calls, _MockBackendHandler.records

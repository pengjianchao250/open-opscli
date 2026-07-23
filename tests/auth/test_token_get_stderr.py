"""token get 错误路径回归测试。

修复既有 latent bug：token_get 的错误分支曾用 rich `console.print(..., err=True)`，
而 rich Console.print 不接受 err 参数会抛 TypeError。改为 typer.echo(..., err=True)，
错误须落 stderr（本命令 stdout 为纯 JWT，供脚本 $(...) 捕获）。
"""
from __future__ import annotations

from typer.testing import CliRunner

from opscli.auth.cli import app as auth_app
from opscli.auth.exceptions import NotAuthenticatedError


def test_token_get_error_goes_to_stderr_without_crash(monkeypatch):
    """未登录时 token get 应退出码 1、错误落 stderr、stdout 不含错误、且不崩溃。"""

    class _FakeClient:
        def get_token(self, system):
            raise NotAuthenticatedError("未登录，请运行: opscli auth login")

    # 替换命令内部的 AuthClient 工厂，避免触碰真实 Keychain / 本机存储
    monkeypatch.setattr("opscli.auth.cli._client", lambda: _FakeClient())

    # Click 8.2+ 默认分离 stdout / stderr，可直接分别断言
    result = CliRunner().invoke(auth_app, ["token", "get", "-s", "ops"])

    assert result.exit_code == 1
    # 不应有未捕获异常（旧代码会因 TypeError 崩溃）
    assert result.exception is None or isinstance(result.exception, SystemExit)
    # 错误在 stderr，不污染 stdout
    assert "opscli auth login" in result.stderr
    assert result.stdout.strip() == ""

"""skills upgrade 未登录交互式引导登录测试。

场景约定（与设计评估一致）：
- 交互终端（stdin 为 TTY）遇认证类失败 → 询问是否登录 → 同意则登录成功后自动重试一次
- 非交互环境（AI Agent / 管道 / self-update 子进程）→ 保持原行为：JSON 错误 + exit 1，绝不发起登录
- 登录失败 / 用户拒绝 / 重试再失败 → 按原失败路径退出 1，不循环

全部测试不发真实网络请求、不触发真实 Device Flow（铁律8）：
SkillsManager 与登录函数均打桩。
"""

from unittest.mock import MagicMock, patch

import typer
from typer.testing import CliRunner

from opscli.auth.exceptions import AuthError
from opscli.skills.cli import app
from opscli.skills.commands.cli import _is_auth_failure
from opscli.skills.domain.exceptions import SkillRemoteError


def _auth_error() -> SkillRemoteError:
    """构造"未登录"类失败：SkillRemoteError 且 __cause__ 为 AuthError。"""
    exc = SkillRemoteError("未登录 ops，请先执行 `opscli auth login`", endpoint="/manifest")
    exc.__cause__ = AuthError("未登录")
    return exc


def _success_result() -> MagicMock:
    """构造 manager.upgrade 成功返回值（命令层只消费 to_dict()）。"""
    result = MagicMock()
    result.to_dict.return_value = {"updated": []}
    return result


class TestIsAuthFailure:
    """认证类失败判定测试：覆盖预检未登录与执行中鉴权失效两类信号。"""

    def test_cause_auth_error_is_auth_failure(self):
        """__cause__ 为 AuthError（本地无凭证预检失败）判定为认证失败。"""
        assert _is_auth_failure(_auth_error()) is True

    def test_status_401_is_auth_failure(self):
        """HTTP/业务 401（JWT 失效）判定为认证失败。"""
        exc = SkillRemoteError("鉴权失败", endpoint="/manifest", status_code=401)
        assert _is_auth_failure(exc) is True

    def test_status_407_is_auth_failure(self):
        """业务 407（服务端 session 已登出，本地凭证看似有效）判定为认证失败。"""
        exc = SkillRemoteError("您已登出", endpoint="/manifest", status_code=407)
        assert _is_auth_failure(exc) is True

    def test_status_500_is_not_auth_failure(self):
        """服务端异常不属于认证失败，不应触发登录引导。"""
        exc = SkillRemoteError("服务异常", endpoint="/manifest", status_code=500)
        assert _is_auth_failure(exc) is False

    def test_generic_exception_is_not_auth_failure(self):
        """非 SkillRemoteError 异常不属于认证失败。"""
        assert _is_auth_failure(ValueError("其他错误")) is False


class TestUpgradeLoginPrompt:
    """upgrade 命令登录引导流程测试（CliRunner 走完整 Typer 链路）。"""

    def _invoke(
        self,
        upgrade_side_effects: list,
        *,
        isatty: bool,
        confirm: bool | None = None,
        login_side_effect=None,
    ):
        """打桩后执行 opscli skills upgrade。

        Args:
            upgrade_side_effects: manager.upgrade 各次调用的返回/异常序列。
            isatty: 模拟 stdin 是否为交互终端。
            confirm: typer.confirm 的返回值；None 表示断言不会走到询问。
            login_side_effect: 登录函数的副作用（None=成功，异常=失败）。
        """
        manager = MagicMock()
        manager.upgrade.side_effect = upgrade_side_effects
        confirm_mock = MagicMock(return_value=confirm)
        login_mock = MagicMock(side_effect=login_side_effect)
        with (
            patch("opscli.skills.commands.cli.SkillsManager", return_value=manager),
            # 注意：CliRunner.invoke 期间会替换 sys.stdin，直接 patch sys.stdin
            # 会被覆盖，因此实现层提供 _stdin_is_tty() 缝隙供测试打桩
            patch("opscli.skills.commands.cli._stdin_is_tty", return_value=isatty),
            patch("opscli.skills.commands.cli.typer.confirm", confirm_mock),
            patch("opscli.auth.cli.login", login_mock),
        ):
            result = CliRunner().invoke(app, ["upgrade"])
        return result, manager, confirm_mock, login_mock

    def test_non_tty_keeps_current_behavior(self):
        """非交互环境：不询问、不登录，按原行为 JSON 错误 + exit 1。"""
        result, manager, confirm_mock, login_mock = self._invoke(
            [_auth_error()], isatty=False,
        )
        assert result.exit_code == 1
        assert '"success": false' in result.output
        confirm_mock.assert_not_called()
        login_mock.assert_not_called()
        assert manager.upgrade.call_count == 1

    def test_tty_declined_fails_as_before(self):
        """交互终端但用户拒绝登录：不登录、按原失败路径退出 1。"""
        result, manager, confirm_mock, login_mock = self._invoke(
            [_auth_error()], isatty=True, confirm=False,
        )
        assert result.exit_code == 1
        confirm_mock.assert_called_once()
        login_mock.assert_not_called()
        assert manager.upgrade.call_count == 1

    def test_tty_login_success_retries_once_and_succeeds(self):
        """交互终端 + 同意登录 + 登录成功：自动重试一次并成功。"""
        result, manager, confirm_mock, login_mock = self._invoke(
            [_auth_error(), _success_result()], isatty=True, confirm=True,
        )
        assert result.exit_code == 0
        assert '"success": true' in result.output
        login_mock.assert_called_once()
        assert manager.upgrade.call_count == 2

    def test_tty_login_failure_no_retry(self):
        """登录失败（Device Flow 超时/拒绝，登录函数以 typer.Exit 退出）：不重试 upgrade，退出 1。"""
        result, manager, confirm_mock, login_mock = self._invoke(
            [_auth_error()], isatty=True, confirm=True,
            login_side_effect=typer.Exit(1),
        )
        assert result.exit_code == 1
        confirm_mock.assert_called_once()
        login_mock.assert_called_once()
        assert manager.upgrade.call_count == 1

    def test_tty_retry_fails_again_no_loop(self):
        """重试后仍认证失败（如权限未生效）：只重试一次，不进入循环。"""
        result, manager, confirm_mock, login_mock = self._invoke(
            [_auth_error(), _auth_error()], isatty=True, confirm=True,
        )
        assert result.exit_code == 1
        assert '"success": false' in result.output
        # 登录与询问只发生一轮
        confirm_mock.assert_called_once()
        login_mock.assert_called_once()
        assert manager.upgrade.call_count == 2

    def test_tty_non_auth_error_never_prompts(self):
        """交互终端但失败原因非认证类（如服务端 500）：不询问、不登录。"""
        exc = SkillRemoteError("服务异常", endpoint="/manifest", status_code=500)
        result, manager, confirm_mock, login_mock = self._invoke(
            [exc], isatty=True,
        )
        assert result.exit_code == 1
        confirm_mock.assert_not_called()
        login_mock.assert_not_called()
        assert manager.upgrade.call_count == 1

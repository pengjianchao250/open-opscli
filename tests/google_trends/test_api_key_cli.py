"""Google Trends 本地 SerpApi Key 管理命令测试。"""

from types import SimpleNamespace

from typer.testing import CliRunner

from opscli.google_trends import cli as google_trends_cli


runner = CliRunner()


def _record(*, name: str = "primary", status: str = "active"):
    """构造只暴露脱敏摘要的测试记录。"""
    return SimpleNamespace(
        key_id="key-1",
        name=name,
        status=status,
        to_public_dict=lambda: {
            "key_id": "key-1",
            "name": name,
            "api_key_masked": "secr****mary",
            "status": status,
            "remark": "主账号",
        },
    )


def test_api_key_add_uses_hidden_prompt_and_outputs_masked_summary(monkeypatch):
    """新增命令应隐藏输入，并且不能回显明文 Key。"""
    calls = {}

    class FakeStore:
        def add_key(self, **kwargs):
            calls.update(kwargs)
            return _record()

    monkeypatch.setattr(google_trends_cli, "SerpApiKeyStore", FakeStore)

    result = runner.invoke(
        google_trends_cli.app,
        ["api-key", "add", "--name", "primary", "--remark", "主账号"],
        input="secret-primary\n",
    )

    assert result.exit_code == 0
    assert calls == {
        "name": "primary",
        "api_key": "secret-primary",
        "remark": "主账号",
    }
    assert "secret-primary" not in result.stdout
    assert '"api_key_masked": "secr****mary"' in result.stdout


def test_api_key_list_outputs_only_public_summaries(monkeypatch):
    """列表命令应逐条调用公开摘要，不能输出明文 Key。"""
    secret = "secret-primary"
    record = _record()
    record.api_key = secret
    monkeypatch.setattr(
        google_trends_cli,
        "SerpApiKeyStore",
        lambda: SimpleNamespace(list_keys=lambda: [record]),
    )

    result = runner.invoke(google_trends_cli.app, ["api-key", "list"])

    assert result.exit_code == 0
    assert secret not in result.stdout
    assert '"name": "primary"' in result.stdout


def test_api_key_test_checks_named_account(monkeypatch):
    """测试命令应把按名称找到的内部 ID 交给 Account 检查。"""
    calls = []
    record = _record()

    class FakeStore:
        def get_by_name(self, name):
            calls.append(("get", name))
            return record

    class FakeClient:
        def __init__(self, *, key_store):
            calls.append(("client", key_store))

        def check_account(self, key_id):
            calls.append(("check", key_id))
            return {
                "name": "primary",
                "api_key_masked": "secr****mary",
                "status": "active",
                "total_searches_left": 9,
            }

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(google_trends_cli, "SerpApiKeyStore", FakeStore)
    monkeypatch.setattr(
        google_trends_cli,
        "SerpApiGoogleTrendsClient",
        FakeClient,
    )

    result = runner.invoke(
        google_trends_cli.app,
        ["api-key", "test", "--name", "PRIMARY"],
    )

    assert result.exit_code == 0
    assert [call[0] for call in calls] == ["get", "client", "check", "close"]
    assert calls[2] == ("check", "key-1")
    assert '"total_searches_left": 9' in result.stdout


def test_api_key_enable_and_disable_update_named_account(monkeypatch):
    """启用和禁用命令应按账号名称显式更新状态。"""
    statuses = []
    current_status = {"value": "active"}

    class FakeStore:
        def get_by_name(self, name):
            return _record(name=name, status=current_status["value"])

        def set_status(self, key_id, status):
            statuses.append((key_id, status))
            current_status["value"] = status

    monkeypatch.setattr(google_trends_cli, "SerpApiKeyStore", FakeStore)

    disabled = runner.invoke(
        google_trends_cli.app,
        ["api-key", "disable", "--name", "primary"],
    )
    enabled = runner.invoke(
        google_trends_cli.app,
        ["api-key", "enable", "--name", "primary"],
    )

    assert disabled.exit_code == 0
    assert enabled.exit_code == 0
    assert statuses == [("key-1", "disabled"), ("key-1", "active")]
    assert '"status": "disabled"' in disabled.stdout
    assert '"status": "active"' in enabled.stdout


def test_api_key_command_rejects_missing_name(monkeypatch):
    """按名称操作不存在的账号时应清晰报错并返回非零状态。"""
    monkeypatch.setattr(
        google_trends_cli,
        "SerpApiKeyStore",
        lambda: SimpleNamespace(get_by_name=lambda _name: None),
    )

    result = runner.invoke(
        google_trends_cli.app,
        ["api-key", "disable", "--name", "missing"],
    )

    assert result.exit_code != 0
    assert "SerpApi 账号不存在：missing" in result.stderr

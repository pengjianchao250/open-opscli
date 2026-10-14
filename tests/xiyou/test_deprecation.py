"""验证废弃的西柚入口不会再次加载或注册。"""

from typer.main import get_command

from opscli.cli import app
from opscli.xiyou import providers


def test_formal_xiyou_cli_does_not_restore_legacy_commands_or_provider():
    commands = get_command(app).commands
    # 新入口只代理远端目录和通用调用，不恢复旧网页任务/导出命令。
    group = commands["xiyou"]._materialize()
    assert set(group.commands) == {"operations", "call"}
    assert not hasattr(providers, "XydcMcpProvider")
    assert providers.XYDC_OPENAPI_PROVIDER == "xydc_openapi"

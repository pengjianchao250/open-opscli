"""验证废弃的西柚入口不会再次加载或注册。"""

from typer.main import get_command

from opscli.cli import app
from opscli.xiyou import providers


def test_legacy_xiyou_command_and_provider_are_unavailable():
    commands = get_command(app).commands
    assert "xiyou" not in commands
    assert not hasattr(providers, "XydcMcpProvider")
    assert providers.XYDC_OPENAPI_PROVIDER == "xydc_openapi"

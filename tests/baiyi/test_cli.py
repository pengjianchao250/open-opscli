"""佰易 CLI 命令测试。"""

from __future__ import annotations

import json

import httpx
import respx
from typer.main import get_command
from typer.testing import CliRunner

from opscli.cli import app as root_app
from opscli.baiyi.cli import app
from opscli.baiyi.domain.exceptions import InvalidBaiyiCompanySkuError
from opscli.baiyi.domain.models import BaiyiProductInfoResult


runner = CliRunner()


def _result(*, found: bool) -> BaiyiProductInfoResult:
    """构造 CLI 测试使用的产品信息结果。"""
    return BaiyiProductInfoResult(
        request={"company_sku": "AUKEY-US-EU-001"},
        found=found,
        data={
            "binding_sku_info": {"company_sku": "US-EU-001"} if found else None,
            "stcodes": [],
            "product_center_sku": [],
            "sealed_sample": [],
            "supply_stock": [],
            "field_labels": {},
        },
    )


def test_root_cli_registers_baiyi_namespace() -> None:
    """顶层命令必须注册佰易业务数据命名空间。"""
    root_command = get_command(root_app)

    assert "baiyi" in root_command.commands
    assert "polaris" not in root_command.commands


def test_baiyi_help_exposes_product_info_command() -> None:
    """佰易帮助必须展示产品信息子命令。"""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "product-info" in result.stdout


def test_product_info_help_exposes_required_options() -> None:
    """产品信息帮助必须展示公司 SKU 和 pretty 选项。"""
    result = runner.invoke(app, ["product-info", "--help"])

    assert result.exit_code == 0
    assert "--company-sku" in result.stdout
    assert "--pretty" in result.stdout


def test_product_info_outputs_compact_success_json(monkeypatch) -> None:
    """默认输出必须是单个紧凑成功 JSON。"""
    class DummyManager:
        def fetch(self, company_sku: str) -> BaiyiProductInfoResult:
            assert company_sku == "AUKEY-US-EU-001"
            return _result(found=True)

    monkeypatch.setattr(
        "opscli.baiyi.commands.cli.BaiyiProductInfoManager",
        lambda: DummyManager(),
    )

    result = runner.invoke(
        app,
        ["product-info", "--company-sku", "AUKEY-US-EU-001"],
    )

    assert result.exit_code == 0
    assert "\n  \"success\"" not in result.stdout
    assert json.loads(result.stdout) == {
        "success": True,
        "command": "baiyi product-info",
        "request": {"company_sku": "AUKEY-US-EU-001"},
        "found": True,
        "data": {
            "binding_sku_info": {"company_sku": "US-EU-001"},
            "stcodes": [],
            "product_center_sku": [],
            "sealed_sample": [],
            "supply_stock": [],
            "field_labels": {},
        },
        "error": None,
    }


def test_product_info_pretty_only_changes_formatting(monkeypatch) -> None:
    """pretty 选项只能改变缩进，不能改变 JSON 语义。"""
    class DummyManager:
        def fetch(self, company_sku: str) -> BaiyiProductInfoResult:
            return _result(found=False)

    monkeypatch.setattr(
        "opscli.baiyi.commands.cli.BaiyiProductInfoManager",
        lambda: DummyManager(),
    )

    compact = runner.invoke(
        app,
        ["product-info", "--company-sku", "AUKEY-US-EU-001"],
    )
    pretty = runner.invoke(
        app,
        ["product-info", "--company-sku", "AUKEY-US-EU-001", "--pretty"],
    )

    assert compact.exit_code == 0
    assert pretty.exit_code == 0
    assert "\n  \"success\"" in pretty.stdout
    assert json.loads(compact.stdout) == json.loads(pretty.stdout)
    assert json.loads(pretty.stdout)["found"] is False


def test_product_info_outputs_structured_error(monkeypatch) -> None:
    """业务异常必须输出固定错误信封并以状态码 1 退出。"""
    class DummyManager:
        def fetch(self, company_sku: str) -> BaiyiProductInfoResult:
            raise InvalidBaiyiCompanySkuError("公司 SKU 不能为空")

    monkeypatch.setattr(
        "opscli.baiyi.commands.cli.BaiyiProductInfoManager",
        lambda: DummyManager(),
    )

    result = runner.invoke(
        app,
        ["product-info", "--company-sku", "BAD-SKU"],
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "success": False,
        "command": "baiyi product-info",
        "request": {"company_sku": "BAD-SKU"},
        "found": None,
        "data": None,
        "error": {
            "code": "INVALID_BAIYI_COMPANY_SKU",
            "message": "公司 SKU 不能为空",
        },
    }


def test_product_info_missing_company_sku_uses_typer_exit_code() -> None:
    """缺少必填选项时保留 Typer 的参数错误状态码。"""
    result = runner.invoke(app, ["product-info"])

    assert result.exit_code == 2


@respx.mock
def test_root_cli_runs_complete_product_info_chain(monkeypatch) -> None:
    """顶层命令必须贯通 manager 与 mock transport，并只输出一个 JSON。"""
    class FakeAuthClient:
        """提供不接触本地凭证的固定认证信息。"""

        def build_request_auth(
            self,
            alias: str,
        ) -> tuple[dict[str, str], dict[str, str]]:
            """返回测试 Header 和 Cookie。"""
            assert alias == "ops"
            return (
                {"Authorization": "Bearer fake-jwt"},
                {"polarisUserToken": "fake-session"},
            )

    monkeypatch.setattr(
        "opscli.baiyi.transport.client.load_config",
        lambda: {"ops_system_url": "http://ops.example.com"},
    )
    monkeypatch.setattr(
        "opscli.baiyi.transport.client.AuthClient",
        FakeAuthClient,
    )
    monkeypatch.setattr(
        "opscli.shared.update_check.check_and_notify",
        lambda: None,
    )
    monkeypatch.setattr(
        "opscli.telemetry.reporter.TelemetryReporter.fire",
        lambda **kwargs: None,
    )
    route = respx.post(
        "http://ops.example.com/dataMetrics/v1/binding-sku-product-info"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "binding_sku_info": {"company_sku": "MATCHED-SKU"},
                    "future_section": {"kept": True},
                },
            },
        )
    )

    result = runner.invoke(
        root_app,
        ["baiyi", "product-info", "--company-sku", "  Input-SKU  "],
    )

    assert result.exit_code == 0
    assert route.called
    assert json.loads(result.stdout) == {
        "success": True,
        "command": "baiyi product-info",
        "request": {"company_sku": "Input-SKU"},
        "found": True,
        "data": {
            "binding_sku_info": {"company_sku": "MATCHED-SKU"},
            "future_section": {"kept": True},
        },
        "error": None,
    }

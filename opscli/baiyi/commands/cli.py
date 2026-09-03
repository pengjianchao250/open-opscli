"""佰易 CLI 子命令。

提供面向 AI Agent 与 Skill 的公司 SKU 产品信息查询入口。
"""

from __future__ import annotations

import json

import typer

from opscli.baiyi.services.manager import BaiyiProductInfoManager


COMMAND_NAME = "baiyi product-info"

app = typer.Typer(
    help="佰易产品数据查询",
    no_args_is_help=True,
)


@app.callback()
def _main() -> None:
    """佰易产品数据查询命令组入口。"""


def _emit(payload: dict, pretty: bool) -> None:
    """将单个 JSON 对象输出到标准输出。"""
    typer.echo(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2 if pretty else None,
        )
    )


def _error_payload(company_sku: str, exc: Exception) -> dict:
    """构造稳定的产品信息查询错误信封。"""
    if hasattr(exc, "to_dict"):
        error = exc.to_dict()
    else:
        error = {"code": type(exc).__name__, "message": str(exc)}
    return {
        "success": False,
        "command": COMMAND_NAME,
        "request": {"company_sku": company_sku.strip()},
        "found": None,
        "data": None,
        "error": error,
    }


@app.command("product-info")
def product_info(
    company_sku: str = typer.Option(
        ...,
        "--company-sku",
        help="公司 SKU 编码，最长 128 个字符",
    ),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出 JSON"),
) -> None:
    """查询单个公司 SKU 的映射、海关、产品中心、封样和库存信息。"""
    try:
        result = BaiyiProductInfoManager().fetch(company_sku)
    except Exception as exc:
        _emit(_error_payload(company_sku, exc), pretty)
        raise typer.Exit(1)

    _emit(result.to_dict(), pretty)


__all__ = ["app"]

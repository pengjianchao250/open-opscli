"""第三方 API 多账号凭据管理命令。"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from opscli.api_credentials.config import load_settings
from opscli.api_credentials.crypto import ApiKeyCipher
from opscli.api_credentials.repository import MySqlApiCredentialRepository


app = typer.Typer(help="统一管理 SerpAPI、Canopy、scrape.do 的多账号 API Key。")


@app.command("init-schema")
def init_schema() -> None:
    """使用迁移账号创建 API 凭据池 MySQL 表结构。

    Returns:
        无；成功后向终端输出完成信息。

    Raises:
        ApiCredentialConfigError: 部署配置不完整。
        Exception: MySQL DDL 或版本检查失败。
    """
    _repository().create_schema()
    typer.echo("API 凭据池 MySQL 表结构初始化完成")


@app.command("add")
def add_account(
    provider: str = typer.Option(..., "--provider", help="serpapi/canopy/scrape_do"),
    name: str = typer.Option(..., "--name", help="平台内唯一账号名称"),
    priority: int = typer.Option(100, "--priority", min=1, help="数值越小越优先"),
    remark: str | None = typer.Option(None, "--remark", help="账号用途或负责人"),
    actor: str | None = typer.Option(None, "--actor", help="变更操作人"),
) -> None:
    """新增账号；同名账号存在时安全轮换 API Key。

    Args:
        provider: Provider 标识。
        name: Provider 内账号名称。
        priority: 账号选择优先级。
        remark: 账号用途备注。
        actor: 审计操作人。

    Returns:
        无；终端仅输出脱敏账号摘要。
    """
    api_key = typer.prompt("API Key", hide_input=True, confirmation_prompt=True)
    account = _repository().upsert_account(
        provider=provider,
        name=name,
        api_key=api_key,
        priority=priority,
        remark=remark,
        actor=actor,
    )
    _echo_public(account)


@app.command("list")
def list_accounts(
    provider: str | None = typer.Option(None, "--provider", help="按 Provider 筛选"),
) -> None:
    """列出账号、掩码 Key、额度和运行状态。

    Args:
        provider: 可选 Provider 过滤条件。

    Returns:
        无；终端输出脱敏 JSON 列表。
    """
    accounts = _repository().list_accounts(provider)
    typer.echo(
        json.dumps(
            [account.to_public_dict() for account in accounts],
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("rotate")
def rotate_key(
    account_id: int = typer.Option(..., "--account-id", min=1, help="账号内部 ID"),
    actor: str | None = typer.Option(None, "--actor", help="变更操作人"),
) -> None:
    """轮换指定账号的 API Key，并保留旧版本审计记录。

    Args:
        account_id: 待轮换账号 ID。
        actor: 审计操作人。

    Returns:
        无；终端输出脱敏账号摘要。
    """
    api_key = typer.prompt("New API Key", hide_input=True, confirmation_prompt=True)
    _echo_public(_repository().rotate_key(account_id, api_key, actor=actor))


@app.command("enable")
def enable_account(
    account_id: int = typer.Option(..., "--account-id", min=1),
    actor: str | None = typer.Option(None, "--actor"),
) -> None:
    """启用指定账号。

    Args:
        account_id: 账号内部 ID。
        actor: 审计操作人。

    Returns:
        无；终端输出更新后的脱敏摘要。
    """
    repository = _repository()
    repository.set_status(account_id, "active", actor=actor)
    account = repository.get_account(account_id)
    if account is None:
        raise typer.BadParameter(f"API 账号不存在：{account_id}")
    _echo_public(account)


@app.command("disable")
def disable_account(
    account_id: int = typer.Option(..., "--account-id", min=1),
    actor: str | None = typer.Option(None, "--actor"),
) -> None:
    """禁用指定账号。

    Args:
        account_id: 账号内部 ID。
        actor: 审计操作人。

    Returns:
        无；终端输出更新后的脱敏摘要。
    """
    repository = _repository()
    repository.set_status(account_id, "disabled", actor=actor)
    account = repository.get_account(account_id)
    if account is None:
        raise typer.BadParameter(f"API 账号不存在：{account_id}")
    _echo_public(account)


@app.command("migrate-serpapi-sqlite")
def migrate_serpapi_sqlite(
    sqlite_path: Path | None = typer.Option(
        None,
        "--sqlite-path",
        help="旧 SerpAPI SQLite 路径；默认读取 opscli 历史路径",
    ),
    actor: str | None = typer.Option(None, "--actor", help="迁移操作人"),
) -> None:
    """将旧 SerpAPI 多 Key、状态和额度一次性导入 MySQL。

    Args:
        sqlite_path: 可选历史 SQLite 文件路径。
        actor: 迁移审计操作人。

    Returns:
        无；终端输出迁移账号数并明确保留源文件。

    Raises:
        typer.BadParameter: SQLite 文件不存在。
        Exception: 读取、加密或 MySQL 写入失败。
    """
    from opscli.google_trends.api.key_store import (
        DEFAULT_SERPAPI_DB_PATH,
        SerpApiKeyStore,
    )

    source_path = Path(sqlite_path or DEFAULT_SERPAPI_DB_PATH).expanduser().resolve()
    if not source_path.is_file():
        raise typer.BadParameter(f"SerpAPI SQLite 文件不存在：{source_path}")
    source = SerpApiKeyStore(source_path)
    repository = _repository()
    migrated = 0
    for record in source.list_keys():
        account = repository.upsert_account(
            provider="serpapi",
            name=record.name,
            api_key=record.api_key,
            remark=record.remark,
            actor=actor,
        )
        repository.update_runtime(
            account.account_id,
            {
                "remaining_quota": record.total_searches_left,
                "current_usage": record.this_month_usage,
                "quota_reset_at": record.plan_renewal_date,
                "last_used_at": record.last_used_at,
                "last_verified_at": record.last_checked_at,
                "last_error_code": "legacy_serpapi_error" if record.last_error else None,
                "last_error_message": record.last_error,
                "provider_metadata": {
                    "plan_name": record.plan_name,
                    "plan_renewal_date": record.plan_renewal_date,
                    "exhausted_at": record.exhausted_at,
                    "migrated_from": "serpapi_sqlite",
                },
            },
        )
        repository.set_status(account.account_id, record.status, actor=actor)
        migrated += 1
    typer.echo(
        json.dumps(
            {
                "migrated_accounts": migrated,
                "source_retained": True,
                "source_path": str(source_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _repository() -> MySqlApiCredentialRepository:
    settings = load_settings()
    settings.validate()
    return MySqlApiCredentialRepository(
        settings=settings.mysql,
        cipher=ApiKeyCipher(settings.master_key),
    )


def _echo_public(account) -> None:
    typer.echo(json.dumps(account.to_public_dict(), ensure_ascii=False, indent=2))

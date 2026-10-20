"""AppHub 应用管理、本地开发预览与源码推送命令。"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from opscli.app.domain.exceptions import AppError
from opscli.app.services.dev import DevService
from opscli.app.services.git_environment import GitEnvironmentService
from opscli.app.services.manager import AppManager
from opscli.app.services.migration import MigrationService
from opscli.app.services.template import TemplateService

app = typer.Typer(help="管理 AppHub 应用、Git 仓库、本地开发预览和源码推送")
migrate_app = typer.Typer(help="管理源码复制迁移项目")
app.add_typer(migrate_app, name="migrate")


def _emit(payload: dict, *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if payload.get("success"):
        data = payload.get("data") or {}
        if data.get("message"):
            typer.echo(data["message"])
        if data.get("credential_refreshed"):
            typer.echo("Git 认证已自动刷新。")
        for key in (
            "app_id", "app_name", "slug", "path", "repo_url", "default_branch",
            "runtime_env_status", "runtime_env_value", "runtime_env_expected_value",
            "runtime_env_updated", "commit_sha", "ready", "status", "platform",
            "architecture", "translated", "git_path", "detected_via", "git_version",
            "minimum_version", "install_method", "migration_id", "origin_type", "phase",
            "startup_status", "target_root", "source_root", "copy_manifest",
            "startup_manifest", "adaptation_status", "adaptation_manifest", "delivery_ready",
            "passed", "state_path", "target_reason", "target_notice",
        ):
            if data.get(key) is not None:
                typer.echo(f"{key}: {data[key]}")
        return
    error = payload.get("error") or {}
    typer.echo(f"错误 [{error.get('code', 'UNKNOWN')}]: {error.get('message', '未知错误')}", err=True)
    if error.get("fix_hint"):
        typer.echo(f"建议: {error['fix_hint']}", err=True)
    if error.get("request_id"):
        typer.echo(f"request_id: {error['request_id']}", err=True)


def _run(command: str, action, *, json_output: bool) -> None:
    manager = AppManager()
    try:
        _emit(
            {"success": True, "command": command, "data": action(manager), "error": None},
            json_output=json_output,
        )
    except AppError as exc:
        _emit(
            {"success": False, "command": command, "data": None, "error": exc.to_dict()},
            json_output=json_output,
        )
        raise typer.Exit(1) from exc
    except Exception as exc:
        _emit(
            {
                "success": False,
                "command": command,
                "data": None,
                "error": {
                    "code": "UNKNOWN",
                    "message": "命令发生未预期错误。",
                    "fix_hint": "重试后仍失败请提交反馈。",
                    "request_id": None,
                    "detail": {"error_type": type(exc).__name__},
                },
            },
            json_output=json_output,
        )
        raise typer.Exit(1) from exc
    finally:
        manager.close()


def _run_migration(command: str, action, *, json_output: bool) -> None:
    service = MigrationService()
    try:
        _emit(
            {"success": True, "command": command, "data": action(service), "error": None},
            json_output=json_output,
        )
    except AppError as exc:
        _emit(
            {"success": False, "command": command, "data": None, "error": exc.to_dict()},
            json_output=json_output,
        )
        raise typer.Exit(1) from exc
    except Exception as exc:
        _emit(
            {
                "success": False,
                "command": command,
                "data": None,
                "error": {
                    "code": "UNKNOWN",
                    "message": "迁移命令发生未预期错误。",
                    "fix_hint": "重试后仍失败请提交反馈。",
                    "request_id": None,
                    "detail": {"error_type": type(exc).__name__},
                },
            },
            json_output=json_output,
        )
        raise typer.Exit(1) from exc
    finally:
        service.close()


@migrate_app.command("start")
def migrate_start(
    source: Path = typer.Option(..., "--source", help="旧项目源码目录，只读"),
    target_root: Path | None = typer.Option(None, "--target-root", help="迁移后的目标项目根目录"),
    app_name: str | None = typer.Option(None, "--app-name", help="AppHub 应用名称；省略时使用源目录名"),
    migration_id: str | None = typer.Option(None, "--migration-id", help="可选迁移任务 ID"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """复制源码并自动完成 AppHub 创建与 Git 初始化。"""
    _run_migration(
        "app migrate start",
        lambda service: service.start(
            source,
            target_root,
            app_name=app_name,
            migration_id=migration_id,
        ),
        json_output=json_output,
    )


@migrate_app.command("status")
def migrate_status(
    target: Path = typer.Option(Path("."), "--target", help="迁移目标项目目录"),
    migration_id: str | None = typer.Option(None, "--migration-id", help="迁移任务 ID"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """查看源码复制迁移状态。"""
    _run_migration(
        "app migrate status",
        lambda service: service.status(target, migration_id=migration_id),
        json_output=json_output,
    )


@migrate_app.command("resume")
def migrate_resume(
    target: Path = typer.Option(Path("."), "--target", help="迁移目标项目目录"),
    migration_id: str | None = typer.Option(None, "--migration-id", help="迁移任务 ID"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """从本地持久化阶段继续迁移，不重复复制或创建应用。"""
    _run_migration(
        "app migrate resume",
        lambda service: service.resume(target, migration_id=migration_id),
        json_output=json_output,
    )


@migrate_app.command("scan-startup")
def migrate_scan_startup(
    target: Path = typer.Option(Path("."), "--target", help="迁移目标项目目录"),
    migration_id: str | None = typer.Option(None, "--migration-id", help="迁移任务 ID"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """重新扫描迁移项目的前后端启动方式。"""
    _run_migration(
        "app migrate scan-startup",
        lambda service: service.scan_startup(target, migration_id=migration_id),
        json_output=json_output,
    )


@migrate_app.command("verify")
def migrate_verify(
    target: Path = typer.Option(Path("."), "--target", help="迁移目标项目目录"),
    migration_id: str | None = typer.Option(None, "--migration-id", help="迁移任务 ID"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """执行迁移复制、启动、身份和 Git 交付检查。"""
    _run_migration(
        "app migrate verify",
        lambda service: service.verify(target, migration_id=migration_id),
        json_output=json_output,
    )


@migrate_app.command("convert-legacy")
def migrate_convert_legacy(
    target: Path = typer.Option(Path("."), "--target", help="包含旧迁移状态的项目目录"),
    migration_id: str | None = typer.Option(None, "--migration-id", help="迁移任务 ID"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """一次性备份并清理旧的模板重构迁移状态。"""
    _run_migration(
        "app migrate convert-legacy",
        lambda service: service.convert_legacy(target, migration_id=migration_id),
        json_output=json_output,
    )


@app.command("create")
def create_app(
    app_name: str = typer.Argument(..., help="应用名称"),
    path: Path | None = typer.Option(None, "--path", help="绑定目录；默认使用应用 slug"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """在 AppHub 创建应用并保存本地基础信息。"""
    _run(
        "app create",
        lambda manager: manager.create_app(app_name, path=path),
        json_output=json_output,
    )


@app.command("ensure-git")
def ensure_git(
    install: bool = typer.Option(False, "--install", help="Git 未就绪时按受控渠道安装"),
    check: bool = typer.Option(False, "--check", help="只检测，不安装系统软件"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """检测本机 Git，并按需从官方可信渠道安装。"""
    if install and check:
        raise typer.BadParameter("--install 与 --check 不能同时使用。")
    try:
        data = GitEnvironmentService().ensure(install=install)
        _emit(
            {"success": True, "command": "app ensure-git", "data": data, "error": None},
            json_output=json_output,
        )
    except AppError as exc:
        _emit(
            {
                "success": False,
                "command": "app ensure-git",
                "data": None,
                "error": exc.to_dict(),
            },
            json_output=json_output,
        )
        raise typer.Exit(1) from exc


@app.command("clone-template")
def clone_template(
    path: Path = typer.Argument(..., help="不存在或为空的目标项目目录"),
    repo_url: str = typer.Option(
        "http://120.76.218.247:3000/ops-admin/template",
        "--repo-url",
        help="统一模板仓库地址",
    ),
    branch: str = typer.Option("master", "--branch", help="模板分支"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """使用 opscli 自带运行时 Git 克隆统一模板并脱离模板仓库。"""
    try:
        data = TemplateService().clone(path, repo_url=repo_url, branch=branch)
        _emit(
            {"success": True, "command": "app clone-template", "data": data, "error": None},
            json_output=json_output,
        )
    except AppError as exc:
        _emit(
            {"success": False, "command": "app clone-template", "data": None, "error": exc.to_dict()},
            json_output=json_output,
        )
        raise typer.Exit(1) from exc


@app.command("init")
def init_git(
    path: Path = typer.Argument(Path("."), help="应用源码目录"),
    app_slug: str | None = typer.Option(None, "--app", help="可选核对 slug；不能用于选择或创建应用"),
    app_id: str | None = typer.Option(None, "--app-id", help="恢复已有应用的五位公开 ID，区分大小写"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """恢复应用信息并初始化本地 Git，不生成或覆盖业务源码。"""
    _run(
        "app init",
        lambda manager: manager.init_git(
            path,
            app_slug=app_slug,
            app_id=app_id,
        ),
        json_output=json_output,
    )


@app.command("dev")
def dev(
    path: Path = typer.Argument(Path("."), help="看板源码目录"),
    backend_port: int | None = typer.Option(
        None,
        "--backend-port",
        help="后端开发端口；省略时从 8035 起自动选择空闲端口",
    ),
    frontend_port: int | None = typer.Option(
        None,
        "--frontend-port",
        help="前端开发端口；省略时从 5173 起自动选择空闲端口",
    ),
) -> None:
    """准备本地环境并启动后端 reload 与前端热更新预览。"""
    try:
        DevService().run(
            path,
            backend_port=backend_port,
            frontend_port=frontend_port,
        )
    except AppError as exc:
        _emit(
            {"success": False, "command": "app dev", "data": None, "error": exc.to_dict()},
            json_output=False,
        )
        raise typer.Exit(1) from exc


@app.command("dev-status")
def dev_status(
    path: Path = typer.Argument(Path("."), help="看板源码目录"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """校验本地开发预览是否仍属于当前项目。"""
    try:
        data = DevService().status(path)
        _emit(
            {"success": True, "command": "app dev-status", "data": data, "error": None},
            json_output=json_output,
        )
    except AppError as exc:
        _emit(
            {"success": False, "command": "app dev-status", "data": None, "error": exc.to_dict()},
            json_output=json_output,
        )
        raise typer.Exit(1) from exc


@app.command("push")
def push(
    path: Path = typer.Argument(Path("."), help="应用源码目录"),
    message: str = typer.Option(..., "--message", "-m", help="Git 提交说明"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """提交并推送源码到应用绑定的远端默认分支，不创建 AppHub release。"""
    _run(
        "app push",
        lambda manager: manager.push(path, message=message),
        json_output=json_output,
    )

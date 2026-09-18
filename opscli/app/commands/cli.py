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
migrate_app = typer.Typer(help="管理旧看板到标准模板的迁移重构任务")
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
            "app_id",
            "app_name",
            "slug",
            "path",
            "repo_url",
            "default_branch",
            "runtime_env_status",
            "runtime_env_value",
            "runtime_env_expected_value",
            "runtime_env_updated",
            "commit_sha",
            "ready",
            "status",
            "platform",
            "architecture",
            "translated",
            "git_path",
            "detected_via",
            "git_version",
            "minimum_version",
            "install_method",
            "migration_id",
            "phase",
            "gate",
            "passed",
            "total_items",
            "dynamic_items",
            "state_path",
            "project_root",
            "running",
            "active",
            "identity_verified",
            "ports_reused",
            "frontend_url",
            "backend_url",
            "supervisor_pid",
            "frontend_pid",
            "backend_pid",
            "state_file",
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
    """执行迁移服务动作，并复用 `opscli app` 的稳定输出信封。"""
    try:
        _emit(
            {"success": True, "command": command, "data": action(MigrationService()), "error": None},
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


@migrate_app.command("init")
def migrate_init(
    source: Path = typer.Option(..., "--source", help="旧看板源码目录，只读"),
    target: Path = typer.Option(Path("."), "--target", help="标准模板目标项目目录"),
    migration_id: str | None = typer.Option(None, "--migration-id", help="可选迁移任务 ID"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """初始化迁移任务、审计快照、覆盖矩阵、UI 蓝图和项目文档。"""
    _run_migration(
        "app migrate init",
        lambda service: service.initialize(source, target, migration_id=migration_id),
        json_output=json_output,
    )


@migrate_app.command("audit")
def migrate_audit(
    target: Path = typer.Option(Path("."), "--target", help="目标项目目录"),
    migration_id: str | None = typer.Option(None, "--migration-id", help="迁移任务 ID"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """重新扫描旧项目只读候选证据。"""
    _run_migration(
        "app migrate audit",
        lambda service: service.audit(target, migration_id=migration_id),
        json_output=json_output,
    )


@migrate_app.command("plan")
def migrate_plan(
    target: Path = typer.Option(Path("."), "--target", help="目标项目目录"),
    migration_id: str | None = typer.Option(None, "--migration-id", help="迁移任务 ID"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """生成迁移计划、UI 规格和数据规格。"""
    _run_migration(
        "app migrate plan",
        lambda service: service.plan(target, migration_id=migration_id),
        json_output=json_output,
    )


@migrate_app.command("status")
def migrate_status(
    target: Path = typer.Option(Path("."), "--target", help="目标项目目录"),
    migration_id: str | None = typer.Option(None, "--migration-id", help="迁移任务 ID"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """查看迁移阶段、门禁状态、交付就绪状态和阻塞项。"""
    _run_migration(
        "app migrate status",
        lambda service: service.status(target, migration_id=migration_id),
        json_output=json_output,
    )


@migrate_app.command("check")
def migrate_check(
    gate: str = typer.Option(..., "--gate", help="inventory、ui、data 或 release"),
    target: Path = typer.Option(Path("."), "--target", help="目标项目目录"),
    migration_id: str | None = typer.Option(None, "--migration-id", help="迁移任务 ID"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """只读检查指定迁移门禁，不推进阶段。"""
    _run_migration(
        "app migrate check",
        lambda service: service.check(target, gate=gate, migration_id=migration_id),
        json_output=json_output,
    )


def _verify_migration(
    command: str,
    gate: str,
    target: Path,
    migration_id: str | None,
    json_output: bool,
) -> None:
    """复用阶段验证命令的参数转发和统一输出。"""
    _run_migration(
        command,
        lambda service: service.verify(target, gate=gate, migration_id=migration_id),
        json_output=json_output,
    )


@migrate_app.command("verify-ui")
def migrate_verify_ui(
    target: Path = typer.Option(Path("."), "--target", help="目标项目目录"),
    migration_id: str | None = typer.Option(None, "--migration-id", help="迁移任务 ID"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """验证 UI 结构门禁并推进到真实数据接入阶段。"""
    _verify_migration("app migrate verify-ui", "ui", target, migration_id, json_output)


@migrate_app.command("verify-data")
def migrate_verify_data(
    target: Path = typer.Option(Path("."), "--target", help="目标项目目录"),
    migration_id: str | None = typer.Option(None, "--migration-id", help="迁移任务 ID"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """验证真实合同、数据层实现和项目工件并推进阶段。"""
    _verify_migration("app migrate verify-data", "data", target, migration_id, json_output)


@migrate_app.command("verify-release")
def migrate_verify_release(
    target: Path = typer.Option(Path("."), "--target", help="目标项目目录"),
    migration_id: str | None = typer.Option(None, "--migration-id", help="迁移任务 ID"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """验证最终交付门禁并完成迁移任务。"""
    _verify_migration("app migrate verify-release", "release", target, migration_id, json_output)


@migrate_app.command("export")
def migrate_export(
    target: Path = typer.Option(Path("."), "--target", help="目标项目目录"),
    migration_id: str | None = typer.Option(None, "--migration-id", help="迁移任务 ID"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """从当前状态重新生成全部迁移文档。"""
    _run_migration(
        "app migrate export",
        lambda service: service.export(target, migration_id=migration_id),
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
        "http://10.1.13.143:3000/aukeys-admin/template",
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


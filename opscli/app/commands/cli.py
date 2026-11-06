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
deployment_app = typer.Typer(help="查询指定提交的自动发布结果")
app.add_typer(migrate_app, name="migrate")
app.add_typer(deployment_app, name="deployment")


def _emit(payload: dict, *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if payload.get("success"):
        data = payload.get("data") or {}
        deployment = data.get("deployment") if isinstance(data.get("deployment"), dict) else None
        if deployment is None and payload.get("command") == "app deployment wait":
            deployment = data
        if deployment:
            status = deployment.get("status")
            if status == "healthy" and deployment.get("is_current_release") and deployment.get("entry_url"):
                typer.echo(f"预览地址：{deployment['entry_url']}")
            elif status == "failed":
                typer.echo(f"构建发布失败 [{deployment.get('error_code') or 'UNKNOWN'}]：{deployment.get('error_summary') or '请查看失败附件。'}")
                build_log = deployment.get("build_log_attachment") or {}
                if build_log.get("path"):
                    typer.echo(f"完整构建日志：{build_log['path']}")
                elif deployment.get("logs_unavailable"):
                    typer.echo("完整构建日志暂不可用。")
                elif not deployment.get("deployment_id"):
                    typer.echo("失败发生在部署前，未生成构建日志。")
                diagnosis = deployment.get("diagnosis_attachment") or {}
                if diagnosis.get("path"):
                    typer.echo(f"发布诊断：{diagnosis['path']}")
                elif deployment.get("diagnosis_unavailable"):
                    typer.echo("发布诊断暂不可用。")
            elif status == "unknown_timeout":
                typer.echo("本轮等待超时，发布结果尚未确认。可登录运营系统 → 应用 → 我的应用管理查看，或按本次 SHA 继续等待。")
                typer.echo(f"opscli app deployment wait \"{deployment.get('path') or data.get('path') or '.'}\" --commit {deployment.get('commit_sha')} --json")
            else:
                typer.echo(f"发布状态：{status}；提交 SHA：{deployment.get('commit_sha')}")
            return
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
    retry_create: bool = typer.Option(False, "--retry-create", help="用户明确要求时重试未完成的应用创建"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """从本地持久化阶段继续迁移，不重复复制或创建应用。"""
    _run_migration(
        "app migrate resume",
        lambda service: service.resume(
            target, migration_id=migration_id, retry_create=retry_create,
        ),
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
    persistent_data_isolation: str = typer.Option(..., "--persistent-data-isolation", help="持久化业务数据按用户隔离：Y=是，N=站点共享"),
    retry_create: bool = typer.Option(False, "--retry-create", help="用户明确要求时重试未完成的应用创建"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """在 AppHub 创建应用并保存本地基础信息。"""
    _run(
        "app create",
        lambda manager: manager.create_app(
            app_name, path=path, persistent_data_isolation=persistent_data_isolation,
            retry_create=retry_create,
        ),
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
    wait: bool = typer.Option(False, "--wait", help="等待本次提交的自动发布结果"),
    timeout: int = typer.Option(1200, "--timeout", min=1, max=3600, help="等待上限，单位秒"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """推送源码；--wait 按本次提交等待自动发布。"""
    _run(
        "app push",
        lambda manager: (
            manager.push(path, message=message, wait=True, timeout=timeout)
            if wait else manager.push(path, message=message)
        ),
        json_output=json_output,
    )


@deployment_app.command("wait")
def deployment_wait(
    path: Path = typer.Argument(Path("."), help="已绑定的应用源码目录"),
    commit: str = typer.Option(..., "--commit", help="本次推送的完整 40 位提交 SHA"),
    timeout: int = typer.Option(1200, "--timeout", min=1, max=3600, help="等待上限，单位秒"),
    json_output: bool = typer.Option(False, "--json", help="输出单个最终 JSON"),
) -> None:
    """继续等待指定提交的发布结果，不再次推送代码。"""
    _run(
        "app deployment wait",
        lambda manager: manager.wait_deployment(path, commit_sha=commit, timeout=timeout),
        json_output=json_output,
    )

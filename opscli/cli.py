"""opscli 顶级 CLI 入口。

基于 Typer 框架，注册所有子模块命令组（auth、skills 等）。
"""
import sys
import time

import typer
from opscli.amazon.cli import app as amazon_app
from opscli.amazon_rufus.cli import app as amazon_rufus_app
from opscli.auth.cli import app as auth_app
from opscli.feedback.cli import app as feedback_app
from opscli.mcp.cli import app as mcp_app
# from opscli.methods_card.cli import app as methods_card_app
from opscli.query.cli import app as query_app
from opscli.seller_sprite.cli import app as seller_sprite_app
from opscli.skills.cli import app as skills_app
from opscli.version import get_version


def _version_callback(value: bool):
    """处理 --version/-V 标志，打印版本号后立即退出。"""
    if value:
        typer.echo(f"opscli v{get_version()}")
        raise typer.Exit()


app = typer.Typer(help="Aukeys 运营 CLI 工具集")

# 模块注册：每新增一个子模块只需在此追加一行（铁律1）
app.add_typer(auth_app, name="auth")
app.add_typer(amazon_app, name="amazon")
app.add_typer(amazon_rufus_app, name="amazon-rufus")
app.add_typer(query_app, name="query")
app.add_typer(feedback_app, name="feedback")
# app.add_typer(methods_card_app, name="methods-card")
app.add_typer(skills_app, name="skills")
app.add_typer(mcp_app, name="mcp")
app.add_typer(seller_sprite_app, name="seller-sprite")


def _get_current_user_email() -> str | None:
    """静默读取当前登录用户的 email，未登录或读取失败均返回 None。"""
    try:
        from opscli.auth.storage.credential_store import CredentialStore
        data = CredentialStore().load()
        return data.get("email") if data else None
    except Exception:
        return None


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        None, "--version", "-V", help="显示版本信息",
        callback=_version_callback, is_eager=True,
    ),
):
    """主回调：为顶级全局选项预留入口，同时注入遥测采集。"""
    # Windows GBK 编码兜底：防止 Rich 输出 Unicode 字符时崩溃
    if sys.platform == "win32":
        for _stream in (sys.stdout, sys.stderr):
            if hasattr(_stream, "reconfigure"):
                try:
                    _stream.reconfigure(errors="replace")
                except Exception:
                    pass
    # 版本更新检查（仅 CLI 模式，MCP 入口不经过此处）
    from opscli.shared.update_check import check_and_notify
    check_and_notify()

    # 记录命令开始时间，用于计算耗时
    _start_ms = time.monotonic()

    def _report_telemetry():
        """命令执行完毕后，异步上报遥测数据。"""
        from opscli.telemetry.collector import build_event, pop_error_type, pop_status
        from opscli.telemetry.reporter import TelemetryReporter

        # sys.argv[1:] 取完整命令行参数，如 ["query", "run", "--dataset", "xxx"]
        argv = sys.argv[1:]
        command_parts = [p for p in argv[:3] if not p.startswith("-")][:2]
        command = " ".join(command_parts) if command_parts else "(unknown)"
        module = command_parts[0] if command_parts else ""

        event = build_event(
            event_type="cli_command",
            command=command,
            module=module,
            status=pop_status(),
            duration_ms=int((time.monotonic() - _start_ms) * 1000),
            error_type=pop_error_type(),
            user_email=_get_current_user_email(),
            raw_payload={"argv": argv} if argv else None,
        )
        TelemetryReporter.fire(**event)

    # 注册关闭钩子：命令执行完毕时自动触发上报
    ctx.call_on_close(_report_telemetry)

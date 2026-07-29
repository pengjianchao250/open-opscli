"""opscli 顶级 CLI 入口。

基于 Typer 框架，注册所有子模块命令组（auth、skills 等）。
"""
import sys
import time

import typer
from opscli.amazon.cli import app as amazon_app
from opscli.amazon_rufus.cli import app as amazon_rufus_app
from opscli.asin_data.cli import app as asin_data_app
from opscli.auth.cli import app as auth_app
from opscli.calculator.cli import app as calculator_app
from opscli.canopy.cli import app as canopy_app
from opscli.canopy_debug.cli import app as canopy_debug_app
from opscli.feedback.cli import app as feedback_app
from opscli.feedtask.cli import app as feedtask_app
from opscli.google_trends.cli import app as google_trends_app
from opscli.google_trends_debug.cli import app as google_trends_debug_app
from opscli.keepa.cli import app as keepa_app
from opscli.keepa_debug.cli import app as keepa_debug_app
from opscli.mcp.cli import app as mcp_app
# from opscli.methods_card.cli import app as methods_card_app
from opscli.notify.cli import app as notify_app
from opscli.query.cli import app as query_app
from opscli.scrape_do.cli import app as scrape_do_app
from opscli.shopify.cli import app as shopify_app
from opscli.seller_sprite.cli import app as seller_sprite_app
from opscli.seller_sprite_debug.cli import app as seller_sprite_debug_app
from opscli.sif.cli import app as sif_app
from opscli.skills.cli import app as skills_app
from opscli.version import get_version
from opscli.xiyou.cli import app as xiyou_app

try:
    from opscli.asin_review.cli import app as asin_review_app
except ModuleNotFoundError as exc:
    if exc.name != "opscli.asin_review":
        raise
    asin_review_app = None


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
app.add_typer(asin_data_app, name="asin-data")
app.add_typer(calculator_app, name="calculator")
if asin_review_app is not None:
    app.add_typer(asin_review_app, name="asin-review")
app.add_typer(canopy_app, name="canopy")
# app.add_typer(canopy_debug_app, name="canopy-debug")
app.add_typer(query_app, name="query")
app.add_typer(scrape_do_app, name="scrape-do")
# app.add_typer(shopify_app, name="shopify")
app.add_typer(feedback_app, name="feedback")
app.add_typer(notify_app, name="notify")
app.add_typer(feedtask_app, name="feedtask")
app.add_typer(google_trends_app, name="google-trends")
# app.add_typer(google_trends_debug_app, name="google-trends-debug")
app.add_typer(keepa_app, name="keepa")
# app.add_typer(keepa_debug_app, name="keepa-debug")
app.add_typer(seller_sprite_app, name="seller-sprite")
# app.add_typer(seller_sprite_debug_app, name="seller-sprite-debug")
# app.add_typer(sif_app, name="sif")
# app.add_typer(xiyou_app, name="xiyou")
# app.add_typer(methods_card_app, name="methods-card")
app.add_typer(skills_app, name="skills")
app.add_typer(mcp_app, name="mcp")


@app.command("self-update")
def self_update():
    """一键升级 opscli 并自动同步 Skills（等效于 pip 升级 + skills install/upgrade）。"""
    # 延迟导入：避免拖慢所有命令的启动耗时
    from opscli.shared.self_update import run_self_update

    code = run_self_update()
    if code != 0:
        raise typer.Exit(code)


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
    # Windows GBK 编码兜底：将 stdout/stderr 强制切换为 UTF-8，
    # 防止 Rich 输出 ✓/↻ 等 Unicode 字符时因 GBK 编码失败而崩溃
    if sys.platform == "win32":
        for _stream in (sys.stdout, sys.stderr):
            if hasattr(_stream, "reconfigure"):
                try:
                    _stream.reconfigure(encoding="utf-8", errors="replace")
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


# 显式授权参数 → 内部字段名的映射（全局参数，可加在任意子命令尾部）
_EXPLICIT_AUTH_FLAGS = {
    "--ops-jwt-token": "ops_jwt",
    "--polaris-jwt-token": "polaris_jwt",
    "--session-id": "session_id",
}


def _extract_explicit_credentials(argv: list[str]):
    """从 argv 中摘出显式授权参数，返回 (清理后的 argv, ExplicitCredentials | None)。

    这是"显式授权中间件"的参数捕获层：在 Typer 解析前先把三个全局参数
    （--ops-jwt-token / --polaris-jwt-token / --session-id）从命令行摘除并注入上下文，
    使其可加在任意子命令尾部（如 opscli query simple ... --ops-jwt-token=x --session-id=y）
    而无需逐个命令改造。

    支持两种写法：
    - --flag=value
    - --flag value（空格分隔）

    校验规则（强制 session-id）：只要提供了任一 JWT，就必须同时提供 --session-id，
    否则打印错误并以退出码 2 终止。

    Args:
        argv: 去掉程序名后的参数列表（即 sys.argv[1:]）

    Returns:
        (cleaned_argv, creds)：cleaned_argv 为移除显式参数后的 argv；
        creds 为解析出的 ExplicitCredentials，未提供任何显式参数时为 None。
    """
    from opscli.auth.context import ExplicitCredentials

    collected: dict[str, str] = {}
    cleaned: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        # 形式一：--flag=value
        if arg.startswith("--") and "=" in arg:
            name, _, value = arg.partition("=")
            if name in _EXPLICIT_AUTH_FLAGS:
                collected[_EXPLICIT_AUTH_FLAGS[name]] = value
                i += 1
                continue
        # 形式二：--flag value（下一个参数为值）
        if arg in _EXPLICIT_AUTH_FLAGS:
            if i + 1 < len(argv):
                collected[_EXPLICIT_AUTH_FLAGS[arg]] = argv[i + 1]
                i += 2
                continue
            # 缺少值：不拦截，交回 Typer 走标准报错
        cleaned.append(arg)
        i += 1

    # 未提供任何显式参数 → 走本地存储常规流程
    if not collected:
        return cleaned, None

    session_id = collected.get("session_id")
    # 强制 session-id：提供了 JWT 却缺 session_id 时直接终止
    if not session_id:
        typer.echo(
            "错误：使用 --ops-jwt-token / --polaris-jwt-token 时必须同时提供 --session-id",
            err=True,
        )
        raise SystemExit(2)

    creds = ExplicitCredentials(
        session_id=session_id,
        ops_jwt=collected.get("ops_jwt"),
        polaris_jwt=collected.get("polaris_jwt"),
    )
    return cleaned, creds


def run() -> None:
    """opscli 进程入口：先摘取显式授权参数注入上下文，再交给 Typer 处理。

    注意：与 `@app.callback()` 装饰的 `main` 回调是两个不同角色——
    `main` 是 Typer 顶层回调（每条命令执行前运行），`run` 是 console_scripts 进程入口。
    """
    from opscli.auth.context import set_explicit_credentials

    cleaned, creds = _extract_explicit_credentials(sys.argv[1:])
    if creds is not None:
        set_explicit_credentials(creds)
        # 用清理后的 argv 覆盖，避免 Typer 因未知选项报错
        sys.argv = [sys.argv[0], *cleaned]
    app()


if __name__ == "__main__":
    run()

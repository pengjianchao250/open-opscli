"""opscli 顶级 CLI 入口。

基于 Typer 框架，注册所有子模块命令组（auth、skills 等）。

子命令懒加载：注册表只登记 (命令名, 模块路径, help)，懒加载代理在顶级
Group 构造时放入 commands 字典（代理本身零导入），顶级 --help 渲染不触发
任何子模块导入；子命令首次分发（执行/--help/补全）时代理才导入真实模块。
动机：正式 wheel 为 Cython 编译，升级后每个 .so 首次 dlopen 需过 macOS
安全评估（数百 ms/个），急切导入全部子命令会把 `opscli -V` 这类轻量命令
拖到 30~90s。详见 docs/plans/CLI子命令懒加载方案.md。
"""
import importlib
import importlib.util
import sys
import time

import typer
from typer.core import TyperGroup

from opscli.version import get_version

# ============================================================================
# 子命令注册表（铁律1：新增子模块只需在此追加一行）
# 元组：(命令名, 子模块 cli 路径, help 文案)
# - 顺序即 `opscli --help` 的 Commands 列表顺序（self-update 等直属命令排最前）
# - help 必须与该子模块 typer.Typer(help=...) 逐字一致，
#   由 tests/test_cli_lazy_loading.py 的注册表一致性测试守护
# - 已停用命令保留注释备查（不进注册表）：canopy-debug / shopify /
#   google-trends-debug / keepa-debug / seller-sprite-debug / sif / methods-card
# ============================================================================
_SUBCOMMANDS: tuple[tuple[str, str, str], ...] = (
    ("auth", "opscli.auth.cli", "认证授权管理"),
    ("app", "opscli.app.cli", "管理 AppHub 应用、Git 仓库、本地开发预览和源码推送"),
    ("api-credentials", "opscli.api_credentials.cli", "统一管理 SerpAPI、Canopy、scrape.do、Keepa 和西柚的多账号 API Key。"),
    ("amazon", "opscli.amazon.cli", "Amazon 商品抓取与 ops 提交通道"),
    ("amazon-rufus", "opscli.amazon_rufus.cli", "Amazon Rufus 自动问答采集"),
    ("asin-data", "opscli.asin_data.cli", "ASIN 批量取数服务"),
    ("calculator", "opscli.calculator.cli", "新品计算器"),
    ("asin-review", "opscli.asin_review.cli", "复盘 ASIN 数据查询"),
    ("canopy", "opscli.canopy.cli", "Canopy 远端 MCP 正式命令面。"),
    ("collector-monitor", "opscli.collector_monitor.cli", "只读查看 Collector Monitor 状态。"),
    ("query", "opscli.query.cli", "数据查询入口，统一转发远端查询请求"),
    ("scrape-do", "opscli.scrape_do.cli", "Scrape.do Amazon Scraper 远端 MCP 正式命令面。"),
    ("feedback", "opscli.feedback.cli", "用户反馈提交与查询"),
    ("notify", "opscli.notify.cli", "发送企业微信等内部通知"),
    ("feedtask", "opscli.feedtask.cli", "通用工单管理"),
    ("google-trends", "opscli.google_trends.cli", "Google Trends 正式场景与本地运维命令。"),
    ("keepa", "opscli.keepa.cli", "Keepa 远端 MCP 正式命令面。"),
    ("seller-sprite", "opscli.seller_sprite.cli", "卖家精灵远端 MCP 正式命令面。"),
    ("skills", "opscli.skills.cli", "Skill 生命周期管理"),
    ("mcp", "opscli.mcp.cli", "MCP Server 管理"),
    ("baiyi", "opscli.baiyi.cli", "佰易产品数据查询"),
)

_SUBCOMMAND_MAP: dict[str, tuple[str, str]] = {
    name: (module_path, help_text) for name, module_path, help_text in _SUBCOMMANDS
}


def _is_subcommand_available(name: str) -> bool:
    """可选子命令探测：asin-review 缺包时静默不注册（等价于旧 try/except 行为）。

    find_spec 只查找不执行子模块；父包 opscli 此时已加载，无额外导入开销。
    """
    if name == "asin-review":
        return importlib.util.find_spec("opscli.asin_review") is not None
    return True


class LazyGroupProxy(TyperGroup):
    """子命令组的懒加载代理。

    构造时零导入，只携带 name/help 供顶级 --help 的 Commands 面板渲染与
    命令名建议；首次真正分发（make_context/invoke/子级 --help/参数补全等）
    时导入真实子模块，交给 typer.main.get_group 转成 click Group 并全量委托。
    子模块自身的定制（no_args_is_help 等）因委托真实对象而完整保留。
    """

    def __init__(self, name: str, module_path: str, help_text: str) -> None:
        super().__init__(name=name, help=help_text)
        self._module_path = module_path
        self._real_group: TyperGroup | None = None

    def _materialize(self) -> TyperGroup:
        if self._real_group is None:
            module = importlib.import_module(self._module_path)
            self._real_group = typer.main.get_group(module.app)
        return self._real_group

    def __getattr__(self, item: str):
        # 构造期/拷贝期的未知属性（含 dunder 探测）不得触发子模块导入
        if item.startswith("__") or item in {"_real_group", "_module_path"}:
            raise AttributeError(item)
        return getattr(self._materialize(), item)

    # ---- 以下覆写均为"先物化、再委托" ----
    def make_context(self, info_name, args, **extra):
        return self._materialize().make_context(info_name, args, **extra)

    def invoke(self, ctx):
        return self._materialize().invoke(ctx)

    def get_command(self, ctx, cmd_name):
        return self._materialize().get_command(ctx, cmd_name)

    def list_commands(self, ctx):
        return self._materialize().list_commands(ctx)

    def get_params(self, ctx):
        return self._materialize().get_params(ctx)

    def get_help(self, ctx):
        return self._materialize().get_help(ctx)

    def format_help(self, ctx, formatter):
        return self._materialize().format_help(ctx, formatter)

    def get_usage(self, ctx):
        return self._materialize().get_usage(ctx)

    def shell_complete(self, ctx, incomplete):
        return self._materialize().shell_complete(ctx, incomplete)


_LAZY_PROXIES: dict[str, LazyGroupProxy] = {}


def _get_lazy_proxy(name: str) -> LazyGroupProxy:
    proxy = _LAZY_PROXIES.get(name)
    if proxy is None:
        module_path, help_text = _SUBCOMMAND_MAP[name]
        proxy = LazyGroupProxy(name=name, module_path=module_path, help_text=help_text)
        _LAZY_PROXIES[name] = proxy
    return proxy


class LazyTyperGroup(TyperGroup):
    """顶级命令组：构造时把注册表的懒加载代理放入 commands 字典。

    不覆写 list_commands/get_command/resolve_command——代理已注册进
    commands，顶级 --help 的命令列表、"Did you mean" 建议、补全等全部
    复用 click/typer 原生实现，避免耦合不同 typer 版本（真实 click 与
    内置 _click 后端）的内部类层次。
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        for name in _SUBCOMMAND_MAP:
            if _is_subcommand_available(name):
                self.commands[name] = _get_lazy_proxy(name)


def _version_callback(value: bool):
    """处理 --version/-V 标志，打印版本号后立即退出。"""
    if value:
        typer.echo(f"opscli v{get_version()}")
        raise typer.Exit()


app = typer.Typer(help="Aukeys 运营 CLI 工具集", cls=LazyTyperGroup)


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

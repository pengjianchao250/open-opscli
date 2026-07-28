"""auth 子命令 CLI 层。

提供认证授权相关的所有 CLI 命令，包括：
- 授权管理：login（Device Flow 登录）、logout（清除凭证）、doctor（环境诊断）
- Token 操作：status（查看状态）、get（获取 JWT）、check（检测有效性）、refresh（刷新）
- 系统管理：list（列出系统）、sync（从 ops 同步）、add/remove（手动管理）
"""
import sys
import base64
import json as _json
import webbrowser
import typer
import httpx
from rich.console import Console
from rich.table import Table
from opscli.auth import AuthClient, BUILTIN_SYSTEMS, OPS_URL
from opscli.auth.storage.credential_store import CredentialStore
from opscli.auth.core.system_registry import SystemRegistry
from opscli.auth.core.device_flow import DeviceFlow
from opscli.auth.exceptions import (
    NotAuthenticatedError,
    SystemNotFoundError,
    DeviceFlowExpiredError,
    DeviceFlowDeniedError,
)

app = typer.Typer(help="认证授权管理")
token_app = typer.Typer(help="JWT Token 管理")
system_app = typer.Typer(help="系统注册管理")
app.add_typer(token_app, name="token")
app.add_typer(system_app, name="system")

console = Console()


def _display_scope(jwt: str, system: str):
    """解析 JWT payload 展示已授权权限范围。

    JWT 格式为 header.payload.signature，此处仅解码 payload 部分。
    Base64 URL 安全编码需要补齐 padding（=）才能正确解码。
    """
    try:
        parts = jwt.split(".")
        if len(parts) < 2:
            return
        # Base64 URL 安全编码可能缺少 padding，按 4 的倍数补齐
        padding = "=" * (-len(parts[1]) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(parts[1] + padding))
        scope = payload.get("scope", "")
        if scope:
            scopes = scope.split()
            console.print(f"    [dim]权限（{len(scopes)} 项）：{', '.join(scopes)}[/dim]")
    except Exception:
        pass


def _client() -> AuthClient:
    """创建默认配置的 AuthClient 实例。"""
    return AuthClient()


def _registry() -> SystemRegistry:
    """创建包含内置系统的 SystemRegistry 实例。"""
    return SystemRegistry(builtin_systems=BUILTIN_SYSTEMS)


# ── 授权管理 ──────────────────────────────────────────

@app.command()
def login():
    """发起 Device Flow 授权（自动打开浏览器）。"""
    store = CredentialStore()
    flow = DeviceFlow(ops_url=OPS_URL, store=store)
    try:
        code = flow.request_device_code()
        console.print(f"\n[bold]请在浏览器打开：[/bold] {code['verification_url']}")
        console.print(f"[bold]输入验证码：  [/bold] [green]{code['user_code']}[/green]")
        console.print(f"等待授权中...（{code['expires_in']} 秒内完成）\n")
        webbrowser.open(f"{code['verification_url']}?code={code['user_code']}")
        result = flow.poll(code["device_code"], interval=code.get("interval", 3))
        # 登录成功后自动同步系统列表，免去用户手动运行 opscli auth system sync
        client = _client()
        try:
            resp = httpx.get(
                f"{OPS_URL}/v1/cli/systems",
                headers=client.build_session_headers("ops"),
                timeout=10,
            )
            if resp.status_code == 200:
                _registry().sync_from_ops(resp.json().get("systems", []))
        except Exception as _sync_exc:
            import logging
            logging.getLogger("opscli.auth").debug("登录后系统列表同步失败（不影响登录）: %s", _sync_exc)
        # 系统同步完成后，使用 session_id 预刷新所有系统 Token，后续命令可直接使用缓存
        try:
            refresh_results = client._tm.refresh_all()
            import logging
            logging.getLogger("opscli.auth").debug("登录后 Token 预刷新结果: %s", refresh_results)
        except Exception as _refresh_exc:
            import logging
            logging.getLogger("opscli.auth").debug("登录后 Token 预刷新失败（不影响登录）: %s", _refresh_exc)
        # 登录成功后失效元数据缓存：授权范围可能随账号变化，强制下次重新拉取
        # 惰性导入避免 auth→query 的模块级环依赖
        from opscli.query.services.metadata_cache import invalidate_metadata_cache

        invalidate_metadata_cache(user_email=result.get("email") or None)
        console.print(f"[green]√ 授权成功！账号：{result.get('email', '')}[/green]")
    except (DeviceFlowExpiredError, DeviceFlowDeniedError) as e:
        console.print(f"[red]× {e}[/red]")
        raise typer.Exit(1)


@app.command()
def logout():
    """清除本地所有凭证"""
    CredentialStore().clear()
    # 登出即失效元数据缓存（避免残留上一个账号的授权数据）
    # 惰性导入避免 auth→query 的模块级环依赖
    from opscli.query.services.metadata_cache import invalidate_metadata_cache

    invalidate_metadata_cache()
    console.print("[green]√ 已退出，本地凭证已清除[/green]")


@app.command()
def me(
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出 JSON"),
):
    """查看当前授权用户信息（调用 /api/v1/auth/me）。

    支持显式授权：opscli auth me --session-id=xxx [--ops-jwt-token=xxx]
    未传显式凭证时使用本地登录态。
    """
    try:
        info = _client().get_me()
    except Exception as e:
        console.print(f"[red]× 获取用户信息失败: {e}[/red]")
        raise typer.Exit(1)
    # 纯 JSON 输出，便于脚本消费；--pretty 时缩进美化
    typer.echo(_json.dumps(info, ensure_ascii=False, indent=2 if pretty else None))


@token_app.command("status")
def status():
    """查看当前登录状态与各系统 Token 情况"""
    c = _client()
    data = c._store.load()
    if not data:
        console.print("[yellow]未登录[/yellow]")
        return
    console.print(f"[green]已登录[/green]  {data.get('email', '')}")
    console.print(f"Session ID：{data.get('session_id', 'N/A')}")
    console.print(f"Session 过期：{data.get('session_expires_at', 'N/A')}\n")
    t = Table("别名", "系统", "Token 状态", "剩余时间(s)")
    for s in c._registry.list_all():
        r = c.check_token(s["alias"])
        t.add_row(
            s["alias"],
            s["system_key"],
            "[green]有效[/green]" if r["valid"] else "[red]无效/未获取[/red]",
            str(r["expires_in"]),
        )
    console.print(t)
    # 展示各系统已授权权限（从已缓存 JWT 解析）
    store_data = c._store.load() or {}
    tokens = store_data.get("tokens", {})
    for s in c._registry.list_all():
        td = tokens.get(s["system_key"])
        if td and td.get("jwt"):
            _display_scope(td["jwt"], s["alias"])


# ── Token 操作 ─────────────────────────────────────────

@token_app.command("get")
def token_get(
    system: str = typer.Option(..., "--system", "-s", help="系统别名"),
):
    """获取指定系统 JWT（纯文本输出，适合脚本）"""
    try:
        typer.echo(_client().get_token(system))
    except (NotAuthenticatedError, SystemNotFoundError) as e:
        # 错误必须走 stderr：本命令 stdout 是纯 JWT，供脚本 $(...) 捕获，
        # 错误混入 stdout 会污染捕获结果。rich Console.print 不支持 err 参数（会抛
        # TypeError），故改用 typer.echo(..., err=True) 输出到 stderr。
        typer.echo(f"{e}", err=True)
        raise typer.Exit(1)


@token_app.command("check")
def token_check(system: str = typer.Option(..., "--system", "-s")):
    """检测指定系统 JWT 有效性"""
    r = _client().check_token(system)
    if r["valid"]:
        console.print(f"[green]√ 有效[/green]  剩余 {r['expires_in']} 秒")
    else:
        console.print("[red]× 已过期或未获取[/red]")
        raise typer.Exit(1)


@token_app.command("refresh")
def token_refresh(
    system: str = typer.Option(None, "--system", "-s"),
    all_systems: bool = typer.Option(False, "--all"),
):
    """刷新 JWT（--system 指定单个，--all 刷新全部）"""
    c = _client()
    if all_systems:
        for alias, st in c._tm.refresh_all().items():
            icon = "[green]√[/green]" if st == "ok" else "[red]×[/red]"
            console.print(f"{icon} {alias}: {st}")
    elif system:
        try:
            c.refresh_token(system)
            console.print(f"[green]√ {system} JWT 已刷新[/green]")
        except Exception as e:
            console.print(f"[red]× {e}[/red]")
            raise typer.Exit(1)
    else:
        console.print("[red]请指定 --system 或 --all[/red]")
        raise typer.Exit(1)


# ── 系统管理 ───────────────────────────────────────────

@system_app.command("list")
def system_list():
    """列出所有已注册系统"""
    t = Table("别名", "System Key", "URL", "来源")
    for s in _registry().list_all():
        t.add_row(s["alias"], s["system_key"], s["url"], s.get("source", ""))
    console.print(t)


@system_app.command("sync")
def system_sync():
    """从 ops 同步多实例系统列表"""
    client = _client()
    if not client.is_authenticated():
        console.print("[red]未登录，请先运行: opscli auth login[/red]")
        raise typer.Exit(1)
    try:
        resp = httpx.get(
            f"{OPS_URL}/api/v1/cli/systems",
            headers=client.build_session_headers("ops"),
            timeout=10,
        )
        resp.raise_for_status()
        systems = resp.json().get("systems", [])
        _registry().sync_from_ops(systems)
        console.print(f"[green]√ 同步完成，共 {len(systems)} 个系统[/green]")
    except Exception as e:
        console.print(f"[red]× 同步失败: {e}[/red]")
        raise typer.Exit(1)


@system_app.command("add")
def system_add(
    alias: str = typer.Option(..., "--alias"),
    url: str = typer.Option(..., "--url"),
    key: str = typer.Option(None, "--key", help="存储键，默认由 alias 生成"),
):
    """手动添加系统实例（source=local）"""
    system_key = key or alias.replace(" ", "_").lower()
    _registry().add_local(alias, system_key, url)
    console.print(f"[green]√ 已添加：{alias}[/green]")


@system_app.command("remove")
def system_remove(alias: str = typer.Option(..., "--alias")):
    """移除手动添加的系统"""
    try:
        _registry().remove(alias)
        console.print(f"[green]√ 已移除：{alias}[/green]")
    except SystemNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


# ── 诊断 ───────────────────────────────────────────────

@app.command()
def doctor():
    """检查登录状态与各系统连通性"""
    c = _client()
    console.print("[bold]opscli auth 环境检查\n[/bold]")
    if c.is_authenticated():
        console.print("[green]√ 已登录[/green]")
    else:
        console.print("[red]× 未登录（运行 opscli auth login）[/red]")
    for s in c._registry.list_all():
        try:
            httpx.get(s["url"], timeout=5)
            console.print(f"[green]√ {s['alias']} 可访问[/green]")
        except Exception:
            console.print(f"[red]× {s['alias']} 不可达 ({s['url']})[/red]")

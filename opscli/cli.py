"""opscli 顶级 CLI 入口。

基于 Typer 框架，注册所有子模块命令组（auth、skills 等）。
"""
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


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-V", help="显示版本信息",
        callback=_version_callback, is_eager=True,
    ),
):
    """主回调：为顶级全局选项预留入口。"""
    # 版本更新检查（仅 CLI 模式，MCP 入口不经过此处）
    from opscli.shared.update_check import check_and_notify
    check_and_notify()

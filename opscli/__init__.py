"""opscli 包入口。

有意 re-export AuthClient，使以下两种导入方式均可用（铁律3）：
    from opscli import AuthClient        # 通过顶层 re-export
    from opscli.auth import AuthClient   # 直接导入子模块

re-export 通过 PEP 562 `__getattr__` 惰性实现：`import opscli` 本身零子模块
开销，首次访问 `AuthClient` / `__version__` 时才加载对应子树。动机与子命令
懒加载一致——升级后每个 .so 首次 dlopen 需过 macOS 安全评估（数百 ms/个），
顶层急切导入会把最轻的命令也拖慢（见 docs/plans/CLI子命令懒加载方案.md）。
"""

from typing import TYPE_CHECKING

__all__ = ["AuthClient", "__version__"]

if TYPE_CHECKING:  # 供静态检查器解析类型，运行时不导入
    from opscli.auth import AuthClient
    from opscli.config import __version__


def __getattr__(name: str):
    if name == "AuthClient":
        from opscli.auth import AuthClient

        return AuthClient
    if name == "__version__":
        from opscli.config import __version__

        return __version__
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

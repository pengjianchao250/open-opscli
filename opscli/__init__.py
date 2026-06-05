"""opscli 包入口。

有意 re-export AuthClient，使以下两种导入方式均可用（铁律3）：
    from opscli import AuthClient        # 通过顶层 re-export
    from opscli.auth import AuthClient   # 直接导入子模块
"""
from opscli.config import __version__  # noqa: F401 — 暴露给外部 from opscli import __version__
from opscli.auth import AuthClient

__all__ = ["AuthClient"]

"""兼容导出层：将 commands.cli.app 暴露为模块级属性。"""

from opscli.asin_review.commands.cli import app

__all__ = ["app"]

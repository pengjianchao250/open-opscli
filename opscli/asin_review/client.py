"""兼容导出层：将 transport.client.AsinReviewClient 暴露为模块级属性。"""

from opscli.asin_review.transport.client import AsinReviewClient

__all__ = ["AsinReviewClient"]

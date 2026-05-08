"""feedback 模块入口。"""

from opscli.feedback.services.manager import FeedbackManager
from opscli.feedback.transport.client import FeedbackClient

__all__ = ["FeedbackManager", "FeedbackClient"]

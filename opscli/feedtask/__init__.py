"""通用工单模块。

封装北极星刊登系统的工单 API（createCustomTask / taskManage/detail），
不绑定任何业务平台，任何模块均可通过本模块提交和查询工单。
"""

from opscli.feedtask.domain.exceptions import (
    BadRemoteJsonError,
    FeedTaskAuthError,
    FeedTaskError,
    FeedTaskParamsError,
    RemoteBusinessError,
    RemoteHttpError,
)
from opscli.feedtask.domain.models import TaskResult, TaskStatus
from opscli.feedtask.services.manager import FeedTaskManager
from opscli.feedtask.transport.client import FeedTaskClient

__all__ = [
    "FeedTaskClient",
    "FeedTaskManager",
    "TaskResult",
    "TaskStatus",
    "FeedTaskError",
    "FeedTaskAuthError",
    "FeedTaskParamsError",
    "RemoteHttpError",
    "RemoteBusinessError",
    "BadRemoteJsonError",
]

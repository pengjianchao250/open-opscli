"""通用工单业务编排层。"""

from __future__ import annotations

from opscli.auth import AuthClient
from opscli.feedtask.domain.models import TaskResult, TaskStatus
from opscli.feedtask.transport.client import FeedTaskClient


class FeedTaskManager:
    """通用工单业务编排层。

    提供工单创建、查询详情等能力，不绑定任何业务平台。
    """

    def __init__(
        self,
        auth_client: AuthClient | None = None,
        jwt: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.client = FeedTaskClient(
            auth_client=auth_client, jwt=jwt, session_id=session_id
        )

    def create(self, payload: dict) -> TaskResult:
        """创建工单，返回结果。

        Args:
            payload: 完整的 createCustomTask 请求体
        """
        result = self.client.create(payload)
        data = result.get("data") or {}
        return TaskResult(
            success=True,
            task_id=data.get("task_id") or data.get("id") or result.get("task_id"),
            message=result.get("msg") or result.get("message") or "工单已提交",
        )

    def get_detail(self, task_id: str) -> TaskStatus:
        """查询工单详情。

        Args:
            task_id: 工单 ID
        """
        result = self.client.get_detail(task_id)
        data = result.get("data") or {}
        return TaskStatus(
            task_id=task_id,
            status=data.get("status") or data.get("approve_state") or "unknown",
            message=data.get("msg") or data.get("message"),
            detail=data,
        )

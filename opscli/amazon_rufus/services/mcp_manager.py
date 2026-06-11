"""Amazon Rufus MCP-facing 编排服务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opscli.amazon_rufus.domain.mcp_models import (
    RufusGetRequest,
    RufusMcpResult,
    RufusRemoteConsentRequest,
    RufusWatchLoginRequest,
)
from opscli.amazon_rufus.services.answer_report_writer import AnswerReportWriter
from opscli.amazon_rufus.services.manager import RufusManager
from opscli.amazon_rufus.services.remote_consent import RemoteConsentStore
from opscli.amazon_rufus.transport.client import RufusTransportClient
from opscli.auth import AuthClient


class RufusMcpManager:
    """封装 Rufus MCP Tool 的凭证绑定、脱敏响应和报告写入。"""

    _SENSITIVE_KEYS = {
        "authorization",
        "content",
        "cookie",
        "cookies",
        "curl",
        "curl_data",
        "headers",
        "localstorage",
        "payload",
        "payload_template",
        "request_body",
        "request_headers",
        "seed",
        "seed_request",
        "storage_state",
        "upload_payload",
    }

    def __init__(
        self,
        *,
        rufus_manager: RufusManager,
        remote_consent_store: RemoteConsentStore,
        report_writer: AnswerReportWriter | None = None,
    ) -> None:
        """初始化 MCP-facing manager。"""
        self.rufus_manager = rufus_manager
        self.remote_consent_store = remote_consent_store
        self.report_writer = report_writer or AnswerReportWriter()

    @classmethod
    def for_current_request(cls, credential_dir: Path | None = None) -> "RufusMcpManager":
        """按当前 MCP 请求隔离目录创建 Rufus MCP manager。"""
        auth_client = AuthClient(base_dir=credential_dir) if credential_dir else AuthClient()
        transport = RufusTransportClient(auth_client=auth_client)
        consent_store = (
            RemoteConsentStore(base_dir=credential_dir / "amazon-rufus")
            if credential_dir
            else RemoteConsentStore()
        )
        return cls(
            rufus_manager=RufusManager(transport_client=transport),
            remote_consent_store=consent_store,
        )

    def remote_consent_status(self, country: str) -> dict[str, Any]:
        """读取国家站点远程授权偏好的 MCP-safe 摘要。"""
        data = self.remote_consent_store.status(country)
        return self._result(self._pick_payload(
            data,
            [
                "country",
                "status",
                "use_remote_authorization",
                "updated_at",
                "source",
            ],
        ))

    def remote_consent_set(self, request: RufusRemoteConsentRequest) -> dict[str, Any]:
        """保存国家站点远程授权偏好并返回 MCP-safe 摘要。"""
        if request.allowed is None:
            raise ValueError("allowed 不能为空")
        data = self.remote_consent_store.save(
            country=request.country,
            allowed=request.allowed,
            source="mcp",
        )
        return self._result(self._pick_payload(
            data,
            [
                "country",
                "status",
                "use_remote_authorization",
                "updated_at",
                "source",
            ],
        ))

    def login_status(self, country: str) -> dict[str, Any]:
        """读取 Rufus 获取前登录态的 MCP-safe 摘要。"""
        data = self.rufus_manager.login_status(country=country)
        return self._result(self._pick_payload(
            data,
            [
                "country",
                "status",
                "has_login_state",
                "can_get_backend",
                "session_cookie_count",
                "has_streaming_request",
            ],
        ))

    def watch_login(self, request: RufusWatchLoginRequest) -> dict[str, Any]:
        """执行 Amazon 登录采集并返回 MCP-safe 保存摘要。"""
        data = self.rufus_manager.watch_login(**request.to_manager_kwargs())
        return self._result(self._pick_payload(
            data,
            [
                "country",
                "asin",
                "saved",
                "login_detected",
                "cookie_count",
                "origin_count",
                "streaming_request_saved",
                "has_payload_template",
            ],
        ))

    def logout(self, *, country: str, include_browser_profile: bool = True) -> dict[str, Any]:
        """清理 Rufus 登录态并返回 MCP-safe 摘要。"""
        data = self.rufus_manager.logout(
            country=country,
            include_browser_profile=include_browser_profile,
        )
        return self._result(self._pick_payload(
            data,
            [
                "country",
                "state_deleted",
                "browser_profile_deleted",
                "mcp_state_cleared",
            ],
        ))

    def platform_cookie_save(self, *, platform: str, country: str, content: str) -> dict[str, Any]:
        """通过 OPS 平台 Cookie 接口保存亚马逊 Rufus 登录态 content，并只返回脱敏摘要。"""
        data = self.rufus_manager.save_platform_cookie(
            platform=platform,
            country=country,
            content=content,
        )
        return self._result(self._pick_payload(
            data,
            [
                "platform",
                "country",
                "status",
                "message",
                "content_length",
            ],
        ))

    def platform_cookie_get(
        self,
        *,
        platform: str,
        country: str,
        include_content: bool = False,
    ) -> dict[str, Any]:
        """读取 OPS 平台 Cookie 接口 content，默认隐藏敏感原文。"""
        data = self.rufus_manager.get_platform_cookie(
            platform=platform,
            country=country,
        )
        payload = self._pick_payload(
            data,
            [
                "platform",
                "country",
                "status",
                "message",
                "content_length",
            ],
        )
        content = str(data.get("content") or "")
        payload["has_content"] = bool(content)
        if include_content:
            payload["content"] = content
            return self._result(payload, allowed_sensitive_keys={"content"})
        return self._result(payload)

    def curl_save(self, *, asin: str, country: str, raw_curl: str) -> dict[str, Any]:
        """保存 Copy-as-cURL 状态，并只返回脱敏摘要。"""
        data = self.rufus_manager.save_curl(
            asin=asin,
            country=country,
            raw_curl=raw_curl,
        )
        return self._result(self._pick_payload(
            data,
            [
                "country",
                "asin",
                "saved",
                "cookie_count",
                "header_count",
                "has_curl",
                "has_payload_template",
            ],
        ))

    def get(self, request: RufusGetRequest) -> dict[str, Any]:
        """获取 Rufus 回答、写入报告，并返回 MCP-safe 报告摘要。"""
        data = self.rufus_manager.get_backend(**request.to_backend_kwargs())
        report_path = self.report_writer.write(data)
        answers = data.get("answers")
        return self._result({
            "report_path": report_path.as_posix(),
            "asin": str(data.get("asin") or "").strip().upper(),
            "country": str(data.get("country") or "").strip().upper(),
            "question_count": int(data.get("question_count") or len(data.get("questions") or [])),
            "answer_count": len(answers) if isinstance(answers, list) else 0,
            "next_action": "已生成 Rufus 报告，请读取 report_path 查看完整答案。",
        })

    def _result(
        self,
        payload: dict[str, Any],
        *,
        allowed_sensitive_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        """构造 MCP-safe 结果并执行敏感字段保护。"""
        self._assert_no_sensitive_keys(payload, allowed_sensitive_keys=allowed_sensitive_keys)
        return RufusMcpResult(payload=payload).to_dict()

    def _pick_payload(self, data: dict[str, Any], keys: list[str]) -> dict[str, Any]:
        """按 allowlist 构造响应。"""
        return {key: data.get(key) for key in keys if key in data}

    def _assert_no_sensitive_keys(
        self,
        value: Any,
        *,
        allowed_sensitive_keys: set[str] | None = None,
    ) -> None:
        """阻止敏感字段穿透到 MCP 响应。"""
        allowed = allowed_sensitive_keys or set()
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = str(key).lower()
                if normalized in self._SENSITIVE_KEYS and normalized not in allowed:
                    raise ValueError(f"MCP 响应包含敏感字段：{key}")
                self._assert_no_sensitive_keys(nested, allowed_sensitive_keys=allowed)
        elif isinstance(value, list):
            for item in value:
                self._assert_no_sensitive_keys(item, allowed_sensitive_keys=allowed)

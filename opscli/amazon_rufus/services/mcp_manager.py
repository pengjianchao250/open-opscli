"""Amazon Rufus MCP-facing 编排服务。"""

from __future__ import annotations

import logging
import shlex
from pathlib import Path
from typing import Any

from opscli.amazon_rufus.domain.exceptions import RufusReportUploadError
from opscli.amazon_rufus.domain.mcp_models import (
    RufusGetRequest,
    RufusMcpResult,
    RufusRemoteConsentRequest,
    RufusWatchLoginRequest,
)
from opscli.amazon_rufus.services.answer_report_publisher import AnswerReportPublisher
from opscli.amazon_rufus.services.manager import RufusManager
from opscli.amazon_rufus.services.remote_consent import RemoteConsentStore
from opscli.amazon_rufus.transport.client import RufusTransportClient
from opscli.auth import AuthClient
from opscli.mcp.context import get_current_api_key, get_current_auth_mode
from opscli.shared.file_uploads import FileUploadClient

_logger = logging.getLogger(__name__)


def _is_remote_mcp_request() -> bool:
    """判断当前 Tool 调用是否来自 HTTP/SSE 远端 MCP 请求。

    与 helpers._get_credential_dir 相同，以 API Key 判定远端；另外认证中间件会为可信上游
    （internal 等）写入 auth_mode 但不带 API Key，这类请求同样经 HTTP 到达，不能当成 stdio
    （与 permissions 的判定口径一致）。stdio 模式两者皆为空。
    """
    return bool(get_current_api_key() or get_current_auth_mode())


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
        report_publisher: AnswerReportPublisher | None = None,
    ) -> None:
        """初始化 MCP-facing manager。"""
        self.rufus_manager = rufus_manager
        self.remote_consent_store = remote_consent_store
        self.report_publisher = report_publisher or AnswerReportPublisher()

    @classmethod
    def for_current_request(
        cls,
        credential_dir: Path | None = None,
        *,
        jwt: str | None = None,
        session_id: str | None = None,
    ) -> "RufusMcpManager":
        """按当前 MCP 请求隔离目录创建 Rufus MCP manager。"""
        auth_client = AuthClient(base_dir=credential_dir) if credential_dir else AuthClient()
        transport = RufusTransportClient(auth_client=auth_client)
        report_publisher = AnswerReportPublisher(
            file_upload_client=FileUploadClient(auth_client=auth_client, jwt=jwt, session_id=session_id),
        )
        consent_store = (
            RemoteConsentStore(base_dir=credential_dir / "amazon-rufus")
            if credential_dir
            else RemoteConsentStore()
        )
        return cls(
            rufus_manager=RufusManager(transport_client=transport),
            remote_consent_store=consent_store,
            report_publisher=report_publisher,
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
        """获取 Rufus 回答、发布报告，并按 MCP 运行模式返回报告摘要。

        报告由 MCP 进程写在自身工作目录下：
        - 远端 HTTP/SSE 模式（多客户端共享部署）：文件在 MCP 服务器上，调用方读不到，
          因此 report_path 置空、只给 download_url 和下载指引；服务端路径只写服务端日志，
          不放进响应，避免再次诱导调用方去本地读取；
        - 本地 stdio 模式：与调用方同机，返回绝对路径，避免子进程 CWD 与调用方不同导致相对路径失效。

        Returns:
            MCP-safe 报告摘要，含 storage_scope / local_readable / next_action 等字段。

        Raises:
            RufusReportUploadError: 上传失败；远端模式不带 report_path，stdio 模式带绝对路径。
        """
        data = self.rufus_manager.get_backend(**request.to_backend_kwargs())
        remote = _is_remote_mcp_request()
        try:
            published_report = self.report_publisher.publish(data)
        except RufusReportUploadError as exc:
            # 上传失败同样按模式改写路径：远端文件调用方不可读，只记服务端日志；stdio 给绝对路径。
            if remote:
                _logger.warning("Rufus 报告上传失败，报告仅保留在 MCP 服务器：%s", exc.report_path)
            raise RufusReportUploadError(
                None if remote else exc.report_path.resolve(),
                upload_error=exc.upload_error,
            ) from exc
        answers = data.get("answers")
        report_url = published_report.url
        if remote:
            # 服务端报告路径仅用于审计排障，记日志而不下发给调用方。
            _logger.info("Rufus 报告已写入 MCP 服务器：%s", published_report.path.as_posix())
            report_fields = {
                "report_path": None,
                "report_url": report_url,
                "storage_scope": "remote",
                "local_readable": False,
                "download_url": report_url,
            }
            # curl 必须带 -f：链接失效时以非 0 退出，避免把 OSS 错误页当成报告写入本地；
            # URL 经 shlex.quote 引用，防止 $、反引号等字符在调用方 shell 中被展开执行。
            next_action = (
                "报告保存在远端 MCP 服务器，调用方本地不存在该文件，不要在本地文件系统查找"
                "（report_path 为空）；需要阅读内容时用 "
                f"curl -fsSL {shlex.quote(report_url)} -o <本地文件> "
                "下载后再做回答质量判断，下载失败时如实返回错误；最终向用户返回 report_url。"
            )
        else:
            report_fields = {
                "report_path": published_report.path.resolve().as_posix(),
                "report_url": report_url,
                "storage_scope": "local",
                "local_readable": True,
            }
            next_action = "请读取 report_path（本机绝对路径）做回答质量判断，最终向用户返回 report_url。"
        return self._result({
            **report_fields,
            "asin": str(data.get("asin") or "").strip().upper(),
            "country": str(data.get("country") or "").strip().upper(),
            "question_count": int(data.get("question_count") or len(data.get("questions") or [])),
            "answer_count": len(answers) if isinstance(answers, list) else 0,
            "next_action": next_action,
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

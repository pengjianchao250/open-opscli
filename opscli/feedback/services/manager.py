"""feedback 模块业务编排层。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opscli.auth import AuthClient
from opscli.feedback.domain.exceptions import InvalidPayloadError
from opscli.feedback.domain.models import FEEDBACK_SCHEMA, FEEDBACK_TYPES, SEVERITIES, SOURCES
from opscli.feedback.transport.client import FeedbackClient
from opscli.version import get_version


class FeedbackManager:
    """构造、校验并提交用户反馈。"""

    def __init__(
        self,
        auth_client: AuthClient | None = None,
        jwt: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.client = FeedbackClient(auth_client=auth_client, jwt=jwt, session_id=session_id)

    def schema(self) -> dict:
        return {
            "feedback_types": list(FEEDBACK_TYPES),
            "severities": list(SEVERITIES),
            "sources": list(SOURCES),
            "payload_schema": FEEDBACK_SCHEMA,
        }

    def submit(
        self,
        *,
        feedback_type: str,
        title: str,
        content: str,
        severity: str = "medium",
        source: str = "cli",
        payload: dict | None = None,
        context: dict | None = None,
        execution_summary: dict | None = None,
        attachments: list[dict] | None = None,
        app_version: str | None = None,
        system_alias: str = "ops",
        client_name: str = "opscli",
        client_version: str | None = None,
        skill_name: str | None = None,
        skill_version: str | None = None,
        command_name: str | None = None,
        mcp_tool_name: str | None = None,
    ) -> dict:
        request_payload = self.build_payload(
            feedback_type=feedback_type,
            title=title,
            content=content,
            severity=severity,
            source=source,
            payload=payload,
            context=context,
            execution_summary=execution_summary,
            attachments=attachments,
            app_version=app_version,
            system_alias=system_alias,
            client_name=client_name,
            client_version=client_version,
            skill_name=skill_name,
            skill_version=skill_version,
            command_name=command_name,
            mcp_tool_name=mcp_tool_name,
        )
        return self.client.submit(request_payload)

    def submit_payload(self, payload: dict) -> dict:
        request_payload = self.normalize_payload(payload)
        self.validate_payload(request_payload)
        return self.client.submit(request_payload)

    def detail(self, feedback_uuid: str) -> dict:
        feedback_uuid = feedback_uuid.strip()
        if not feedback_uuid:
            raise InvalidPayloadError("feedback_uuid 不能为空")
        return self.client.detail(feedback_uuid)

    def build_payload(
        self,
        *,
        feedback_type: str,
        title: str,
        content: str,
        severity: str = "medium",
        source: str = "cli",
        payload: dict | None = None,
        context: dict | None = None,
        execution_summary: dict | None = None,
        attachments: list[dict] | None = None,
        app_version: str | None = None,
        system_alias: str = "ops",
        client_name: str = "opscli",
        client_version: str | None = None,
        skill_name: str | None = None,
        skill_version: str | None = None,
        command_name: str | None = None,
        mcp_tool_name: str | None = None,
    ) -> dict:
        version = get_version()
        ctx = dict(context or {})
        ctx["app_version"] = version
        ctx.setdefault("client_name", client_name)
        if command_name:
            ctx.setdefault("command_name", command_name)
        if skill_name:
            ctx.setdefault("skill_name", skill_name)
        if skill_version:
            ctx.setdefault("skill_version", skill_version)
        if mcp_tool_name:
            ctx.setdefault("mcp_tool_name", mcp_tool_name)

        request_payload = {
            "source": source,
            "feedback_type": feedback_type,
            "severity": severity,
            "title": title,
            "content": content,
            "payload": payload,
            "context": ctx,
            "execution_summary": execution_summary,
            "attachments": attachments,
            "app_version": version,
            "system_alias": system_alias,
            "client_name": client_name,
            "client_version": version,
            "skill_name": skill_name,
            "skill_version": skill_version,
            "command_name": command_name,
            "mcp_tool_name": mcp_tool_name,
        }
        compacted = {key: value for key, value in request_payload.items() if value is not None}
        self.validate_payload(compacted)
        return compacted

    def normalize_payload(self, payload: dict) -> dict:
        """Normalize externally supplied payloads before validation/submission.

        Version fields are always sourced from the running aukeys-opscli package.
        Callers may not override them, including in --file mode.
        """
        if not isinstance(payload, dict):
            raise InvalidPayloadError("反馈 payload 必须是 JSON 对象")

        version = get_version()
        request_payload = dict(payload)
        context = request_payload.get("context")
        if context is None:
            context = {}
        elif not isinstance(context, dict):
            raise InvalidPayloadError("context 必须是 JSON 对象")
        else:
            context = dict(context)

        context["app_version"] = version
        request_payload["context"] = context
        request_payload["app_version"] = version
        request_payload["client_version"] = version
        return request_payload

    def validate_payload(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            raise InvalidPayloadError("反馈 payload 必须是 JSON 对象")

        feedback_type = str(payload.get("feedback_type") or "")
        if feedback_type not in FEEDBACK_TYPES:
            raise InvalidPayloadError(f"feedback_type 必须是: {', '.join(FEEDBACK_TYPES)}")

        severity = str(payload.get("severity") or "medium")
        if severity not in SEVERITIES:
            raise InvalidPayloadError(f"severity 必须是: {', '.join(SEVERITIES)}")

        source = str(payload.get("source") or "cli")
        if source not in SOURCES:
            raise InvalidPayloadError(f"source 必须是: {', '.join(SOURCES)}")

        title = str(payload.get("title") or "").strip()
        if not title:
            raise InvalidPayloadError("title 不能为空")
        if len(title) > 200:
            raise InvalidPayloadError("title 不能超过 200 个字符")

        content = str(payload.get("content") or "").strip()
        if not content:
            raise InvalidPayloadError("content 不能为空")

        for key in ("payload", "context", "execution_summary"):
            if key in payload and payload[key] is not None and not isinstance(payload[key], dict):
                raise InvalidPayloadError(f"{key} 必须是 JSON 对象")

        attachments = payload.get("attachments")
        if attachments is not None and not isinstance(attachments, list):
            raise InvalidPayloadError("attachments 必须是 JSON 数组")

        execution_summary = payload.get("execution_summary") or {}
        failed_calls = execution_summary.get("failed_calls") if isinstance(execution_summary, dict) else None
        if failed_calls is not None:
            if not isinstance(failed_calls, list):
                raise InvalidPayloadError("execution_summary.failed_calls 必须是数组")
            for idx, item in enumerate(failed_calls, start=1):
                if not isinstance(item, dict):
                    raise InvalidPayloadError(f"execution_summary.failed_calls[{idx}] 必须是对象")
                if not str(item.get("tool") or "").strip():
                    raise InvalidPayloadError(f"execution_summary.failed_calls[{idx}].tool 不能为空")
                if not str(item.get("error_message") or "").strip():
                    raise InvalidPayloadError(f"execution_summary.failed_calls[{idx}].error_message 不能为空")
                call_params = item.get("call_params")
                if call_params is not None and not isinstance(call_params, dict):
                    raise InvalidPayloadError(f"execution_summary.failed_calls[{idx}].call_params 必须是对象")


def load_json_arg(value: str | None, *, label: str) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except Exception as exc:
        raise InvalidPayloadError(f"{label} 不是合法 JSON") from exc


def load_json_file(path: str | None, *, label: str) -> Any:
    if path is None:
        return None
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise InvalidPayloadError(f"{label} 文件不存在: {file_path}")
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise InvalidPayloadError(f"{label} 文件不是合法 JSON: {file_path}") from exc

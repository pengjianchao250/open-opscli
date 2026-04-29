"""Rufus SSE 解析服务。"""

from __future__ import annotations

import json
from typing import Any

from opscli.amazon_rufus.domain.models import AnswerData


class RufusParserService:
    """解析 Rufus SSE 文本为结构化回答。"""

    def parse(self, raw_text: str) -> AnswerData:
        """解析 SSE 文本。"""
        text_parts: list[str] = []
        blocks: list[dict] = []
        thread_id: str | None = None
        for event in self._iter_sse_data(raw_text):
            if thread_id is None:
                thread_id = self._extract_thread_id(event)
            extracted = self._extract_text(event)
            if extracted:
                text_parts.append(extracted)
            if isinstance(event.get("blocks"), list):
                blocks.extend(event["blocks"])
        text = "".join(text_parts).strip()
        return AnswerData(text=text, blocks=blocks, is_success=bool(text), thread_id=thread_id)

    def _iter_sse_data(self, raw_text: str) -> list[dict[str, Any]]:
        """提取 SSE data 行。"""
        events: list[dict[str, Any]] = []
        for line in raw_text.splitlines():
            if not line.startswith("data:"):
                continue
            payload = line.removeprefix("data:").strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                value = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                events.append(value)
        return events

    def _extract_text(self, event: dict[str, Any]) -> str:
        """从常见 Rufus 字段中提取文本。"""
        for key in ("answer", "text", "content", "message"):
            value = event.get(key)
            if isinstance(value, str):
                return value
        inference = event.get("inference")
        if isinstance(inference, dict):
            return self._extract_text(inference)
        return ""

    def _extract_thread_id(self, event: dict[str, Any]) -> str | None:
        """提取会话线程 ID。"""
        metadata = event.get("conversation_metadata") or event.get("conversationMetadata")
        if isinstance(metadata, dict):
            value = metadata.get("threadId") or metadata.get("thread_id")
            if isinstance(value, str):
                return value
        return None

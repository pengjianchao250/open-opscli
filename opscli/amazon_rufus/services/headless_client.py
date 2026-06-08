"""Rufus headless streaming 请求客户端。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from opscli.amazon_rufus.domain.exceptions import HeadlessRufusRequestError
from opscli.amazon_rufus.domain.models import AnswerData, SeedRequestRecord
from opscli.amazon_rufus.services.parser import RufusParserService
from opscli.amazon_rufus.services.replay import RufusReplayService


@dataclass(slots=True)
class HeadlessRufusClient:
    """使用 Cookie 和 payload_template 获取 Rufus SSE 答案。"""

    parser: RufusParserService | None = None
    replay: RufusReplayService | None = None

    def __post_init__(self) -> None:
        """初始化默认依赖。"""
        self.parser = self.parser or RufusParserService()
        self.replay = self.replay or RufusReplayService()

    def query(
        self,
        *,
        streaming_url: str,
        seed: SeedRequestRecord,
        questions: list[str],
        cookie: str,
        headers: dict[str, str] | None,
        payload_template: dict[str, Any] | None,
        timeout_seconds: int,
    ) -> list[AnswerData]:
        """按问题顺序请求 Rufus 并解析答案。"""
        normalized_url = str(streaming_url or "").strip()
        if "/rufus/cl/streaming" not in normalized_url:
            raise HeadlessRufusRequestError("streaming_url 必须包含 /rufus/cl/streaming")

        normalized_cookie = str(cookie or "").strip()
        if not normalized_cookie:
            raise HeadlessRufusRequestError("cookie 不能为空")

        answers: list[AnswerData] = []
        thread_id: str | None = None
        request_headers = self._build_headers(headers or {}, normalized_cookie)
        seed_body_text = (
            json.dumps(payload_template, ensure_ascii=False) if payload_template is not None else seed.request_body
        )

        for question in questions:
            payload = self.replay.build_payload(seed_body_text, question, thread_id, seed.asin, origin_url=seed.page_url)
            raw_text = self._post_rufus(
                url=normalized_url,
                headers=request_headers,
                payload=payload,
                timeout_seconds=timeout_seconds,
            )
            answer = self.parser.parse(raw_text)
            thread_id = answer.thread_id or thread_id
            answers.append(answer)
        return answers

    def _build_headers(self, base_headers: dict[str, str], cookie: str) -> dict[str, str]:
        """构造 Rufus 请求头。"""
        headers = {"accept": "*/*"}
        headers.update({str(k): str(v) for k, v in base_headers.items() if str(k).lower() != "cookie"})
        headers["Cookie"] = cookie
        if not any(key.lower() == "content-type" for key in headers):
            headers["content-type"] = "application/json"
        headers.pop("content-length", None)
        headers.pop("Content-Length", None)
        return headers

    def _post_rufus(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> str:
        """发起 Rufus streaming 请求并收集原始 SSE 文本。"""
        body = json.dumps(payload, ensure_ascii=False)
        try:
            with httpx.Client(timeout=httpx.Timeout(timeout_seconds)) as client:
                with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    content=body.encode("utf-8"),
                ) as response:
                    if response.status_code < 200 or response.status_code >= 300:
                        raise HeadlessRufusRequestError(f"Rufus 请求失败: {response.status_code}")
                    raw_parts: list[str] = []
                    for chunk in response.iter_text():
                        if chunk:
                            raw_parts.append(chunk)
                    return "".join(raw_parts)
        except httpx.HTTPError as exc:
            raise HeadlessRufusRequestError(f"Rufus 请求失败: {exc}") from exc

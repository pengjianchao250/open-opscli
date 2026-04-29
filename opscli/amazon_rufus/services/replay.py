"""Rufus 请求重放服务。"""

from __future__ import annotations

import json

from opscli.amazon_rufus.domain.exceptions import RufusReplayError
from opscli.amazon_rufus.domain.models import AnswerData, SeedRequestRecord
from opscli.amazon_rufus.services.parser import RufusParserService


class RufusReplayService:
    """基于 seed request 逐题重放 Rufus。"""

    def __init__(self, parser: RufusParserService | None = None) -> None:
        self.parser = parser or RufusParserService()

    def build_payload(self, seed_body: str, question: str, thread_id: str | None = None) -> dict:
        """基于 seed body 替换 query。"""
        try:
            payload = json.loads(seed_body or "{}")
        except json.JSONDecodeError as exc:
            raise RufusReplayError("seed request body 不是合法 JSON") from exc
        query_context = payload.setdefault("queryContext", {})
        if not isinstance(query_context, dict):
            query_context = {}
            payload["queryContext"] = query_context
        query_context["query"] = question
        if thread_id:
            payload["historyThreadContext"] = {"threadId": thread_id}
        return payload

    def replay(self, seed: SeedRequestRecord, questions: list[str]) -> list[AnswerData]:
        """无页面句柄时返回失败占位，正式运行由页面重放实现覆盖。"""
        return []

    def replay_with_page(self, page, seed: SeedRequestRecord, questions: list[str]) -> list[AnswerData]:
        """在页面上下文中逐题 fetch Rufus。"""
        answers: list[AnswerData] = []
        thread_id: str | None = None
        for question in questions:
            payload = self.build_payload(seed.request_body, question, thread_id)
            raw_text = page.evaluate(
                """
                async ({ url, body }) => {
                  const response = await fetch(url, {
                    method: 'POST',
                    headers: { 'content-type': 'application/json' },
                    body: JSON.stringify(body)
                  });
                  return await response.text();
                }
                """,
                {"url": seed.request_url, "body": payload},
            )
            answer = self.parser.parse(raw_text)
            thread_id = answer.thread_id or thread_id
            answers.append(answer)
        return answers


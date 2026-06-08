"""Rufus 请求重放服务。"""

from __future__ import annotations

import copy
import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from opscli.amazon_rufus.domain.exceptions import RufusReplayError
from opscli.amazon_rufus.domain.models import AnswerData, SeedRequestRecord
from opscli.amazon_rufus.services.parser import RufusParserService


class RufusReplayService:
    """基于 seed request 逐题重放 Rufus。"""

    REPLAY_HEADER_ALLOWLIST = {
        "anti-csrftoken-a2z",
        "content-type",
        "x-amz-is-papyrus",
    }

    def __init__(self, parser: RufusParserService | None = None) -> None:
        self.parser = parser or RufusParserService()

    def build_payload(
        self,
        seed_body: str,
        question: str,
        thread_id: str | None = None,
        asin: str | None = None,
        origin_url: str | None = None,
    ) -> dict:
        """基于 curl payload_template 复刻 Rufus 请求上下文。"""
        try:
            parsed = json.loads(seed_body or "{}")
        except json.JSONDecodeError as exc:
            raise RufusReplayError("seed request body 不是合法 JSON") from exc
        payload = copy.deepcopy(parsed) if isinstance(parsed, dict) else {}
        query_context = payload.setdefault("queryContext", {})
        if not isinstance(query_context, dict):
            query_context = {}
            payload["queryContext"] = query_context
        query_context["query"] = question
        query_context["actionType"] = "SEARCH"
        query_context["qis"] = "NileCLTextInput"

        page_context = payload.setdefault("pageContext", {})
        if not isinstance(page_context, dict):
            page_context = {}
            payload["pageContext"] = page_context
        page_context["pageType"] = "DETAIL_PAGE"
        page_context["targetPageType"] = "DETAIL_PAGE"
        page_context["originPageType"] = "DETAIL_PAGE"
        normalized_asin = (asin or "").strip().upper()
        if normalized_asin:
            if origin_url:
                page_context["targetUrl"] = str(origin_url)
                page_context["originUrl"] = str(origin_url)
            self._upsert_asin_metadata(page_context, "targetPageMetadata", normalized_asin)
            self._upsert_asin_metadata(page_context, "pageMetadata", normalized_asin)
            self._upsert_asin_metadata(page_context, "originPageMetadata", normalized_asin)

        bottom_sheet_context = payload.setdefault("bottomSheetContext", {})
        if not isinstance(bottom_sheet_context, dict):
            bottom_sheet_context = {}
            payload["bottomSheetContext"] = bottom_sheet_context
        bottom_sheet_context["previousTurnsBottomSheetSize"] = "expanded"

        impressions_context = payload.setdefault("impressionsContext", {})
        if not isinstance(impressions_context, dict):
            impressions_context = {}
            payload["impressionsContext"] = impressions_context
        impressions_context["FIRST_TIME_USER_MESSAGE_SEEN_STATUS"] = "SEEN"

        history_context = payload.get("historyThreadContext")
        if not isinstance(history_context, dict):
            history_context = {}
        payload["historyThreadContext"] = {
            "threadId": thread_id,
            "threadState": history_context.get("threadState") or "THREAD_STATE_UNKNOWN",
        }
        return payload

    def build_replay_url(self, seed: SeedRequestRecord) -> str:
        """补齐扩展端 Rufus replay URL 参数。"""
        parts = urlsplit(seed.request_url)
        query_pairs = parse_qsl(parts.query, keep_blank_values=True)
        query: dict[str, str] = dict(query_pairs)
        if seed.tab_id:
            query["tabId"] = seed.tab_id
        query.setdefault("programId", "NILE_CLASSIC:desktop-cl")
        query.setdefault("ref", "nl_cl_dsk_csq")
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    def replay(self, seed: SeedRequestRecord, questions: list[str]) -> list[AnswerData]:
        """无页面句柄时返回失败占位，正式运行由页面重放实现覆盖。"""
        return []

    def replay_with_page(self, page, seed: SeedRequestRecord, questions: list[str]) -> list[AnswerData]:
        """在页面上下文中逐题 fetch Rufus。"""
        answers: list[AnswerData] = []
        thread_id: str | None = None
        headers = self._build_replay_headers(seed.request_headers)
        replay_url = self.build_replay_url(seed)
        for question in questions:
            payload = self.build_payload(seed.request_body, question, thread_id, seed.asin)
            raw_text = page.evaluate(
                """
                async ({ url, body, headers }) => {
                  const response = await fetch(url, {
                    method: 'POST',
                    headers,
                    body: JSON.stringify(body)
                  });
                  return await response.text();
                }
                """,
                {"url": replay_url, "body": payload, "headers": headers},
            )
            answer = self.parser.parse(raw_text)
            thread_id = answer.thread_id or thread_id
            answers.append(answer)
        return answers

    def _build_replay_headers(self, request_headers: dict[str, str]) -> dict[str, str]:
        """提取浏览器允许脚本设置且 Rufus 必需的请求头。"""
        headers: dict[str, str] = {}
        for key, value in request_headers.items():
            normalized = key.lower()
            if normalized in self.REPLAY_HEADER_ALLOWLIST:
                headers[normalized] = value
        headers.setdefault("content-type", "application/json")
        return headers

    def _upsert_asin_metadata(self, page_context: dict, key: str, asin: str) -> None:
        """确保页面 metadata 中存在目标 ASIN。"""
        metadata = page_context.get(key)
        if not isinstance(metadata, list):
            metadata = []
            page_context[key] = metadata
        for item in metadata:
            if isinstance(item, dict) and item.get("type") == "ASIN":
                item["value"] = asin
                return
        metadata.append({"type": "ASIN", "value": asin})


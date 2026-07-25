"""Rufus headless streaming request client."""

from __future__ import annotations

import concurrent.futures
import json
import re
import time
from dataclasses import dataclass, replace
from typing import Any

import httpx

from opscli.amazon_rufus.domain.exceptions import HeadlessRufusRequestError, RufusAnswerValidationError
from opscli.amazon_rufus.domain.models import AnswerData, SeedRequestRecord
from opscli.amazon_rufus.services.parser import RufusParserService
from opscli.amazon_rufus.services.replay import RufusReplayService


_OFFICIAL_ERROR_PHRASES = (
    "sorry, something went wrong",
    "something went wrong",
    "try again",
)
_SHOPPING_SCOPE_REFUSAL_PHRASES = (
    "i'm designed specifically to help customers with shopping decisions on amazon",
    "designed specifically to help customers with shopping decisions on amazon",
    "falls outside my scope as a shopping assistant",
    "outside my scope as a shopping assistant",
    "我是专门为帮助顾客在亚马逊上做购物决定而设计的",
    "我是专门为帮助客户在亚马逊上做购物决定而设计的",
    "我是专门为帮助顾客在亚马逊上做购物决策而设计的",
    "我是专门为帮助客户在亚马逊上做购物决策而设计的",
    "专门帮助顾客在亚马逊上做购物决定",
    "专门帮助客户在亚马逊上做购物决定",
    "专门帮助顾客在亚马逊上做购物决策",
    "专门帮助客户在亚马逊上做购物决策",
    "超出了我作为购物助手的范围",
    "超出我作为购物助手的范围",
    "超出了我的购物助手范围",
    "超出我的购物助手范围",
)
_CHINESE_SCOPE_REFUSAL_CONTEXT_PHRASES = (
    "购物助手",
    "购物决策",
    "购物决定",
    "内部业务分析",
    "内部商业分析",
    "产品优化策略",
)
_CHINESE_SCOPE_REFUSAL_ACTION_PHRASES = (
    "不能回答",
    "无法回答",
    "不能提供",
    "无法提供",
    "不便提供",
    "不能帮助",
    "无法帮助",
    "超出",
    "不在我的范围",
    "不属于我的范围",
    "不在我的职责范围",
    "不属于我的职责范围",
)
_PLACEHOLDER_PHRASES = (
    "thinking",
    "thinking...",
)
_MIN_STRICT_TEXT_LENGTH = 20
_MIN_DIAGNOSIS_SECTION_TEXT_LENGTH = 20


@dataclass(slots=True)
class HeadlessRufusClient:
    """Fetch Rufus SSE answers with stored cookie and payload template."""

    parser: RufusParserService | None = None
    replay: RufusReplayService | None = None

    def __post_init__(self) -> None:
        """Initialize default dependencies."""
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
        parallel: bool = False,
        concurrency: int = 3,
        retry: int = 0,
        strict_answer: bool = False,
    ) -> list[AnswerData]:
        """Fetch answers in order; parallel mode keeps one independent Rufus thread per question."""
        normalized_url = str(streaming_url or "").strip()
        if "/rufus/cl/streaming" not in normalized_url:
            raise HeadlessRufusRequestError("streaming_url must contain /rufus/cl/streaming")

        normalized_cookie = str(cookie or "").strip()
        if not normalized_cookie:
            raise HeadlessRufusRequestError("cookie cannot be empty")

        request_headers = self._build_headers(headers or {}, normalized_cookie)
        seed_body_text = (
            json.dumps(payload_template, ensure_ascii=False) if payload_template is not None else seed.request_body
        )

        if parallel:
            return self._query_parallel(
                streaming_url=normalized_url,
                seed=seed,
                questions=questions,
                request_headers=request_headers,
                seed_body_text=seed_body_text,
                timeout_seconds=timeout_seconds,
                concurrency=concurrency,
                retry=retry,
                strict_answer=strict_answer,
            )

        answers: list[AnswerData] = []
        thread_id: str | None = None
        for question in questions:
            answer = self._query_one_with_retries(
                streaming_url=normalized_url,
                seed=seed,
                question=question,
                question_index=len(answers) + 1,
                thread_id=thread_id,
                request_headers=request_headers,
                seed_body_text=seed_body_text,
                timeout_seconds=timeout_seconds,
                retry=retry,
                strict_answer=strict_answer,
            )
            thread_id = answer.thread_id or thread_id
            answers.append(answer)
        return answers

    def _query_parallel(
        self,
        *,
        streaming_url: str,
        seed: SeedRequestRecord,
        questions: list[str],
        request_headers: dict[str, str],
        seed_body_text: str,
        timeout_seconds: int,
        concurrency: int,
        retry: int,
        strict_answer: bool,
    ) -> list[AnswerData]:
        """Fetch multiple questions concurrently without sharing thread_id."""
        if not questions:
            return []
        max_workers = min(max(1, int(concurrency or 1)), len(questions))
        answers_by_index: dict[int, AnswerData] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(
                    self._query_one_with_retries,
                    streaming_url=streaming_url,
                    seed=seed,
                    question=question,
                    question_index=index,
                    thread_id=None,
                    request_headers=request_headers,
                    seed_body_text=seed_body_text,
                    timeout_seconds=timeout_seconds,
                    retry=retry,
                    strict_answer=strict_answer,
                ): index
                for index, question in enumerate(questions, start=1)
            }
            for future in concurrent.futures.as_completed(future_map):
                index = future_map[future]
                answers_by_index[index] = future.result()
        return [answers_by_index[index] for index in range(1, len(questions) + 1)]

    def _query_one_with_retries(
        self,
        *,
        streaming_url: str,
        seed: SeedRequestRecord,
        question: str,
        question_index: int,
        thread_id: str | None,
        request_headers: dict[str, str],
        seed_body_text: str,
        timeout_seconds: int,
        retry: int,
        strict_answer: bool,
    ) -> AnswerData:
        """Fetch one question and retry invalid official placeholder answers."""
        max_attempts = max(1, int(retry or 0) + 1)
        last_answer: AnswerData | None = None
        last_reason = ""
        for attempt in range(1, max_attempts + 1):
            answer = self._query_one(
                streaming_url=streaming_url,
                seed=seed,
                question=question,
                thread_id=thread_id,
                request_headers=request_headers,
                seed_body_text=seed_body_text,
                timeout_seconds=timeout_seconds,
            )
            reason = self._answer_invalid_reason(answer, question=question, strict_answer=strict_answer)
            answer = replace(answer, is_success=not reason, error_reason=reason, attempt_count=attempt)
            if not reason:
                return answer
            last_answer = answer
            last_reason = reason
            if attempt < max_attempts:
                time.sleep(min(2 ** attempt, 10))
        if strict_answer:
            raise RufusAnswerValidationError(
                f"Rufus question {question_index} answer failed validation: {last_reason}",
                question_index=question_index,
                question=question,
                reason=last_reason,
                attempt_count=max_attempts,
            )
        return last_answer or AnswerData(text="", is_success=False, error_reason=last_reason, attempt_count=max_attempts)

    def _query_one(
        self,
        *,
        streaming_url: str,
        seed: SeedRequestRecord,
        question: str,
        thread_id: str | None,
        request_headers: dict[str, str],
        seed_body_text: str,
        timeout_seconds: int,
    ) -> AnswerData:
        """Execute one Rufus request."""
        payload = self.replay.build_payload(seed_body_text, question, thread_id, seed.asin, origin_url=seed.page_url)
        raw_text = self._post_rufus(
            url=streaming_url,
            headers=request_headers,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        return self.parser.parse(raw_text)

    def _answer_invalid_reason(self, answer: AnswerData, *, question: str = "", strict_answer: bool) -> str:
        """Classify official error/placeholder answers."""
        text = str(answer.text or "").strip()
        html = str(answer.html or "").strip()
        combined = f"{text}\n{html}".lower()
        if not text and not html:
            return "empty_answer"
        for phrase in _OFFICIAL_ERROR_PHRASES:
            if phrase in combined:
                return "official_error_placeholder"
        for phrase in _SHOPPING_SCOPE_REFUSAL_PHRASES:
            if phrase in combined:
                return "shopping_scope_refusal"
        if self._is_chinese_shopping_scope_refusal(combined):
            return "shopping_scope_refusal"
        normalized_text = " ".join(text.lower().split())
        if normalized_text in _PLACEHOLDER_PHRASES:
            return "thinking_placeholder"
        if (
            strict_answer
            and text
            and len(text) < _MIN_STRICT_TEXT_LENGTH
            and not answer.blocks
            and not answer.product_links
            and not answer.recommended_asins
        ):
            return "answer_too_short"
        if strict_answer and self._is_diagnosis_template_question(question):
            diagnosis_reason = self._diagnosis_answer_invalid_reason(text or self._html_to_text(html), question=question)
            if diagnosis_reason:
                return diagnosis_reason
        return ""

    def _is_chinese_shopping_scope_refusal(self, combined_text: str) -> bool:
        """Detect Chinese Rufus refusals without matching generic 'cannot answer' alone."""
        compact = "".join(combined_text.split())
        if not compact:
            return False
        has_context = any(phrase in compact for phrase in _CHINESE_SCOPE_REFUSAL_CONTEXT_PHRASES)
        has_action = any(phrase in compact for phrase in _CHINESE_SCOPE_REFUSAL_ACTION_PHRASES)
        return has_context and has_action

    def _diagnosis_required_section_count(self, question: str) -> int:
        """Return the requested numbered section count for Listing diagnosis prompts."""
        normalized = str(question or "")
        compact = "".join(normalized.split())
        if not (
            "按这个格式输出" in compact
            and "ASIN" in normalized.upper()
        ):
            return 0
        if all(f"{index}、" in normalized for index in range(1, 7)):
            return 6
        if all(f"{index}、" in normalized for index in range(1, 5)):
            return 4
        return 0

    def _is_diagnosis_template_question(self, question: str) -> bool:
        """Detect the default Listing diagnosis prompts that require numbered sections."""
        return self._diagnosis_required_section_count(question) > 0

    def _diagnosis_answer_invalid_reason(self, text: str, *, question: str = "") -> str:
        """Validate the default diagnosis answer shape under strict mode."""
        required_count = self._diagnosis_required_section_count(question) or 4
        sections = self._split_diagnosis_answer_sections(text)
        for index in range(1, required_count + 1):
            if index not in sections:
                return f"diagnosis_section_missing_{index}"
            if self._is_incomplete_diagnosis_section(sections[index]):
                return f"diagnosis_section_incomplete_{index}"
        return ""

    def _split_diagnosis_answer_sections(self, text: str) -> dict[int, list[str]]:
        """Split Rufus diagnosis answers by their numbered markers."""
        sections: dict[int, list[str]] = {}
        current: int | None = None
        for raw_line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = raw_line.strip()
            match = re.match(r"^(?:#{1,6}\s*)?(?:\*\*)?\s*([1-9]\d*)、\s*(.*?)(?:\*\*)?\s*$", line)
            if match:
                current = int(match.group(1))
                sections.setdefault(current, [])
                inline = self._strip_numbered_heading_body(match.group(2))
                if inline:
                    sections[current].append(inline)
                continue
            if current is not None:
                sections.setdefault(current, []).append(raw_line)
        return sections

    def _legacy_is_diagnosis_template_question(self, question: str) -> bool:
        """Compatibility shim for older tests/imports."""
        normalized = str(question or "")
        compact = "".join(normalized.split())
        return bool(
            "按这个格式输出" in compact
            and "ASIN" in normalized.upper()
            and all(f"{index}、" in normalized for index in range(1, 5))
        )

    def _strip_numbered_heading_body(self, value: str) -> str:
        """Keep useful inline content after a numbered diagnosis heading."""
        text = str(value or "").strip()
        if not text:
            return ""
        if text.endswith("**"):
            text = text[:-2].strip()
        for separator in ("：", ":"):
            if separator in text:
                left, right = text.split(separator, 1)
                if right.strip():
                    return right.strip()
                return ""
        return ""

    def _is_incomplete_diagnosis_section(self, lines: list[str]) -> bool:
        """Detect empty, placeholder, or too-thin diagnosis subsections."""
        content_lines: list[str] = []
        for raw_line in lines:
            line = str(raw_line or "").strip()
            if not line:
                continue
            if re.match(r"^-{3,}$", line):
                continue
            if re.match(r"^\|\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?$", line):
                continue
            content_lines.append(line)
        if not content_lines:
            return True
        compact = "".join(content_lines).strip().lower()
        placeholder = re.sub(r"[\s。.,，、|/\\\-_*`~：:；;（）()【】\[\]{}<>]", "", compact)
        if placeholder in {"无", "暂无", "没有", "未提供", "none", "na", "n/a"}:
            return True
        meaningful = re.sub(r"[\s|*_`>#\-:：;,，。.!！?？]", "", "".join(content_lines))
        return len(meaningful) < _MIN_DIAGNOSIS_SECTION_TEXT_LENGTH

    def _html_to_text(self, html: str) -> str:
        """Convert minimal HTML fallback content to text for validation."""
        without_tags = re.sub(r"<[^>]+>", " ", str(html or ""))
        return " ".join(without_tags.split())

    def _build_headers(self, base_headers: dict[str, str], cookie: str) -> dict[str, str]:
        """Build Rufus request headers."""
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
        """POST to Rufus streaming endpoint and collect raw SSE text."""
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
                        raise HeadlessRufusRequestError(f"Rufus request failed: {response.status_code}")
                    raw_parts: list[str] = []
                    for chunk in response.iter_text():
                        if chunk:
                            raw_parts.append(chunk)
                    return "".join(raw_parts)
        except httpx.HTTPError as exc:
            raise HeadlessRufusRequestError(f"Rufus request failed: {exc}") from exc

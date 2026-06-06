"""Rufus 业务编排服务。"""

from __future__ import annotations

import json
from typing import Any

from opscli.amazon_rufus.constants import DEFAULT_RUFUS_TIMEOUT_SECONDS
from opscli.amazon_rufus.domain.exceptions import InvalidQuestionError, InvalidRufusCookieError
from opscli.amazon_rufus.runtime.country_map import build_product_url, resolve_marketplace
from opscli.amazon_rufus.services.backend_secret import RufusBackendSecretProvider
from opscli.amazon_rufus.services.browser import BrowserAttachService
from opscli.amazon_rufus.services.browser_state_store import RufusBrowserStateStore
from opscli.amazon_rufus.services.headless_capture import HeadlessRufusCaptureService
from opscli.amazon_rufus.services.headless_client import HeadlessRufusClient
from opscli.amazon_rufus.services.question_bank import QuestionBankService
from opscli.amazon_rufus.services.replay import RufusReplayService


class RufusManager:
    """协调题库、CDP/headless 获取与输出结构。"""

    def __init__(
        self,
        *,
        question_bank: QuestionBankService | None = None,
        browser: BrowserAttachService | None = None,
        replay: RufusReplayService | None = None,
        headless_capture: HeadlessRufusCaptureService | None = None,
        headless_client: HeadlessRufusClient | None = None,
        browser_state_store: RufusBrowserStateStore | None = None,
        backend_secret_provider: RufusBackendSecretProvider | None = None,
    ) -> None:
        self.question_bank = question_bank
        self.browser = browser or BrowserAttachService()
        self.replay = replay or RufusReplayService()
        self.headless_capture = headless_capture or HeadlessRufusCaptureService()
        self.headless_client = headless_client or HeadlessRufusClient()
        self._browser_state_store = browser_state_store
        self._backend_secret_provider = backend_secret_provider

    @property
    def browser_state_store(self) -> RufusBrowserStateStore:
        """按需创建 Rufus 浏览器状态存储，避免普通流程写真实配置目录。"""
        if self._browser_state_store is None:
            self._browser_state_store = RufusBrowserStateStore()
        return self._browser_state_store

    @property
    def backend_secret_provider(self) -> RufusBackendSecretProvider:
        """按需创建 Rufus 后端请求凭证 provider。"""
        if self._backend_secret_provider is None:
            self._backend_secret_provider = RufusBackendSecretProvider(
                browser_state_store=self.browser_state_store,
            )
        return self._backend_secret_provider

    def init(
        self,
        *,
        country: str,
        cdp_url: str = "http://127.0.0.1:9222",
        timeout_seconds: int = 30,
        chrome_path: str | None = None,
        launch_if_needed: bool = True,
    ) -> dict:
        """打开对应国家站点，供用户登录 Amazon。"""
        marketplace = resolve_marketplace(country.strip().upper())
        self.browser.open_marketplace_for_login(
            marketplace_url=marketplace.base_url,
            cdp_url=cdp_url,
            timeout_seconds=timeout_seconds,
            chrome_path=chrome_path,
            launch_if_needed=launch_if_needed,
        )
        return {"country": marketplace.country, "url": marketplace.base_url}

    def save_state(
        self,
        *,
        country: str,
        cdp_url: str = "http://127.0.0.1:9222",
        timeout_seconds: int = 30,
        chrome_path: str | None = None,
        launch_if_needed: bool = False,
    ) -> dict:
        """捕获并加密保存指定国家站点的浏览器状态。"""
        marketplace = resolve_marketplace(country.strip().upper())
        storage_state = self.browser.capture_storage_state(
            marketplace_url=marketplace.base_url,
            cdp_url=cdp_url,
            timeout_seconds=timeout_seconds,
            chrome_path=chrome_path,
            launch_if_needed=launch_if_needed,
        )
        self.browser_state_store.save(
            country=marketplace.country,
            marketplace_origin=marketplace.base_url,
            storage_state=storage_state,
        )
        return {
            "country": marketplace.country,
            "saved": True,
            "cookie_count": len(storage_state.get("cookies", [])) if isinstance(storage_state, dict) else 0,
            "origin_count": len(storage_state.get("origins", [])) if isinstance(storage_state, dict) else 0,
        }

    def get(
        self,
        *,
        asin: str,
        country: str,
        question: str | None = None,
        questions: list[str] | None = None,
        skills_dir: str | None = None,
        cdp_url: str = "http://127.0.0.1:9222",
        new_chrome: bool = False,
        keep_chrome_open: bool = False,
        chrome_path: str | None = None,
        launch_if_needed: bool = False,
        timeout_seconds: int = DEFAULT_RUFUS_TIMEOUT_SECONDS,
        include_upload_payload: bool = True,
    ) -> dict:
        """通过本机 Chrome CDP 捕获 seed request，并在页面上下文内回放 Rufus。"""
        normalized_asin = asin.strip().upper()
        normalized_country = country.strip().upper()
        resolve_marketplace(normalized_country)
        resolved_questions = self._resolve_questions(
            question=question,
            questions=questions,
            skills_dir=skills_dir,
        )
        page_url = build_product_url(normalized_asin, normalized_country)
        answers: list[Any] = []

        def replay_before_browser_closes(page: Any, seed: Any) -> bool:
            replay_with_page = getattr(self.replay, "replay_with_page", None)
            if callable(replay_with_page):
                answers.extend(replay_with_page(page, seed, resolved_questions))
            return False

        seed = self.browser.capture_seed_request(
            asin=normalized_asin,
            country=normalized_country,
            page_url=page_url,
            cdp_url=cdp_url,
            timeout_seconds=timeout_seconds,
            new_chrome=new_chrome,
            keep_chrome_open=keep_chrome_open,
            chrome_path=chrome_path,
            launch_if_needed=launch_if_needed,
            on_captured=replay_before_browser_closes,
        )
        if not answers:
            answers = self.replay.replay(seed, resolved_questions)
        return self._build_result(
            asin=normalized_asin,
            country=normalized_country,
            page_url=page_url,
            questions=resolved_questions,
            answers=answers,
            seed=seed,
            include_upload_payload=include_upload_payload,
        )

    def get_headless(
        self,
        *,
        asin: str,
        country: str,
        streaming_url: str | None = None,
        cookie: str | None = None,
        storage_state: dict | None = None,
        question: str | None = None,
        questions: list[str] | None = None,
        headers: dict[str, str] | None = None,
        payload_template: dict[str, Any] | None = None,
        skills_dir: str | None = None,
        timeout_seconds: int = DEFAULT_RUFUS_TIMEOUT_SECONDS,
        include_upload_payload: bool = True,
    ) -> dict:
        """使用 headless browser 和传入 Cookie 获取 Rufus 数据。"""
        normalized_asin = asin.strip().upper()
        normalized_country = country.strip().upper()
        marketplace = resolve_marketplace(normalized_country)
        questions = self._resolve_questions(question=question, questions=questions, skills_dir=skills_dir)
        normalized_cookie = (cookie or "").strip()
        if not normalized_cookie and storage_state is not None:
            normalized_cookie = self.browser_state_store.build_cookie_header(storage_state, marketplace.base_url)
        if not normalized_cookie:
            raise InvalidRufusCookieError("cookie 不能为空")
        page_url = build_product_url(normalized_asin, normalized_country)

        seed = self.headless_capture.capture_seed_request(
            asin=normalized_asin,
            country=normalized_country,
            cookie=normalized_cookie,
            storage_state=storage_state,
            timeout_seconds=timeout_seconds,
            page_url=page_url,
            streaming_url=streaming_url,
        )
        request_url = str(streaming_url or seed.request_url).strip()
        answers = self.headless_client.query(
            streaming_url=request_url,
            seed=seed,
            questions=questions,
            cookie=normalized_cookie,
            headers=headers,
            payload_template=payload_template,
            timeout_seconds=timeout_seconds,
        )
        return self._build_result(
            asin=normalized_asin,
            country=normalized_country,
            page_url=page_url,
            questions=questions,
            answers=answers,
            seed=seed,
            include_upload_payload=include_upload_payload,
        )

    def get_backend(
        self,
        *,
        asin: str,
        country: str,
        question: str | None = None,
        questions: list[str] | None = None,
        skills_dir: str | None = None,
        timeout_seconds: int = DEFAULT_RUFUS_TIMEOUT_SECONDS,
        include_upload_payload: bool = True,
    ) -> dict:
        """使用后端请求凭证、headless 捕获和 HTTP streaming 获取 Rufus 数据。"""
        normalized_asin = asin.strip().upper()
        normalized_country = country.strip().upper()
        resolve_marketplace(normalized_country)
        questions = self._resolve_questions(question=question, questions=questions, skills_dir=skills_dir)
        secret = self.backend_secret_provider.load(country=normalized_country)
        page_url = build_product_url(normalized_asin, normalized_country)
        streaming_url = str(getattr(secret, "url", "") or "").strip() or None

        seed = self.headless_capture.capture_seed_request(
            asin=normalized_asin,
            country=normalized_country,
            cookie=str(getattr(secret, "cookies", "") or ""),
            storage_state=getattr(secret, "storage_state", None),
            timeout_seconds=timeout_seconds,
            page_url=page_url,
            streaming_url=streaming_url,
        )
        request_url = streaming_url or seed.request_url
        answers = self.headless_client.query(
            streaming_url=request_url,
            seed=seed,
            questions=questions,
            cookie=str(getattr(secret, "cookies", "") or ""),
            headers=getattr(secret, "headers", None),
            payload_template=getattr(secret, "payload_template", None),
            timeout_seconds=timeout_seconds,
        )
        return self._build_result(
            asin=normalized_asin,
            country=normalized_country,
            page_url=page_url,
            questions=questions,
            answers=answers,
            seed=seed,
            include_upload_payload=include_upload_payload,
        )

    def _resolve_questions(
        self,
        *,
        question: str | None,
        questions: list[str] | None,
        skills_dir: str | None,
    ) -> list[str]:
        """根据临时问题参数或本地题库生成本次 Rufus 问题列表。"""
        explicit_questions = questions or None
        if question is not None and explicit_questions is not None:
            raise InvalidQuestionError("question 和 questions 不能同时传入")
        if explicit_questions is not None:
            normalized_questions = [item.strip() for item in explicit_questions]
            if any(not item for item in normalized_questions):
                raise InvalidQuestionError("question 不能为空")
            return normalized_questions
        if question is not None:
            normalized_question = question.strip()
            if not normalized_question:
                raise InvalidQuestionError("question 不能为空")
            return [normalized_question]
        bank = self.question_bank or QuestionBankService(skills_dir=skills_dir)
        templates = bank.load_templates()
        return [item.text for template in templates for item in template.questions if item.text]

    def _build_result(
        self,
        *,
        asin: str,
        country: str,
        page_url: str,
        questions: list[str],
        answers: list[Any],
        seed: Any,
        include_upload_payload: bool,
    ) -> dict:
        """组装各条获取链路统一返回结构。"""
        data = {
            "asin": asin,
            "country": country,
            "page_url": page_url,
            "question_count": len(questions),
            "questions": questions,
            "answers": [answer.to_dict() for answer in answers],
            "seed_request": seed.to_dict(),
        }
        if include_upload_payload:
            data["upload_payload"] = self.build_upload_payload(
                asin=asin,
                country=country,
                request_url=seed.request_url,
                request_body=self._safe_json(seed.request_body),
                page_url=seed.page_url,
                tab_id=seed.tab_id,
                questions=questions,
                captured_at=seed.captured_at,
            )
        return data

    def build_upload_payload(
        self,
        *,
        asin: str,
        country: str,
        request_url: str,
        request_body: dict,
        page_url: str,
        tab_id: str,
        questions: list[str],
        captured_at: int,
    ) -> dict:
        """构造一期只输出不发送的上传 payload。"""
        normalized_asin = asin.strip().upper()
        return {
            "records": [
                {
                    "configId": "opscli-amazon-rufus",
                    "requestUrl": request_url,
                    "requestMethod": "POST",
                    "requestBody": json.dumps(
                        {
                            "asin": normalized_asin,
                            "country": country.strip().upper(),
                            "seed": request_body,
                            "source": "opscli_rufus_cli",
                        },
                        ensure_ascii=False,
                    ),
                    "pageUrl": page_url,
                    "country": country.strip().upper(),
                    "tabId": tab_id,
                    "capturedAt": captured_at,
                    "asin": normalized_asin,
                    "businessType": "asin_rufus_cli",
                    "questions": [
                        {"question": question, "capturedAt": captured_at}
                        for question in questions
                    ],
                }
            ]
        }

    def _safe_json(self, value: str) -> dict:
        """安全解析 JSON 字符串。"""
        try:
            parsed = json.loads(value or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}



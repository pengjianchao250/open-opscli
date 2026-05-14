"""Rufus 业务编排服务。"""

from __future__ import annotations

import json

from opscli.amazon_rufus.domain.exceptions import InvalidQuestionError
from opscli.amazon_rufus.domain.models import AnswerData
from opscli.amazon_rufus.runtime.country_map import build_product_url, resolve_marketplace
from opscli.amazon_rufus.services.browser import BrowserAttachService
from opscli.amazon_rufus.services.question_bank import QuestionBankService
from opscli.amazon_rufus.services.replay import RufusReplayService


class RufusManager:
    """协调题库、浏览器、重放与输出结构。"""

    def __init__(
        self,
        *,
        question_bank: QuestionBankService | None = None,
        browser: BrowserAttachService | None = None,
        replay: RufusReplayService | None = None,
    ) -> None:
        self.question_bank = question_bank
        self.browser = browser or BrowserAttachService()
        self.replay = replay or RufusReplayService()

    def init(
        self,
        *,
        country: str,
        cdp_url: str = "http://127.0.0.1:9222",
        timeout_seconds: int = 30,
    ) -> dict:
        """打开对应国家站点，供用户登录 Amazon。"""
        marketplace = resolve_marketplace(country)
        self.browser.open_marketplace_for_login(
            marketplace_url=marketplace.base_url,
            cdp_url=cdp_url,
            timeout_seconds=timeout_seconds,
        )
        return {"country": marketplace.country, "url": marketplace.base_url}

    def get(
        self,
        *,
        asin: str,
        country: str,
        question: str | None = None,
        skills_dir: str | None = None,
        cdp_url: str = "http://127.0.0.1:9222",
        new_chrome: bool = False,
        keep_chrome_open: bool = False,
        chrome_path: str | None = None,
        launch_if_needed: bool = False,
        timeout_seconds: int = 90,
        include_upload_payload: bool = True,
    ) -> dict:
        """执行 Rufus 获取链路。"""
        normalized_asin = asin.strip().upper()
        normalized_country = country.strip().upper()
        resolve_marketplace(normalized_country)
        questions = self._resolve_questions(question=question, skills_dir=skills_dir)
        page_url = build_product_url(normalized_asin, normalized_country)
        answers: list[AnswerData] = []

        def replay_before_browser_closes(page, seed) -> None:
            # Playwright 页面只能在 sync_playwright 上下文关闭前使用。
            if hasattr(self.replay, "replay_with_page"):
                answers.extend(self.replay.replay_with_page(page, seed, questions))

        seed = self.browser.capture_seed_request(
            asin=normalized_asin,
            country=normalized_country,
            page_url=page_url,
            cdp_url=cdp_url,
            new_chrome=new_chrome,
            keep_chrome_open=keep_chrome_open,
            timeout_seconds=timeout_seconds,
            on_captured=replay_before_browser_closes,
        )
        if not answers:
            answers = self.replay.replay(seed, questions)
        data = {
            "asin": normalized_asin,
            "country": normalized_country,
            "page_url": page_url,
            "question_count": len(questions),
            "questions": questions,
            "answers": [answer.to_dict() for answer in answers],
            "seed_request": seed.to_dict(),
        }
        if include_upload_payload:
            data["upload_payload"] = self.build_upload_payload(
                asin=normalized_asin,
                country=normalized_country,
                request_url=seed.request_url,
                request_body=self._safe_json(seed.request_body),
                page_url=seed.page_url,
                tab_id=seed.tab_id,
                questions=questions,
                captured_at=seed.captured_at,
            )
        return data

    def _resolve_questions(self, *, question: str | None, skills_dir: str | None) -> list[str]:
        """根据单题参数或本地题库生成本次 Rufus 问题列表。"""
        if question is not None:
            normalized_question = question.strip()
            if not normalized_question:
                raise InvalidQuestionError("question 不能为空")
            return [normalized_question]
        bank = self.question_bank or QuestionBankService(skills_dir=skills_dir)
        templates = bank.load_templates()
        return [item.text for template in templates for item in template.questions if item.text]

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



"""卖家精灵 Playwright 采集器。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from opscli.config import CONFIG_DIR
from opscli.seller_sprite.domain.exceptions import (
    SellerSpriteCaptchaRequiredError,
    SellerSpriteDependencyError,
    SellerSpriteLoginRequiredError,
)
from opscli.seller_sprite.domain.models import SellerSpriteCollectOptions
from opscli.seller_sprite.scraping.api_recorder import SellerSpriteApiRecorder
from opscli.seller_sprite.scraping.archiver import SellerSpriteArchiver
from opscli.seller_sprite.scraping.captcha import SellerSpriteCaptchaDetector


class SellerSpriteScraper:
    """基于 Playwright 的卖家精灵采集器。"""

    KEYWORD_MINING_URL = "https://www.sellersprite.com/v3/keyword-miner"
    KEYWORD_REVERSE_URL = "https://www.sellersprite.com/v3/keyword-reverse"
    LOGIN_URL = "https://www.sellersprite.com/w/user/login?callback=/v3/keyword-miner"
    DEFAULT_TIMEOUT_MS = 120000
    DEFAULT_WAIT_MS = 3000
    SITE_LABELS = {
        "us": "美国站",
        "jp": "日本站",
        "uk": "英国站",
        "de": "德国站",
        "fr": "法国站",
        "it": "意大利站",
        "es": "西班牙站",
        "ca": "加拿大站",
        "mx": "墨西哥站",
    }
    PERIOD_LABELS = {
        "30d": "最近30天",
    }
    TREND_TABS = {
        "search": "搜索趋势",
        "google": "Google Trends",
        "aba": "ABA集中度",
        "ppc": "PPC竞价",
        "market": "市场分析",
    }
    TREND_ARCHIVE_SELECTOR = "#search-anlysis-drawer-echarts-trends"

    def __init__(self, *, headless: bool = False, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.profile_dir = CONFIG_DIR / "seller_sprite" / "browser_profile"
        self.captcha_detector = SellerSpriteCaptchaDetector()

    def collect(
        self,
        *,
        options: SellerSpriteCollectOptions,
        run_id: str,
        run_dir: Path,
        account: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """同步执行完整采集。"""
        return asyncio.run(self.collect_async(options=options, run_id=run_id, run_dir=run_dir, account=account))

    def collect_frequency(self, *, options: SellerSpriteCollectOptions, run_id: str, run_dir: Path) -> dict[str, Any]:
        """同步执行高频词采集。"""
        return asyncio.run(self.collect_frequency_async(options=options, run_id=run_id, run_dir=run_dir))

    def collect_keyword_mining(self, *, options: SellerSpriteCollectOptions, run_id: str, run_dir: Path) -> dict[str, Any]:
        """同步执行关键词挖掘采集。"""
        return asyncio.run(self.collect_keyword_mining_async(options=options, run_id=run_id, run_dir=run_dir))

    def collect_keyword_reverse(
        self,
        *,
        options: SellerSpriteCollectOptions,
        run_id: str,
        run_dir: Path,
        account: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """同步执行关键词反查采集。"""
        return asyncio.run(
            self.collect_keyword_reverse_async(options=options, run_id=run_id, run_dir=run_dir, account=account)
        )

    def archive_url(self, *, options: SellerSpriteCollectOptions, run_id: str, run_dir: Path) -> dict[str, Any]:
        """同步归档指定 URL。"""
        return asyncio.run(self.archive_url_async(options=options, run_id=run_id, run_dir=run_dir))

    def login(self) -> dict[str, Any]:
        """同步打开登录页并等待用户完成登录。"""
        return asyncio.run(self.login_async())

    def login_status(self, *, options: SellerSpriteCollectOptions, run_id: str, run_dir: Path) -> dict[str, Any]:
        """同步检查当前浏览器 profile 登录状态。"""
        return asyncio.run(self.login_status_async(options=options, run_id=run_id, run_dir=run_dir))

    async def collect_async(
        self,
        *,
        options: SellerSpriteCollectOptions,
        run_id: str,
        run_dir: Path,
        account: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """完整采集高频词与关键词挖掘数据。"""
        async with self._browser_page() as page:
            return await self._collect_all_sections_with_page(
                page,
                options=options,
                run_dir=run_dir,
                account=account,
            )

    async def collect_frequency_async(self, *, options: SellerSpriteCollectOptions, run_id: str, run_dir: Path) -> dict[str, Any]:
        """采集高频词接口响应。"""
        return await self._collect_section(
            options=options,
            run_dir=run_dir,
            section="frequency",
            response_url_keyword="frequency",
        )

    async def collect_keyword_mining_async(self, *, options: SellerSpriteCollectOptions, run_id: str, run_dir: Path) -> dict[str, Any]:
        """采集关键词挖掘接口响应。"""
        return await self._collect_section(
            options=options,
            run_dir=run_dir,
            section="keyword_mining",
            response_url_keyword="keyword",
        )

    async def collect_keyword_reverse_async(
        self,
        *,
        options: SellerSpriteCollectOptions,
        run_id: str,
        run_dir: Path,
        account: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """采集关键词反查接口响应。"""
        async with self._browser_page() as page:
            return await self._collect_keyword_reverse_with_page(
                page,
                options=options,
                run_dir=run_dir,
                account=account,
            )

    async def archive_url_async(self, *, options: SellerSpriteCollectOptions, run_id: str, run_dir: Path) -> dict[str, Any]:
        """打开并归档指定 URL。"""
        async with self._browser_page() as page:
            archiver = SellerSpriteArchiver(run_dir)
            await page.goto(options.url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await page.wait_for_timeout(self.DEFAULT_WAIT_MS)
            captcha_required = await self.captcha_detector.detect(page)
            files = await archiver.archive_page(page, section="archive")
            return {
                "files": files,
                "captcha_required": captcha_required,
                "missing_sections": [],
                "errors": [],
            }

    async def login_async(self) -> dict[str, Any]:
        """打开登录页，用户手动登录后回车保存登录态。"""
        async with self._browser_page() as page:
            await page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await page.wait_for_timeout(self.DEFAULT_WAIT_MS)
            await asyncio.to_thread(input, "请在打开的浏览器中完成卖家精灵登录，完成后回到终端按回车继续...")
            await page.goto(self.KEYWORD_MINING_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await page.wait_for_timeout(self.DEFAULT_WAIT_MS)
            return {
                "profile_dir": str(self.profile_dir),
                "current_url": page.url,
                "logged_in": await self._detect_logged_in(page),
            }

    async def login_status_async(self, *, options: SellerSpriteCollectOptions, run_id: str, run_dir: Path) -> dict[str, Any]:
        """检查当前浏览器 profile 是否已有卖家精灵登录态。"""
        async with self._browser_page() as page:
            archiver = SellerSpriteArchiver(run_dir)
            await page.goto(self.KEYWORD_MINING_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await page.wait_for_timeout(self.DEFAULT_WAIT_MS)
            captcha_required = await self.captcha_detector.detect(page)
            files = await archiver.archive_page(page, section="login_status")
            return {
                "profile_dir": str(self.profile_dir),
                "current_url": page.url,
                "logged_in": await self._detect_logged_in(page),
                "files": files,
                "captcha_required": captcha_required,
            }

    async def _collect_section(
        self,
        *,
        options: SellerSpriteCollectOptions,
        run_dir: Path,
        section: str,
        response_url_keyword: str,
    ) -> dict[str, Any]:
        """打开关键词挖掘页并捕获指定分区接口响应。"""
        async with self._browser_page() as page:
            return await self._collect_section_with_page(
                page,
                options=options,
                run_dir=run_dir,
                section=section,
                response_url_keyword=response_url_keyword,
            )

    async def _collect_section_with_page(
        self,
        page,
        *,
        options: SellerSpriteCollectOptions,
        run_dir: Path,
        section: str,
        response_url_keyword: str,
    ) -> dict[str, Any]:
        """使用已有页面采集指定分区。"""
        recorder = SellerSpriteApiRecorder()
        archiver = SellerSpriteArchiver(run_dir)

        async def _capture(response):
            await recorder.capture_json_response(
                response,
                section=section,
                url_keyword=response_url_keyword,
            )

        page.on("response", _capture)
        await page.goto(self.KEYWORD_MINING_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
        await page.wait_for_timeout(self.DEFAULT_WAIT_MS)
        captcha_required = await self.captcha_detector.detect(page)
        logged_in = await self._detect_logged_in(page)
        if captcha_required or not logged_in:
            page.remove_listener("response", _capture)
            files = await archiver.archive_page(page, section=section)
            error = (
                {"code": SellerSpriteCaptchaRequiredError.code, "message": "页面出现验证码"}
                if captcha_required
                else {"code": SellerSpriteLoginRequiredError.code, "message": "卖家精灵未登录，请先执行 `opscli seller-sprite login`"}
            )
            return {
                section: None,
                "files": files,
                "captcha_required": captcha_required,
                "missing_sections": [section],
                "errors": [error],
            }
        await self._fill_keyword_form(page, options)
        if section == "frequency":
            await self._set_frequency_phrase_count(page, options.frequency_phrase_count)
        await self._wait_for_payloads(recorder, [section])
        await page.wait_for_timeout(1000)
        page.remove_listener("response", _capture)
        files = await archiver.archive_page(page, section=section)
        files.update(recorder.save_all(run_dir / section))
        trend_details: list[dict[str, Any]] = []
        if section == "keyword_mining" and options.trend_limit:
            trend_result = await self._collect_trend_details(
                page,
                options=options,
                run_dir=run_dir,
                keywords=self._keywords_from_payload(recorder.get_payload(section)),
            )
            trend_details = trend_result["trend_details"]
            files.update(trend_result["files"])
        payload = recorder.get_payload(section)
        return {
            section: payload,
            "trend_details": trend_details,
            "files": files,
            "captcha_required": False,
            "missing_sections": [] if payload else [section],
            "errors": [] if payload else [{"code": "SELLER_SPRITE_RESPONSE_MISSING", "message": f"{section} 响应未捕获"}],
        }

    async def _collect_all_sections_with_page(
        self,
        page,
        *,
        options: SellerSpriteCollectOptions,
        run_dir: Path,
        account: dict[str, str] | None,
    ) -> dict[str, Any]:
        """一次查询同时采集高频词与关键词挖掘结果。"""
        recorder = SellerSpriteApiRecorder()
        archiver = SellerSpriteArchiver(run_dir)

        async def _capture(response):
            await recorder.capture_json_response(response, section="frequency", url_keyword="frequency")
            await recorder.capture_json_response(response, section="keyword_mining", url_keyword="keyword")

        page.on("response", _capture)
        await page.goto(self.KEYWORD_MINING_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
        await page.wait_for_timeout(self.DEFAULT_WAIT_MS)

        captcha_required = await self.captcha_detector.detect(page)
        logged_in = await self._detect_logged_in(page)
        if not captcha_required and not logged_in and account:
            await self._login_with_account(page, account)
            await page.goto(self.KEYWORD_MINING_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await page.wait_for_timeout(self.DEFAULT_WAIT_MS)
            captcha_required = await self.captcha_detector.detect(page)
            logged_in = await self._detect_logged_in(page)
        if captcha_required or not logged_in:
            page.remove_listener("response", _capture)
            files = await archiver.archive_page(page, section="collect")
            error = (
                {"code": SellerSpriteCaptchaRequiredError.code, "message": "页面出现验证码"}
                if captcha_required
                else {"code": SellerSpriteLoginRequiredError.code, "message": "卖家精灵未登录，请先执行 `opscli seller-sprite login`"}
            )
            return {
                "frequency": None,
                "keyword_mining": None,
                "files": files,
                "captcha_required": captcha_required,
                "missing_sections": ["frequency", "keyword_mining"],
                "errors": [error],
            }

        await self._fill_keyword_form(page, options)
        await self._set_frequency_phrase_count(page, options.frequency_phrase_count)
        await self._wait_for_payloads(recorder, ["frequency", "keyword_mining"])
        await page.wait_for_timeout(1000)
        page.remove_listener("response", _capture)

        files = await archiver.archive_page(page, section="collect")
        files.update(recorder.save_all(run_dir / "collect"))
        trend_details: list[dict[str, Any]] = []
        if options.trend_limit:
            trend_result = await self._collect_trend_details(
                page,
                options=options,
                run_dir=run_dir,
                keywords=self._keywords_from_payload(recorder.get_payload("keyword_mining")),
            )
            trend_details = trend_result["trend_details"]
            files.update(trend_result["files"])
        frequency = recorder.get_payload("frequency")
        keyword_mining = recorder.get_payload("keyword_mining")
        missing_sections = []
        if not frequency:
            missing_sections.append("frequency")
        if not keyword_mining:
            missing_sections.append("keyword_mining")
        return {
            "frequency": frequency,
            "keyword_mining": keyword_mining,
            "trend_details": trend_details,
            "files": files,
            "captcha_required": False,
            "missing_sections": missing_sections,
            "errors": [
                {"code": "SELLER_SPRITE_RESPONSE_MISSING", "message": f"{section} 响应未捕获"}
                for section in missing_sections
            ],
        }

    async def _collect_keyword_reverse_with_page(
        self,
        page,
        *,
        options: SellerSpriteCollectOptions,
        run_dir: Path,
        account: dict[str, str] | None,
    ) -> dict[str, Any]:
        """采集关键词反查页面数据。"""
        recorder = SellerSpriteApiRecorder()
        archiver = SellerSpriteArchiver(run_dir)

        async def _capture(response):
            await recorder.capture_json_response(response, section="reverse_monthly", url_keyword="relation/ta/monthly")
            await recorder.capture_json_response(response, section="reverse_stats", url_keyword="relation/stat-keywords")
            await recorder.capture_json_response(response, section="keyword_reverse", url_keyword="relation/reversing")
            await recorder.capture_json_response(
                response,
                section="reverse_frequency",
                url_keyword="high-frequency-words-new",
            )

        page.on("response", _capture)
        await page.goto(self.KEYWORD_REVERSE_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
        await page.wait_for_timeout(self.DEFAULT_WAIT_MS)

        captcha_required = await self.captcha_detector.detect(page)
        logged_in = await self._detect_logged_in(page)
        if not captcha_required and not logged_in and account:
            await self._login_with_account(page, account)
            await page.goto(self.KEYWORD_REVERSE_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await page.wait_for_timeout(self.DEFAULT_WAIT_MS)
            captcha_required = await self.captcha_detector.detect(page)
            logged_in = await self._detect_logged_in(page)
        if captcha_required or not logged_in:
            page.remove_listener("response", _capture)
            files = await archiver.archive_page(page, section="keyword_reverse")
            error = (
                {"code": SellerSpriteCaptchaRequiredError.code, "message": "页面出现验证码"}
                if captcha_required
                else {"code": SellerSpriteLoginRequiredError.code, "message": "卖家精灵未登录，请先执行 `opscli seller-sprite login`"}
            )
            return {
                "keyword_reverse": None,
                "reverse_frequency": None,
                "reverse_monthly": None,
                "reverse_stats": None,
                "files": files,
                "captcha_required": captcha_required,
                "missing_sections": ["keyword_reverse", "reverse_frequency"],
                "errors": [error],
            }

        await self._fill_keyword_reverse_form(page, options)
        await self._wait_for_payloads(recorder, ["keyword_reverse", "reverse_frequency"], timeout_ms=10000)
        await page.wait_for_timeout(1000)
        page.remove_listener("response", _capture)

        files = await archiver.archive_page(page, section="keyword_reverse")
        files.update(recorder.save_all(run_dir / "keyword_reverse"))
        trend_details: list[dict[str, Any]] = []
        if options.trend_limit:
            trend_result = await self._collect_trend_details(
                page,
                options=options,
                run_dir=run_dir,
                keywords=self._keywords_from_payload(recorder.get_payload("keyword_reverse")),
            )
            trend_details = trend_result["trend_details"]
            files.update(trend_result["files"])

        required_sections = ["keyword_reverse", "reverse_frequency"]
        missing_sections = [section for section in required_sections if not recorder.get_payload(section)]
        return {
            "keyword_reverse": recorder.get_payload("keyword_reverse"),
            "reverse_frequency": recorder.get_payload("reverse_frequency"),
            "reverse_monthly": recorder.get_payload("reverse_monthly"),
            "reverse_stats": recorder.get_payload("reverse_stats"),
            "trend_details": trend_details,
            "files": files,
            "captcha_required": False,
            "missing_sections": missing_sections,
            "errors": [
                {"code": "SELLER_SPRITE_RESPONSE_MISSING", "message": f"{section} 响应未捕获"}
                for section in missing_sections
            ],
        }

    async def _fill_keyword_form(self, page, options: SellerSpriteCollectOptions) -> None:
        """填写关键词查询表单并触发查询。"""
        await self._select_site(page, options.site)
        await self._select_period(page, options.period)
        if options.keyword:
            await page.locator("input[placeholder*='输入关键词']").first.fill(options.keyword)
        await page.locator("button:has-text('立即查询')").first.click()

    async def _fill_keyword_reverse_form(self, page, options: SellerSpriteCollectOptions) -> None:
        """填写关键词反查表单并触发查询。"""
        await self._select_site(page, options.site)
        await self._select_period(page, options.period)
        await page.locator("input[placeholder*='ASIN'], input[placeholder*='产品链接']").first.fill(options.asin or "")
        await page.locator("button:has-text('立即查询')").first.click()

    async def _select_site(self, page, site: str) -> None:
        """按站点代码切换卖家精灵站点下拉。"""
        target_label = self.SITE_LABELS.get(site.lower(), site)
        await self._select_dropdown_by_text(page, list(self.SITE_LABELS.values()), target_label)

    async def _select_period(self, page, period: str) -> None:
        """按时间窗口切换卖家精灵时间下拉。"""
        target_label = self.PERIOD_LABELS.get(period.lower(), period)
        month_labels = [f"{year}-{month:02d}" for year in range(2020, 2031) for month in range(1, 13)]
        await self._select_dropdown_by_text(page, ["最近30天", *month_labels], target_label)

    async def _select_dropdown_by_text(self, page, current_labels: list[str], target_label: str) -> None:
        """通过已选中文案打开下拉并点击目标文案。"""
        if await page.get_by_text(target_label, exact=True).first.is_visible(timeout=500):
            return
        trigger = None
        for label in current_labels:
            locator = page.get_by_text(label, exact=True).first
            if await locator.is_visible(timeout=500):
                trigger = locator
                break
        if trigger is None:
            return
        await trigger.click()
        option = page.locator(".el-select-dropdown__item:visible").filter(has_text=target_label).last
        await option.click(timeout=10000)
        await page.wait_for_timeout(500)

    async def _set_frequency_phrase_count(self, page, phrase_count: int) -> None:
        """切换高频词词组个数。"""
        if phrase_count == 1:
            await page.locator("label.el-radio:has-text('一个词')").first.click(timeout=5000)
        elif phrase_count == 2:
            await page.locator("label.el-radio:has-text('两个词')").first.click(timeout=5000)
        else:
            await page.locator("label.el-radio:has(input[value='custom'])").first.click(timeout=5000)
            await page.locator(".el-input-number input").first.fill(str(phrase_count))
        await page.wait_for_timeout(1000)

    async def _collect_trend_details(
        self,
        page,
        *,
        options: SellerSpriteCollectOptions,
        run_dir: Path,
        keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        """点击关键词历史走势图标并归档各子 tab。"""
        archiver = SellerSpriteArchiver(run_dir)
        files: dict[str, str] = {}
        trend_details: list[dict[str, Any]] = []
        tab_items = self._selected_trend_tabs(options.trend_tabs)
        keyword_candidates = keywords or []
        icons = page.locator(".icon-historical-trend:visible")
        icon_count = min(options.trend_limit, await icons.count())
        for index in range(icon_count):
            icon = icons.nth(index)
            keyword = (
                keyword_candidates[index]
                if index < len(keyword_candidates)
                else await self._keyword_from_trend_icon(icon, index)
            )
            open_responses: list[dict[str, Any]] = []

            async def _capture_open(response):
                await self._capture_sellersprite_json(response, open_responses)

            page.on("response", _capture_open)
            await icon.scroll_into_view_if_needed(timeout=10000)
            await icon.click()
            await page.wait_for_timeout(1500)
            page.remove_listener("response", _capture_open)
            keyword_tabs = []
            for tab_index, (tab_key, tab_label) in enumerate(tab_items):
                responses: list[dict[str, Any]] = list(open_responses) if tab_index == 0 else []

                async def _capture(response):
                    await self._capture_sellersprite_json(response, responses)

                page.on("response", _capture)
                await page.locator(".el-tabs__item:visible").filter(has_text=tab_label).first.click(timeout=10000)
                await page.wait_for_timeout(2000)
                page.remove_listener("response", _capture)
                section = f"trend_{index + 1:02d}_{self._slug(keyword)}_{tab_key}"
                trend_container = page.locator(self.TREND_ARCHIVE_SELECTOR).first
                files.update(await archiver.archive_locator(trend_container, section=section))
                response_path = archiver.save_json(
                    section=section,
                    filename="responses.json",
                    payload={"keyword": keyword, "tab": tab_label, "responses": responses},
                )
                files[f"{section}_responses"] = response_path
                keyword_tabs.append(
                    {
                        "tab": tab_label,
                        "section": section,
                        "response_count": len(responses),
                        "response_path": response_path,
                    }
                )
            trend_details.append({"keyword": keyword, "tabs": keyword_tabs})
            drawer = page.locator(self.TREND_ARCHIVE_SELECTOR).first
            await drawer.locator(".close-btn").first.click(timeout=10000)
            await drawer.wait_for(state="hidden", timeout=10000)
        return {"trend_details": trend_details, "files": files}

    def _keywords_from_payload(self, payload: Any) -> list[str]:
        """从关键词列表接口结果提取表格顺序关键词。"""
        if not isinstance(payload, dict):
            return []
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            return []
        keywords = []
        for item in data["items"]:
            if not isinstance(item, dict):
                continue
            keyword = item.get("keyword") or item.get("keywords")
            if keyword:
                keywords.append(str(keyword))
        return keywords

    def _selected_trend_tabs(self, trend_tabs: str) -> list[tuple[str, str]]:
        """解析历史走势 tab 参数。"""
        if trend_tabs == "all":
            return list(self.TREND_TABS.items())
        selected = []
        for item in trend_tabs.split(","):
            key = item.strip()
            if key in self.TREND_TABS:
                selected.append((key, self.TREND_TABS[key]))
        return selected or list(self.TREND_TABS.items())

    async def _capture_sellersprite_json(self, response, responses: list[dict[str, Any]]) -> None:
        """保存一次 tab 切换期间的卖家精灵 JSON 响应。"""
        if "sellersprite.com" not in response.url.lower():
            return
        try:
            payload = await response.json()
        except Exception:
            return
        responses.append({"url": response.url, "status": response.status, "payload": payload})

    async def _keyword_from_trend_icon(self, icon, index: int) -> str:
        """从历史走势图标所在行提取关键词。"""
        try:
            row_text = await icon.locator("xpath=ancestor::tr[1]").inner_text(timeout=3000)
        except Exception:
            return f"keyword_{index + 1}"
        for line in row_text.splitlines():
            value = line.strip()
            if value and not value.isdigit() and value not in {"AC"}:
                return value
        return f"keyword_{index + 1}"

    def _slug(self, value: str) -> str:
        """生成文件路径友好的短标识。"""
        slug = "".join(char.lower() if char.isalnum() else "_" for char in value)
        slug = "_".join(part for part in slug.split("_") if part)
        return (slug or "keyword")[:40]

    async def _login_with_account(self, page, account: dict[str, str]) -> None:
        """使用命名账号在当前浏览器窗口登录。"""
        await page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
        await page.wait_for_timeout(self.DEFAULT_WAIT_MS)
        if await self._detect_logged_in(page):
            return
        await self._fill_login_form(page, account)
        await page.wait_for_timeout(self.DEFAULT_WAIT_MS)
        if await self.captcha_detector.detect(page) or not await self._detect_logged_in(page):
            await asyncio.to_thread(
                input,
                "已自动填写卖家精灵账号密码。如页面需要验证码或二次确认，请在浏览器中完成后回到终端按回车继续...",
            )

    async def _fill_login_form(self, page, account: dict[str, str]) -> None:
        """填写卖家精灵登录表单。"""
        username = account.get("username") or ""
        password = account.get("password") or ""
        password_input = page.locator("input[type='password']:visible").first
        await password_input.wait_for(state="visible", timeout=10000)
        username_input = page.locator(
            "input[placeholder*='手机号']:visible:not([readonly]):not([disabled]), "
            "input[placeholder*='邮箱']:visible:not([readonly]):not([disabled]), "
            "input[placeholder*='账号']:visible:not([readonly]):not([disabled]), "
            "input[placeholder*='用户名']:visible:not([readonly]):not([disabled]), "
            "input[type='email']:visible:not([readonly]):not([disabled]), "
            "input[type='text']:visible:not([readonly]):not([disabled])"
        ).first
        await username_input.fill(username)
        await password_input.fill(password)
        login_button = page.locator(
            "button:visible:has-text('登录'), button:visible:has-text('登 录'), button:visible:has-text('立即登录')"
        ).first
        await login_button.click()

    async def _detect_logged_in(self, page) -> bool:
        """根据页面文案和 URL 粗略判断是否登录。"""
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await page.wait_for_timeout(1000)
        if "/w/user/login" in page.url:
            return False
        if await self._has_visible_text(page, "未登录") or await self._has_visible_text(page, "游客"):
            return False
        return True

    async def _has_visible_text(self, page, text: str) -> bool:
        """检查页面是否存在可见文本。"""
        locator = page.get_by_text(text).first
        try:
            return await locator.is_visible(timeout=1000)
        except Exception:
            return False

    async def _wait_for_payloads(
        self,
        recorder: SellerSpriteApiRecorder,
        sections: list[str],
        *,
        timeout_ms: int | None = None,
    ) -> None:
        """等待目标接口响应到达。"""
        deadline = asyncio.get_running_loop().time() + (timeout_ms or self.DEFAULT_WAIT_MS) / 1000
        while asyncio.get_running_loop().time() < deadline:
            if all(recorder.get_payload(section) for section in sections):
                return
            await asyncio.sleep(0.2)

    def _load_playwright(self):
        """延迟导入 Playwright，避免未安装时影响其他模块。"""
        try:
            from playwright.async_api import async_playwright
        except ModuleNotFoundError as exc:
            raise SellerSpriteDependencyError(
                "缺少 playwright 依赖，请安装 `pip install opscli` 并执行 `python -m playwright install chromium --no-shell`"
            ) from exc
        return async_playwright

    def _browser_page(self):
        """创建持久化浏览器上下文。"""
        async_playwright = self._load_playwright()

        class _PageContext:
            def __init__(self, outer: SellerSpriteScraper):
                self.outer = outer
                self.playwright = None
                self.context = None
                self.page = None

            async def __aenter__(self):
                self.playwright = await async_playwright().start()
                self.outer.profile_dir.mkdir(parents=True, exist_ok=True)
                self.context = await self.playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.outer.profile_dir),
                    headless=self.outer.headless,
                    channel="chromium",
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
                )
                self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
                return self.page

            async def __aexit__(self, exc_type, exc, tb):
                if self.context is not None:
                    await self.context.close()
                if self.playwright is not None:
                    await self.playwright.stop()

        return _PageContext(self)

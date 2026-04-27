"""amazon 模块抓取器。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from urllib.parse import quote_plus

from opscli.amazon.domain.exceptions import InvalidAsinError, ScraperDependencyError
from opscli.amazon.domain.models import AmazonProductSnapshot, AmazonSearchResult
from opscli.amazon.scraping.parser import normalize_text, parse_price, parse_rating, parse_review_count


class AmazonScraper:
    """基于 Playwright 的 Amazon 抓取器。"""

    PRODUCT_URL_TEMPLATE = "https://www.amazon.com/dp/{asin}"
    SEARCH_URL_TEMPLATE = "https://www.amazon.com/s?k={keyword}&s=review-rank"
    DEFAULT_TIMEOUT_MS = 120000
    DEFAULT_WAIT_MS = 3000

    def __init__(self, *, headless: bool = True, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms

    def scrape_product(self, asin: str, zip_code: str = "10001") -> AmazonProductSnapshot:
        """同步抓取单个商品。"""
        return asyncio.run(self.scrape_product_async(asin, zip_code))

    def search_products(
        self,
        keyword: str,
        *,
        max_results: int = 10,
        zip_code: str = "10001",
    ) -> list[AmazonSearchResult]:
        """同步抓取搜索结果。"""
        return asyncio.run(self.search_products_async(keyword, max_results=max_results, zip_code=zip_code))

    async def scrape_product_async(self, asin: str, zip_code: str = "10001") -> AmazonProductSnapshot:
        """异步抓取单个商品。"""
        self._validate_asin(asin)
        async with self._browser_page() as page:
            page_url = self.PRODUCT_URL_TEMPLATE.format(asin=asin)
            await page.goto(page_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await page.wait_for_timeout(self.DEFAULT_WAIT_MS)
            # 处理 Amazon 的中间验证页（"Click the button below to continue shopping"）
            await self._bypass_continue_shopping(page)
            await self._apply_zip_code(page, zip_code)

            page_title = await page.title()
            invalid_reason = self._get_invalid_reason(page_title)
            if invalid_reason:
                return AmazonProductSnapshot(
                    asin=asin,
                    zip_code=zip_code,
                    marketplace="amazon.com",
                    page_url=page_url,
                    page_title=page_title,
                    product_name="",
                    price_text="",
                    price_amount=None,
                    currency=None,
                    rating_text="",
                    rating_value=None,
                    review_count_text="",
                    review_count_value=None,
                    location="",
                    collected_at=self._now(),
                    valid=False,
                    error=invalid_reason,
                )

            # 等待商品标题元素出现，确认页面真实加载（最多等 8 秒）
            try:
                await page.wait_for_selector("#productTitle", timeout=8000)
            except Exception:
                pass

            product_name = await self._get_text(page, ["#productTitle", "#title"])
            if len(product_name) < 50 and page_title:
                product_name = self._choose_better_title(product_name, page_title)

            price_text = await self._get_text(
                page,
                [
                    "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
                    ".a-price .a-offscreen",
                    ".reinventPricePriceToPayMargin .a-offscreen",
                ],
            )
            rating_text = await self._get_text(
                page,
                [
                    "#acrPopover .a-icon-alt",
                    "[data-hook='rating-out-of-text']",
                ],
            )
            review_count_text = await self._get_text(
                page,
                [
                    "#acrCustomerReviewText",
                    "[data-hook='total-review-count']",
                    "#acrCustomerReviewLink",
                ],
            )
            location = await self._get_text(page, ["#glow-ingress-line2"])

            price_amount, currency = parse_price(price_text)
            rating_value = parse_rating(rating_text)
            review_count_value = parse_review_count(review_count_text)

            # 核心字段全为空说明页面被 Bot 检测拦截，标记为无效
            core_empty = not product_name and not price_text and not rating_text
            real_product_name = product_name if not self._is_generic_title(product_name) else ""
            if core_empty or (not real_product_name and not price_text and not rating_text):
                return AmazonProductSnapshot(
                    asin=asin,
                    zip_code=zip_code,
                    marketplace="amazon.com",
                    page_url=page_url,
                    page_title=page_title,
                    product_name="",
                    price_text="",
                    price_amount=None,
                    currency=None,
                    rating_text="",
                    rating_value=None,
                    review_count_text="",
                    review_count_value=None,
                    location=location,
                    collected_at=self._now(),
                    valid=False,
                    error="商品数据为空，疑似 Bot 检测拦截，请稍后重试",
                )

            return AmazonProductSnapshot(
                asin=asin,
                zip_code=zip_code,
                marketplace="amazon.com",
                page_url=page_url,
                page_title=page_title,
                product_name=real_product_name or product_name,
                price_text=price_text,
                price_amount=price_amount,
                currency=currency,
                rating_text=rating_text,
                rating_value=rating_value,
                review_count_text=review_count_text,
                review_count_value=review_count_value,
                location=location,
                collected_at=self._now(),
                valid=True,
                raw={
                    "productName": real_product_name or product_name,
                    "price": price_text,
                    "rating": rating_text,
                    "reviewCount": review_count_text,
                    "location": location,
                },
            )

    async def search_products_async(
        self,
        keyword: str,
        *,
        max_results: int = 10,
        zip_code: str = "10001",
    ) -> list[AmazonSearchResult]:
        """异步抓取搜索结果。"""
        async with self._browser_page() as page:
            search_url = self.SEARCH_URL_TEMPLATE.format(keyword=quote_plus(keyword))
            await page.goto(search_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await page.wait_for_timeout(self.DEFAULT_WAIT_MS)
            await self._bypass_continue_shopping(page)
            await self._apply_zip_code(page, zip_code)

            items = await page.query_selector_all('[data-component-type="s-search-result"], .s-result-item')
            results: list[AmazonSearchResult] = []
            for item in items:
                asin = normalize_text(await item.get_attribute("data-asin"))
                if not asin:
                    continue

                title = await self._get_text_from_scope(
                    item,
                    [
                        "h2 .a-link-normal span",
                        ".a-size-medium.a-color-base.a-text-normal",
                    ],
                )
                price_text = await self._get_text_from_scope(item, [".a-price .a-offscreen", ".a-price-whole"])
                rating_text = await self._get_text_from_scope(item, [".a-icon-alt"])
                review_count_text = await self._get_review_count_from_scope(item)
                badge = await item.query_selector("[aria-label*='Best Seller']")

                price_amount, _ = parse_price(price_text)
                rating_value = parse_rating(rating_text)
                review_count_value = parse_review_count(review_count_text)

                results.append(
                    AmazonSearchResult(
                        asin=asin,
                        keyword=keyword,
                        zip_code=zip_code,
                        rank=len(results) + 1,
                        title=title,
                        price_text=price_text,
                        price_amount=price_amount,
                        rating_text=rating_text,
                        rating_value=rating_value,
                        review_count_text=review_count_text,
                        review_count_value=review_count_value,
                        is_best_seller=badge is not None,
                    )
                )
                if len(results) >= max_results:
                    break

            return results

    async def _bypass_continue_shopping(self, page) -> None:
        """检测并点击 Amazon 的"Continue shopping"中间验证页按钮。

        Amazon 的 validateCaptcha 中间页（无图片验证码版本）会插入一个表单，
        提交表单后即可跳转到真实商品页。此方法自动检测并点击该按钮。
        """
        try:
            # 确认是验证中间页（页面不含商品/搜索结果元素）
            product_el = await page.query_selector("#productTitle, #dp, .s-search-results")
            if product_el is not None:
                return  # 已是正常商品页，无需处理
            # 查找中间页的 submit 按钮（form action="/errors/validateCaptcha"）
            btn = await page.query_selector("button[type='submit'].a-button-text")
            if btn is None:
                return
            # 点击提交，等待跳转到真实商品页
            await btn.click()
            await page.wait_for_timeout(3000)
        except Exception:
            return

    async def _apply_zip_code(self, page, zip_code: str) -> None:
        """设置邮编以稳定价格口径。"""
        if not zip_code:
            return
        try:
            location_btn = await page.query_selector("#glow-ingress-line2")
            if location_btn:
                await location_btn.click()
                await page.wait_for_timeout(1500)

            zip_input = await page.query_selector("#GLUXZipUpdateInput")
            if not zip_input:
                return

            await zip_input.fill(zip_code)
            await page.wait_for_timeout(600)

            submit_btn = await page.query_selector("#GLUXZipUpdate")
            if submit_btn:
                await submit_btn.click()
                await page.wait_for_timeout(2500)
                await page.reload(wait_until="domcontentloaded", timeout=self.timeout_ms)
                await page.wait_for_timeout(1500)
        except Exception:
            return

    async def _get_text(self, page, selectors: list[str]) -> str:
        """从 page 上按优先级读取文本。"""
        for selector in selectors:
            handle = await page.query_selector(selector)
            if handle:
                value = normalize_text(await handle.inner_text())
                if value:
                    return value
        return ""

    async def _get_text_from_scope(self, scope, selectors: list[str]) -> str:
        """从局部作用域按优先级读取文本。"""
        for selector in selectors:
            handle = await scope.query_selector(selector)
            if handle:
                value = normalize_text(await handle.inner_text())
                if value:
                    return value
        return ""

    async def _get_review_count_from_scope(self, scope) -> str:
        """优先从评论链接中读取评论数，避免误取评分文本。"""
        selectors = [
            "a[href*='customerReviews'] span.a-size-base",
            "a[href*='customerReviews'] .a-size-base",
            "a[href*='customerReviews']",
            "span.a-size-base.s-underline-text",
        ]
        for selector in selectors:
            handles = await scope.query_selector_all(selector)
            for handle in handles:
                for value in (
                    normalize_text(await handle.inner_text()),
                    normalize_text(await handle.get_attribute("aria-label")),
                ):
                    if parse_review_count(value) is not None:
                        return value
        return ""

    def _validate_asin(self, asin: str) -> None:
        """校验 ASIN。"""
        normalized = normalize_text(asin).upper()
        if len(normalized) != 10 or not normalized.isalnum():
            raise InvalidAsinError("ASIN 必须是 10 位字母或数字")

    def _get_invalid_reason(self, page_title: str) -> str:
        """检查页面标题是否异常，返回错误原因字符串；正常页面返回空字符串。"""
        title = normalize_text(page_title).lower()
        # 标题仅为 "amazon.com" / "amazon" 说明被重定向到首页，通常是 Bot 检测触发
        if title in ("amazon.com", "amazon"):
            return "页面重定向到 Amazon 首页，疑似 Bot 检测拦截，请稍后重试"
        if "page not found" in title:
            return "商品页面不存在（404）"
        if "sorry" in title and "amazon" in title:
            return "Amazon 拒绝访问（疑似触发人机验证）"
        return ""

    def _is_generic_title(self, title: str) -> bool:
        """判断是否为无意义的通用标题（如首页标题）。"""
        normalized = normalize_text(title).lower()
        return normalized in ("amazon.com", "amazon", "")

    def _choose_better_title(self, product_name: str, page_title: str) -> str:
        """当 DOM 标题过短时，回退使用页面标题（排除首页通用标题）。"""
        candidate = normalize_text(page_title.split(":", 1)[0])
        # 排除首页标题，避免将 "Amazon.com" 误作商品名
        if self._is_generic_title(candidate):
            return product_name
        if len(candidate) > len(product_name):
            return candidate
        return product_name

    def _now(self) -> str:
        """返回统一的抓取时间。"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _load_playwright(self):
        """延迟导入 Playwright，避免未安装时影响其他模块。"""
        try:
            from playwright.async_api import async_playwright
        except ModuleNotFoundError as exc:
            raise ScraperDependencyError(
                "缺少 playwright 依赖，请安装 `pip install opscli` 并执行 `playwright install chromium`"
            ) from exc
        return async_playwright

    def _browser_page(self):
        """创建 page 上下文。"""
        async_playwright = self._load_playwright()
        # 尝试加载 stealth，2.0+ 需要包装整个 playwright() 上下文
        stealth_cls = None
        try:
            from playwright_stealth import Stealth
            stealth_cls = Stealth
        except ImportError:
            pass

        class _PageContext:
            def __init__(self, outer: AmazonScraper):
                self.outer = outer
                self.playwright = None
                self.browser = None
                self.context = None
                self.page = None
                self._stealth_cm = None

            async def __aenter__(self):
                pw_cm = async_playwright()
                # stealth 2.0+ 包装整个 playwright 上下文以自动注入所有页面
                if stealth_cls is not None:
                    self._stealth_cm = stealth_cls().use_async(pw_cm)
                    self.playwright = await self._stealth_cm.__aenter__()
                else:
                    self.playwright = await pw_cm.start()

                self.browser = await self.playwright.chromium.launch(headless=self.outer.headless)
                self.context = await self.browser.new_context(
                    locale="en-US",
                    # 伪造真实 Chrome User-Agent，降低 Bot 识别概率
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                    device_scale_factor=2,
                    extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                )
                self.page = await self.context.new_page()
                return self.page

            async def __aexit__(self, exc_type, exc, tb):
                if self.context is not None:
                    await self.context.close()
                if self.browser is not None:
                    await self.browser.close()
                if self._stealth_cm is not None:
                    await self._stealth_cm.__aexit__(exc_type, exc, tb)
                elif self.playwright is not None:
                    await self.playwright.stop()

        return _PageContext(self)

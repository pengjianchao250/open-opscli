"""amazon 模块抓取器。

基于 Playwright 驱动 Chromium 抓取 Amazon 商品页与搜索结果。

反拦截设计（针对阿里云等数据中心 IP 被 Amazon 拦截的问题）：
  1. 代理出口：支持注入住宅 / 移动代理，把来源 IP 切出机房段（根因修复，
     见 opscli/amazon/config.py 的说明）。
  2. 指纹伪装：随机 User-Agent + 随机视口 + 反自动化 launch 参数 +
     自注入 stealth 脚本（覆盖 navigator.webdriver 等自动化特征）。
  3. 退避重试：命中 Bot 检测（首页重定向 / 空数据 / 验证页）时，
     用全新指纹上下文重试若干次。
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime
from urllib.parse import quote_plus

import opscli.amazon.config as amazon_config
from opscli.amazon.domain.exceptions import InvalidAsinError, ScraperDependencyError
from opscli.amazon.domain.models import AmazonProductSnapshot, AmazonSearchResult
from opscli.amazon.scraping.parser import normalize_text, parse_price, parse_rating, parse_review_count

# 自注入的 stealth 脚本：在页面任何脚本执行前抹掉常见自动化特征。
# 不依赖第三方 playwright_stealth（该包未在 pyproject 声明，生产环境常缺失）。
_STEALTH_INIT_SCRIPT = """
// 抹掉 navigator.webdriver（自动化最明显的特征）
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
// 伪造 languages，避免为空被识别
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
// 伪造 plugins 数量，无头浏览器默认为空
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
// 注入 window.chrome，真实 Chrome 存在此对象而无头默认缺失
window.chrome = window.chrome || {runtime: {}};
// 修正 permissions.query，避免 notifications 权限探测暴露无头特征
const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
if (originalQuery) {
  window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
      ? Promise.resolve({state: Notification.permission})
      : originalQuery(parameters)
  );
}
"""

# 反自动化 launch 参数：关闭 AutomationControlled 特征、沙箱等。
# --no-sandbox 为 Linux 服务器（如阿里云）以 root 运行 Chromium 所必需。
_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-infobars",
    "--window-size=1280,800",
]


class AmazonScraper:
    """基于 Playwright 的 Amazon 抓取器。"""

    PRODUCT_URL_TEMPLATE = "https://www.amazon.com/dp/{asin}"
    SEARCH_URL_TEMPLATE = "https://www.amazon.com/s?k={keyword}&s=review-rank"
    DEFAULT_TIMEOUT_MS = 120000
    DEFAULT_WAIT_MS = 3000

    def __init__(
        self,
        *,
        headless: bool | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        proxy: dict | None = None,
        max_retries: int | None = None,
        user_agent: str | None = None,
    ) -> None:
        """初始化抓取器。

        Args:
            headless: 是否无头；None 时读 config（默认 True）。
            timeout_ms: 页面加载超时（毫秒）。
            proxy: Playwright 代理 dict；None 时读 config（未配置则不使用代理）。
            max_retries: 命中拦截时的最大尝试次数；None 时读 config（默认 3）。
            user_agent: 固定 UA；None 时每次尝试从 UA 池随机选取。
        """
        # headless / proxy / max_retries 未显式指定时回退到配置层，
        # 使 CLI 与服务端无需改代码即可通过 config.ini / 环境变量调参。
        self.headless = amazon_config.get_headless() if headless is None else headless
        self.timeout_ms = timeout_ms
        self.proxy = amazon_config.get_proxy() if proxy is None else proxy
        # 至少尝试 1 次，防止显式传入 0 导致空循环
        self.max_retries = amazon_config.get_max_retries() if max_retries is None else max(1, max_retries)
        self.user_agent = user_agent

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
        """异步抓取单个商品，命中 Bot 检测时用全新指纹重试。"""
        self._validate_asin(asin)
        last_snapshot: AmazonProductSnapshot | None = None
        for attempt in range(1, self.max_retries + 1):
            # 每次尝试都开一个全新的浏览器上下文（新 UA / 新视口），
            # 避免沿用已被 Amazon 标记的指纹。
            async with self._browser_page() as page:
                snapshot = await self._scrape_product_once(page, asin, zip_code)
            last_snapshot = snapshot
            # 成功或遇到不可重试的错误（如 404）直接返回
            if snapshot.valid or not self._is_retryable(snapshot.error):
                return snapshot
            # 命中拦截：随机退避后换指纹重试（最后一次不再等待）
            if attempt < self.max_retries:
                await asyncio.sleep(random.uniform(2.0, 5.0))
        # max_retries 恒 >= 1，循环至少执行一次，last_snapshot 必已赋值
        assert last_snapshot is not None
        return last_snapshot  # 所有尝试均被拦截，返回最后一次快照

    async def _scrape_product_once(self, page, asin: str, zip_code: str) -> AmazonProductSnapshot:
        """在给定 page 上完成一次商品抓取（单次尝试，不含重试）。"""
        page_url = self.PRODUCT_URL_TEMPLATE.format(asin=asin)
        await page.goto(page_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        await page.wait_for_timeout(self.DEFAULT_WAIT_MS)
        # 处理 Amazon 的中间验证页（"Click the button below to continue shopping"）
        await self._bypass_continue_shopping(page)
        await self._apply_zip_code(page, zip_code)

        page_title = await page.title()
        invalid_reason = self._get_invalid_reason(page_title)
        if invalid_reason:
            return self._invalid_snapshot(asin, zip_code, page_url, page_title, "", invalid_reason)

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

        # 核心字段全为空说明页面被 Bot 检测拦截，标记为无效（可重试）
        core_empty = not product_name and not price_text and not rating_text
        real_product_name = product_name if not self._is_generic_title(product_name) else ""
        if core_empty or (not real_product_name and not price_text and not rating_text):
            return self._invalid_snapshot(
                asin,
                zip_code,
                page_url,
                page_title,
                location,
                "商品数据为空，疑似 Bot 检测拦截，请稍后重试",
            )

        # 抓取扩展字段（品牌 / 库存 / 五点 / 描述 / 图片 / BSR / 类目 / 配送 / 卖家）
        extended = await self._extract_extended_fields(page)

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
            brand=extended["brand"],
            availability=extended["availability"],
            bullet_points=extended["bullet_points"],
            description=extended["description"],
            images=extended["images"],
            best_sellers_rank=extended["best_sellers_rank"],
            categories=extended["categories"],
            delivery_info=extended["delivery_info"],
            ships_from=extended["ships_from"],
            sold_by=extended["sold_by"],
            coupon=extended["coupon"],
            raw={
                "productName": real_product_name or product_name,
                "price": price_text,
                "rating": rating_text,
                "reviewCount": review_count_text,
                "location": location,
                **extended,
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

    async def _extract_extended_fields(self, page) -> dict:
        """抓取商品页扩展字段，返回统一结构的 dict。

        单次 JS evaluate 完成大部分文本 / 列表 / 图片提取，减少往返；
        任何字段缺失均返回空值，不影响其它字段。
        """
        try:
            return await page.evaluate(
                """
                () => {
                    const txt = (sel) => {
                        const el = document.querySelector(sel);
                        return el ? el.textContent.replace(/\\s+/g, ' ').trim() : '';
                    };
                    // 品牌：bylineInfo 常见形如 "Brand: Xxx" 或 "Visit the Xxx Store"
                    let brand = txt('#bylineInfo');
                    brand = brand.replace(/^Brand:\\s*/i, '')
                                 .replace(/^Visit the\\s*/i, '')
                                 .replace(/\\s*Store$/i, '').trim();
                    // 五点描述
                    const bullets = Array.from(
                        document.querySelectorAll('#feature-bullets ul li span.a-list-item')
                    ).map(e => e.textContent.replace(/\\s+/g, ' ').trim()).filter(Boolean);
                    // 面包屑类目
                    const cats = Array.from(
                        document.querySelectorAll('#wayfinding-breadcrumbs_feature_div a')
                    ).map(e => e.textContent.trim()).filter(Boolean);
                    // 图片：优先动态图 map 与 hi-res，回退缩略图并还原为大图
                    const imgs = new Set();
                    const hero = document.querySelector('#landingImage, #imgBlkFront, #main-image');
                    if (hero) {
                        const dyn = hero.getAttribute('data-a-dynamic-image');
                        if (dyn) { try { Object.keys(JSON.parse(dyn)).forEach(u => imgs.add(u)); } catch(e){} }
                        const hires = hero.getAttribute('data-old-hires');
                        if (hires) imgs.add(hires);
                        if (hero.src) imgs.add(hero.src);
                    }
                    document.querySelectorAll('#altImages img, #imageBlock img').forEach(img => {
                        if (img.src) imgs.add(img.src.replace(/\\._[^.]+_\\./, '.'));
                    });
                    // BSR：在明细区块中定位含 "Best Sellers Rank" 的条目
                    let bsr = '';
                    document.querySelectorAll(
                        '#detailBulletsWrapper_feature_div li, #productDetails_detailBullets_sections1 tr, #SalesRank'
                    ).forEach(el => {
                        const t = el.textContent.replace(/\\s+/g, ' ').trim();
                        if (!bsr && /Best Sellers Rank/i.test(t)) bsr = t;
                    });
                    // buybox：发货方 / 卖家
                    let shipsFrom = '', soldBy = '';
                    document.querySelectorAll(
                        '#tabular-buybox .tabular-buybox-text, #tabular_feature_div .a-row'
                    ).forEach(el => {
                        const t = el.textContent.replace(/\\s+/g, ' ').trim();
                        if (/Ships from/i.test(t)) shipsFrom = t.replace(/Ships from/i, '').trim();
                        if (/Sold by/i.test(t)) soldBy = t.replace(/Sold by/i, '').trim();
                    });
                    if (!soldBy) soldBy = txt('#merchant-info');
                    return {
                        brand: brand,
                        availability: txt('#availability span') || txt('#availability'),
                        bullet_points: bullets,
                        description: txt('#productDescription'),
                        images: Array.from(imgs).slice(0, 15),
                        best_sellers_rank: bsr,
                        categories: cats,
                        delivery_info: txt('#mir-layout-DELIVERY_BLOCK') || txt('#deliveryBlockMessage'),
                        ships_from: shipsFrom,
                        sold_by: soldBy,
                        coupon: txt('.couponLabelText') || txt('#promoPriceBlockMessage .a-color-success'),
                    };
                }
                """
            )
        except Exception:
            # 扩展字段提取失败不应影响核心采集，返回全空结构
            return {
                "brand": "",
                "availability": "",
                "bullet_points": [],
                "description": "",
                "images": [],
                "best_sellers_rank": "",
                "categories": [],
                "delivery_info": "",
                "ships_from": "",
                "sold_by": "",
                "coupon": "",
            }

    def _invalid_snapshot(
        self,
        asin: str,
        zip_code: str,
        page_url: str,
        page_title: str,
        location: str,
        error: str,
    ) -> AmazonProductSnapshot:
        """构造一个标记为无效的快照（拦截 / 404 等场景复用）。"""
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
            error=error,
        )

    def _is_retryable(self, error: str | None) -> bool:
        """判断错误是否为可重试的 Bot 拦截（区别于 404 等确定性失败）。"""
        if not error:
            return False
        # 命中拦截 / 首页重定向 / 人机验证的错误值得换指纹重试；
        # "页面不存在（404）" 属于确定性失败，不重试。
        keywords = ("Bot 检测", "人机验证", "首页", "拦截")
        return any(k in error for k in keywords)

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
        """创建 page 上下文（含代理、随机指纹、反自动化参数与 stealth 注入）。"""
        async_playwright = self._load_playwright()
        outer = self

        class _PageContext:
            def __init__(self) -> None:
                self.playwright = None
                self.browser = None
                self.context = None
                self.page = None

            async def __aenter__(self):
                self.playwright = await async_playwright().start()

                # 组装 launch 参数：反自动化 args + 可选代理。
                # 代理是绕过阿里云等数据中心 IP 被封的关键出口切换手段。
                launch_kwargs: dict = {"headless": outer.headless, "args": _LAUNCH_ARGS}
                if outer.proxy:
                    launch_kwargs["proxy"] = outer.proxy
                self.browser = await self.playwright.chromium.launch(**launch_kwargs)

                # 每次上下文随机选取 UA 与视口，降低固定指纹被识别的概率
                user_agent = outer.user_agent or random.choice(amazon_config.USER_AGENTS)
                viewport = random.choice(amazon_config.VIEWPORTS)
                self.context = await self.browser.new_context(
                    locale="en-US",
                    user_agent=user_agent,
                    viewport=viewport,
                    device_scale_factor=1,
                    extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
                )
                # 在页面脚本执行前注入 stealth，抹除自动化特征
                await self.context.add_init_script(_STEALTH_INIT_SCRIPT)
                self.page = await self.context.new_page()
                return self.page

            async def __aexit__(self, exc_type, exc, tb):
                if self.context is not None:
                    await self.context.close()
                if self.browser is not None:
                    await self.browser.close()
                if self.playwright is not None:
                    await self.playwright.stop()

        return _PageContext()

"""Amazon 工具模块。

将 opscli amazon 子模块的核心能力暴露为 MCP 工具：
- amazon_scrape   — 抓取单个 Amazon 商品快照
- amazon_search   — 按关键词搜索竞品列表
- amazon_history  — 读取本地历史快照（无网络依赖）
- amazon_schema   — 输出数据模型结构（静态，无依赖）
- amazon_payload  — 抓取商品并构造 ops 提交 payload

⚠️ 异步注意事项：
    MCP 工具运行在 FastMCP 的 asyncio 事件循环中。
    AmazonScraper 的同步公开方法（scrape_product / search_products）内部调用
    asyncio.run()，在已有事件循环中嵌套调用会引发
    "RuntimeError: This event loop is already running"。
    因此所有工具必须直接 await scraper 的 *_async 方法，
    绕过同步包装器，不得经由 AmazonManager 的同步接口触发 Playwright。

依赖：
    amazon 工具依赖可选扩展 playwright，未安装时 server.py 中会跳过注册。
    安装命令：pip install opscli && playwright install chromium

所有工具函数定义在模块级，可直接导入调用（测试友好）。
调用 register(mcp) 将以上工具批量注册到指定 MCP 实例。
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from .helpers import _err, _ok


# ── 工具实现 ─────────────────────────────────────────────────────────

async def amazon_scrape(
    asin: str,
    zip_code: str = "10001",
    save_history: bool = True,
    include_raw: bool = False,
) -> dict:
    """抓取单个 Amazon 商品快照（价格、评分、评论数等）。

    基于 Playwright 无头浏览器采集，耗时约 10~30 秒。
    采集完成后可选将快照追加写入本地历史文件（JSONL 格式）。

    Args:
        asin:         目标商品 ASIN（10 位字母数字）
        zip_code:     美国邮编，用于稳定价格口径（默认 "10001" 纽约）
        save_history: 是否将快照追加写入本地历史文件（默认 True）
        include_raw:  是否在返回结果中包含原始抓取字段（默认 False）
    """
    try:
        from opscli.amazon.scraping.scraper import AmazonScraper
        from opscli.amazon.services.manager import AmazonManager

        scraper = AmazonScraper()
        # 直接调用异步方法，绕过 scraper.scrape_product() 的 asyncio.run() 包装器
        snapshot = await scraper.scrape_product_async(asin, zip_code)

        history_path: str | None = None
        if save_history:
            # 写历史是同步文件 I/O，可在事件循环中直接调用
            manager = AmazonManager(scraper=scraper)
            path = manager._append_history(snapshot)
            history_path = str(path)

        return _ok({
            "snapshot": snapshot.to_dict(include_raw=include_raw),
            "history_path": history_path,
        })
    except Exception as exc:
        return _err(exc)


async def amazon_search(
    keyword: str,
    zip_code: str = "10001",
    limit: int = 10,
) -> dict:
    """按关键词抓取 Amazon 搜索结果页，返回竞品列表。

    基于 Playwright 无头浏览器采集，结果按评论数排序（s=review-rank）。
    耗时约 10~30 秒。

    Args:
        keyword:  搜索关键词
        zip_code: 美国邮编，用于稳定价格口径（默认 "10001" 纽约）
        limit:    最大结果数（1~50，默认 10）
    """
    try:
        from opscli.amazon.scraping.scraper import AmazonScraper

        scraper = AmazonScraper()
        # 直接调用异步方法，绕过 scraper.search_products() 的 asyncio.run() 包装器
        results = await scraper.search_products_async(
            keyword,
            max_results=max(1, min(limit, 50)),
            zip_code=zip_code,
        )
        return _ok({
            "keyword": keyword,
            "zip_code": zip_code,
            "count": len(results),
            "results": [item.to_dict() for item in results],
        })
    except Exception as exc:
        return _err(exc)


async def amazon_history(asin: str) -> dict:
    """读取指定 ASIN 的本地历史快照列表（无网络依赖，仅读本地文件）。

    历史文件存储在 ~/.config/opscli/amazon/history/<ASIN>.jsonl，
    每次 amazon_scrape（save_history=True）都会向该文件追加一条记录。

    Args:
        asin: 目标商品 ASIN（10 位字母数字）
    """
    try:
        from opscli.amazon.services.manager import AmazonManager

        records = AmazonManager().load_history(asin)
        return _ok({
            "asin": asin.upper(),
            "count": len(records),
            "records": records,
        })
    except Exception as exc:
        return _err(exc)


async def amazon_schema() -> dict:
    """输出 Amazon 抓取数据模型与提交 payload 的字段结构（静态信息，无网络依赖）。

    可用于了解 amazon_scrape / amazon_search / amazon_payload 的返回字段含义。
    """
    return _ok({
        "snapshot_fields": {
            "asin": "string — 商品 ASIN",
            "zip_code": "string — 采集时使用的邮编",
            "marketplace": "string — 市场标识（amazon.com）",
            "page_url": "string — 商品页 URL",
            "page_title": "string — 浏览器页面标题",
            "product_name": "string — 商品名称",
            "price_text": "string — 原始价格文本",
            "price_amount": "number|null — 解析后的价格数值",
            "currency": "string|null — 货币代码（USD）",
            "rating_text": "string — 原始评分文本",
            "rating_value": "number|null — 解析后的星级数值（0~5）",
            "review_count_text": "string — 原始评论数文本",
            "review_count_value": "integer|null — 解析后的评论数",
            "location": "string — 配送地区文本",
            "collected_at": "string — 采集时间（YYYY-MM-DD HH:MM:SS）",
            "valid": "boolean — 页面是否有效（False 表示链接失效）",
            "error": "string|null — 采集失败原因",
        },
        "search_result_fields": {
            "asin": "string — 商品 ASIN",
            "keyword": "string — 搜索关键词",
            "zip_code": "string — 采集时使用的邮编",
            "rank": "integer — 搜索结果排名（从 1 开始）",
            "title": "string — 商品标题",
            "price_text": "string — 原始价格文本",
            "price_amount": "number|null — 解析后的价格数值",
            "rating_text": "string — 原始评分文本",
            "rating_value": "number|null — 解析后的星级数值",
            "review_count_text": "string — 原始评论数文本",
            "review_count_value": "integer|null — 解析后的评论数",
            "is_best_seller": "boolean — 是否带有 Best Seller 标记",
        },
        "submit_payload_structure": {
            "source": "string — 固定值 opscli.amazon",
            "snapshot": "AmazonProductSnapshot — 完整快照对象（含 raw 字段）",
        },
    })


async def amazon_payload(
    asin: str,
    zip_code: str = "10001",
    save_history: bool = True,
) -> dict:
    """抓取商品并构造标准 ops 提交 payload（预留提交通道，当前不自动发送）。

    基于 Playwright 无头浏览器采集，耗时约 10~30 秒。
    返回的 payload 可通过 ops 接口提交，当前须手动调用提交接口。

    Args:
        asin:         目标商品 ASIN（10 位字母数字）
        zip_code:     美国邮编，用于稳定价格口径（默认 "10001" 纽约）
        save_history: 是否将快照追加写入本地历史文件（默认 True）
    """
    try:
        from opscli.amazon.scraping.scraper import AmazonScraper
        from opscli.amazon.services.manager import AmazonManager

        scraper = AmazonScraper()
        # 直接调用异步方法，绕过 asyncio.run() 包装器
        snapshot = await scraper.scrape_product_async(asin, zip_code)

        manager = AmazonManager(scraper=scraper)
        history_path: str | None = None
        if save_history:
            path = manager._append_history(snapshot)
            history_path = str(path)

        payload = manager.build_submit_payload(snapshot)
        return _ok({
            "payload": payload,
            "history_path": history_path,
        })
    except Exception as exc:
        return _err(exc)


# ── 工具注解（提示 MCP 客户端工具的副作用与访问范围）──────────────────

# 抓取/搜索类：访问外部网络（Amazon），部分写本地历史文件
_SCRAPE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,        # 写本地历史文件
    openWorldHint=True,        # 访问 Amazon 公网
    destructiveHint=False,     # 不删除数据
)

_SEARCH_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,         # 不写任何本地文件
    openWorldHint=True,        # 访问 Amazon 公网
    destructiveHint=False,
)

# 本地只读类：仅读本地文件，无网络依赖
_LOCAL_READ_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    openWorldHint=False,
    destructiveHint=False,
)


# ── 工具函数列表（供 register() 批量注册使用）────────────────────────
_ALL_TOOLS: list[tuple] = [
    (amazon_scrape,   _SCRAPE_ANNOTATIONS),
    (amazon_search,   _SEARCH_ANNOTATIONS),
    (amazon_history,  _LOCAL_READ_ANNOTATIONS),
    (amazon_schema,   _LOCAL_READ_ANNOTATIONS),
    (amazon_payload,  _SCRAPE_ANNOTATIONS),
]


def register(mcp) -> None:
    """向指定 MCP 实例批量注册所有 amazon_* 工具。

    注意：此函数仅在 playwright 已安装时被 server.py 调用。

    Args:
        mcp: FastMCP 实例，由 server.py 统一创建并传入
    """
    for fn, annotations in _ALL_TOOLS:
        mcp.tool(annotations=annotations)(fn)

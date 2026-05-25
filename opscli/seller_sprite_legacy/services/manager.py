"""卖家精灵采集业务编排层。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from opscli.seller_sprite_legacy.domain.exceptions import InvalidAsinError, InvalidCollectOptionError, SellerSpriteResponseError
from opscli.seller_sprite_legacy.domain.models import (
    SellerSpriteArchiveManifest,
    SellerSpriteCollectOptions,
    SellerSpriteCollectResult,
    SellerSpriteFrequencyTerm,
    SellerSpriteKeywordItem,
    SellerSpriteReverseKeywordItem,
)
from opscli.seller_sprite_legacy.scraping.scraper import SellerSpriteScraper
from opscli.seller_sprite_legacy.services.account_store import SellerSpriteAccountStore


class SellerSpriteManager:
    """协调卖家精灵页面采集、标准化和本地落盘。"""

    def __init__(
        self,
        *,
        base_dir: Path | None = None,
        scraper: SellerSpriteScraper | None = None,
        account_store: SellerSpriteAccountStore | None = None,
    ) -> None:
        self.runs_dir = Path(base_dir) if base_dir else Path.cwd() / "seller_sprite_runs"
        self.scraper = scraper or SellerSpriteScraper()
        self.account_store = account_store or SellerSpriteAccountStore()

    def collect(self, options: SellerSpriteCollectOptions) -> SellerSpriteCollectResult:
        """按显式关键词执行完整采集。"""
        self._validate_collect_options(options, require_asin=False, require_keyword=True)
        run_id = self._build_run_id()
        run_dir = self._build_run_dir(options, run_id)
        account = self.account_store.get(name=options.account) if options.account else None
        raw = self.scraper.collect(options=options, run_id=run_id, run_dir=run_dir, account=account)
        result = self._build_result(options=options, run_id=run_id, run_dir=run_dir, raw=raw)
        self._save_result(run_dir, result)
        return result

    def collect_frequency(self, options: SellerSpriteCollectOptions) -> SellerSpriteCollectResult:
        """只采集高频词。"""
        self._validate_collect_options(options, require_asin=False, require_keyword=True)
        run_id = self._build_run_id()
        run_dir = self._build_run_dir(options, run_id)
        raw = self.scraper.collect_frequency(options=options, run_id=run_id, run_dir=run_dir)
        result = self._build_result(options=options, run_id=run_id, run_dir=run_dir, raw=raw)
        self._save_result(run_dir, result)
        return result

    def collect_keyword_mining(self, options: SellerSpriteCollectOptions) -> SellerSpriteCollectResult:
        """只采集关键词挖掘结果。"""
        self._validate_collect_options(options, require_asin=False, require_keyword=True)
        run_id = self._build_run_id()
        run_dir = self._build_run_dir(options, run_id)
        raw = self.scraper.collect_keyword_mining(options=options, run_id=run_id, run_dir=run_dir)
        result = self._build_result(options=options, run_id=run_id, run_dir=run_dir, raw=raw)
        self._save_result(run_dir, result)
        return result

    def archive_url(self, options: SellerSpriteCollectOptions) -> SellerSpriteCollectResult:
        """只归档指定页面 URL。"""
        if not options.url:
            raise InvalidCollectOptionError("archive 命令必须提供 --url")
        run_id = self._build_run_id()
        run_dir = self._build_run_dir(options, run_id)
        raw = self.scraper.archive_url(options=options, run_id=run_id, run_dir=run_dir)
        result = self._build_result(options=options, run_id=run_id, run_dir=run_dir, raw=raw)
        self._save_result(run_dir, result)
        return result

    def collect_keyword_reverse(self, options: SellerSpriteCollectOptions) -> SellerSpriteCollectResult:
        """采集关键词反查结果。"""
        self._validate_collect_options(options, require_asin=True, require_keyword=False)
        run_id = self._build_run_id()
        run_dir = self._build_run_dir(options, run_id)
        account = self.account_store.get(name=options.account) if options.account else None
        raw = self.scraper.collect_keyword_reverse(options=options, run_id=run_id, run_dir=run_dir, account=account)
        result = self._build_result(options=options, run_id=run_id, run_dir=run_dir, raw=raw)
        self._save_result(run_dir, result)
        return result

    def login(self) -> dict[str, Any]:
        """打开浏览器让用户手动建立卖家精灵登录态。"""
        return self.scraper.login()

    def login_status(self, options: SellerSpriteCollectOptions) -> dict[str, Any]:
        """检查当前卖家精灵浏览器 profile 登录状态。"""
        run_id = self._build_run_id()
        run_dir = self._build_run_dir(options, run_id)
        raw = self.scraper.login_status(options=options, run_id=run_id, run_dir=run_dir)
        return {
            "run_id": run_id,
            "root_dir": str(run_dir),
            "profile_dir": raw.get("profile_dir"),
            "current_url": raw.get("current_url"),
            "logged_in": bool(raw.get("logged_in", False)),
            "captcha_required": bool(raw.get("captcha_required", False)),
            "files": raw.get("files", {}),
        }

    def schema(self) -> dict:
        """输出当前卖家精灵标准化字段契约。"""
        return {
            "collect_options": {
                "asin": "string|null",
                "keyword": "string|null",
                "site": "string",
                "period": "string",
                "limit": "integer",
                "frequency_phrase_count": "integer",
                "trend_limit": "integer",
                "trend_tabs": "string",
                "archive": "boolean",
                "url": "string|null",
                "output_dir": "string|null",
                "account": "string|null",
            },
            "frequency_term": {
                "keyword": "string",
                "frequency": "integer",
                "percentage": "number",
            },
            "keyword_item": {
                "keyword": "string",
                "keyword_cn": "string",
                "keyword_jp": "string",
                "departments": "array<object>",
                "trends": "array<object>",
                "searches": "integer|null",
                "purchases": "integer|null",
                "purchase_rate": "number|null",
                "impressions": "integer|null",
                "clicks": "integer|null",
                "cvs_share_rate": "number|null",
                "products": "integer|null",
                "ad_products": "integer|null",
                "supply_demand_ratio": "number|null",
                "avg_price": "number|null",
                "avg_reviews": "integer|null",
                "avg_rating": "number|null",
                "bid": "number|null",
                "phrase_ppc": "number|null",
                "exact_ppc": "number|null",
                "broad_ppc": "number|null",
                "title_density": "integer|null",
                "spr": "integer|null",
                "relevancy": "number|null",
                "monopoly_asins": "array<object>",
                "related_products": "array<object>",
            },
            "reverse_keyword_item": {
                "keyword": "string",
                "position": "string",
                "traffic_percentage": "number|null",
                "searches": "integer|null",
                "purchases": "integer|null",
                "bid": "number|null",
                "related_products": "array<object>",
            },
            "trend_detail": {
                "keyword": "string",
                "tabs": "array<object>",
            },
        }

    def _validate_collect_options(
        self,
        options: SellerSpriteCollectOptions,
        *,
        require_asin: bool,
        require_keyword: bool,
    ) -> None:
        """校验采集参数，保证命令输入边界稳定。"""
        if require_asin and not options.asin:
            raise InvalidAsinError("collect 命令必须提供 --asin")
        if options.asin:
            asin = self._extract_asin(options.asin)
            if not asin:
                raise InvalidAsinError("ASIN 必须是 10 位字母或数字，或包含 ASIN 的 Amazon 产品链接")
            options.asin = asin
        if require_keyword and not options.keyword:
            raise InvalidCollectOptionError("必须提供 --keyword")
        if options.limit < 1 or options.limit > 200:
            raise InvalidCollectOptionError("--limit 范围必须是 1-200")
        if options.frequency_phrase_count < 1 or options.frequency_phrase_count > 10:
            raise InvalidCollectOptionError("--frequency-phrase-count 范围必须是 1-10")
        if options.trend_limit < 0 or options.trend_limit > options.limit:
            raise InvalidCollectOptionError("--trend-limit 范围必须是 0 到 --limit")

    def _extract_asin(self, value: str) -> str | None:
        """从裸 ASIN 或 Amazon 产品链接中提取 ASIN。"""
        text = value.strip().upper()
        if len(text) == 10 and text.isalnum():
            return text
        for pattern in [r"/DP/([A-Z0-9]{10})", r"/GP/PRODUCT/([A-Z0-9]{10})", r"\b(B[A-Z0-9]{9})\b"]:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None

    def _build_result(
        self,
        *,
        options: SellerSpriteCollectOptions,
        run_id: str,
        run_dir: Path,
        raw: dict[str, Any],
    ) -> SellerSpriteCollectResult:
        """将原始接口响应转换为标准化结果。"""
        archive = SellerSpriteArchiveManifest(
            run_id=run_id,
            root_dir=run_dir,
            files=raw.get("files", {}),
            captcha_required=bool(raw.get("captcha_required", False)),
            missing_sections=list(raw.get("missing_sections", [])),
            errors=list(raw.get("errors", [])),
        )
        return SellerSpriteCollectResult(
            asin=options.asin,
            keyword=options.keyword,
            site=options.site,
            period=options.period,
            limit=options.limit,
            frequency_phrase_count=options.frequency_phrase_count,
            trend_limit=options.trend_limit,
            trend_tabs=options.trend_tabs,
            run_id=run_id,
            frequency_terms=self._normalize_frequency(raw.get("frequency") or raw.get("reverse_frequency")),
            keyword_items=self._normalize_keyword_items(raw.get("keyword_mining"), limit=options.limit),
            reverse_keyword_items=self._normalize_reverse_keyword_items(raw.get("keyword_reverse"), limit=options.limit),
            keyword_trends=self._extract_keyword_trends(raw.get("keyword_mining"), limit=options.limit),
            trend_details=list(raw.get("trend_details") or []),
            competitor_asins=self._extract_competitor_asins(raw.get("keyword_mining"), limit=options.limit),
            product_info=self._extract_reverse_product_info(raw.get("reverse_monthly")),
            variation_asins=self._extract_reverse_variations(raw.get("reverse_monthly")),
            reverse_stats=self._extract_reverse_stats(raw.get("reverse_stats")),
            market_summary=self._build_market_summary(raw.get("keyword_mining") or raw.get("keyword_reverse")),
            archive_manifest=archive,
        )

    def _normalize_frequency(self, payload: dict[str, Any] | None) -> list[SellerSpriteFrequencyTerm]:
        """标准化高频词接口响应。"""
        if not payload:
            return []
        data = payload.get("data")
        if not isinstance(data, list):
            raise SellerSpriteResponseError("高频词接口缺少 data 数组")
        terms: list[SellerSpriteFrequencyTerm] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            terms.append(
                SellerSpriteFrequencyTerm(
                    keyword=str(item.get("keyword", "")),
                    frequency=int(item.get("frequency") or 0),
                    percentage=float(item.get("percentage") or 0),
                )
            )
        return terms

    def _normalize_keyword_items(self, payload: dict[str, Any] | None, *, limit: int) -> list[SellerSpriteKeywordItem]:
        """标准化关键词挖掘接口响应。"""
        items = self._keyword_items(payload)[:limit]
        normalized: list[SellerSpriteKeywordItem] = []
        for item in items:
            normalized.append(
                SellerSpriteKeywordItem(
                    keyword=str(item.get("keyword", "")),
                    keyword_cn=str(item.get("keywordCn", "")),
                    keyword_jp=str(item.get("keywordJp", "")),
                    departments=list(item.get("departments") or []),
                    trends=list(item.get("trends") or []),
                    searches=item.get("searches"),
                    purchases=item.get("purchases"),
                    purchase_rate=item.get("purchaseRate"),
                    impressions=item.get("impressions"),
                    clicks=item.get("clicks"),
                    cvs_share_rate=item.get("cvsShareRate"),
                    products=item.get("products"),
                    ad_products=item.get("adProducts"),
                    supply_demand_ratio=item.get("supplyDemandRatio"),
                    avg_price=item.get("avgPrice"),
                    avg_reviews=item.get("avgReviews"),
                    avg_rating=item.get("avgRating"),
                    bid=item.get("bid"),
                    phrase_ppc=item.get("phrasePpc"),
                    exact_ppc=item.get("exactPpc"),
                    broad_ppc=item.get("broadPpc"),
                    title_density=item.get("titleDensity"),
                    spr=item.get("spr"),
                    relevancy=item.get("relevancy"),
                    absolute_relevancy=item.get("absoluteRelevancy"),
                    amazon_choice=item.get("amazonChoice"),
                    monopoly_asins=list(item.get("monopolyAsinDtos") or []),
                    monopoly_click_rate=item.get("monopolyClickRate"),
                    related_products=list(item.get("gkDatas") or []),
                )
            )
        return normalized

    def _keyword_items(self, payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        """读取关键词挖掘 items。"""
        if not payload:
            return []
        data = payload.get("data")
        if not isinstance(data, dict):
            raise SellerSpriteResponseError("关键词挖掘接口缺少 data 对象")
        items = data.get("items")
        if not isinstance(items, list):
            raise SellerSpriteResponseError("关键词挖掘接口缺少 items 数组")
        return [item for item in items if isinstance(item, dict)]

    def _normalize_reverse_keyword_items(
        self,
        payload: dict[str, Any] | None,
        *,
        limit: int,
    ) -> list[SellerSpriteReverseKeywordItem]:
        """标准化关键词反查 items。"""
        items = self._reverse_keyword_items(payload)[:limit]
        normalized: list[SellerSpriteReverseKeywordItem] = []
        for item in items:
            normalized.append(
                SellerSpriteReverseKeywordItem(
                    keyword=str(item.get("keywords", "")),
                    keyword_cn=str(item.get("keywordCn", "")),
                    keyword_jp=str(item.get("keywordJp", "")),
                    position=str(item.get("position", "")),
                    badges=list(item.get("badges") or []),
                    traffic_percentage=item.get("trafficPercentage"),
                    searches=item.get("searches"),
                    purchases=item.get("purchases"),
                    purchase_rate=item.get("purchaseRate"),
                    products=item.get("products"),
                    impressions=item.get("impressions"),
                    clicks=item.get("clicks"),
                    spr=item.get("cprExact"),
                    title_density=item.get("titleDensityExact"),
                    bid=item.get("bid"),
                    phrase_ppc=item.get("phrasePpc"),
                    exact_ppc=item.get("exactPpc"),
                    broad_ppc=item.get("broadPpc"),
                    searches_trend=list(item.get("searchesTrend") or []),
                    related_products=list(item.get("gkDatas") or []),
                )
            )
        return normalized

    def _reverse_keyword_items(self, payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        """读取关键词反查 items。"""
        if not payload:
            return []
        data = payload.get("data")
        if not isinstance(data, dict):
            raise SellerSpriteResponseError("关键词反查接口缺少 data 对象")
        items = data.get("items")
        if not isinstance(items, list):
            raise SellerSpriteResponseError("关键词反查接口缺少 items 数组")
        return [item for item in items if isinstance(item, dict)]

    def _extract_reverse_product_info(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        """提取关键词反查产品信息。"""
        data = payload.get("data") if payload else None
        if not isinstance(data, dict):
            return {}
        monthly = data.get("monthlyDto")
        return dict(monthly) if isinstance(monthly, dict) else {}

    def _extract_reverse_variations(self, payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        """提取关键词反查变体 ASIN。"""
        data = payload.get("data") if payload else None
        if not isinstance(data, dict):
            return []
        variations = data.get("variations")
        return [item for item in variations if isinstance(item, dict)] if isinstance(variations, list) else []

    def _extract_reverse_stats(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        """提取关键词反查统计信息。"""
        data = payload.get("data") if payload else None
        if not isinstance(data, dict):
            return {}
        stat = data.get("statDto")
        return dict(stat) if isinstance(stat, dict) else {}

    def _extract_keyword_trends(self, payload: dict[str, Any] | None, *, limit: int) -> list[dict[str, Any]]:
        """提取关键词趋势数据。"""
        return [
            {
                "keyword": item.get("keyword"),
                "trends": item.get("trends") or [],
            }
            for item in self._keyword_items(payload)[:limit]
        ]

    def _extract_competitor_asins(self, payload: dict[str, Any] | None, *, limit: int) -> list[dict[str, Any]]:
        """提取关键词关联竞品 ASIN。"""
        competitors: list[dict[str, Any]] = []
        for item in self._keyword_items(payload)[:limit]:
            keyword = item.get("keyword")
            for asin_item in item.get("monopolyAsinDtos") or []:
                if isinstance(asin_item, dict):
                    row = dict(asin_item)
                    row["source_keyword"] = keyword
                    competitors.append(row)
        return competitors

    def _build_market_summary(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        """生成给 Agent 快速读取的市场摘要。"""
        items = self._keyword_items(payload) if payload and "keyword" in str(payload.get("data", {})) else self._reverse_keyword_items(payload)
        return {
            "total": payload.get("data", {}).get("total") if payload else None,
            "item_count": len(items),
            "top_keywords": [(item.get("keyword") or item.get("keywords")) for item in items[:10]],
        }

    def _save_result(self, run_dir: Path, result: SellerSpriteCollectResult) -> None:
        """写入 result.json 和 manifest.json。"""
        run_dir.mkdir(parents=True, exist_ok=True)
        result_path = run_dir / "result.json"
        manifest_path = run_dir / "manifest.json"
        result_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        manifest = result.archive_manifest.to_dict() if result.archive_manifest else {}
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _build_run_id(self) -> str:
        """生成本地采集批次 ID。"""
        return datetime.now().strftime("%Y%m%d-%H%M%S")

    def _build_run_dir(self, options: SellerSpriteCollectOptions, run_id: str) -> Path:
        """生成本次采集输出目录。"""
        base_dir = Path(options.output_dir).expanduser() if options.output_dir else self.runs_dir
        if not base_dir.is_absolute():
            base_dir = Path.cwd() / base_dir
        return base_dir.resolve() / f"seller-sprite-{run_id}"

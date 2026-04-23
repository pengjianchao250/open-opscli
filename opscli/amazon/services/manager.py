"""amazon 模块业务编排层。"""

from __future__ import annotations

import json
from pathlib import Path

from opscli.amazon.domain.models import AmazonCollectResult, AmazonProductSnapshot, AmazonSearchResult
from opscli.amazon.scraping.scraper import AmazonScraper
from opscli.amazon.transport.client import AmazonOpsClient
from opscli.config import CONFIG_DIR


class AmazonManager:
    """协调抓取、本地落盘和远端提交。"""

    def __init__(
        self,
        *,
        base_dir: Path | None = None,
        scraper: AmazonScraper | None = None,
        client: AmazonOpsClient | None = None,
    ) -> None:
        self.base_dir = Path(base_dir or CONFIG_DIR)
        self.data_dir = self.base_dir / "amazon"
        self.history_dir = self.data_dir / "history"
        self.scraper = scraper or AmazonScraper()
        self.client = client or AmazonOpsClient()

    def scrape_product(
        self,
        *,
        asin: str,
        zip_code: str = "10001",
        save_history: bool = True,
    ) -> AmazonCollectResult:
        """抓取单个商品并可选写历史。"""
        snapshot = self.scraper.scrape_product(asin, zip_code)
        history_path = self._append_history(snapshot) if save_history else None
        return AmazonCollectResult(snapshot=snapshot, history_path=history_path)

    def scrape_and_submit(
        self,
        *,
        asin: str,
        zip_code: str = "10001",
        endpoint: str | None = None,
        save_history: bool = True,
    ) -> AmazonCollectResult:
        """抓取后直接提交到 ops。"""
        result = self.scrape_product(asin=asin, zip_code=zip_code, save_history=save_history)
        result.submit_result = self.client.submit_snapshot(result.snapshot, endpoint=endpoint)
        return result

    def build_submit_payload(self, snapshot: AmazonProductSnapshot) -> dict:
        """构造未来提交到 ops 的标准 payload。"""
        return {
            "source": "opscli.amazon",
            "snapshot": snapshot.to_dict(include_raw=True),
        }

    def scrape_payload(
        self,
        *,
        asin: str,
        zip_code: str = "10001",
        save_history: bool = True,
    ) -> dict:
        """抓取商品并输出未来用于提交 ops 的 payload。"""
        result = self.scrape_product(asin=asin, zip_code=zip_code, save_history=save_history)
        return {
            "payload": self.build_submit_payload(result.snapshot),
            "history_path": str(result.history_path) if result.history_path else None,
        }

    def search_products(
        self,
        *,
        keyword: str,
        zip_code: str = "10001",
        limit: int = 10,
    ) -> list[AmazonSearchResult]:
        """搜索竞品列表。"""
        return self.scraper.search_products(keyword, max_results=limit, zip_code=zip_code)

    def load_history(self, asin: str) -> list[dict]:
        """读取本地历史快照。"""
        history_path = self.history_dir / f"{asin.upper()}.jsonl"
        if not history_path.exists():
            return []
        records: list[dict] = []
        for line in history_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(json.loads(line))
        return records

    def _append_history(self, snapshot: AmazonProductSnapshot) -> Path:
        """将快照附加写入本地历史文件。"""
        self.history_dir.mkdir(parents=True, exist_ok=True)
        history_path = self.history_dir / f"{snapshot.asin.upper()}.jsonl"
        with history_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(snapshot.to_dict(include_raw=True), ensure_ascii=False))
            fh.write("\n")
        return history_path

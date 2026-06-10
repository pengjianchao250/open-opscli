"""Amazon Rufus 数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Marketplace:
    """Amazon 国家站点映射。"""

    country: str
    base_url: str


@dataclass(frozen=True)
class Question:
    """默认题目。"""

    id: int
    text: str
    position: int


@dataclass(frozen=True)
class QuestionTemplate:
    """合并题目后的模板。"""

    id: int
    description: str
    preferred_version_index: int
    questions: list[Question] = field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class SeedRequestRecord:
    """Rufus seed request 捕获结果。"""

    request_url: str
    request_headers: dict[str, str]
    request_body: str
    page_url: str
    tab_id: str
    asin: str
    country: str
    captured_at: int

    def to_dict(self) -> dict:
        """转换为 JSON 结构。"""
        return asdict(self)


@dataclass(frozen=True)
class ParsedCurlRufusRequest:
    """从浏览器 Copy-as-cURL 中解析出的 Rufus 请求材料。"""

    url: str
    headers: dict[str, str]
    cookies: str
    payload_template: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """转换为可本地保存的结构。"""
        return {
            "url": self.url,
            "headers": dict(self.headers),
            "cookies": self.cookies,
            "payload_template": self.payload_template,
        }


@dataclass(frozen=True)
class AnswerData:
    """Rufus 回答结构。"""

    text: str
    html: str = ""
    summary_text: str = ""
    product_links: list[str] = field(default_factory=list)
    recommended_asins: list[str] = field(default_factory=list)
    blocks: list[dict] = field(default_factory=list)
    is_success: bool = True
    thread_id: str | None = None

    def to_dict(self) -> dict:
        """转换为前端兼容字段。"""
        return {
            "text": self.text,
            "html": self.html,
            "summaryText": self.summary_text,
            "productLinks": self.product_links,
            "recommendedAsins": self.recommended_asins,
            "blocks": self.blocks,
            "isSuccess": self.is_success,
            "threadId": self.thread_id,
        }

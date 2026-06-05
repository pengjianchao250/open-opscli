"""西柚洞察接口场景注册表。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from opscli.xiyou.api.payloads import make_ranking_payload
from opscli.xiyou.domain.exceptions import XiyouConfigError


@dataclass(frozen=True)
class XiyouRankingScenario:
    """西柚洞察排行榜场景定义。"""

    function: str
    target: str
    title: str
    endpoint: str
    allowed_rank_patterns: tuple[str, ...]
    default_rank_pattern: str

    def to_public_dict(self) -> dict[str, Any]:
        """返回 MCP 可公开的场景说明。"""
        return asdict(self)

    def build_payload(
        self,
        *,
        site: str,
        period: str,
        rank_pattern: str | None,
        query: str,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        """构造排行榜 payload。"""
        normalized_rank_pattern = self.normalize_rank_pattern(rank_pattern)
        return make_ranking_payload(
            {
                "site": site,
                "period": period,
                "rank_pattern": normalized_rank_pattern,
                "query": query,
                "page": page,
                "page_size": page_size,
            }
        )

    def normalize_rank_pattern(self, value: str | None) -> str:
        """校验并返回排行榜类型。"""
        rank_pattern = (value or self.default_rank_pattern).lower()
        if rank_pattern not in self.allowed_rank_patterns:
            allowed = ", ".join(self.allowed_rank_patterns)
            raise XiyouConfigError(f"{self.target} 排行榜 rank_pattern 仅支持：{allowed}")
        return rank_pattern


SCENARIOS: dict[str, XiyouRankingScenario] = {
    "asin": XiyouRankingScenario(
        function="ranking",
        target="asin",
        title="ASIN 排行榜",
        endpoint="/v2/rankingList/asins",
        allowed_rank_patterns=("flow", "surge"),
        default_rank_pattern="flow",
    ),
    "keyword": XiyouRankingScenario(
        function="ranking",
        target="keyword",
        title="关键词排行榜",
        endpoint="/v3/rankingList/searchTerms",
        allowed_rank_patterns=("aba", "surge"),
        default_rank_pattern="aba",
    ),
}


def list_scenarios() -> list[dict[str, Any]]:
    """列出可用排行榜场景。"""
    return [scenario.to_public_dict() for scenario in SCENARIOS.values()]


def get_scenario(target: str) -> XiyouRankingScenario:
    """按 target 获取排行榜场景。"""
    key = (target or "").lower()
    scenario = SCENARIOS.get(key)
    if not scenario:
        raise XiyouConfigError("ranking target 仅支持：asin, keyword")
    return scenario


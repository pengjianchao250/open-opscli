"""卖家精灵各列表场景的分页请求和响应合同。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opscli.seller_sprite.domain.exceptions import SellerSpriteConfigError


@dataclass(frozen=True)
class ScenarioPaginationContract:
    """描述一个场景的页字段、响应路径和可验证上限。"""

    scenario: str
    request_page_field: str | None
    request_size_field: str | None
    response_items_path: tuple[str, ...]
    response_total_paths: tuple[tuple[str, ...], ...]
    verified_access_limit: int | None = None
    response_page_validation: bool = False
    notes: str = ""

    def page_payload(self, payload: dict[str, Any], *, page: int, page_size: int) -> dict[str, Any]:
        """构造一页请求，保留查询筛选并覆盖场景实际使用的页字段。"""
        result = dict(payload)
        if self.request_page_field:
            result[self.request_page_field] = page
        if self.request_size_field:
            result[self.request_size_field] = page_size
        if self.scenario == "keyword-reverse":
            result["skip"] = (page - 1) * page_size
            result.pop("page", None)
            result.pop("pageNum", None)
            result.pop("pageNo", None)
        return result

    def parse(self, response: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
        """按本场景独立路径解析 rows 和 total。"""
        items = _path_value(response, self.response_items_path)
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise SellerSpriteConfigError(
                f"{self.scenario} 分页响应缺少有效 {'.'.join(self.response_items_path)}"
            )
        total = None
        for path in self.response_total_paths:
            candidate = _path_value(response, path)
            if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate >= 0:
                total = candidate
                break
        return items, total


PAGINATION_CONTRACTS: dict[str, ScenarioPaginationContract] = {
    "competitor-lookup": ScenarioPaginationContract(
        scenario="competitor-lookup",
        request_page_field="page",
        request_size_field="size",
        response_items_path=("data", "items"),
        response_total_paths=(("data", "total"),),
        verified_access_limit=2000,
        response_page_validation=True,
        notes="网页已验证前 2000 条；翻页总数仍需检测漂移。",
    ),
    "keyword-miner": ScenarioPaginationContract(
        scenario="keyword-miner",
        request_page_field="pageNum",
        request_size_field="pageSize",
        response_items_path=("data", "items"),
        response_total_paths=(("data", "total"),),
        notes="网页已验证可访问超过 2000 条；高频词请求是查询级附加请求。",
    ),
    "keyword-reverse": ScenarioPaginationContract(
        scenario="keyword-reverse",
        request_page_field=None,
        request_size_field="limit",
        response_items_path=("data", "items"),
        response_total_paths=(("data", "total"),),
        notes="使用 limit/skip；page 仅为本地编排字段。",
    ),
    "traffic-source": ScenarioPaginationContract(
        scenario="traffic-source",
        request_page_field="pageNo",
        request_size_field="pageSize",
        response_items_path=("data", "pager", "items"),
        response_total_paths=(("data", "pager", "total"), ("data", "total")),
        notes="历史响应可能返回 pager.page=0、size=null，不能强校验响应页字段。",
    ),
}


def get_pagination_contract(scenario: str) -> ScenarioPaginationContract:
    """获取已核验的普通 JSON 场景合同。"""
    try:
        return PAGINATION_CONTRACTS[scenario]
    except KeyError as exc:
        raise SellerSpriteConfigError(f"场景 {scenario} 尚未注册分页合同") from exc


def _path_value(value: Any, path: tuple[str, ...]) -> Any:
    """读取嵌套响应路径。"""
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current

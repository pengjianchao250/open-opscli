"""卖家精灵各列表场景的分页请求和响应合同。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from opscli.seller_sprite.domain.exceptions import (
    SellerSpriteApiError,
    SellerSpriteConfigError,
    SellerSpriteTaskTimeoutError,
)


MAX_ACCESS_ROWS = 2000
MAX_PAGE_BYTES = 8 * 1024 * 1024
PAGE_SIZE = 100


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


def atomic_json(path: Path, value: Any) -> None:
    """原子写入分页原始响应，避免异常退出留下半个 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class ScenarioPagination:
    """按独立场景合同获取最多 2,000 行，并支持逐页恢复。"""

    def __init__(
        self,
        *,
        root: Path,
        task_root: Path,
        account_key: str,
        request_identity: dict[str, Any],
        payload: dict[str, Any],
        contract: ScenarioPaginationContract,
        page_size: int,
        timeout_seconds: float,
        checkpoint: dict[str, Any] | None = None,
        save_checkpoint: Any = None,
        progress: Any = None,
    ) -> None:
        if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size <= 0:
            raise SellerSpriteConfigError("分页 page_size 必须是正整数")
        self.root = root.resolve()
        self.task_root = task_root.resolve()
        self.contract = contract
        self.page_size = page_size
        self.save_checkpoint = save_checkpoint
        self.progress = progress
        identity = _fingerprint(request_identity)
        self.state = (
            json.loads(json.dumps(checkpoint, ensure_ascii=False))
            if checkpoint
            else {
                "version": 1,
                "identity": identity,
                "scenario": contract.scenario,
                "account_key": account_key,
                "payload": payload,
                "page_size": page_size,
                "deadline": time.time() + timeout_seconds,
                "pages": [],
                "attempts": {},
                "source_total": None,
                "rows_received": 0,
                "rows_written": 0,
                "duplicate_count": 0,
                "drift": False,
                "finished": False,
                "stop_reason": "collecting",
            }
        )
        if (
            self.state.get("version") != 1
            or self.state.get("identity") != identity
            or self.state.get("scenario") != contract.scenario
            or int(self.state.get("page_size", page_size)) != page_size
        ):
            raise SellerSpriteConfigError("分页恢复检查点与查询条件不一致")
        self.remaining()
        if self.state.get("account_key") != account_key:
            if self.state.get("pages"):
                raise SellerSpriteConfigError("分页已有数据，不能切换账号拼接结果")
            self.state["account_key"] = account_key
        self.seen: set[str] = set()
        for index, page in enumerate(self.state.get("pages", []), 1):
            if int(page.get("page", 0)) != index:
                raise SellerSpriteConfigError("分页恢复检查点页码不连续")
            rows, _ = self.contract.parse(self._read_page(page))
            self.seen.update(_row_fingerprint(row) for row in rows)

    def _read_page(self, page: dict[str, Any]) -> dict[str, Any]:
        path = (self.task_root / str(page["path"])).resolve()
        if not path.is_relative_to(self.task_root) or path.stat().st_size > MAX_PAGE_BYTES:
            raise SellerSpriteConfigError("分页检查点页面路径或文件大小异常")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != page.get("sha256"):
            raise SellerSpriteConfigError("分页检查点页面校验失败，请重新发起任务")
        return json.loads(content)

    def remaining(self) -> float:
        remaining = float(self.state["deadline"]) - time.time()
        if remaining <= 0:
            raise SellerSpriteTaskTimeoutError("分页任务累计执行时间已超过上限")
        return remaining

    def summary(self) -> dict[str, Any]:
        total = self.state.get("source_total")
        complete = bool(self.state.get("finished") and not self.state.get("drift") and not self.state.get("duplicate_count"))
        if self.state.get("drift") or self.state.get("duplicate_count"):
            coverage = "unverified"
        elif not complete:
            coverage = "partial"
        elif total is not None and total > MAX_ACCESS_ROWS:
            coverage = "source_limited"
        elif total is None:
            coverage = "unverified"
        else:
            coverage = "matched_range"
        return {
            "scope": "all",
            "scenario": self.contract.scenario,
            "source_total": total,
            "access_limit": MAX_ACCESS_ROWS,
            "target_rows": min(total, MAX_ACCESS_ROWS) if isinstance(total, int) else MAX_ACCESS_ROWS,
            "page_size": self.page_size,
            "current_page": max((int(page) for page in self.state.get("attempts", {})), default=0),
            "pages_completed": len(self.state.get("pages", [])),
            "page_requests": sum(int(value) for value in self.state.get("attempts", {}).values()),
            "rows_received": int(self.state.get("rows_received", 0)),
            "rows_written": int(self.state.get("rows_written", 0)),
            "duplicate_count": int(self.state.get("duplicate_count", 0)),
            "collection_complete": complete,
            "coverage": coverage,
            "stop_reason": self.state.get("stop_reason", "collecting"),
        }

    def persist(self) -> None:
        self.state["collection"] = self.summary()
        atomic_json(self.root / "raw.json", {"version": 1, "kind": "scenario-pages", **self.state})
        if self.save_checkpoint:
            self.save_checkpoint(self.state)

    async def collect(self, fetch: Any, *, cooldown_seconds: float = 0) -> None:
        self.persist()
        while not self.state.get("finished"):
            self.remaining()
            page_number = len(self.state.get("pages", [])) + 1
            target = self.state.get("source_total")
            if isinstance(target, int):
                target = min(target, MAX_ACCESS_ROWS)
                if (page_number - 1) * self.page_size >= target:
                    self.state.update(finished=True, stop_reason="access_limit" if self.state.get("source_total", 0) > MAX_ACCESS_ROWS else "total_reached")
                    self.persist()
                    break
            elif (page_number - 1) * self.page_size >= MAX_ACCESS_ROWS:
                self.state.update(finished=True, stop_reason="access_limit")
                self.persist()
                break
            attempt = int(self.state.get("attempts", {}).get(str(page_number), 0))
            if attempt >= 3:
                raise SellerSpriteConfigError("当前分页重试预算已耗尽")
            self.state.setdefault("attempts", {})[str(page_number)] = attempt + 1
            self.persist()
            if self.progress:
                self.progress("requesting", {"current_page": page_number, "rows_received": self.state.get("rows_received", 0)})
            page_payload = self.contract.page_payload(self.state["payload"], page=page_number, page_size=self.page_size)
            try:
                response = await asyncio.wait_for(fetch(page_payload, self.root / "requests" / f"page-{page_number:03d}-{attempt + 1}"), timeout=self.remaining())
            except asyncio.TimeoutError as exc:
                self.state.update(stop_reason="timeout")
                self.persist()
                raise SellerSpriteTaskTimeoutError("分页请求超过任务时间上限，已保留分页检查点") from exc
            except asyncio.CancelledError:
                self.state.update(stop_reason="cancelled")
                self.persist()
                raise
            except SellerSpriteApiError as exc:
                if exc.status_code not in {502, 503, 504} or attempt >= 2:
                    raise
                await asyncio.sleep(min(max(cooldown_seconds, 2**attempt), self.remaining()))
                continue
            encoded = json.dumps(response, ensure_ascii=False).encode("utf-8")
            if len(encoded) > MAX_PAGE_BYTES:
                raise SellerSpriteConfigError("分页单页响应超过8MiB，已停止以限制内存占用")
            rows, total = self.contract.parse(response)
            if len(rows) > self.page_size:
                raise SellerSpriteConfigError("分页响应行数超过请求 page_size")
            if self.state.get("source_total") is None:
                self.state["source_total"] = total
            elif total is not None and total != self.state.get("source_total"):
                self.state.update(drift=True, finished=True, stop_reason="total_drift")
            for row in rows:
                key = _row_fingerprint(row)
                if key in self.seen:
                    self.state["duplicate_count"] = int(self.state.get("duplicate_count", 0)) + 1
                self.seen.add(key)
            path = self.root / "pages" / f"page-{page_number:03d}.json"
            atomic_json(path, response)
            self.state.setdefault("pages", []).append({"page": page_number, "path": path.relative_to(self.task_root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "row_count": len(rows)})
            self.state["rows_received"] = int(self.state.get("rows_received", 0)) + len(rows)
            target_rows = self.state.get("source_total")
            if not isinstance(target_rows, int):
                target_rows = MAX_ACCESS_ROWS
            self.state["rows_written"] = min(len(self.seen), target_rows, MAX_ACCESS_ROWS)
            if self.state.get("drift"):
                self.state.update(finished=True, stop_reason="total_drift")
            elif self.state.get("duplicate_count"):
                self.state.update(finished=True, stop_reason="inconsistent_pages")
            elif not rows or len(rows) < self.page_size:
                self.state.update(finished=True, stop_reason="short_page")
            elif isinstance(self.state.get("source_total"), int) and page_number * self.page_size >= min(int(self.state["source_total"]), MAX_ACCESS_ROWS):
                self.state.update(finished=True, stop_reason="access_limit" if int(self.state["source_total"]) > MAX_ACCESS_ROWS else "total_reached")
            elif page_number * self.page_size >= MAX_ACCESS_ROWS:
                self.state.update(finished=True, stop_reason="access_limit")
            self.persist()

    def iter_rows(self):
        seen: set[str] = set()
        target_rows = self.state.get("source_total")
        if not isinstance(target_rows, int):
            target_rows = MAX_ACCESS_ROWS
        target_rows = min(target_rows, MAX_ACCESS_ROWS)
        if target_rows <= 0:
            return
        for page in self.state.get("pages", []):
            rows, _ = self.contract.parse(self._read_page(page))
            for row in rows:
                key = _row_fingerprint(row)
                if key not in seen:
                    seen.add(key)
                    yield row
                    if len(seen) >= target_rows:
                        return


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _row_fingerprint(row: dict[str, Any]) -> str:
    return _fingerprint(row)


PAGINATION_CONTRACTS: dict[str, ScenarioPaginationContract] = {
    "aba-research": ScenarioPaginationContract(
        scenario="aba-research",
        request_page_field="page",
        request_size_field="size",
        response_items_path=("data", "items"),
        response_total_paths=(("data", "total"),),
        notes="网页已确认 page/size 可翻页；周期、排序和筛选条件必须冻结。",
    ),
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
    "association-traffic": ScenarioPaginationContract(
        scenario="association-traffic",
        request_page_field="pageNum",
        request_size_field="pageSize",
        response_items_path=("data", "pagerDto", "items"),
        response_total_paths=(("data", "pagerDto", "total"),),
        notes="网页请求已确认支持 pageNum/pageSize；全部变体和排序条件必须跨页冻结。",
    ),
    "traffic-source": ScenarioPaginationContract(
        scenario="traffic-source",
        request_page_field="pageNo",
        request_size_field="pageSize",
        response_items_path=("data", "pager", "items"),
        response_total_paths=(("data", "pager", "total"), ("data", "total")),
        notes="历史响应可能返回 pager.page=0、size=null，不能强校验响应页字段。",
    ),
    "keyword-research": ScenarioPaginationContract(
        scenario="keyword-research",
        request_page_field="page",
        request_size_field="size",
        response_items_path=("data", "items"),
        response_total_paths=(("data", "total"),),
        notes="HTML 页面分页；total 缺失时以短页或 2,000 行安全上限结束并标记 unverified。",
    ),
    "market-research": ScenarioPaginationContract(
        scenario="market-research",
        request_page_field="page",
        request_size_field="size",
        response_items_path=("data", "items"),
        response_total_paths=(("data", "total"),),
        notes="HTML 表单分页；total 缺失时以短页或 2,000 行安全上限结束并标记 unverified。",
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

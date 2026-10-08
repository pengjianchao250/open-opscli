"""选产品专用分页合同、磁盘检查点与有界行迭代。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from opscli.seller_sprite.domain.exceptions import (
    SellerSpriteApiError,
    SellerSpriteConfigError,
    SellerSpriteTaskTimeoutError,
)

ACCESS_LIMIT = 2000
PAGE_SIZE = 100
MAX_PAGE_BYTES = 8 * 1024 * 1024


def fingerprint(value: Any) -> str:
    """为冻结条件生成稳定摘要，不保存认证信息。"""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    """先完整写入临时文件，再原子替换，最后由调用方提交检查点。"""
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


def parse_product_page(response: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """仅接受选产品 data.items/data.total，禁止套用其他场景的 pager。"""
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise SellerSpriteConfigError("选产品分页响应缺少 data.items")
    total = data.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise SellerSpriteConfigError("选产品分页响应缺少有效 data.total")
    rows = data["items"]
    if len(rows) > PAGE_SIZE or any(not isinstance(row, dict) for row in rows):
        raise SellerSpriteConfigError("选产品分页响应行结构或数量异常")
    return rows, total


class ProductPagination:
    """逐页保存原始响应，以小检查点恢复同账号同查询的采集。"""

    def __init__(
        self,
        *,
        root: Path,
        task_root: Path,
        account_key: str,
        request_identity: dict[str, Any],
        payload: dict[str, Any],
        timeout_seconds: float,
        checkpoint: dict[str, Any] | None = None,
        save_checkpoint: Callable[[dict[str, Any]], None] | None = None,
        progress: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.task_root = task_root.resolve()
        self.save_checkpoint = save_checkpoint
        self.progress = progress
        self.seen: set[str] = set()
        identity = fingerprint(request_identity)
        self.state = (
            json.loads(json.dumps(checkpoint))
            if checkpoint
            else {
                "version": 1,
                "identity": identity,
                "account_key": account_key,
                "payload": payload,
                "deadline": time.time() + timeout_seconds,
                "pages": [],
                "attempts": {},
                "source_total": None,
                "rows_received": 0,
                "rows_written": 0,
                "duplicate_count": 0,
                "drift": False,
                "finished": False,
            }
        )
        if self.state.get("version") != 1 or self.state.get("identity") != identity:
            raise SellerSpriteConfigError("选产品恢复检查点与查询条件不一致")
        self.remaining()
        if self.state["account_key"] != account_key:
            if self.state["pages"]:
                raise SellerSpriteConfigError(
                    "选产品分页已有数据，不能切换账号拼接结果"
                )
            self.state["account_key"] = account_key
        if len(self.state["pages"]) > ACCESS_LIMIT // PAGE_SIZE:
            raise SellerSpriteConfigError("选产品恢复检查点超过网页访问上限")
        for index, page in enumerate(self.state["pages"], 1):
            if page["page"] != index:
                raise SellerSpriteConfigError("选产品恢复检查点页码不连续")
            rows, _ = parse_product_page(self._read_page(page))
            self.seen.update(self._asin(row) for row in rows)

    @staticmethod
    def _asin(row: dict[str, Any]) -> str:
        """按子 ASIN 判重；不合并同父体的不同变体。"""
        asin = row.get("asin")
        if not isinstance(asin, str) or not asin.strip() or len(asin) > 32:
            raise SellerSpriteConfigError("选产品分页行缺少有效 ASIN，无法确认完整性")
        return asin.strip().upper()

    def _read_page(self, page: dict[str, Any]) -> dict[str, Any]:
        """读取一页并验证路径与内容摘要，拒绝损坏文件和越界路径。"""
        path = (self.task_root / page["path"]).resolve()
        if (
            not path.is_relative_to(self.task_root)
            or path.stat().st_size > MAX_PAGE_BYTES
        ):
            raise SellerSpriteConfigError("选产品检查点页面路径或文件大小异常")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != page["sha256"]:
            raise SellerSpriteConfigError("选产品检查点页面校验失败，请重新发起任务")
        return json.loads(content)

    def summary(self) -> dict[str, Any]:
        """只公开计数与完整性，不暴露账号、条件、文件路径。"""
        state = self.state
        total = state["source_total"]
        last_total = state.get("source_total_last", total)
        total_changed = state.get("total_changed", False)
        complete = bool(
            state["finished"] and not state["drift"] and not state["duplicate_count"]
            and not total_changed
        )
        coverage = (
            "unverified"
            if state["drift"] or state["duplicate_count"] or total_changed
            else "partial"
            if not complete
            else "source_limited"
            if total > ACCESS_LIMIT
            else "matched_range"
        )
        return {
            "scope": "all",
            "source_total": total,
            "source_total_last": last_total,
            "total_changed": total_changed,
            "access_limit": ACCESS_LIMIT,
            "target_rows": min(last_total, ACCESS_LIMIT) if last_total is not None else None,
            "page_size": PAGE_SIZE,
            "current_page": max((int(page) for page in state["attempts"]), default=0),
            "planned_pages": max(
                1, (min(last_total, ACCESS_LIMIT) + PAGE_SIZE - 1) // PAGE_SIZE
            )
            if total is not None
            else None,
            "pages_completed": len(state["pages"]),
            "page_requests": sum(state["attempts"].values()),
            "retry_requests": sum(
                max(0, count - 1) for count in state["attempts"].values()
            ),
            "rows_received": state["rows_received"],
            "rows_written": state["rows_written"],
            "duplicate_count": state["duplicate_count"],
            "collection_complete": complete,
            "coverage": coverage,
            "stop_reason": state.get("stop_reason", "collecting"),
        }

    def persist(self) -> None:
        """清单先落盘，SQLite 回调最后提交，旧代际无法推进有效检查点。"""
        self.state["collection"] = self.summary()
        atomic_json(
            self.root / "raw.json",
            {"version": 1, "kind": "product-pages", **self.state},
        )
        if self.save_checkpoint:
            self.save_checkpoint(self.state)

    def remaining(self) -> float:
        """恢复时不重置任务总时限；停机时间也计入预算。"""
        remaining = self.state["deadline"] - time.time()
        if remaining <= 0:
            raise SellerSpriteTaskTimeoutError("选产品分页任务累计执行时间已超过上限")
        return remaining

    async def collect(
        self,
        fetch: Callable[[dict[str, Any], Path], Awaitable[dict[str, Any]]],
        *,
        cooldown_seconds: float = 0,
    ) -> None:
        """顺序请求至目标末页；只对临时服务故障进行最多两次额外重试。"""
        self.persist()
        while not self.state["finished"]:
            self.remaining()
            page_number = len(self.state["pages"]) + 1
            if page_number > ACCESS_LIMIT // PAGE_SIZE:
                raise SellerSpriteConfigError("选产品分页不可超过网页前2000条")
            payload = {**self.state["payload"], "page": page_number, "size": PAGE_SIZE}
            attempt = self.state["attempts"].get(str(page_number), 0)
            if attempt >= 3:
                raise SellerSpriteConfigError("选产品当前页重试预算已耗尽")
            self.state["attempts"][str(page_number)] = attempt + 1
            self.persist()
            if self.progress:
                self.progress(
                    "requesting",
                    {
                        "current_page": page_number,
                        "rows_received": self.state["rows_received"],
                    },
                )
            try:
                response = await asyncio.wait_for(
                    fetch(
                        payload,
                        self.root
                        / "requests"
                        / f"page-{page_number:03d}-{attempt + 1}",
                    ),
                    timeout=self.remaining(),
                )
            except SellerSpriteApiError as exc:
                # 429 交给已有浏览器冷却机制；认证、额度、业务错误均不盲目重试。
                if exc.status_code not in {502, 503, 504} or attempt >= 2:
                    raise
                await asyncio.sleep(
                    min(max(cooldown_seconds, 2**attempt), self.remaining())
                )
                continue
            rows, total = parse_product_page(response)
            for field, expected_value in (("page", page_number), ("size", PAGE_SIZE)):
                if (
                    field in response["data"]
                    and response["data"][field] != expected_value
                ):
                    raise SellerSpriteConfigError(f"选产品响应 {field} 与请求不一致")
            encoded = json.dumps(response, ensure_ascii=False).encode("utf-8")
            if len(encoded) > MAX_PAGE_BYTES:
                raise SellerSpriteConfigError(
                    "选产品单页响应超过8MiB，已停止以限制内存占用"
                )
            if self.state["source_total"] is None:
                self.state["source_total"] = total
            self.state["source_total_last"] = total
            # 总数可能实时波动；保留发生过变化的事实，按最新总数判断自然末页。
            # 行数异常仍停止，不能因放宽总数检查而接受漏页；最多请求 20 页。
            self.state["total_changed"] = (
                self.state.get("total_changed", False)
                or total != self.state["source_total"]
            )
            target = min(total, ACCESS_LIMIT)
            expected = min(PAGE_SIZE, max(0, target - (page_number - 1) * PAGE_SIZE))
            self.state["drift"] |= len(rows) != expected
            for row in rows:
                asin = self._asin(row)
                if asin in self.seen:
                    self.state["duplicate_count"] += 1
                self.seen.add(asin)
            path = self.root / "pages" / f"page-{page_number:03d}.json"
            atomic_json(path, response)
            self.state["pages"].append(
                {
                    "page": page_number,
                    "path": path.relative_to(self.task_root).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "row_count": len(rows),
                }
            )
            self.state["rows_received"] += len(rows)
            self.state["rows_written"] = len(self.seen)
            if self.state["drift"] or self.state["duplicate_count"]:
                self.state.update(finished=True, stop_reason="inconsistent_pages")
            elif page_number * PAGE_SIZE >= target:
                self.state.update(
                    finished=True,
                    stop_reason="access_limit"
                    if total > ACCESS_LIMIT
                    else "total_reached",
                )
            self.persist()

    def iter_rows(self) -> Iterator[dict[str, Any]]:
        """每次只加载一页，ASIN 判重集合最多2000个。"""
        seen: set[str] = set()
        for page in self.state["pages"]:
            rows, _ = parse_product_page(self._read_page(page))
            for row in rows:
                asin = self._asin(row)
                if asin not in seen:
                    seen.add(asin)
                    yield row

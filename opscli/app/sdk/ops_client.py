"""AppHub 应用双模式取数客户端。"""

from __future__ import annotations

from typing import Any

import httpx

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.sdk.context import detect_headers
from opscli.auth.config import get_ops_url
from opscli.query.services.manager import QueryManager


class OpsClient:
    """有 X-Ops-Token 时走 viewer；否则复用开发者本地登录态。"""

    def __init__(
        self,
        *,
        request: Any | None = None,
        viewer_token: str | None = None,
        ops_url: str | None = None,
        http_client: httpx.Client | None = None,
        query_manager: QueryManager | None = None,
    ) -> None:
        headers = detect_headers(request)
        self.viewer_token = viewer_token or headers.get("x-ops-token")
        self.ops_url = (ops_url or get_ops_url()).rstrip("/")
        self.http = http_client or httpx.Client(timeout=60)
        self._owns_http = http_client is None
        self.query_manager = query_manager

    def close(self) -> None:
        if self._owns_http:
            self.http.close()

    def metadata(self, *, dataset_alias: str | None = None, table_id: int | None = None) -> dict:
        if self.viewer_token:
            response = self.http.get(
                f"{self.ops_url}/v1/data-metrics/viewer/query-metadata",
                headers={"X-Ops-Token": self.viewer_token},
                params={
                    **({"dataset_alias": dataset_alias} if dataset_alias else {}),
                    **({"table_id": table_id} if table_id is not None else {}),
                },
            )
            return _response_json(response)
        return self._local_manager().metadata(dataset_alias=dataset_alias, table_id=table_id).to_dict()

    def query(
        self,
        dataset_alias: str | None = None,
        *,
        table_id: int | None = None,
        dimensions: list[dict] | list[str] | None = None,
        metrics: list[dict] | list[str] | None = None,
        filters: list[dict] | None = None,
        data_comparison: dict | None = None,
        order_by: list[dict] | None = None,
        limit: int = 20,
        offset: int = 0,
        global_currency: str | None = None,
    ) -> dict:
        resolved_table_id = table_id
        if resolved_table_id is None:
            metadata = self.metadata(dataset_alias=dataset_alias)
            dataset = metadata.get("dataset") or _find_dataset(metadata, dataset_alias)
            if not dataset or dataset.get("table_id") is None:
                raise AppProjectError("DATASET_NOT_FOUND", f"未找到数据集：{dataset_alias}")
            resolved_table_id = int(dataset["table_id"])
        payload = {
            "tableId": int(resolved_table_id),
            "dimensions": _normalize_fields(dimensions),
            "metrics": _normalize_fields(metrics),
            "filters": filters or [],
            "dataComparison": data_comparison,
            "orderBy": order_by or [],
            "limit": limit,
            "offset": offset,
        }
        if global_currency:
            payload["globalCurrency"] = global_currency
        payload = {key: value for key, value in payload.items() if value is not None}
        if self.viewer_token:
            response = self.http.post(
                f"{self.ops_url}/v1/data-metrics/viewer/cli-query/simple",
                headers={"X-Ops-Token": self.viewer_token},
                json=payload,
            )
            return _response_json(response)
        return self._local_manager().client.cli_simple_query(payload)

    def query_df(self, *args, **kwargs):
        try:
            import pandas as pd
        except ImportError as exc:
            raise AppProjectError(
                "PKG-001",
                "query_df() 需要 pandas。",
                fix_hint="安装 pandas，或改用 query()。",
            ) from exc
        result = self.query(*args, **kwargs)
        return pd.DataFrame(_extract_rows(result))

    def _local_manager(self) -> QueryManager:
        if self.query_manager is None:
            self.query_manager = QueryManager()
        return self.query_manager


def ops_client(request: Any | None = None) -> OpsClient:
    return OpsClient(request=request)


def _normalize_fields(items: list[dict] | list[str] | None) -> list[dict]:
    normalized: list[dict] = []
    for item in items or []:
        if isinstance(item, dict):
            normalized.append(dict(item))
        else:
            field = str(item)
            normalized.append({"field": field, "alias": field.rsplit(".", 1)[-1]})
    return normalized


def _find_dataset(metadata: dict, alias: str | None) -> dict | None:
    for item in metadata.get("datasets") or metadata.get("all_datasets") or []:
        if alias is None or item.get("dataset_alias") == alias:
            return item
    return None


def _response_json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise AppProjectError("OPS-DATA-PROTOCOL", "取数服务返回了无效 JSON。") from exc
    if response.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        source = detail if isinstance(detail, dict) else payload if isinstance(payload, dict) else {}
        raise AppProjectError(
            str(source.get("code") or f"HTTP-{response.status_code}"),
            str(source.get("message") or "取数服务请求失败。"),
            fix_hint=source.get("fix_hint"),
        )
    if not isinstance(payload, dict):
        raise AppProjectError("OPS-DATA-PROTOCOL", "取数服务 JSON 响应必须是对象。")
    return payload


def _extract_rows(payload: dict) -> list[dict]:
    candidates = [
        (((payload.get("result") or {}).get("data") or {}).get("rows")),
        ((payload.get("data") or {}).get("rows")),
        ((payload.get("result") or {}).get("rows")),
        payload.get("rows"),
        payload.get("data") if isinstance(payload.get("data"), list) else None,
    ]
    for rows in candidates:
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    return []

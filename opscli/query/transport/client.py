"""query 模块远端请求客户端。"""

from __future__ import annotations

import httpx

from opscli.auth import AuthClient, OPS_URL
from opscli.mcp.context import get_mcp_request_headers
from opscli.query.domain.exceptions import BadRemoteJsonError, RemoteBusinessError, RemoteHttpError
from opscli.shared.http import parse_remote_response


class QueryClient:
    """统一封装 query 模块的远端请求。

    支持无状态模式：通过外部传入的 jwt 和 session_id 构造请求头，
    不依赖本地 CredentialStore。适用于远程共享 MCP 服务器场景。
    """

    def __init__(
        self,
        auth_client: AuthClient | None = None,
        jwt: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.auth_client = auth_client or AuthClient()
        self.jwt = jwt
        self.session_id = session_id
        self.ops_url = OPS_URL.rstrip("/")

    def _get_auth(self, alias: str = "ops") -> tuple[dict[str, str], dict[str, str]]:
        """获取请求认证头。优先使用外部传入的凭证，否则回退到本地存储。

        无状态模式下：只要有 session_id，就优先使用它；如果 jwt 缺失，
        自动用 session_id 向后端换取，不依赖本地 CredentialStore。
        """
        if self.session_id:
            jwt = self.jwt
            if not jwt:
                # 无状态模式：用 session_id 实时向后端换取 JWT
                jwt = self.auth_client.get_token_by_session(self.session_id, alias)
            headers = {"Authorization": f"Bearer {jwt}"}
            headers.update(get_mcp_request_headers())
            cookies = {"polarisUserToken": self.session_id}
            return headers, cookies
        headers, cookies = self.auth_client.build_request_auth(alias)
        headers.update(get_mcp_request_headers())
        return headers, cookies

    def fetch_chart_bundle(self, chart_uuid: str) -> dict:
        """通过 chart_uuid 获取图表查询结构，兼容新旧两种返回格式。"""
        headers, cookies = self._get_auth("ops")
        response = httpx.get(
            f"{self.ops_url}/v1/data-metrics/cli-query/latest-request-data",
            params={"chart_uuid": chart_uuid},
            headers=headers,
            cookies=cookies,
            timeout=20,
        )
        payload = parse_remote_response(
            response,
            http_error_cls=RemoteHttpError,
            business_error_cls=RemoteBusinessError,
            bad_json_error_cls=BadRemoteJsonError,
        )
        data = payload.get("data")
        if isinstance(data, list):
            return self._normalize_legacy_chart_bundle(chart_uuid, data)
        if isinstance(data, dict):
            return self._normalize_chart_bundle(chart_uuid, data)
        raise BadRemoteJsonError("远端返回的 chart query 数据结构既不是数组也不是对象")

    def fetch_dataset_catalog(self) -> dict:
        """从远端拉取数据集业务语义索引。"""
        headers, cookies = self._get_auth("ops")
        response = httpx.get(
            f"{self.ops_url}/v1/data-metrics/datasets/skill/catalog",
            headers=headers,
            cookies=cookies,
            timeout=20,
        )
        payload = parse_remote_response(
            response,
            http_error_cls=RemoteHttpError,
            business_error_cls=RemoteBusinessError,
            bad_json_error_cls=BadRemoteJsonError,
        )
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    def fetch_user_preferences(self) -> list[dict]:
        """从远端获取当前用户的图表字段偏好列表。"""
        headers, cookies = self._get_auth("ops")
        response = httpx.get(
            f"{self.ops_url}/v1/data-metrics/cli-query/user-preferences",
            headers=headers,
            cookies=cookies,
            timeout=20,
        )
        payload = parse_remote_response(
            response,
            http_error_cls=RemoteHttpError,
            business_error_cls=RemoteBusinessError,
            bad_json_error_cls=BadRemoteJsonError,
        )
        data = payload.get("data")
        return data if isinstance(data, list) else []

    def fetch_query_metadata(self) -> dict:
        """从远端拉取最新的数据集与字段元数据。

        调用 GET /v1/data-metrics/datasets/query-metadata，
        返回 {"datasets": [...], "fields": [...]} 结构。
        """
        headers, cookies = self._get_auth("ops")
        response = httpx.get(
            f"{self.ops_url}/v1/data-metrics/datasets/query-metadata",
            headers=headers,
            cookies=cookies,
            timeout=20,
        )
        payload = parse_remote_response(
            response,
            http_error_cls=RemoteHttpError,
            business_error_cls=RemoteBusinessError,
            bad_json_error_cls=BadRemoteJsonError,
        )
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    def fetch_chart_queries(self, chart_uuid: str) -> list[dict]:
        """通过 chart_uuid 获取图表的查询结构列表。"""
        bundle = self.fetch_chart_bundle(chart_uuid)
        queries = bundle.get("queries")
        if not isinstance(queries, list):
            raise BadRemoteJsonError("远端返回的 chart query bundle 缺少 queries 数组")
        return queries

    def _normalize_legacy_chart_bundle(self, chart_uuid: str, items: list[dict]) -> dict:
        """将旧版数组格式归一化为 bundle。"""
        dataset_map: dict[tuple[str, int | None, str], dict] = {}

        for idx, item in enumerate(items):
            dataset_alias = self._extract_dataset_alias(item)
            table_id = item.get("tableId")
            data_source = str(item.get("dataSource") or "")
            key = (dataset_alias, table_id if isinstance(table_id, int) else None, data_source)

            dataset = dataset_map.setdefault(
                key,
                {
                    "dataset_alias": dataset_alias or None,
                    "tableId": table_id,
                    "dataSource": item.get("dataSource"),
                    "filterable_fields": [],
                    "fields": [],
                    "_field_keys": set(),
                },
            )

            filterable_fields = item.get("filterable_fields") or []
            if isinstance(filterable_fields, list) and not dataset["filterable_fields"]:
                dataset["filterable_fields"] = filterable_fields

            field_mappings = item.get("field_mappings") or []
            if isinstance(field_mappings, list):
                for mapping in field_mappings:
                    if not isinstance(mapping, dict):
                        continue
                    field_key = self._chart_field_key(mapping)
                    if field_key in dataset["_field_keys"]:
                        existing = next((f for f in dataset["fields"] if self._chart_field_key(f) == field_key), None)
                        if existing is not None:
                            self._merge_dataset_field(existing, mapping)
                        continue
                    dataset["_field_keys"].add(field_key)
                    dataset["fields"].append(self._build_dataset_field(mapping))

            if "query_index" not in item:
                item["query_index"] = idx

        datasets = []
        for dataset in dataset_map.values():
            dataset.pop("_field_keys", None)
            datasets.append(dataset)

        return {
            "chart_uuid": chart_uuid,
            "request_id": None,
            "datasets": datasets,
            "queries": items,
        }

    def _normalize_chart_bundle(self, chart_uuid: str, payload: dict) -> dict:
        """将新版对象格式归一化，并补全 queries 的兼容字段。"""
        datasets = payload.get("datasets")
        queries = payload.get("queries")
        if not isinstance(datasets, list) or not isinstance(queries, list):
            raise BadRemoteJsonError("远端返回的 chart query bundle 缺少 datasets/queries 数组")

        dataset_index: dict[tuple[str, int | None, str], dict] = {}
        for dataset in datasets:
            if not isinstance(dataset, dict):
                continue
            key = (
                str(dataset.get("dataset_alias") or ""),
                dataset.get("tableId") if isinstance(dataset.get("tableId"), int) else None,
                str(dataset.get("dataSource") or ""),
            )
            dataset_index[key] = dataset

        normalized_queries: list[dict] = []
        for idx, query_item in enumerate(queries):
            if not isinstance(query_item, dict):
                continue

            item = dict(query_item)
            dataset_alias = str(item.get("dataset_alias") or self._extract_dataset_alias(item) or "")
            table_id = item.get("tableId") if isinstance(item.get("tableId"), int) else None
            data_source = str(item.get("dataSource") or "")
            dataset = dataset_index.get((dataset_alias, table_id, data_source))

            if dataset and "filterable_fields" not in item:
                item["filterable_fields"] = dataset.get("filterable_fields") or []

            if "field_mappings" not in item:
                field_refs = item.get("field_refs") or {}
                field_mappings: list[dict] = []
                if isinstance(field_refs, dict):
                    for section in ("select", "conditions"):
                        refs = field_refs.get(section) or []
                        if not isinstance(refs, list):
                            continue
                        for ref in refs:
                            if not isinstance(ref, dict):
                                continue
                            merged = dict(ref)
                            if dataset:
                                self._enrich_query_field_ref(merged, dataset.get("fields") or [])
                            field_mappings.append(merged)
                item["field_mappings"] = field_mappings

            if "query_index" not in item:
                item["query_index"] = idx
            normalized_queries.append(item)

        return {
            "chart_uuid": payload.get("chart_uuid") or chart_uuid,
            "request_id": payload.get("request_id"),
            "datasets": datasets,
            "queries": normalized_queries,
        }

    def _extract_dataset_alias(self, item: dict) -> str:
        """从 query item 中提取 dataset_alias。"""
        query = item.get("query") or {}
        if isinstance(query, dict):
            from_block = query.get("from") or {}
            if isinstance(from_block, dict):
                alias = str(from_block.get("alias") or "").strip()
                if alias:
                    return alias
            for select_item in query.get("select") or []:
                if not isinstance(select_item, dict):
                    continue
                expr = str(select_item.get("expr") or "").strip()
                if "." in expr:
                    return expr.split(".", 1)[0]
        return str(item.get("dataset_alias") or "").strip()

    def _chart_field_key(self, mapping: dict) -> str:
        """生成字段去重 key。"""
        return (
            str(mapping.get("global_alias") or "").strip()
            or str(mapping.get("origin_name") or "").strip()
            or str(mapping.get("field_name") or "").strip()
            or str(mapping.get("query_alias") or "").strip()
        )

    def _build_dataset_field(self, mapping: dict) -> dict:
        """从 query field mapping 生成数据集字段信息。"""
        query_aliases = [mapping.get("query_alias")] if mapping.get("query_alias") else []
        aggregations = [mapping.get("aggregation")] if mapping.get("aggregation") else []
        sources = [mapping.get("source")] if mapping.get("source") else []
        return {
            "field_type": mapping.get("field_type"),
            "verbose_name": mapping.get("verbose_name"),
            "field_name": mapping.get("field_name"),
            "origin_name": mapping.get("origin_name"),
            "global_alias": mapping.get("global_alias"),
            "query_aliases": query_aliases,
            "aggregations": aggregations,
            "sources": sources,
        }

    def _merge_dataset_field(self, existing: dict, mapping: dict) -> None:
        """将额外 query mapping 信息合并到数据集字段信息。"""
        if mapping.get("query_alias") and mapping.get("query_alias") not in existing.get("query_aliases", []):
            existing.setdefault("query_aliases", []).append(mapping.get("query_alias"))
        if mapping.get("aggregation") and mapping.get("aggregation") not in existing.get("aggregations", []):
            existing.setdefault("aggregations", []).append(mapping.get("aggregation"))
        if mapping.get("source") and mapping.get("source") not in existing.get("sources", []):
            existing.setdefault("sources", []).append(mapping.get("source"))

    def _enrich_query_field_ref(self, ref: dict, dataset_fields: list[dict]) -> None:
        """根据 datasets.fields 补全 query field ref 的详细信息。"""
        global_alias = str(ref.get("global_alias") or "").strip()
        origin_name = str(ref.get("origin_name") or ref.get("query_field") or "").strip()
        field_name = str(ref.get("field_name") or "").strip()
        query_alias = str(ref.get("query_alias") or "").strip()

        matched = None
        for field in dataset_fields:
            if not isinstance(field, dict):
                continue
            if global_alias and str(field.get("global_alias") or "").strip() == global_alias:
                matched = field
                break
            if origin_name and str(field.get("origin_name") or "").strip() == origin_name:
                matched = field
                break
            if field_name and str(field.get("field_name") or "").strip() == field_name:
                matched = field
                break
            if query_alias:
                query_aliases = field.get("query_aliases") or []
                if query_alias in [str(a).strip() for a in query_aliases if a]:
                    matched = field
                    break
        if not matched:
            return

        for key in ("field_type", "verbose_name", "field_name", "origin_name", "global_alias"):
            if not ref.get(key) and matched.get(key):
                ref[key] = matched.get(key)

    def cli_query(self, payload: dict) -> dict:
        """转发查询请求到 auto-scheduler 的 cli-query 接口。"""
        headers, cookies = self._get_auth("ops")
        response = httpx.post(
            f"{self.ops_url}/v1/data-metrics/cli-query",
            json=payload,
            headers=headers,
            cookies=cookies,
            timeout=30,
        )
        return parse_remote_response(
            response,
            http_error_cls=RemoteHttpError,
            business_error_cls=RemoteBusinessError,
            bad_json_error_cls=BadRemoteJsonError,
        )

    def cli_simple_query(self, payload: dict) -> dict:
        """转发简化查询请求到 auto-scheduler 的 cli-query/simple 接口。"""
        headers, cookies = self._get_auth("ops")
        response = httpx.post(
            f"{self.ops_url}/v1/data-metrics/cli-query/simple",
            json=payload,
            headers=headers,
            cookies=cookies,
            timeout=30,
        )
        return parse_remote_response(
            response,
            http_error_cls=RemoteHttpError,
            business_error_cls=RemoteBusinessError,
            bad_json_error_cls=BadRemoteJsonError,
        )

"""query 模块业务编排层。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from opscli.auth import AuthClient
from opscli.query.domain.exceptions import DatasetNotFoundError, InvalidPayloadError, QueryMetadataNotReadyError
from opscli.query.domain.models import QueryMetadataResult
from opscli.query.transport.client import QueryClient
from opscli.skills.discovery.detector import SkillDetector


@dataclass
class _FieldSpec:
    field_name: str
    alias: str | None
    aggregation: str | None = None


SELECT_ALIAS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class QueryManager:
    """协调本地 metadata 与远端 query 执行。

    支持无状态模式：通过外部传入的 jwt 和 session_id 构造 QueryClient，
    不依赖本地 CredentialStore。适用于远程共享 MCP 服务器场景。
    """

    def __init__(
        self,
        auth_client: AuthClient | None = None,
        jwt: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.detector = SkillDetector()
        self.client = QueryClient(auth_client=auth_client, jwt=jwt, session_id=session_id)
        self.template_dir = Path(__file__).resolve().parent.parent.parent / "skills" / "templates" / "ops-dataset-query" / "data"

    def list_datasets(self, *, skills_dir: str | None = None, cwd: Path | None = None) -> list[dict]:
        """列出所有可用的数据集（从本地 query_metadata.json 读取）。"""
        payload = self._load_query_metadata(skills_dir=skills_dir, cwd=cwd)
        return payload.get("datasets") or []

    def list_fields(self, *, dataset_alias: str | None = None, table_id: int | None = None, skills_dir: str | None = None, cwd: Path | None = None) -> list[dict]:
        """列出所有可用的字段，或指定数据集的字段（从本地 query_metadata.json 读取）。"""
        payload = self._load_query_metadata(skills_dir=skills_dir, cwd=cwd)
        fields = payload.get("fields") or []

        if dataset_alias or table_id is not None:
            datasets = payload.get("datasets") or []
            matched = None
            if dataset_alias:
                matched = next(
                    (item for item in datasets if item.get("dataset_alias") == dataset_alias or item.get("dataset_name") == dataset_alias),
                    None,
                )
            elif table_id is not None:
                matched = next((item for item in datasets if int(item.get("table_id", -1)) == int(table_id)), None)

            if matched:
                target_table_id = int(matched.get("table_id", -1))
                fields = [f for f in fields if int(f.get("table_id", -1)) == target_table_id]

        return fields

    def metadata(
        self,
        *,
        dataset_alias: str | None = None,
        table_id: int | None = None,
        skills_dir: str | None = None,
        cwd: Path | None = None,
    ) -> QueryMetadataResult:
        """按数据集别名或 table_id 查询本地 query metadata。"""
        if not dataset_alias and table_id is None:
            raise InvalidPayloadError("必须提供 --dataset 或 --table-id")

        payload = self._load_query_metadata(skills_dir=skills_dir, cwd=cwd)
        datasets = payload.get("datasets") or []
        fields = payload.get("fields") or []

        matched = None
        if dataset_alias:
            # 优先匹配 dataset_alias（全局唯一标识），其次匹配 dataset_name（业务名）
            matched = next(
                (item for item in datasets
                 if item.get("dataset_alias") == dataset_alias
                 or item.get("dataset_name") == dataset_alias),
                None,
            )
        elif table_id is not None:
            matched = next((item for item in datasets if int(item.get("table_id", -1)) == int(table_id)), None)

        if matched is None:
            needle = dataset_alias if dataset_alias else str(table_id)
            raise DatasetNotFoundError(f"未找到目标数据集: {needle}")

        matched_fields = [
            item for item in fields
            if int(item.get("table_id", -1)) == int(matched.get("table_id", -1))
        ]
        return QueryMetadataResult(dataset=matched, fields=matched_fields, source="local")

    def run(self, *, payload_path: str) -> dict:
        """读取本地 payload 文件并转发执行查询。"""
        payload_file = Path(payload_path).expanduser()
        if not payload_file.exists():
            raise InvalidPayloadError(f"payload 文件不存在: {payload_file}")

        try:
            payload = json.loads(payload_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise InvalidPayloadError(f"payload 不是合法 JSON: {payload_file}") from exc

        self._validate_payload(payload)
        return self.client.cli_query(payload)

    def build(
        self,
        *,
        dataset_alias: str | None = None,
        table_id: int | None = None,
        dimensions: list[str] | None = None,
        metrics: list[str] | None = None,
        where_conditions: list[str] | None = None,
        where_json: str | None = None,
        where_file: str | None = None,
        having_conditions: list[str] | None = None,
        order_by: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
        dry_run: bool = False,
        skills_dir: str | None = None,
        cwd: Path | None = None,
        output_path: str | None = None,
        data_comparison: str | None = None,
    ) -> dict:
        """基于简化参数构造标准 query payload。"""
        if not dimensions and not metrics:
            raise InvalidPayloadError("至少需要提供一个 --dimension 或 --metric")
        where_source_count = sum(1 for item in (where_conditions, where_json, where_file) if item)
        if where_source_count > 1:
            raise InvalidPayloadError("--where、--where-json 和 --where-file 只能使用一种")

        metadata = self.metadata(
            dataset_alias=dataset_alias,
            table_id=table_id,
            skills_dir=skills_dir,
            cwd=cwd,
        )
        dataset = metadata.dataset

        select_items: list[dict] = []
        group_by: list[str] = []

        for spec in dimensions or []:
            item = self._parse_dimension_spec(spec)
            resolved = self._resolve_field(metadata.fields, item.field_name, field_type="dimension")
            output_alias = self._resolve_output_alias(item.alias, resolved)
            select_items.append(
                {
                    "expr": f"{dataset['dataset_alias']}.{resolved['field_name']}",
                    "alias": output_alias,
                }
            )
            group_by.append(output_alias)

        for spec in metrics or []:
            item = self._parse_metric_spec(spec)
            resolved = self._resolve_field(metadata.fields, item.field_name, field_type="metric")
            output_alias = self._resolve_output_alias(item.alias, resolved)
            select_row = {
                "expr": self._resolve_metric_expr(str(dataset["dataset_alias"]), resolved),
                "alias": output_alias,
            }
            if item.aggregation and select_row["expr"] == f"{dataset['dataset_alias']}.{resolved['field_name']}":
                select_row["aggregation"] = item.aggregation
            select_items.append(select_row)

        # 构建 select → alias 映射，用于 order-by 表达式解析
        alias_map: dict[str, str] = {}
        for item in select_items:
            alias_map[item["alias"]] = item["alias"]
            # 从 expr 中提取 field_name（如 ds_xxx.price → price）
            if "." in item["expr"]:
                alias_map[item["expr"].rsplit(".", 1)[-1]] = item["alias"]

        payload = {
            "tableId": int(dataset["table_id"]),
            "query": {
                "select": select_items,
                "groupBy": group_by,
                "orderBy": self._build_order_by(order_by or [], alias_map=alias_map),
                "limit": limit,
                "offset": offset,
            },
        }
        if dry_run:
            payload["dryRun"] = True

        where_payload = self._load_where_clause(
            where_conditions=where_conditions or [],
            where_json=where_json,
            where_file=where_file,
            dataset_alias=str(dataset["dataset_alias"]),
        )
        if where_payload is not None:
            payload["query"]["where"] = where_payload

        having_payload = self._build_having_clause(having_conditions or [])
        if having_payload:
            payload["query"]["having"] = having_payload

        # 构造 dataComparison（数据对比）
        if data_comparison:
            payload["dataComparison"] = self._build_data_comparison(
                data_comparison, dataset_alias=str(dataset["dataset_alias"]),
            )

        self._validate_payload(payload)
        if output_path:
            output_file = Path(output_path).expanduser()
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "dataset": dataset,
            "payload": payload,
            "output": str(Path(output_path).expanduser()) if output_path else None,
        }

    def build_and_run(self, **kwargs) -> dict:
        """先构造 payload，再立即执行查询。"""
        build_result = self.build(**kwargs)
        query_result = self.client.cli_query(build_result["payload"])
        return {
            **build_result,
            "result": query_result,
        }

    # ── chart query 支持 ──────────────────────────────────────────────

    def fetch_chart_queries(self, chart_uuid: str) -> list[dict]:
        """通过 chart_uuid 从远端获取图表的查询结构列表。"""
        return self.client.fetch_chart_queries(chart_uuid)

    def fetch_chart_bundle(self, chart_uuid: str) -> dict:
        """通过 chart_uuid 从远端获取图表查询 bundle。"""
        return self.client.fetch_chart_bundle(chart_uuid)

    def build_payload_from_chart_query(self, chart_item: dict) -> dict:
        """将后端返回的 chart query 结构转换为 cli_query 可用 payload。

        输入结构：
            {
                "query": {"from": {...}, "select": [...], ...},
                "dataSource": "doris_analytics",
                "tableId": 1
            }

        输出结构：
            {"tableId": 1, "query": {"select": [...], ...}}

        自动剔除 query.from 字段，因为 cli_query 通过 tableId 定位数据集。
        """
        table_id = chart_item.get("tableId")
        if table_id is None:
            raise InvalidPayloadError("chart query 缺少 tableId")

        query = chart_item.get("query") or {}
        if not isinstance(query, dict):
            raise InvalidPayloadError("chart query 的 query 字段必须是对象")

        # 构造标准 cli_query payload：复制 query 内容并移除 from
        payload_query = dict(query)
        payload_query.pop("from", None)

        return {
            "tableId": int(table_id),
            "query": payload_query,
        }

    def run_chart_queries(
        self,
        chart_uuid: str,
        *,
        dry_run: bool = False,
    ) -> dict:
        """获取图表查询结构 → 执行所有 query → 合并输出结果。

        每个 query 独立执行，失败时记录错误但不中断后续 query。
        最终返回包含各 query 结果及合并视图的字典。

        Returns:
            {
                "chart_uuid": "xxx",
                "queries": [
                    {
                        "index": 0,
                        "table_id": 1,
                        "data_source": "doris_analytics",
                        "payload": {...},
                        "result": {...},          # 成功时
                        "error": {...},           # 失败时
                    }
                ],
                "merged": {
                    "rows": [...],                # 所有 rows 扁平合并（加 _query_index）
                    "meta": {"rowCount": 150, "queryCount": 3, "successCount": 3},
                },
            }
        """
        chart_items = self.fetch_chart_queries(chart_uuid)

        queries: list[dict] = []
        all_rows: list[dict] = []
        total_row_count = 0
        success_count = 0

        for idx, item in enumerate(chart_items):
            table_id = item.get("tableId")
            data_source = item.get("dataSource")
            filterable_fields = item.get("filterable_fields", [])
            query_structure = item.get("query", {})

            try:
                payload = self.build_payload_from_chart_query(item)
            except Exception as exc:
                queries.append({
                    "index": idx,
                    "table_id": table_id,
                    "data_source": data_source,
                    "filterable_fields": filterable_fields,
                    "query_structure": query_structure,
                    "payload": None,
                    "result": None,
                    "error": {"code": "INVALID_PAYLOAD", "message": str(exc)},
                })
                continue

            if dry_run:
                payload["dryRun"] = True

            try:
                result = self.client.cli_query(payload)
                queries.append({
                    "index": idx,
                    "table_id": table_id,
                    "data_source": data_source,
                    "filterable_fields": filterable_fields,
                    "query_structure": query_structure,
                    "payload": payload,
                    "result": result,
                    "error": None,
                })

                rows = result.get("rows") or []
                for row in rows:
                    all_rows.append({"_query_index": idx, **row})
                total_row_count += result.get("meta", {}).get("rowCount", len(rows))
                success_count += 1
            except Exception as exc:
                error = exc.to_dict() if hasattr(exc, "to_dict") else {"code": "QUERY_ERROR", "message": str(exc)}
                queries.append({
                    "index": idx,
                    "table_id": table_id,
                    "data_source": data_source,
                    "filterable_fields": filterable_fields,
                    "query_structure": query_structure,
                    "payload": payload,
                    "result": None,
                    "error": error,
                })

        return {
            "chart_uuid": chart_uuid,
            "queries": queries,
            "merged": {
                "rows": all_rows,
                "meta": {
                    "rowCount": total_row_count,
                    "queryCount": len(chart_items),
                    "successCount": success_count,
                },
            },
        }

    def generate_chart_doc(self, chart_uuid: str) -> dict:
        """生成更适合 Skill / AI 消费的图表查询文档。"""
        chart_bundle = self.fetch_chart_bundle(chart_uuid)
        chart_items = chart_bundle.get("queries") or []
        datasets = chart_bundle.get("datasets") or []

        if not chart_items:
            raise InvalidPayloadError("该图表暂无查询结构数据")

        generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
        dataset_aliases = sorted({
            self._extract_chart_dataset_alias(item)
            for item in chart_items
            if self._extract_chart_dataset_alias(item)
        })

        md_lines: list[str] = []
        md_lines.append("# 图表查询 API 开发文档")
        md_lines.append("")
        md_lines.append("> 目标：为 Skill / AI Agent 提供当前图表查询结构、字段映射关系、过滤能力和可直接执行的请求样例。")
        md_lines.append("")
        md_lines.append(f"- **图表 UUID**: `{chart_uuid}`")
        md_lines.append(f"- **文档生成时间**: `{generated_at}`")
        md_lines.append(f"- **查询数量**: `{len(chart_items)}`")
        md_lines.append(f"- **涉及数据集**: {', '.join(f'`{alias}`' for alias in dataset_aliases) if dataset_aliases else '无'}")
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

        md_lines.append("## 一、使用方式")
        md_lines.append("")
        md_lines.append("1. 用 `GET /v1/data-metrics/cli-query/latest-request-data` 获取图表当前最新一组查询快照。")
        md_lines.append("2. 从返回结果读取 `datasets` 公共字段信息，以及每个 Query 的 `query` / `field_mappings`。")
        md_lines.append("3. 执行查询时，使用 `POST /v1/data-metrics/cli-query`，请求体只传 `tableId + query (+ dataComparison)`。")
        md_lines.append("4. Skill 开发时，优先使用本文中的 `origin_name` 构造过滤条件，使用 `global_alias` / `query_alias` 对齐结果列名。")
        md_lines.append("")

        md_lines.append("## 二、关键术语")
        md_lines.append("")
        md_lines.append("| 术语 | 含义 | 典型用途 |")
        md_lines.append("|------|------|----------|")
        md_lines.append("| `query_alias` | 当前 Query 中 `select.alias` 使用的输出列别名 | 对齐查询结果列名、`groupBy`、`orderBy` |")
        md_lines.append("| `field_name` | 统一字段映射表中的字段名 | 业务识别、脚本内字段归类 |")
        md_lines.append("| `origin_name` | 字段原始引用名，通常为 `dataset_alias.column_name` | 构造 `where` / `dataComparison.field` |")
        md_lines.append("| `global_alias` | 字段统一全局别名 | 与图表配置、查询结果做稳定映射 |")
        md_lines.append("| `field_type` | `dimension` 或 `metric` | 决定字段角色与用法 |")
        md_lines.append("")

        md_lines.append("## 三、图表总览")
        md_lines.append("")
        md_lines.append("| Query | dataset_alias | tableId | dataSource | SELECT | GROUP BY | ORDER BY | 可过滤字段 |")
        md_lines.append("|------|---------------|---------|------------|--------|----------|----------|------------|")
        for idx, item in enumerate(chart_items, 1):
            query = item.get("query", {}) or {}
            dataset_alias = self._extract_chart_dataset_alias(item)
            md_lines.append(
                f"| Q{idx} | `{dataset_alias or '-'}` | `{item.get('tableId', '-')}` | "
                f"`{item.get('dataSource', '-')}` | `{len(query.get('select', []) or [])}` | "
                f"`{len(query.get('groupBy', []) or [])}` | `{len(query.get('orderBy', []) or [])}` | "
                f"`{len(item.get('filterable_fields', []) or [])}` |"
            )
        md_lines.append("")

        md_lines.append("## 四、接口调用顺序")
        md_lines.append("")
        md_lines.append("### 4.1 获取图表查询快照")
        md_lines.append("")
        md_lines.append("```http")
        md_lines.append(f"GET /v1/data-metrics/cli-query/latest-request-data?chart_uuid={chart_uuid}")
        md_lines.append("Authorization: Bearer <your_jwt_token>")
        md_lines.append("```")
        md_lines.append("")
        md_lines.append("返回重点字段：")
        md_lines.append("")
        md_lines.append("| 字段 | 说明 |")
        md_lines.append("|------|------|")
        md_lines.append("| `tableId` | 执行查询时使用的目标数据集 ID |")
        md_lines.append("| `datasets[].fields` | 数据集级字段信息总表，适合做字段语义理解 |")
        md_lines.append("| `datasets[].filterable_fields` | 数据集级可过滤字段清单 |")
        md_lines.append("| `queries[].query` | 原始图表查询结构快照 |")
        md_lines.append("| `queries[].field_mappings` | 当前 Query 实际涉及字段的映射结果 |")
        md_lines.append("")
        md_lines.append("### 4.2 执行数据查询")
        md_lines.append("")
        md_lines.append("```http")
        md_lines.append("POST /v1/data-metrics/cli-query")
        md_lines.append("Content-Type: application/json")
        md_lines.append("Authorization: Bearer <your_jwt_token>")
        md_lines.append("```")
        md_lines.append("")
        md_lines.append("请求体只需要 `tableId + query (+ dataComparison)`，不要再传原始 `query.from.table` 和 `query.from.permission`。")
        md_lines.append("")

        md_lines.append("## 五、数据集字段信息表")
        md_lines.append("")
        for idx, dataset in enumerate(datasets, 1):
            if not isinstance(dataset, dict):
                continue
            dataset_alias = str(dataset.get("dataset_alias") or "").strip() or "-"
            md_lines.append(f"### Dataset {idx}: `{dataset_alias}`")
            md_lines.append("")
            md_lines.append("| 属性 | 值 |")
            md_lines.append("|------|-----|")
            md_lines.append(f"| tableId | `{dataset.get('tableId', '-')}` |")
            md_lines.append(f"| dataSource | `{dataset.get('dataSource', '-')}` |")
            md_lines.append(f"| 字段数量 | `{len(dataset.get('fields') or [])}` |")
            md_lines.append(f"| 可过滤字段数量 | `{len(dataset.get('filterable_fields') or [])}` |")
            md_lines.append("")

            fields = dataset.get("fields") or []
            if fields:
                md_lines.append("#### 5.1 字段信息总表")
                md_lines.append("")
                md_lines.append("| verbose_name | field_type | field_name | origin_name | global_alias | query_aliases | aggregations | sources |")
                md_lines.append("|--------------|------------|------------|-------------|--------------|---------------|--------------|---------|")
                for field in fields:
                    if not isinstance(field, dict):
                        continue
                    query_aliases = ", ".join(f"`{item}`" for item in (field.get("query_aliases") or []) if item) or "-"
                    aggregations = ", ".join(f"`{item}`" for item in (field.get("aggregations") or []) if item) or "-"
                    sources = ", ".join(f"`{item}`" for item in (field.get("sources") or []) if item) or "-"
                    md_lines.append(
                        f"| {field.get('verbose_name') or '-'} | `{field.get('field_type') or '-'}` | "
                        f"`{field.get('field_name') or '-'}` | `{field.get('origin_name') or '-'}` | "
                        f"`{field.get('global_alias') or '-'}` | {query_aliases} | {aggregations} | {sources} |"
                    )
                md_lines.append("")

            filterable_fields = dataset.get("filterable_fields") or []
            if filterable_fields:
                md_lines.append("#### 5.2 可过滤字段总表")
                md_lines.append("")
                md_lines.append("| column_name | verbose_name | source_column_name | 建议 field 写法 |")
                md_lines.append("|-------------|--------------|--------------------|-----------------|")
                for field in filterable_fields:
                    if not isinstance(field, dict):
                        continue
                    column_name = field.get("column_name") or "-"
                    verbose_name = field.get("verbose_name") or "-"
                    source_name = field.get("source_column_name") or "-"
                    suggested = f"{dataset_alias}.{column_name}" if dataset_alias != "-" and column_name != "-" else "-"
                    md_lines.append(f"| `{column_name}` | {verbose_name} | `{source_name}` | `{suggested}` |")
                md_lines.append("")
            md_lines.append("---")
            md_lines.append("")

        md_lines.append("## 六、WHERE / HAVING 规则")
        md_lines.append("")
        md_lines.append("### 6.1 支持的操作符")
        md_lines.append("")
        md_lines.append("| 操作符 | 含义 | value 类型 |")
        md_lines.append("|--------|------|-----------|")
        md_lines.append("| `eq` | 等于 | string / number |")
        md_lines.append("| `ne` | 不等于 | string / number |")
        md_lines.append("| `gt` | 大于 | number |")
        md_lines.append("| `gte` | 大于等于 | number |")
        md_lines.append("| `lt` | 小于 | number |")
        md_lines.append("| `lte` | 小于等于 | number |")
        md_lines.append("| `in` | 在列表中 | array |")
        md_lines.append("| `not_in` | 不在列表中 | array |")
        md_lines.append("| `between` | 介于两者之间 | [min, max] |")
        md_lines.append("| `like` | 模糊匹配 | string (含 % 通配符) |")
        md_lines.append("| `is_null` | 为空 | 无需 value |")
        md_lines.append("| `is_not_null` | 不为空 | 无需 value |")
        md_lines.append("")
        md_lines.append("### 6.2 条件构造示例")
        md_lines.append("")
        md_lines.append("```json")
        sample_where = {
            "operator": "AND",
            "conditions": [
                {
                    "field": "ds_xxx.date_id",
                    "operator": "between",
                    "value": ["2026-03-13", "2026-04-11"],
                },
                {
                    "field": "ds_xxx.platform_name",
                    "operator": "in",
                    "value": ["Amazon", "eBay"],
                },
            ],
        }
        md_lines.append(json.dumps(sample_where, ensure_ascii=False, indent=2))
        md_lines.append("```")
        md_lines.append("")
        md_lines.append("> `field` 应优先使用 `field_mappings` 中的 `origin_name`，格式通常为 `ds_xxx.column_name`。")
        md_lines.append("")

        md_lines.append("## 七、Query 逐条拆解")
        md_lines.append("")
        # 建立 dataset 索引，便于为每个 query 快速找到对应的 fields
        dataset_field_index: dict[tuple[str, int | None, str], list[dict]] = {}
        for ds in datasets:
            if not isinstance(ds, dict):
                continue
            key = (
                str(ds.get("dataset_alias") or ""),
                ds.get("tableId") if isinstance(ds.get("tableId"), int) else None,
                str(ds.get("dataSource") or ""),
            )
            dataset_field_index[key] = ds.get("fields") or []

        for idx, item in enumerate(chart_items, 1):
            query = item.get("query", {}) or {}
            dataset_alias = self._extract_chart_dataset_alias(item)
            table_id = item.get("tableId") if isinstance(item.get("tableId"), int) else None
            data_source = str(item.get("dataSource") or "")
            dataset_fields = dataset_field_index.get((dataset_alias, table_id, data_source))
            select_field_mappings, condition_field_mappings = self._split_chart_field_mappings(item, dataset_fields=dataset_fields)
            group_by_labels = self._resolve_group_labels(query.get("groupBy", []) or [], select_field_mappings)
            payload_example = self.build_payload_from_chart_query(item)

            md_lines.append(f"### Query {idx}")
            md_lines.append("")
            md_lines.append("| 属性 | 值 |")
            md_lines.append("|------|-----|")
            md_lines.append(f"| dataset_alias | `{dataset_alias or '-'}` |")
            md_lines.append(f"| tableId | `{item.get('tableId', '-')}` |")
            md_lines.append(f"| dataSource | `{item.get('dataSource', '-')}` |")
            md_lines.append(f"| SELECT 数量 | `{len(query.get('select', []) or [])}` |")
            md_lines.append(f"| GROUP BY | {', '.join(f'`{name}`' for name in group_by_labels) if group_by_labels else '无'} |")
            md_lines.append(f"| ORDER BY | `{len(query.get('orderBy', []) or [])}` |")
            md_lines.append("")

            md_lines.append("#### 7.1 输出字段映射")
            md_lines.append("")
            if select_field_mappings:
                md_lines.append("| query_alias | aggregation | verbose_name | field_type | field_name | origin_name | global_alias | expr |")
                md_lines.append("|-------------|-------------|--------------|------------|------------|-------------|--------------|------|")
                for mapping in select_field_mappings:
                    md_lines.append(
                        f"| `{mapping.get('query_alias') or '-'}` | `{mapping.get('aggregation') or '-'}` | "
                        f"{mapping.get('verbose_name') or '-'} | `{mapping.get('field_type') or '-'}` | "
                        f"`{mapping.get('field_name') or '-'}` | `{mapping.get('origin_name') or '-'}` | "
                        f"`{mapping.get('global_alias') or '-'}` | `{mapping.get('query_expr') or '-'}` |"
                    )
            else:
                md_lines.append("当前 Query 未返回可解析的输出字段映射。")
            md_lines.append("")

            md_lines.append("#### 7.2 条件字段映射")
            md_lines.append("")
            if condition_field_mappings:
                md_lines.append("| source | query_field | verbose_name | field_type | field_name | origin_name | global_alias |")
                md_lines.append("|--------|-------------|--------------|------------|------------|-------------|--------------|")
                for mapping in condition_field_mappings:
                    md_lines.append(
                        f"| `{mapping.get('source') or '-'}` | `{mapping.get('query_field') or mapping.get('query_expr') or '-'}` | "
                        f"{mapping.get('verbose_name') or '-'} | `{mapping.get('field_type') or '-'}` | "
                        f"`{mapping.get('field_name') or '-'}` | `{mapping.get('origin_name') or '-'}` | "
                        f"`{mapping.get('global_alias') or '-'}` |"
                    )
            else:
                md_lines.append("当前 Query 未声明额外条件字段映射。")
            md_lines.append("")

            md_lines.append("#### 7.3 可过滤字段")
            md_lines.append("")
            filterable = item.get("filterable_fields", []) or []
            if filterable:
                md_lines.append("| column_name | verbose_name | source_column_name | 建议 field 写法 |")
                md_lines.append("|-------------|--------------|--------------------|-----------------|")
                for field in filterable:
                    column_name = field.get("column_name") or "-"
                    verbose_name = field.get("verbose_name") or "-"
                    source_name = field.get("source_column_name") or "-"
                    suggested = f"{dataset_alias}.{column_name}" if dataset_alias and column_name != "-" else "-"
                    md_lines.append(f"| `{column_name}` | {verbose_name} | `{source_name}` | `{suggested}` |")
            else:
                md_lines.append("当前数据集没有返回 `filterable_fields` 配置。")
            md_lines.append("")

            md_lines.append("#### 7.4 查询条件结构")
            md_lines.append("")
            if query.get("where"):
                md_lines.append("**where**")
                md_lines.append("")
                md_lines.append("```json")
                md_lines.append(json.dumps(query.get("where"), ensure_ascii=False, indent=2))
                md_lines.append("```")
                md_lines.append("")
            if query.get("innerWhere"):
                md_lines.append("**innerWhere**")
                md_lines.append("")
                md_lines.append("```json")
                md_lines.append(json.dumps(query.get("innerWhere"), ensure_ascii=False, indent=2))
                md_lines.append("```")
                md_lines.append("")
            if item.get("dataComparison"):
                md_lines.append("**dataComparison**")
                md_lines.append("")
                md_lines.append("```json")
                md_lines.append(json.dumps(item.get("dataComparison"), ensure_ascii=False, indent=2))
                md_lines.append("```")
                md_lines.append("")

            md_lines.append("#### 7.5 可直接执行的 Payload")
            md_lines.append("")
            md_lines.append("```json")
            md_lines.append(json.dumps(payload_example, ensure_ascii=False, indent=2))
            md_lines.append("```")
            md_lines.append("")
            md_lines.append("---")
            md_lines.append("")

        md_lines.append("*文档由 `opscli query chart-doc` 自动生成。*")

        return {
            "chart_uuid": chart_uuid,
            "markdown": "\n".join(md_lines),
            "query_count": len(chart_items),
            "dataset_aliases": dataset_aliases,
            "dataset_count": len(datasets),
        }

    def _extract_chart_dataset_alias(self, chart_item: dict) -> str:
        """提取 chart item 中的数据集别名。"""
        query = chart_item.get("query", {}) or {}
        from_block = query.get("from", {})
        if isinstance(from_block, dict):
            alias = str(from_block.get("alias") or "").strip()
            if alias:
                return alias
        for item in query.get("select", []) or []:
            expr = str(item.get("expr") or "").strip()
            if "." in expr:
                return expr.split(".", 1)[0]
        return ""

    def _split_chart_field_mappings(self, chart_item: dict, dataset_fields: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
        """拆分输出字段映射与条件字段映射。"""
        raw_mappings = chart_item.get("field_mappings") or []
        normalized = [self._normalize_chart_field_mapping(item) for item in raw_mappings if isinstance(item, dict)]
        if not normalized:
            normalized = self._fallback_chart_field_mappings(chart_item, dataset_fields=dataset_fields)
        select_mappings = [item for item in normalized if item.get("source") == "select"]
        condition_mappings = [item for item in normalized if item.get("source") != "select"]
        return select_mappings, condition_mappings

    def _normalize_chart_field_mapping(self, mapping: dict) -> dict:
        """统一 field_mappings 输出结构。"""
        return {
            "source": str(mapping.get("source") or "").strip() or "unknown",
            "query_alias": str(mapping.get("query_alias") or mapping.get("alias") or "").strip() or None,
            "query_expr": str(mapping.get("query_expr") or mapping.get("expr") or "").strip() or None,
            "query_field": str(mapping.get("query_field") or mapping.get("field") or "").strip() or None,
            "aggregation": str(mapping.get("aggregation") or "").strip() or None,
            "field_type": str(mapping.get("field_type") or "").strip() or None,
            "verbose_name": str(mapping.get("verbose_name") or "").strip() or None,
            "field_name": str(mapping.get("field_name") or "").strip() or None,
            "origin_name": str(mapping.get("origin_name") or "").strip() or None,
            "global_alias": str(mapping.get("global_alias") or "").strip() or None,
        }

    def _fallback_chart_field_mappings(self, chart_item: dict, dataset_fields: list[dict] | None = None) -> list[dict]:
        """在服务端未返回 field_mappings 时，基于 query 结构做最小回退。"""
        query = chart_item.get("query", {}) or {}
        fallback: list[dict] = []
        for select_item in query.get("select", []) or []:
            expr = str(select_item.get("expr") or "").strip()
            # 从 expr（如 ds_xxx.column_name）提取 origin_name 和 field_name
            origin_name = expr if "." in expr else None
            field_name = expr.rsplit(".", 1)[1] if "." in expr else None
            mapping = {
                "source": "select",
                "query_alias": str(select_item.get("alias") or "").strip() or None,
                "query_expr": expr or None,
                "query_field": None,
                "aggregation": str(select_item.get("aggregation") or "").strip() or None,
                "field_type": None,
                "verbose_name": None,
                "field_name": field_name,
                "origin_name": origin_name,
                "global_alias": str(select_item.get("alias") or "").strip() or None,
            }
            if dataset_fields:
                self.client._enrich_query_field_ref(mapping, dataset_fields)
            fallback.append(mapping)
        for source, field_name in self._fallback_condition_field_refs(chart_item):
            # 从条件字段引用（如 ds_xxx.column_name）提取 field_name
            col_name = field_name.rsplit(".", 1)[1] if "." in field_name else field_name
            mapping = {
                "source": source,
                "query_alias": None,
                "query_expr": None,
                "query_field": field_name,
                "aggregation": None,
                "field_type": None,
                "verbose_name": None,
                "field_name": col_name,
                "origin_name": field_name,
                "global_alias": None,
            }
            if dataset_fields:
                self.client._enrich_query_field_ref(mapping, dataset_fields)
            fallback.append(mapping)
        return fallback

    def _fallback_condition_field_refs(self, chart_item: dict) -> list[tuple[str, str]]:
        """提取 where / innerWhere / dataComparison 中的字段引用。"""
        refs: list[tuple[str, str]] = []
        query = chart_item.get("query", {}) or {}

        def visit(node: object, source: str) -> None:
            if not isinstance(node, dict):
                return
            field = str(node.get("field") or "").strip()
            if field:
                refs.append((source, field))
            conditions = node.get("conditions")
            if isinstance(conditions, list):
                for child in conditions:
                    visit(child, source)

        visit(query.get("where"), "where")
        inner_where = query.get("innerWhere")
        if isinstance(inner_where, list):
            for idx, node in enumerate(inner_where):
                visit(node, f"innerWhere[{idx}]")

        data_comparison = chart_item.get("dataComparison")
        if isinstance(data_comparison, dict):
            field = str(data_comparison.get("field") or "").strip()
            if field:
                refs.append(("dataComparison", field))

        deduped: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in refs:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    def _resolve_group_labels(self, group_by: list[object], select_mappings: list[dict]) -> list[str]:
        """将 groupBy alias 映射为更易读的字段标签。"""
        alias_map: dict[str, str] = {}
        for mapping in select_mappings:
            alias = mapping.get("query_alias")
            if not alias:
                continue
            alias_map[str(alias)] = str(
                mapping.get("verbose_name")
                or mapping.get("field_name")
                or mapping.get("origin_name")
                or alias
            )

        labels: list[str] = []
        for item in group_by:
            key = str(item).strip()
            if not key:
                continue
            labels.append(alias_map.get(key, key))
        return labels

    def _build_data_comparison(self, raw: str, *, dataset_alias: str) -> dict:
        """解析 dataComparison 定义：field,start_date,end_date。

        格式示例：date_id,2026-03-01,2026-03-22
        field 可以是纯字段名（自动加前缀）或含前缀的全名。
        """
        parts = [item.strip() for item in raw.split(",")]
        if len(parts) != 3 or not all(parts):
            raise InvalidPayloadError(
                "--data-comparison 格式: field,start_date,end_date"
                "（例: date_id,2026-03-01,2026-03-22）"
            )
        field, start_date, end_date = parts
        # 自动补全数据集别名前缀
        if "." not in field:
            field = f"{dataset_alias}.{field}"
        return {
            "switch": True,
            "field": field,
            "startDate": start_date,
            "endDate": end_date,
        }

    def _validate_payload(self, payload: dict) -> None:
        """校验最小请求结构。"""
        if not isinstance(payload, dict):
            raise InvalidPayloadError("payload 顶层必须是 JSON 对象")
        if "tableId" not in payload:
            raise InvalidPayloadError("payload 缺少 tableId")
        if "query" not in payload or not isinstance(payload["query"], dict):
            raise InvalidPayloadError("payload 缺少 query 对象")

    def _load_query_metadata(self, *, skills_dir: str | None, cwd: Path | None) -> dict:
        """从已安装 Skill 或内置模板中读取 query_metadata.json。"""
        metadata_file = self._resolve_metadata_file(skills_dir=skills_dir, cwd=cwd)
        try:
            payload = json.loads(metadata_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise QueryMetadataNotReadyError(f"query metadata 读取失败: {metadata_file}") from exc

        if not isinstance(payload, dict):
            raise QueryMetadataNotReadyError(f"query metadata 结构非法: {metadata_file}")
        return payload

    def _resolve_metadata_file(self, *, skills_dir: str | None, cwd: Path | None) -> Path:
        """优先使用已安装 Skill 的 metadata 文件，否则回退到内置模板。"""
        records = self.detector.discover(skills_dir=skills_dir, cwd=cwd)
        for record in records:
            if record.name != "ops-dataset-query":
                continue
            metadata_file = record.root / "data" / "query_metadata.json"
            if metadata_file.exists():
                return metadata_file

        fallback = self.template_dir / "query_metadata.json"
        if fallback.exists():
            return fallback
        raise QueryMetadataNotReadyError("本地未找到 query_metadata.json，请先安装并升级 ops-dataset-query")

    def _parse_dimension_spec(self, raw: str) -> _FieldSpec:
        """解析维度定义：field_name[:alias]。"""
        parts = [item.strip() for item in raw.split(":")]
        if len(parts) == 1 and parts[0]:
            return _FieldSpec(field_name=parts[0], alias=None)
        if len(parts) == 2 and parts[0] and parts[1]:
            return _FieldSpec(field_name=parts[0], alias=parts[1])
        raise InvalidPayloadError(f"无效的 --dimension 定义: {raw}")

    def _parse_metric_spec(self, raw: str) -> _FieldSpec:
        """解析指标定义：field_name[:aggregation[:alias]]。

        支持三种格式：
        - field_name                    公式字段（has_formula_config=1），由 _resolve_metric_expr 自动使用 summary_expression
        - field_name:aggregation        普通聚合字段
        - field_name:aggregation:alias  普通聚合字段 + 自定义别名
        - field_name::alias             公式字段 + 自定义别名（aggregation 留空）
        """
        parts = [item.strip() for item in raw.split(":")]
        # 仅有字段名：公式字段，aggregation=None 由 _resolve_metric_expr 处理
        if len(parts) == 1 and parts[0]:
            return _FieldSpec(field_name=parts[0], aggregation=None, alias=None)
        if len(parts) == 2 and parts[0] and parts[1]:
            return _FieldSpec(field_name=parts[0], aggregation=parts[1].upper(), alias=None)
        if len(parts) == 3 and parts[0] and parts[2]:
            # 第二段为空时表示公式字段 + 自定义别名（如 gross_profit_percent::gpp）
            agg = parts[1].upper() if parts[1] else None
            return _FieldSpec(field_name=parts[0], aggregation=agg, alias=parts[2])
        raise InvalidPayloadError(f"无效的 --metric 定义: {raw}，格式: field_name[:aggregation[:alias]]")

    def _build_order_by(self, items: list[str], *, alias_map: dict[str, str] | None = None) -> list[dict]:
        """解析排序定义：expr[:asc|desc]，自动映射到 select 输出别名。"""
        alias_map = alias_map or {}
        result: list[dict] = []
        for raw in items:
            parts = [item.strip() for item in raw.split(":")]
            if len(parts) == 1 and parts[0]:
                expr = parts[0]
                direction = False
            elif len(parts) == 2 and parts[0] and parts[1]:
                expr = parts[0]
                direction_val = parts[1].lower()
                if direction_val not in ("asc", "desc"):
                    raise InvalidPayloadError(f"无效的 --order-by 排序方向: {raw}")
                direction = direction_val == "desc"
            else:
                raise InvalidPayloadError(f"无效的 --order-by 定义: {raw}")
            # 自动映射到 select 输出别名
            resolved_expr = alias_map.get(expr, expr)
            result.append({"expr": resolved_expr, "desc": direction})
        return result

    def _load_where_clause(
        self,
        *,
        where_conditions: list[str],
        where_json: str | None,
        where_file: str | None,
        dataset_alias: str,
    ) -> dict | None:
        """从 JSON 字符串或文件中读取 where 结构。"""
        if where_conditions:
            payload = {
                "operator": "AND",
                "conditions": [self._parse_where_condition(item, dataset_alias=dataset_alias) for item in where_conditions],
            }
        elif where_json:
            try:
                payload = json.loads(where_json)
            except Exception as exc:
                raise InvalidPayloadError("--where-json 不是合法 JSON") from exc
        elif where_file:
            file_path = Path(where_file).expanduser()
            if not file_path.exists():
                raise InvalidPayloadError(f"where 文件不存在: {file_path}")
            try:
                payload = json.loads(file_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise InvalidPayloadError(f"where 文件不是合法 JSON: {file_path}") from exc
        else:
            return None

        if not isinstance(payload, dict):
            raise InvalidPayloadError("where 必须是 JSON 对象")
        return payload

    # 操作符标准化映射：将 Python/SQL 风格符号转换为服务端语义操作符
    _WHERE_OP_MAP: dict[str, str] = {
        ">=": "gte",
        "<=": "lte",
        ">": "gt",
        "<": "lt",
        "=": "eq",
        "==": "eq",
        "!=": "neq",
        "<>": "neq",
    }

    def _parse_where_condition(self, raw: str, *, dataset_alias: str) -> dict:
        """解析 where 简写条件：field|operator|value_json。

        操作符支持两种写法：
        - 语义操作符（服务端原生）：between, eq, neq, gt, gte, lt, lte, in
        - 符号操作符（自动转换）：>=, <=, >, <, =, ==, !=, <>
        """
        parts = raw.split("|", 2)
        if len(parts) != 3:
            raise InvalidPayloadError(f"无效的 --where 定义: {raw}")

        field, operator, value_raw = (item.strip() for item in parts)
        if not field or not operator or not value_raw:
            raise InvalidPayloadError(f"无效的 --where 定义: {raw}")

        # 将符号操作符标准化为服务端语义操作符
        operator = self._WHERE_OP_MAP.get(operator, operator)

        expr = field if "." in field else f"{dataset_alias}.{field}"
        try:
            value = json.loads(value_raw)
        except Exception:
            value = value_raw

        return {
            "field": expr,
            "operator": operator,
            "value": value,
        }

    def _build_having_clause(self, items: list[str]) -> list[dict]:
        """解析 having 简写条件：expr|operator|value_json。"""
        result: list[dict] = []
        for raw in items:
            parts = raw.split("|", 2)
            if len(parts) != 3:
                raise InvalidPayloadError(f"无效的 --having 定义: {raw}")

            expr, operator, value_raw = (item.strip() for item in parts)
            if not expr or not operator or not value_raw:
                raise InvalidPayloadError(f"无效的 --having 定义: {raw}")

            try:
                value = json.loads(value_raw)
            except Exception:
                value = value_raw

            result.append(
                {
                    "field": expr,
                    "operator": operator,
                    "value": value,
                }
            )
        return result

    def _resolve_field(self, fields: list[dict], identifier: str, *, field_type: str) -> dict:
        """按 global_alias > field_name > verbose_name 解析字段。

        当同一标识命中多条记录时，自动筛选最可能的原始字段（非 copy/衍生）：
        - global_alias 优先级：无 _数字 后缀 > 有后缀
        - field_name 优先级：verbose_name 最短（原始字段无 _copy 后缀）> 较长
        - verbose_name 优先级：精确匹配 > 包含匹配
        """
        normalized = identifier.strip().lower()
        if not normalized:
            raise InvalidPayloadError("字段标识不能为空")

        global_alias_matches: list[dict] = []
        field_name_matches: list[dict] = []
        verbose_name_matches: list[dict] = []

        for item in fields:
            current_type = str(item.get("field_type") or "").strip().lower()
            if current_type and current_type != field_type:
                continue

            global_alias = str(item.get("global_alias") or "").strip().lower()
            field_name = str(item.get("field_name") or "").strip().lower()
            verbose_name = str(item.get("verbose_name") or "").strip().lower()

            if global_alias and global_alias == normalized:
                global_alias_matches.append(item)
            if field_name and field_name == normalized:
                field_name_matches.append(item)
            if verbose_name and verbose_name == normalized:
                verbose_name_matches.append(item)

        for key, matches in (
            ("global_alias", global_alias_matches),
            ("field_name", field_name_matches),
            ("verbose_name", verbose_name_matches),
        ):
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                # field_name 完全一致 → 同一字段的 copy 衍生记录，自动筛选原始字段
                if key == "field_name" or all(
                    m.get("field_name") == matches[0].get("field_name") for m in matches
                ):
                    return self._pick_primary_field(matches, identifier)
                raise InvalidPayloadError(
                    f"字段标识存在歧义（{key} 命中多条）: {identifier}，请改用 global_alias 或 field_name"
                )

        raise InvalidPayloadError(f"字段不存在于当前数据集 metadata 中: {identifier}")

    @staticmethod
    def _pick_primary_field(matches: list[dict], identifier: str) -> dict:
        """从多条匹配记录中筛选最可能的原始字段。

        评分规则（从高到低）：
        1. global_alias 无 _数字 后缀（衍生字段会带 _数字 后缀）
        2. verbose_name 最短（原始字段无 _copy 等后缀）
        3. global_alias 最短
        """
        def _score(item: dict) -> tuple:
            alias = str(item.get("global_alias") or "")
            vname = str(item.get("verbose_name") or "")

            # global_alias 是否有 _数字 后缀（衍生字段标志）
            has_derived_suffix = 1 if re.search(r"_\d+$", alias) else 0

            # 先按衍生标记排序（0=原始优先），再按 verbose_name 长度，最后按 alias 长度
            return (has_derived_suffix, len(vname), len(alias))

        sorted_matches = sorted(matches, key=_score)
        return sorted_matches[0]

    def _resolve_output_alias(self, alias: str | None, field: dict) -> str:
        """校验显式 alias，或默认回退到 global_alias。"""
        if alias:
            if not SELECT_ALIAS_PATTERN.match(alias):
                raise InvalidPayloadError(
                    "select alias 仅支持英文、数字和下划线，且不能以数字开头；"
                    "建议省略 alias 自动使用 global_alias"
                )
            return alias

        fallback = str(field.get("global_alias") or "").strip() or str(field.get("field_name") or "").strip()
        if not fallback:
            raise InvalidPayloadError("字段缺少可用 alias，请检查 query metadata")
        return fallback

    def _resolve_metric_expr(self, dataset_alias: str, field: dict) -> str:
        """指标字段优先使用汇总公式，否则回退到原始字段。"""
        summary_expression = str(field.get("summary_expression") or "").strip()
        if summary_expression:
            return summary_expression
        return f"{dataset_alias}.{field['field_name']}"

"""query 模块业务编排层。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

from opscli.auth import AuthClient
from opscli.query.domain.exceptions import DatasetNotFoundError, InvalidPayloadError, QueryMetadataNotReadyError
from opscli.query.domain.models import QueryMetadataResult
from opscli.query.services.intent_matcher import match_catalog_intents
from opscli.query.services.metadata_cache import MetadataCacheResult, get_metadata_cache
from opscli.query.transport.client import QueryClient
from opscli.skills.discovery.detector import SkillDetector


@dataclass
class _FieldSpec:
    field_name: str
    alias: str | None
    aggregation: str | None = None


SELECT_ALIAS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# 目前支持的全局币种白名单（大写 ISO 4217，与后端 dm_global_currencies 表种子一致）
SUPPORTED_GLOBAL_CURRENCIES = ["USD", "GBP", "CAD", "EUR", "JPY", "CNY"]


def _attribution_headers(
    intent_code: str | None, selection_source: str | None, match_record_id: int | None,
) -> dict | None:
    """把归因三元组转成请求头字典；全空返回 None 表示不附加。

    为什么走 Header 而非 payload 字段：cli-query / cli-query/simple 的 body 会原样
    透传给 Python 取数服务，塞入归因字段有被下游拒绝的风险；服务端契约（QA 已上线）
    约定归因信息通过 X-Intent-Code / X-Selection-Source / X-Match-Record-Id 三个请求头传递。
    """
    headers = {}
    if intent_code:
        headers["X-Intent-Code"] = intent_code
    if selection_source:
        headers["X-Selection-Source"] = selection_source
    if match_record_id:
        headers["X-Match-Record-Id"] = str(match_record_id)
    return headers or None


def _normalize_global_currency(value: str | None) -> str | None:
    """归一并校验全局币种：去空格转大写，仅接受白名单 6 种；None/空返回 None，非白名单抛错。"""
    if value is None:
        return None
    code = str(value).strip().upper()
    if code == "":
        return None
    if code not in SUPPORTED_GLOBAL_CURRENCIES:
        raise InvalidPayloadError(
            f"不支持的币种: {value}，仅支持 {'/'.join(SUPPORTED_GLOBAL_CURRENCIES)}"
        )
    return code


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
        timeout: float | None = None,
    ) -> None:
        """初始化管理器。timeout 为查询执行接口的 HTTP 超时秒数，透传给 QueryClient，None 时使用默认值。"""
        self.detector = SkillDetector()
        self.client = QueryClient(auth_client=auth_client, jwt=jwt, session_id=session_id, timeout=timeout)
        self.template_dir = Path(__file__).resolve().parent.parent.parent / "skills" / "templates" / "ops-dataset-query" / "data"

    def metadata_all(
        self, *, user_email: str, base_dir: Path | None = None
    ) -> MetadataCacheResult:
        """获取当前用户的全量元数据（全部数据集全部字段），经用户级缓存。

        缓存未命中/过期时向后端 query-metadata?include_all_fields=1 拉取一次并落盘；
        1 小时内复用；后端失败时回退过期缓存并标 stale。

        Args:
            user_email: 当前用户邮箱（缓存隔离维度，由 CLI/MCP 调用方注入）。
            base_dir: 缓存根目录；CLI 默认 CONFIG_DIR，MCP 传隔离目录。

        Returns:
            MetadataCacheResult。
        """
        cache = get_metadata_cache(base_dir)
        # fetch_fn 惰性拉取全量：仅在缓存未命中/过期时才真正打后端
        return cache.get(
            user_email,
            lambda: self.client.fetch_query_metadata(include_all_fields=True),
        )

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
        """按数据集别名或 table_id 查询 query metadata。

        始终远端优先拉取最新数据，远端失败则回退到本地缓存。
        未指定 --dataset / --table-id 时返回所有数据集列表（不含字段），
        指定了筛选条件时返回匹配的数据集及其字段。
        """
        # 远端优先，统一拉取最新数据；过滤参数透传给后端按需收敛
        source = "remote"
        try:
            remote_data = self.client.fetch_query_metadata(
                dataset_alias=dataset_alias,
                table_id=table_id,
            )
            datasets = remote_data.get("datasets") or []
            fields = remote_data.get("fields") or []
        except Exception:
            # 远端失败时回退到本地缓存
            payload = self._load_query_metadata(skills_dir=skills_dir, cwd=cwd)
            datasets = payload.get("datasets") or []
            fields = payload.get("fields") or []
            source = "local"

        # 未指定筛选条件 → 返回所有数据集列表，不含字段
        if not dataset_alias and table_id is None:
            return QueryMetadataResult(dataset={}, fields=[], source=source, all_datasets=datasets)

        # 指定了数据集 → 按条件匹配
        matched = None
        if dataset_alias:
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
            hint = ""
            if source == "local":
                hint = (
                    "\n  当前使用的是本地缓存数据，可能未同步。"
                    "\n  请执行 opscli skills upgrade ops-dataset-query 更新缓存后重试"
                )
            owners = self._component_owner_datasets(datasets, needle)
            if owners:
                # 该 alias 是某个已授权数据集下发的查询组件。这类失败此前只回一句
                # 「未找到目标数据集」，调用方会误以为是自己写错了 alias，
                # 于是反复改名重试——线上取数反馈里 607 条（单项最大）都是这一形态。
                # 真实成因是该组件表未随引用它的数据集一起授权，属服务端权限配置。
                hint = (
                    f"\n  该标识是「{owners[0]}」等 {len(owners)} 个已授权数据集下发的查询组件，"
                    "不是业务数据集，说明它未随引用它的数据集一并授权。"
                    "\n  这不是 alias 写错，重试与改名都无效："
                    "请升级到已修复该问题的服务端版本，或按 references/feedback-guide.md 提交一次反馈。"
                )
            raise DatasetNotFoundError(f"未找到目标数据集: {needle}{hint}")

        # 筛选该数据集对应的字段
        matched_fields = [
            item for item in fields
            if int(item.get("table_id", -1)) == int(matched.get("table_id", -1))
        ]

        # 提取查询组件（select_columns）：远端直接嵌套在 dataset 对象内；
        # 本地回退时从 dataset_select_columns.csv 按 dataset_alias 读取
        select_columns = list(matched.get("select_columns") or [])
        if not select_columns and source == "local":
            matched_alias = str(matched.get("dataset_alias") or "")
            if matched_alias:
                select_columns = self._load_select_columns_from_csv(
                    dataset_alias=matched_alias,
                    skills_dir=skills_dir,
                    cwd=cwd,
                )

        # 提取数据集默认条件：远端响应与本地 query_metadata.json（远端同源缓存）
        # 均在 dataset 对象内嵌 filter_configs，旧缓存缺该字段时回退空列表
        filter_configs = list(matched.get("filter_configs") or [])

        return QueryMetadataResult(
            dataset=matched,
            fields=matched_fields,
            source=source,
            select_columns=select_columns,
            filter_configs=filter_configs,
        )

    def user_preferences(self) -> list[dict]:
        """获取当前用户的图表字段偏好列表（远端实时获取）。"""
        return self.client.fetch_user_preferences()

    def run(
        self,
        *,
        payload_path: str,
        intent_code: str | None = None,
        selection_source: str | None = None,
        match_record_id: int | None = None,
    ) -> dict:
        """读取本地 payload 文件并转发执行查询。

        intent_code/selection_source/match_record_id 为可选的执行归因三元组，
        标注本次查询来自哪次意图匹配/选表来源，以请求头形式透传，不写入 payload。
        """
        payload_file = Path(payload_path).expanduser()
        if not payload_file.exists():
            raise InvalidPayloadError(f"payload 文件不存在: {payload_file}")

        try:
            payload = json.loads(payload_file.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            raise InvalidPayloadError(f"payload 不是合法 JSON: {payload_file}") from exc

        self._validate_payload(payload)
        extra_headers = _attribution_headers(intent_code, selection_source, match_record_id)
        return self.client.cli_query(payload, extra_headers=extra_headers)

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
        global_currency: str | None = None,
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

        # 全局币种：归一+白名单校验后放入 payload 顶层，透传给后端（后端再放到 query.from 层级）
        normalized_currency = _normalize_global_currency(global_currency)
        if normalized_currency:
            payload["globalCurrency"] = normalized_currency

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

    def build_and_run(
        self,
        *,
        intent_code: str | None = None,
        selection_source: str | None = None,
        match_record_id: int | None = None,
        **kwargs,
    ) -> dict:
        """先构造 payload，再立即执行查询。

        intent_code/selection_source/match_record_id 说明见 run()，此处同样以
        请求头形式透传给 cli_query，不进入构造出的 payload。
        """
        build_result = self.build(**kwargs)
        extra_headers = _attribution_headers(intent_code, selection_source, match_record_id)
        query_result = self.client.cli_query(build_result["payload"], extra_headers=extra_headers)
        return {
            **build_result,
            "result": query_result,
        }

    # ── 简化查询支持（Simple Query API）────────────────────────────────

    def build_simple(
        self,
        *,
        table_id: int,
        dataset_alias: str | None = None,
        dimensions: list[dict] | None = None,
        metrics: list[dict] | None = None,
        filters: list[dict] | None = None,
        data_comparison: dict | None = None,
        order_by: list[dict] | None = None,
        limit: int | None = 20,
        offset: int | None = 0,
        dry_run: bool = False,
        output_path: str | None = None,
        validate_fields: bool = False,
        skills_dir: str | None = None,
        cwd: Path | None = None,
        global_currency: str | None = None,
    ) -> dict:
        """基于简化参数构造标准 simple query payload。

        参数格式：
        - dimensions: [{"field": "ds_xxx.dept_name", "alias": "f_xxx"}, ...]
        - metrics: [{"field": "ds_xxx.price", "aggregation": "SUM", "alias": "f_xxx"}, ...]
        - filters: [{"field": "ds_xxx.platform_name", "operator": "in", "value": ["Amazon"]}, ...]
        - data_comparison: {"field": "ds_xxx.date_id", "startDate": "2026-03-01", "endDate": "2026-03-22"}
        - order_by: [{"field": "f_xxx", "desc": true}, ...]

        未显式提供 alias 的 dimension/metric，会自动以 field 末段补齐
        （如 ds_xxx.dept_name → dept_name），与规划器 alias=field_name 约定一致，
        避免后端 simple 接口因 dimensions.*.alias / metrics.*.alias 必填而报 422。
        """
        if not dimensions and not metrics:
            raise InvalidPayloadError("至少需要提供一个 dimension 或 metric")

        if validate_fields:
            metadata = self.metadata(dataset_alias=dataset_alias, table_id=table_id, skills_dir=skills_dir, cwd=cwd)
            self._validate_simple_fields(
                metadata.fields,
                dimensions=dimensions or [],
                metrics=metrics or [],
                filters=filters or [],
                data_comparison=data_comparison,
                select_columns=metadata.select_columns or [],
            )

        # 后端 simple 接口要求每个 dimension/metric 必带 alias（且 alias 即返回结果集的键名）。
        # 此处对缺失/空 alias 的项统一以 field 末段兜底补齐，覆盖 CLI 与 MCP 两条 simple 手工路线。
        dimensions = self._fill_simple_alias(dimensions)
        metrics = self._fill_simple_alias(metrics)
        # 过滤操作符符号形态归一（= → eq、>= → gte …）。
        # 此前归一只作用于 --where 简写（走 _parse_where_condition），
        # 而 query simple 的 filters 直接来自 --json/--payload，从不经过归一，
        # 于是手写 payload 用 "=" 会被服务端硬拒：「无效的过滤操作符: =」。
        # 线上 3987 条取数反馈里有 189 条卡在这里，全部来自绕过执行器直连的场景。
        # 复用既有的 _validate_simple_filter_operators：它就地归一且支持嵌套
        # conditions 与 AND/OR 逻辑节点，此前只在 validate_fields=True 时才可达。
        if filters:
            self._validate_simple_filter_operators(filters)

        payload: dict[str, object] = {
            "tableId": table_id,
        }

        if dimensions:
            payload["dimensions"] = dimensions
        if metrics:
            payload["metrics"] = metrics
        if filters:
            payload["filters"] = filters
        if data_comparison:
            payload["dataComparison"] = data_comparison
        if order_by:
            payload["orderBy"] = order_by

        # None 容错：limit/offset 为 None 时回落默认值，避免 None 进入 payload
        # （编译版 Cython 的 int 参数拒绝 None；此处对任意调用方兜底，沿用后端默认）
        payload["limit"] = 20 if limit is None else limit
        payload["offset"] = 0 if offset is None else offset

        # 全局币种：归一+白名单校验后放入 payload 顶层，透传给后端 simple 接口
        normalized_currency = _normalize_global_currency(global_currency)
        if normalized_currency:
            payload["globalCurrency"] = normalized_currency

        if dry_run:
            payload["dryRun"] = True

        if output_path:
            output_file = Path(output_path).expanduser()
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "payload": payload,
            "output": str(Path(output_path).expanduser()) if output_path else None,
        }

    def build_simple_and_run(
        self,
        *,
        intent_code: str | None = None,
        selection_source: str | None = None,
        match_record_id: int | None = None,
        **kwargs,
    ) -> dict:
        """先构造简化 payload，再立即执行查询。

        intent_code/selection_source/match_record_id 说明见 run()，此处同样以
        请求头形式透传给 cli_simple_query，不进入构造出的 payload。
        """
        build_result = self.build_simple(**kwargs)
        extra_headers = _attribution_headers(intent_code, selection_source, match_record_id)
        query_result = self.client.cli_simple_query(build_result["payload"], extra_headers=extra_headers)
        return {
            **build_result,
            "result": query_result,
        }

    def run_query_template(self, execution_ref: dict) -> dict:
        """按规划器 execution_ref.query_template 直接执行查询（一体化 run_flow 用）。

        query_template 已是就绪的 simple query payload 骨架（tableId/dimensions/
        metrics/filters/dataComparison，以及未填的 orderBy/limit 占位）。执行前删除
        值为 None 的占位键。

        注意：数据集默认条件（default_filters）由服务端在查询时权威注入，
        禁止在客户端预填——客户端预填会与服务端解析后的真实日期 AND 合并导致恒 0 行
        （见 query_plan._build_query_template 的填充规则与 R5 说明）。

        Args:
            execution_ref: 规划合同的 execution_ref，须含 query_template。

        Returns:
            服务端查询结果 dict。

        Raises:
            InvalidPayloadError: execution_ref 缺少可执行的 query_template。
        """
        template = (execution_ref or {}).get("query_template")
        if not isinstance(template, dict):
            raise InvalidPayloadError("execution_ref 缺少 query_template，无法执行")
        # 删除 None 占位键（orderBy/limit 未填时不下发），其余键原样转发
        payload = {key: value for key, value in template.items() if value is not None}
        return self.client.cli_simple_query(payload)

    def _validate_simple_fields(
        self,
        fields: list[dict],
        *,
        dimensions: list[dict],
        metrics: list[dict],
        filters: list[dict],
        data_comparison: dict | None,
        select_columns: list[dict] | None = None,
    ) -> None:
        """校验 simple query 参数中的字段均能唯一落到当前数据集 metadata。

        simple 查询通常由 Agent 根据自然语言拼装参数；如果字段名相似、
        中文名重复或过滤字段未经校验，最容易产生"查得到但口径错"的问题。
        这里在真正执行前做硬门禁：维度、指标、过滤条件和 dataComparison
        字段都必须在当前 table_id 的 metadata 中唯一命中。

        注意：select_columns（查询组件）中的字段即使不在普通 fields 列表中，
        也是合法的过滤条件，过滤校验时会跳过这些字段的 metadata 强制匹配。
        """
        # 构建查询组件字段名集合。提到最前面：dimensions 的校验也要用它区分
        # 「这个字段根本不存在」与「这个字段只能筛选、不能分组」两种情况。
        select_column_names: set[str] = set()
        for sc in (select_columns or []):
            col = str(sc.get("column_name") or "").strip().lower()
            if col:
                select_column_names.add(col)

        if not fields and select_columns:
            # 没有普通字段、只有查询组件时，任何分组维度都不可能成立，
            # 必须在这里就说清楚，不能放行到服务端换一句笼统的「字段不存在」
            for item in dimensions:
                field_ref = self._extract_simple_field_ref(item, context="dimension")
                self._reject_filter_only_dimension(field_ref, select_column_names, fields)
            self._validate_simple_filter_operators(filters)
            return

        if not fields:
            raise InvalidPayloadError("当前数据集 metadata 未返回字段，无法执行字段歧义门禁")

        for item in dimensions:
            field_ref = self._extract_simple_field_ref(item, context="dimension")
            if not self._has_dimension_candidate(fields, field_ref):
                self._reject_filter_only_dimension(field_ref, select_column_names, fields)
            self._resolve_simple_field(fields, field_ref, field_type="dimension", context="dimension")

        for item in metrics:
            if isinstance(item, dict) and item.get("expr") and not item.get("field"):
                continue
            field_ref = self._extract_simple_field_ref(item, context="metric")
            resolved = self._resolve_simple_field(fields, field_ref, field_type="metric", context="metric")
            aggregation = item.get("aggregation") if isinstance(item, dict) else self._extract_simple_metric_aggregation(item)
            if aggregation and self._field_has_formula(resolved):
                # 公式字段已内置聚合表达式，自动修正：移除 aggregation，填入 expr
                formula_expr = (
                    str(resolved.get("summary_expression") or "").strip()
                    or str(resolved.get("detail_expression") or "").strip()
                )
                if formula_expr:
                    item["expr"] = formula_expr
                item.pop("aggregation", None)
                logger.info(
                    "公式字段自动修正: %s 移除 aggregation=%s，%s",
                    field_ref, aggregation, "填入 expr" if formula_expr else "仅移除 aggregation",
                )

        for field_ref in self._iter_filter_field_refs(filters):
            normalized = self._normalize_simple_field_identifier(field_ref)
            if normalized in select_column_names:
                continue
            self._resolve_simple_field(fields, field_ref, field_type=None, context="filter")

        self._validate_simple_filter_operators(filters)

        if data_comparison:
            field_ref = data_comparison.get("field")
            if not field_ref:
                raise InvalidPayloadError("dataComparison 缺少 field")
            self._resolve_simple_field(fields, str(field_ref), field_type=None, context="dataComparison")

    @staticmethod
    def _component_owner_datasets(datasets: list[dict], needle: str) -> list[str]:
        """找出把 needle 作为查询组件下发出去的已授权数据集中文名。

        用于把「未找到目标数据集」这句话，从「你写错了 alias」纠正为
        「这是组件表且未随引用它的数据集一并授权」——两者的处置方式完全不同。
        """
        target = str(needle or "").strip()
        if not target:
            return []
        owners: list[str] = []
        for dataset in datasets:
            for column in dataset.get("select_columns") or []:
                if str(column.get("component_dataset_alias") or "").strip() == target:
                    name = str(
                        dataset.get("description")
                        or dataset.get("dataset_name")
                        or dataset.get("dataset_alias")
                        or ""
                    ).strip()
                    if name and name not in owners:
                        owners.append(name)
                    break
        return owners

    @staticmethod
    def _is_groupable(field: dict) -> bool:
        """字段是否可作为分组维度。

        groupable 由服务端按 dm_table_columns.groupby 下发；老版本 metadata 没有
        这个键，此时一律按可分组处理，保证升级前后行为不回退。
        """
        flag = field.get("groupable")
        if flag is None:
            return True
        return str(flag).strip() not in ("0", "false", "False", "")

    def _has_dimension_candidate(self, fields: list[dict], identifier: str) -> bool:
        """该标识在当前数据集里是否存在可作为分组维度的字段。

        只做存在性判断、不抛异常：用于在报「字段不存在」之前，先分辨出
        「其实存在，但只能筛选不能分组」这一类，给出针对性的错误信息。
        """
        normalized = self._normalize_simple_field_identifier(identifier)
        if not normalized:
            return False
        for item in fields:
            if str(item.get("field_type") or "").strip().lower() != "dimension":
                continue
            if not self._is_groupable(item):
                continue
            for key in ("global_alias", "field_name", "verbose_name"):
                if str(item.get(key) or "").strip().lower() == normalized:
                    return True
        return False

    def _matches_filter_only_field(self, fields: list[dict], identifier: str) -> bool:
        """该标识是否命中了一个「存在但不可分组」的字段。

        与 select_columns 互补：有些字段就在 fields 里，只是服务端把 groupby 关了
        （线上反馈原文：「table_id=13 的 platform_name 仍仅可筛选不可分组」）。
        """
        normalized = self._normalize_simple_field_identifier(identifier)
        if not normalized:
            return False
        for item in fields:
            if self._is_groupable(item):
                continue
            for key in ("global_alias", "field_name", "verbose_name"):
                if str(item.get(key) or "").strip().lower() == normalized:
                    return True
        return False

    def _reject_filter_only_dimension(
        self,
        identifier: str,
        select_column_names: set[str],
        fields: list[dict] | None = None,
    ) -> None:
        """字段只存在于查询组件（select_columns）时，明确告知它不能当分组维度。

        为什么要单独区分：select_columns 里的字段（platform_name / asin / team_name …）
        在 metadata 里可见，也确实是合法的**筛选**字段，但不在 fields 里，
        因此不能进 dimensions。此前这种情况要么被放行到服务端换回一句
        「dimension 字段不存在于当前数据集 metadata 中: platform_name」，
        要么被客户端报成同样笼统的「字段不存在」——两种措辞都在暗示「换个字段名」，
        而真正的解法是「把它从 dimensions 挪到 filters」。
        线上 3987 条取数反馈里 497 条属字段类失败，其中 275 条正是这一形态。
        """
        normalized = self._normalize_simple_field_identifier(identifier)
        if not normalized:
            return
        is_component = normalized in select_column_names
        if not is_component and not self._matches_filter_only_field(fields or [], identifier):
            return
        source = "该数据集的查询组件字段" if is_component else "该数据集中不可分组的字段"
        raise InvalidPayloadError(
            f"dimension 字段 {identifier} 是{source}，只能用于 filters 筛选，"
            f"不能作为分组维度\n"
            f"  处理方式: 把它从 dimensions 移到 filters；"
            f"若确实需要按它分组，请改用本身含该字段可分组的数据集"
        )

    @staticmethod
    def _extract_simple_field_ref(item: dict | str, *, context: str) -> str:
        if isinstance(item, str):
            field_ref = item.split(":", 1)[0].strip()
            if not field_ref:
                raise InvalidPayloadError(f"{context} 缺少 field")
            return field_ref
        field_ref = str(item.get("field") or "").strip()
        if not field_ref:
            raise InvalidPayloadError(f"{context} 缺少 field")
        return field_ref

    @classmethod
    def _fill_simple_alias(cls, items: list[dict] | None) -> list[dict] | None:
        """为缺失/空 alias 的 dimension/metric 项以 field 末段兜底补齐 alias。

        后端 simple 接口强制 dimensions.*.alias / metrics.*.alias 必填，且 alias
        直接作为返回结果集的键名。simple 手工路线（CLI --json / MCP query_simple）
        常只传 field 不传 alias，故在此统一补齐：取 field 末段（ds_xxx.dept_name →
        dept_name），保留原大小写，与规划器 _build_query_template 的 alias=field_name
        约定一致。

        已显式提供非空 alias 的项原样保留；返回新列表 + 新 dict，不原地修改入参。

        Args:
            items: dimension 或 metric 列表，元素为 dict（如 {"field": ..., "alias"?: ...}）

        Returns:
            补齐 alias 后的新列表；入参为空时原样返回。
        """
        if not items:
            return items
        result: list[dict] = []
        for item in items:
            # 已带非空 alias 的项无需处理，直接沿用原引用
            if not isinstance(item, dict) or str(item.get("alias") or "").strip():
                result.append(item)
                continue
            # 取 field 末段作为 alias（复用 _extract_simple_field_ref 兼容 str/dict 并做非空校验）
            field_ref = cls._extract_simple_field_ref(item, context="dimensions/metrics")
            alias = field_ref.rsplit(".", 1)[-1]
            result.append({**item, "alias": alias})
        return result

    @staticmethod
    def _extract_simple_metric_aggregation(item: str) -> str | None:
        parts = item.split(":", 2)
        if len(parts) < 2:
            return None
        return parts[1].strip() or None

    @staticmethod
    def _field_has_formula(field: dict) -> bool:
        if any(str(field.get(key) or "").strip() for key in ("formula_config", "summary_expression", "detail_expression")):
            return True
        flag = str(field.get("has_formula_config") or "").strip().lower()
        return flag not in ("", "0", "false", "none", "null")

    def _iter_filter_field_refs(self, filters: list[dict]) -> list[str]:
        refs: list[str] = []

        def walk(node: dict) -> None:
            if not isinstance(node, dict):
                return
            field_ref = node.get("field")
            if field_ref:
                refs.append(str(field_ref))
            for child in node.get("conditions") or []:
                walk(child)

        for item in filters:
            walk(item)
        return refs

    def _validate_simple_filter_operators(self, filters: list[dict]) -> None:
        """校验并标准化 filters 中的 operator 字段。

        支持符号操作符（=, >=, <=, >, <, !=, <>, ==）自动转换为语义操作符，
        与 query build 的 _WHERE_OP_MAP 行为对齐。就地修改 node 确保后续
        build_simple 构造 payload 时使用标准化后的值。
        """
        valid = self._VALID_FILTER_OPERATORS
        logical = self._LOGICAL_OPERATORS

        def walk(node: dict) -> None:
            if not isinstance(node, dict):
                return
            op = node.get("operator")
            if op:
                op_str = str(op).strip()
                if op_str in logical:
                    pass  # AND/OR 逻辑操作符，合法跳过
                else:
                    # 符号操作符自动标准化为语义操作符
                    normalized = self._WHERE_OP_MAP.get(op_str, op_str)
                    if normalized != op_str:
                        node["operator"] = normalized
                        op_str = normalized
                    if op_str not in valid:
                        raise InvalidPayloadError(
                            f"无效的过滤操作符: {op}\n"
                            f"  支持: {', '.join(sorted(valid))}"
                        )
            for child in node.get("conditions") or []:
                walk(child)

        for item in filters:
            walk(item)

    def _resolve_simple_field(
        self,
        fields: list[dict],
        identifier: str,
        *,
        field_type: str | None,
        context: str,
    ) -> dict:
        normalized = self._normalize_simple_field_identifier(identifier)
        if not normalized:
            raise InvalidPayloadError(f"{context} 字段标识不能为空")

        scoped_fields = []
        for item in fields:
            current_type = str(item.get("field_type") or "").strip().lower()
            if field_type and current_type and current_type != field_type:
                continue
            scoped_fields.append(item)

        tiers = (
            ("global_alias", [item for item in scoped_fields if str(item.get("global_alias") or "").strip().lower() == normalized]),
            ("field_name", [item for item in scoped_fields if str(item.get("field_name") or "").strip().lower() == normalized]),
            ("verbose_name", [item for item in scoped_fields if str(item.get("verbose_name") or "").strip().lower() == normalized]),
        )
        for key, matches in tiers:
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                # field_name 双注册（同一物理字段的英中双名，或公式 vs 裸指标同名）与
                # 规划器 _merge_duplicate_field_rows 口径一致地消歧：可合并则返回规范字段
                # （形态一纯标签差异任取其一；形态二采纳公式注册以保证聚合口径正确），
                # 后端按 field_name 自行解析（实测同名字段后端稳定命中公式口径）。
                # 仅真正的多口径冲突（多个不同公式）才报歧义错误。
                if key == "field_name":
                    merged = self._merge_ambiguous_field_name(matches)
                    if merged is not None:
                        return merged
                raise InvalidPayloadError(
                    self._format_field_ambiguity_error(context, identifier, key, matches)
                )

        fuzzy_matches = [
            item for item in scoped_fields
            if self._simple_field_fuzzy_match(item, normalized)
        ]
        if len(fuzzy_matches) == 1:
            return fuzzy_matches[0]
        if len(fuzzy_matches) > 1:
            raise InvalidPayloadError(
                self._format_field_ambiguity_error(context, identifier, "fuzzy", fuzzy_matches)
            )

        raise InvalidPayloadError(f"{context} 字段不存在于当前数据集 metadata 中: {identifier}")

    @staticmethod
    def _merge_ambiguous_field_name(matches: list[dict]) -> dict | None:
        """对同名（field_name 重复）字段做与规划器一致的双注册消歧。

        返回规范字段：
        - 形态一「纯标签差异」：除展示名外执行语义完全一致 → 任取首个；
        - 形态二「公式 vs 裸指标」：field_type/快照一致，一为公式注册一为裸指标 →
          采纳公式注册（公式表达式是服务端权威聚合口径，避免均值/比率被误 SUM）；
        - 其余（多个不同公式表达式等真口径冲突）→ 返回 None，由调用方报歧义。

        与 planner.metadata_adapter._merge_duplicate_field_rows 的裁决规则对齐，
        保证 query_simple 与规划器对同名双注册的处理一致。
        """
        def _base(f: dict) -> tuple:
            # 公式列以外的执行语义（类型 + 快照标记）必须一致才可能合并
            snap = f.get("snapshot_metric")
            snap = "0" if snap in (None, "") else str(snap).strip()
            return (str(f.get("field_type") or "").strip().lower(), snap)

        if len({_base(f) for f in matches}) != 1:
            return None

        def _is_formula(f: dict) -> bool:
            return (
                str(f.get("has_formula_config")) == "1"
                or bool(str(f.get("summary_expression") or "").strip())
                or bool(str(f.get("detail_expression") or "").strip())
            )

        formula_rows = [f for f in matches if _is_formula(f)]
        plain_rows = [f for f in matches if not _is_formula(f)]
        # 形态一：无公式差异，纯标签差异 → 任取
        if not formula_rows:
            return matches[0]
        # 形态二：公式 + 裸指标，且公式表达式唯一 → 采纳公式
        if plain_rows and len(
            {
                (str(f.get("summary_expression") or ""), str(f.get("detail_expression") or ""))
                for f in formula_rows
            }
        ) == 1:
            return formula_rows[0]
        return None

    @staticmethod
    def _normalize_simple_field_identifier(identifier: str) -> str:
        value = str(identifier).strip()
        if "." in value:
            value = value.rsplit(".", 1)[-1]
        return value.strip().lower()

    @staticmethod
    def _simple_field_fuzzy_match(item: dict, normalized: str) -> bool:
        if len(normalized) < 2:
            return False
        field_name = str(item.get("field_name") or "").strip().lower()
        verbose_name = str(item.get("verbose_name") or "").strip().lower()
        return bool(
            (field_name and normalized in field_name)
            or (verbose_name and normalized in verbose_name)
        )

    @staticmethod
    def _format_field_ambiguity_error(context: str, identifier: str, key: str, matches: list[dict]) -> str:
        candidates = []
        for item in matches[:8]:
            candidates.append(
                f"{item.get('field_name') or '-'} / {item.get('verbose_name') or '-'} / {item.get('global_alias') or '-'}"
            )
        suffix = "；候选过多，仅展示前 8 个" if len(matches) > 8 else ""
        return (
            f"{context} 字段标识存在歧义（{key} 命中 {len(matches)} 条）: {identifier}。"
            f"同名双注册（英中双名 / 公式vs裸指标）已自动消歧；若仍报此错，"
            f"说明该字段名在当前数据集对应多个不同聚合口径，属元数据异常，"
            f"请按 feedback 规范反馈。候选: "
            + "；".join(candidates)
            + suffix
        )

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

        md_lines.append("## 二、关键术语与命名约定")
        md_lines.append("")
        md_lines.append("### 2.1 术语说明")
        md_lines.append("")
        md_lines.append("| 术语 | 含义 | 典型用途 |")
        md_lines.append("|------|------|----------|")
        md_lines.append("| `query_alias` | 当前 Query 中 `select.alias` 使用的输出列别名 | 对齐查询结果列名、`groupBy`、`orderBy` |")
        md_lines.append("| `field_name` | 统一字段映射表中的字段名 | 业务识别、脚本内字段归类 |")
        md_lines.append("| `origin_name` | 字段原始引用名，通常为 `dataset_alias.column_name` | 构造 `where` / `dataComparison.field` |")
        md_lines.append("| `global_alias` | 字段统一全局别名 | 与图表配置、查询结果做稳定映射 |")
        md_lines.append("| `field_type` | `dimension` 或 `metric` | 决定字段角色与用法 |")
        md_lines.append("")
        md_lines.append("### 2.2 字段命名约定")
        md_lines.append("")
        md_lines.append("| 别名类型 | 格式规律 | 生成方式 | 使用场景 |")
        md_lines.append("|----------|----------|----------|----------|")
        md_lines.append("| `query_alias` | `f_[16位16进制]`，如 `f_9064850a20e4d581` | 系统自动生成，**禁止手写** | `select.alias`、`groupBy`、`orderBy` 中引用字段 |")
        md_lines.append("| `global_alias` | `f_[20位字母数字]`，如 `f_WfKn5Dex0mqGINtDlWx` | 系统自动生成，跨 Query 保持稳定 | 字段身份识别，与图表配置做稳定映射 |")
        md_lines.append("| `origin_name` | `{dataset_alias}.{column_name}` | 由数据集别名 + 列名拼接 | `where.field`、`dataComparison.field` 的值 |")
        md_lines.append("| `expr`（select） | 通常等于 `origin_name`；公式字段时为完整 SQL 表达式 | 来自图表配置 | `select.expr`，直接传入查询服务 |")
        md_lines.append("")
        md_lines.append("> **边界场景**：当字段的 `expr` 与 `origin_name` 不同时（即公式字段），构造 select 时必须使用 `expr` 原值，")
        md_lines.append("> 且不得再传 `aggregation`（公式内已内置聚合逻辑）。")
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
        # 建立 dataset 索引，便于为每个 query 快速找到对应的 fields 和 filterable_fields
        dataset_field_index: dict[tuple[str, int | None, str], list[dict]] = {}
        # dataset_filterable_index: key → frozenset of column_names，用于 7.3 节去重判断
        dataset_filterable_index: dict[tuple[str, int | None, str], frozenset[str]] = {}
        for ds in datasets:
            if not isinstance(ds, dict):
                continue
            key = (
                str(ds.get("dataset_alias") or ""),
                ds.get("tableId") if isinstance(ds.get("tableId"), int) else None,
                str(ds.get("dataSource") or ""),
            )
            dataset_field_index[key] = ds.get("fields") or []
            # 将数据集级可过滤字段的 column_name 集合存入索引，供后续去重比对
            dataset_filterable_index[key] = frozenset(
                str(f.get("column_name") or "")
                for f in (ds.get("filterable_fields") or [])
                if isinstance(f, dict) and f.get("column_name")
            )

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
                # 表 A：字段语义（AI 读取，4列）
                md_lines.append("**表A — 字段语义**（用于理解字段业务含义）")
                md_lines.append("")
                md_lines.append("| verbose_name | field_type | aggregation | field_name |")
                md_lines.append("|--------------|------------|-------------|------------|")
                for mapping in select_field_mappings:
                    md_lines.append(
                        f"| {mapping.get('verbose_name') or '-'} | `{mapping.get('field_type') or '-'}` | "
                        f"`{mapping.get('aggregation') or '-'}` | `{mapping.get('field_name') or '-'}` |"
                    )
                md_lines.append("")
                # 表 B：字段引用（AI 构造查询，4列）
                # expr 通常等于 origin_name，仅公式字段时不同；
                # 当 expr != origin_name 时在 select.expr 中必须使用 expr 原值
                md_lines.append("**表B — 字段引用**（用于构造 select / groupBy / where）")
                md_lines.append("")
                md_lines.append("| field_name | query_alias | origin_name | global_alias |")
                md_lines.append("|------------|-------------|-------------|--------------|")
                for mapping in select_field_mappings:
                    expr = mapping.get("query_expr") or ""
                    origin = mapping.get("origin_name") or ""
                    # 当 expr 与 origin_name 不同（公式字段）时标注差异
                    origin_cell = f"`{origin}`" if origin else "-"
                    if expr and expr != origin:
                        origin_cell = f"`{origin}` [!] expr=`{expr}`"
                    md_lines.append(
                        f"| `{mapping.get('field_name') or '-'}` | `{mapping.get('query_alias') or '-'}` | "
                        f"{origin_cell} | `{mapping.get('global_alias') or '-'}` |"
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
                # 比较当前 Query 的过滤字段集合与数据集级别（第五章 §5.2）是否完全相同
                # 若相同则只引用，避免重复渲染浪费 token
                ds_key = (dataset_alias, table_id, data_source)
                ds_filterable_set = dataset_filterable_index.get(ds_key, frozenset())
                query_filterable_set = frozenset(
                    str(f.get("column_name") or "")
                    for f in filterable
                    if isinstance(f, dict) and f.get("column_name")
                )
                if query_filterable_set == ds_filterable_set and ds_filterable_set:
                    # 与数据集级可过滤字段完全相同，直接引用第五章，不重复渲染
                    md_lines.append(f"> 可过滤字段与数据集 `{dataset_alias}` 完全相同，见第五章 §5.2，共 {len(filterable)} 个字段。")
                else:
                    # 与数据集级不同（或无法比对），完整渲染本 Query 的过滤字段
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

    def _load_select_columns_from_csv(
        self,
        *,
        dataset_alias: str,
        skills_dir: str | None,
        cwd: Path | None,
    ) -> list[dict]:
        """从本地 dataset_select_columns.csv 读取指定数据集的查询组件列表。

        用于远端拉取失败、回退本地缓存时补充 select_columns 数据。
        文件不存在或列为空时静默返回空列表。
        """
        import csv

        records = self.detector.discover(skills_dir=skills_dir, cwd=cwd)
        csv_path: Path | None = None
        for record in records:
            if record.name != "ops-dataset-query":
                continue
            candidate = record.root / "data" / "dataset_select_columns.csv"
            if candidate.exists():
                csv_path = candidate
                break

        if csv_path is None:
            candidate = self.template_dir / "dataset_select_columns.csv"
            if candidate.exists():
                csv_path = candidate

        if csv_path is None:
            return []

        try:
            result: list[dict] = []
            with csv_path.open(encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("current_dataset_alias", "").strip() == dataset_alias:
                        result.append({
                            "column_name": row.get("column_name", "").strip(),
                            "verbose_name": row.get("verbose_name", "").strip(),
                            "component_dataset_alias": row.get("component_dataset_alias", "").strip(),
                        })
            return result
        except Exception:
            return []

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

    # ── dataset catalog（AI 业务语义索引）────────────────────────────

    def catalog(
        self,
        *,
        skills_dir: str | None = None,
        cwd: Path | None = None,
        source: str = "remote",
        fallback_local: bool = True,
    ) -> dict:
        """读取 dataset catalog（AI 业务语义索引）。

        返回完整的 catalog JSON 结构，包含 version、intent_count、intents、query_strategy。
        默认远端优先，远端失败时可回退本地缓存；source="local" 时纯本地只读。
        """
        normalized_source = source.strip().lower()
        if normalized_source not in {"remote", "local"}:
            raise InvalidPayloadError("--source 仅支持 remote 或 local")
        if normalized_source == "local":
            return self._load_dataset_catalog(skills_dir=skills_dir, cwd=cwd)

        try:
            return self.client.fetch_dataset_catalog()
        except Exception:
            if fallback_local:
                return self._load_dataset_catalog(skills_dir=skills_dir, cwd=cwd)
            raise

    def local_catalog(
        self,
        *,
        skills_dir: str | None = None,
        cwd: Path | None = None,
    ) -> dict:
        """读取本地 dataset catalog（兼容旧调用语义）。"""
        return self._load_dataset_catalog(skills_dir=skills_dir, cwd=cwd)

    def intent_match(
        self,
        *,
        query: str,
        skills_dir: str | None = None,
        cwd: Path | None = None,
        source: str = "remote",
        fallback_local: bool = True,
        report_source: str = "cli_intent",
    ) -> dict:
        """按自然语言需求匹配 dataset catalog intents，并上报匹配事件。

        上报是 fire-and-forget：闭环遥测的价值在服务端聚合，客户端绝不因
        上报失败影响匹配结果（match_record_id 置 None 即可）。
        """
        catalog = self.catalog(
            skills_dir=skills_dir,
            cwd=cwd,
            source=source,
            fallback_local=fallback_local,
        )
        result = match_catalog_intents(catalog, query)
        result["match_record_id"] = self._report_intent_match(result, query, report_source)
        return result

    def _report_intent_match(self, result: dict, query: str, report_source: str) -> int | None:
        """构造并发送匹配事件；任何异常静默吞掉返回 None（不阻塞主流程，不打印堆栈）。"""
        selected = result.get("selected") or (result.get("candidates") or [{}])[0]
        payload = {
            "matched": bool(result.get("matched")),
            "intent_code": selected.get("intent_code") or None,
            "score": int(selected.get("score") or 0),
            "ask_required": bool(result.get("ask_user_question_required")),
            "fallback_reason": result.get("fallback_reason") or "",
            "match_source": report_source,
            "query_text": query[:500],
            "query_keywords": result.get("fallback_query_keywords")
                or [term for term in selected.get("matched_terms") or []],
            "catalog_version": str(result.get("catalog_version") or ""),
        }
        try:
            response = self.client.report_intent_match(payload)
            record_id = (response.get("data") or {}).get("match_record_id")
            return int(record_id) if record_id else None
        except Exception:
            return None

    def _load_dataset_catalog(self, *, skills_dir: str | None, cwd: Path | None) -> dict:
        """从已安装 Skill 或内置模板中读取 dataset_catalog.json。"""
        catalog_file = self._resolve_catalog_file(skills_dir=skills_dir, cwd=cwd)
        try:
            payload = json.loads(catalog_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise QueryMetadataNotReadyError(f"dataset catalog 读取失败: {catalog_file}") from exc

        if not isinstance(payload, dict):
            raise QueryMetadataNotReadyError(f"dataset catalog 结构非法: {catalog_file}")
        return payload

    def _resolve_catalog_file(self, *, skills_dir: str | None, cwd: Path | None) -> Path:
        """优先使用已安装 Skill 的 catalog 文件，否则回退到内置模板。"""
        records = self.detector.discover(skills_dir=skills_dir, cwd=cwd)
        for record in records:
            if record.name != "ops-dataset-query":
                continue
            catalog_file = record.root / "data" / "dataset_catalog.json"
            if catalog_file.exists():
                return catalog_file

        fallback = self.template_dir / "dataset_catalog.json"
        if fallback.exists():
            return fallback
        raise QueryMetadataNotReadyError("本地未找到 dataset_catalog.json，请先安装并升级 ops-dataset-query")

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
                # utf-8-sig：PowerShell 的 Out-File / > 默认写 UTF-8 with BOM，
                # 用 utf-8 读会在首字符残留 ﻿ 导致 json.loads 直接失败
                # （线上反馈原文：「query build --where-file 无法读取 PowerShell UTF8 输出的 JSON」）
                payload = json.loads(file_path.read_text(encoding="utf-8-sig"))
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

    _VALID_FILTER_OPERATORS: set[str] = {
        "eq", "neq", "lt", "lte", "gt", "gte",
        "in", "not_in", "between", "like", "not_like",
        "is_null", "is_not_null",
    }

    _LOGICAL_OPERATORS: set[str] = {"AND", "OR"}

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

        if operator not in self._VALID_FILTER_OPERATORS:
            hint = f"  (支持: {', '.join(sorted(self._VALID_FILTER_OPERATORS))})"
            raise InvalidPayloadError(f"无效的操作符: {operator}{hint}")

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

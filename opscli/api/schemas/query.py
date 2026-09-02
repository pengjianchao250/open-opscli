"""query 场景 REST 请求合同（Pydantic Schema）。

合同原则：
- extra="forbid"：拒绝 MCP/内部参数（如 session_id/jwt）混入，避免接口随 Tool 演化漂移
- 只暴露 HTTP 语义参数；CLI 的本地文件传参（--payload/--query-file/--where-file）、
  结果落盘（--result-file/--save-result/--output）与 skills_dir 等终端专属概念
  一律不进 REST 合同——把服务端本地路径暴露给远端调用方等于开放任意文件读写
- 结构化优先：CLI 为绕开 Shell 转义设计的字符串简写（where_json 内联 JSON 等）
  在 REST 侧改为原生 JSON 结构
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# 取数引擎对查询 limit 的硬上限（body.query.limit <= 500000，超限返回 VALIDATION_ERROR）
MAX_QUERY_LIMIT = 500_000

# 查询 HTTP 超时秒数上限：REST 侧不允许调用方无限拉长服务端连接占用
MAX_QUERY_TIMEOUT = 300


class QueryPlanRequest(BaseModel):
    """自然语言请求 → 规划合同（只规划不执行，对应 query plan）。"""

    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=1, max_length=4000)
    requested_fields: list[str] = Field(default_factory=list, max_length=100)
    top_n: int | None = Field(default=None, ge=1, le=50)


class QueryFlowOrderBy(BaseModel):
    """查询结果排序项。"""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=128)
    desc: bool = False


class QueryFlowRequest(BaseModel):
    """自然语言取数 API 的稳定请求合同（对应 query flow）。"""

    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=1, max_length=4000)
    requested_fields: list[str] = Field(default_factory=list, max_length=100)
    limit: int | None = Field(default=None, ge=1, le=10000)
    order_by: list[QueryFlowOrderBy] | None = Field(default=None, max_length=50)
    offset: int | None = Field(default=None, ge=0)


class QueryIntentMatchRequest(BaseModel):
    """自然语言需求匹配 dataset catalog intents（对应 query intent）。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4000)
    source: Literal["remote", "local"] = "remote"
    fallback_local: bool = True


class QueryRunRequest(BaseModel):
    """执行已构造完整的 query payload（对应 query run）。

    payload 为 query_spec 规范的完整查询 JSON；userEmail、query.from.* 等构造层
    生成字段禁止手写，服务端校验会直接拒绝。
    """

    model_config = ConfigDict(extra="forbid")

    payload: dict[str, Any]
    intent_code: str | None = Field(default=None, min_length=1, max_length=128)
    selection_source: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="选表来源：planner/intent_route/local_fallback/user_specified",
    )
    match_record_id: int | None = Field(default=None, ge=1)
    timeout: int | None = Field(default=None, ge=1, le=MAX_QUERY_TIMEOUT)


class QueryBuildRequest(BaseModel):
    """基于简化参数构造标准 query payload，可选立即执行（对应 query build）。

    dimensions/metrics 沿用构造层标识格式：
    field_name|global_alias|verbose_name[:alias]（metric 额外支持 :aggregation）。
    """

    model_config = ConfigDict(extra="forbid")

    dataset: str | None = Field(default=None, min_length=1, max_length=128)
    table_id: int | None = Field(default=None, ge=1)
    dimensions: list[str] | None = Field(
        default=None, max_length=100, description="维度定义：field_name|global_alias|verbose_name[:alias]"
    )
    metrics: list[str] | None = Field(
        default=None, max_length=100, description="指标定义：field_name|global_alias|verbose_name:aggregation[:alias]"
    )
    where: list[dict[str, Any]] | None = Field(
        default=None,
        max_length=100,
        description="结构化筛选条件列表（CLI --where-json 的 REST 形态）",
    )
    having: list[str] | None = Field(
        default=None,
        max_length=100,
        description="having 条件：expr|operator|value_json",
    )
    order_by: list[str] | None = Field(default=None, max_length=50)
    limit: int = Field(default=20, ge=1, le=MAX_QUERY_LIMIT)
    offset: int = Field(default=0, ge=0)
    dry_run: bool = False
    data_comparison: str | None = Field(
        default=None,
        max_length=128,
        description="数据对比：field,start_date,end_date（例: date_id,2026-03-01,2026-03-22）",
    )
    global_currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="全局币种（USD/GBP/CAD/EUR/JPY/CNY），白名单由服务层校验",
    )
    run: bool = Field(default=False, description="构造后立即执行查询")
    timeout: int | None = Field(default=None, ge=1, le=MAX_QUERY_TIMEOUT)


class SimpleQuerySpec(BaseModel):
    """simple query 参数体（与 CLI --payload JSON 同构，snake_case 形态）。

    extra="ignore"：与 CLI 的 key_map 行为一致，只取认识的键，未知键不报错。
    """

    model_config = ConfigDict(extra="ignore")

    dimensions: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    metrics: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    filters: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    data_comparison: dict[str, Any] | None = None
    order_by: list[dict[str, Any]] | None = Field(default=None, max_length=50)
    limit: int | None = Field(default=None, ge=1, le=MAX_QUERY_LIMIT)
    offset: int | None = Field(default=None, ge=0)
    dry_run: bool = False
    global_currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="全局币种（USD/GBP/CAD/EUR/JPY/CNY）",
    )


class QuerySimpleRequest(BaseModel):
    """构造 simple query payload 并可选执行（对应 query simple）。"""

    model_config = ConfigDict(extra="forbid")

    table_id: int = Field(ge=1)
    dataset: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="dataset_alias 或 dataset_name，用于字段校验",
    )
    payload: SimpleQuerySpec
    global_currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="全局币种；优先级高于 payload.global_currency（与 CLI 选项优先级一致）",
    )
    run: bool = Field(default=False, description="构造后立即执行查询")
    timeout: int | None = Field(default=None, ge=1, le=MAX_QUERY_TIMEOUT)
    intent_code: str | None = Field(default=None, min_length=1, max_length=128)
    selection_source: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="选表来源：planner/intent_route/local_fallback/user_specified",
    )
    match_record_id: int | None = Field(default=None, ge=1)


class ChartRunRequest(BaseModel):
    """执行图表全部子查询并合并输出（对应 query chart --run）。"""

    model_config = ConfigDict(extra="forbid")

    dry_run: bool = Field(default=False, description="仅生成 SQL，不执行查询")
    timeout: int | None = Field(default=None, ge=1, le=MAX_QUERY_TIMEOUT)

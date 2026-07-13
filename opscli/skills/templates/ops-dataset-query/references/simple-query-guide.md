---
name: ops-dataset-query-simple-query
description: 仅使用本次授权 guidance/metadata 的简化查询参数合同
---

# 简化查询参数合同

## 来源边界

数据集必须已经用户确认。CLI-only 的表标识、维度、指标、公式、聚合和组件仅来自当前账号 selected-dataset guidance；MCP-only 仅来自当前已认证账号的 `query_metadata(dataset=...)` 响应。不猜测、不从其他来源补齐，不把文档占位符当作真实标识。

> 示例不得直接复制；必须将全部占位符替换为本次 guidance/metadata 返回值。

## 七个业务参数

| 概念 | JSON | MCP | 要求 |
|------|------|-----|------|
| 数据集 | `tableId` | `table_id` | 必须来自已选数据集 |
| 维度 | `dimensions` | `dimensions` | 只使用授权维度 |
| 指标 | `metrics` | `metrics` | 只使用授权指标与聚合 |
| 筛选 | `filters` | `filters` | 只使用用户确认条件 |
| 对比 | `dataComparison` | `data_comparison` | 必须与主周期同时传入 |
| 排序 | `orderBy` | `order_by` | 使用本次结果 alias |
| 分页 | `limit` / `offset` | `limit` / `offset` | 使用用户确认行数 |

MCP Tool 使用 snake_case，JSON payload 使用 camelCase，CLI 选项使用 kebab-case。

## 授权占位符模板

```json
{
  "tableId": "$TABLE_ID",
  "dimensions": [
    {
      "field": "$AUTHORIZED_DIMENSION",
      "alias": "$DIMENSION_RESULT_ALIAS"
    }
  ],
  "metrics": [
    {
      "field": "$AUTHORIZED_METRIC",
      "aggregation": "$AUTHORIZED_AGGREGATION",
      "alias": "$METRIC_RESULT_ALIAS"
    }
  ],
  "filters": [
    {
      "field": "$AUTHORIZED_FILTER",
      "operator": "$CONFIRMED_OPERATOR",
      "value": "$CONFIRMED_FILTER_VALUE"
    }
  ],
  "orderBy": [
    {
      "field": "$METRIC_RESULT_ALIAS",
      "desc": "$CONFIRMED_DESC"
    }
  ],
  "limit": "$CONFIRMED_LIMIT",
  "offset": "$CONFIRMED_OFFSET"
}
```

需要环比、同比或上期对比时，在主周期 `filters` 之外增加：

```json
{
  "dataComparison": {
    "field": "$AUTHORIZED_FILTER",
    "startDate": "$COMPARISON_START_DATE",
    "endDate": "$COMPARISON_END_DATE"
  }
}
```

对比字段必须是本次 guidance/metadata 返回的授权日期字段。`filters` 同时传入用户确认的主周期；不得只传 `dataComparison`。

## 公式指标

指标含 `formula_config`、`summary_expression` 或 `detail_expression` 时，不再传普通 `aggregation`。聚合/分组使用本次返回的汇总表达式，明细查询使用本次返回的明细表达式：

```json
{
  "field": "$AUTHORIZED_METRIC",
  "expr": "$AUTHORIZED_FORMULA_EXPRESSION",
  "alias": "$METRIC_RESULT_ALIAS"
}
```

## 快照指标

指标标记为快照类（guidance 中 `is_snapshot=true`，如库存量）时，默认只取最新快照日的值，禁止跨日/跨期累加聚合；需要趋势时按日期维度展示快照序列，不求和。

## 筛选与组件

- 不发明默认筛选，不用文档中的业务值代替用户确认。
- 可用操作符以当前正式查询合同为准；操作符和值必须与字段类型匹配。
- 明确筛选命中查询组件时，先按模式指南取得本次授权的组件关系和枚举。值不在枚举中时停止并请用户重选。

## CLI-only

将占位符替换后，只用正式简化查询入口：

```bash
opscli query simple --table-id "$TABLE_ID" \
  --json "$QUERY_JSON" --run --pretty
```

## MCP-only

将占位符替换后，使用 snake_case 调用正式 Tool：

```python
query_simple(
    table_id="$TABLE_ID",
    dimensions=[
        {"field": "$AUTHORIZED_DIMENSION", "alias": "$DIMENSION_RESULT_ALIAS"}
    ],
    metrics=[
        {
            "field": "$AUTHORIZED_METRIC",
            "aggregation": "$AUTHORIZED_AGGREGATION",
            "alias": "$METRIC_RESULT_ALIAS",
        }
    ],
    filters=[
        {
            "field": "$AUTHORIZED_FILTER",
            "operator": "$CONFIRMED_OPERATOR",
            "value": "$CONFIRMED_FILTER_VALUE",
        }
    ],
    limit="$CONFIRMED_LIMIT",
)
```

## 执行前检查

1. 数据集、维度、指标、筛选和公式是否全部来自本次授权响应。
2. 是否已用中文摘要让用户确认时间、币种、筛选值、排序和行数。
3. 公式指标是否避免二次聚合。
4. 对比查询是否同时包含主周期和对比周期。
5. 所有占位符是否已替换；任一占位符未替换都必须阻断执行。

字段不存在、公式被额外聚合、组件值未授权或对比缺少主周期时，修正参数后再请用户确认。正式工具出现意外失败时才进入反馈流程。

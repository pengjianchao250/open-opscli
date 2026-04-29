# 严重程度评分指南

## 自动评分规则

| 条件 | 基础分 | 加分项 |
|------|--------|--------|
| 退款率 > 品类均值 2 倍 | +30 | 每多 1 倍 +10 |
| 频率 > 20% | +25 | 每多 5% +5 |
| 涉及安全问题 | +50 | — |
| 影响星级 > 0.3 | +20 | — |

## 总分映射

| 总分 | 等级 | 处理时限 |
|------|------|---------|
| 80-100 | 严重（Critical） | 7 天 |
| 50-79 | 重要（Important） | 30 天 |
| 0-49 | 可优化（Nice-to-have） | 按需 |

## 修复成本估算参考

| 问题类型 | 估算成本 | 涉及资源 |
|---------|---------|---------|
| 包装设计改进 | $50-100 | 设计师 0.5-1 天 |
| 文案/图片调整 | $50-100 | 设计师 0.5-1 天 |
| 尺码表修正 | $50-100 | 运营 0.5 天 |
| 质检流程优化 | $200-500 | 运营 + 供应商沟通 |
| 供应商谈判换材料 | $500-2000 | 采购 + 样品测试 |
| 产品设计变更 | $2000-5000 | 工程师 + 模具修改 |
| 新功能开发 | $5000+ | 产品 + 工程团队 |

## 数据集字段映射

> **注意**：构造查询时请使用 `opscli query build` 命令自动生成完整 payload，以下模板仅展示字段映射关系。

### 自定义退款地点设置（`ds_y5EoxUyLf6Aq`）

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "{table}",
      "alias": "ds_y5EoxUyLf6Aq",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "ds_y5EoxUyLf6Aq.asin", "alias": "f_asin" },
      { "expr": "ds_y5EoxUyLf6Aq.refund_reason", "alias": "f_reason" },
      { "expr": "ds_y5EoxUyLf6Aq.refund_amount", "alias": "f_amount", "aggregation": "SUM" },
      { "expr": "COUNT(*)", "alias": "f_count" },
      { "expr": "ds_y5EoxUyLf6Aq.overseas_origin_suffix", "alias": "f_origin" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_y5EoxUyLf6Aq.asin", "operator": "eq", "value": "B08XXXXXX" },
        { "field": "ds_y5EoxUyLf6Aq.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_asin", "f_reason", "f_origin"],
    "limit": 1000
  }
}
```

### order_sale_trend_adv_traffic_inv_set（`ds_d35ac6f3910c`）— 退款率验证

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "{table}",
      "alias": "ds_d35ac6f3910c",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "ds_d35ac6f3910c.asin", "alias": "f_asin" },
      { "expr": "ds_d35ac6f3910c.refund_percent", "alias": "f_refund_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.gross_profit", "alias": "f_profit", "aggregation": "SUM" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.asin", "operator": "eq", "value": "B08XXXXXX" },
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_asin"],
    "limit": 1000
  }
}
```

### custom_operation_suggest_suggestions_set（`ds_zY0BAi0Txsga`）

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "{table}",
      "alias": "ds_zY0BAi0Txsga",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "ds_zY0BAi0Txsga.asin", "alias": "f_asin" },
      { "expr": "ds_zY0BAi0Txsga.issue_type", "alias": "f_issue_type" },
      { "expr": "ds_zY0BAi0Txsga.severity", "alias": "f_severity" },
      { "expr": "ds_zY0BAi0Txsga.suggestion", "alias": "f_suggestion" },
      { "expr": "ds_zY0BAi0Txsga.operation_stage", "alias": "f_stage" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_zY0BAi0Txsga.asin", "operator": "eq", "value": "B08XXXXXX" }
      ]
    },
    "limit": 1000
  }
}
```

### 查询构造命令示例

```bash
# 退款数据
opscli query build \
  --dataset ds_y5EoxUyLf6Aq \
  --dimension asin --dimension refund_reason \
  --metric refund_amount --metric order_status \
  --output payload_refund.json

# 整体退款率验证
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension asin \
  --metric refund_percent --metric gross_profit \
  --output payload_sales.json

# 运营建议
opscli query build \
  --dataset ds_zY0BAi0Txsga \
  --dimension asin --dimension issue_type \
  --metric severity --metric suggestion \
  --output payload_suggest.json
```

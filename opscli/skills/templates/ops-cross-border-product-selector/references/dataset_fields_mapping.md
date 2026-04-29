# 数据集字段映射与 Payload 模板

> **注意**：以下 payload 模板为简化示例，实际使用时请通过 `opscli query build` 命令自动生成完整 payload。
>
> ```bash
> opscli query build \
>   --dataset ds_pdTYjvLRCadv \
>   --dimension asin --dimension product_name \
>   --metric price --metric star --metric reviews_qty --metric subclass_rank \
>   --output payload.json
> ```

## 数据集映射表

| 数据集名称 | dataset_alias | inner_where_enabled | 权限字段 |
|-----------|--------------|-------------------|---------|
| `order_sale_trend_adv_traffic_inv_set` | `ds_d35ac6f3910c` | `false` | `{permission}` |
| `custom_crawler_listing_snapshot` | `ds_pdTYjvLRCadv` | `false` | `{permission}` |
| `custom_inventory_turnover_wk_set` | `ds_97zj6R0KDKpB` | `false` | `{permission}` |

## 品类扫描 - 内部数据（`ds_d35ac6f3910c`）

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
      { "expr": "ds_d35ac6f3910c.category", "alias": "f_category" },
      { "expr": "COUNT(DISTINCT ds_d35ac6f3910c.asin)", "alias": "f_asin_count" },
      { "expr": "ds_d35ac6f3910c.original_price", "alias": "f_total_sales", "aggregation": "SUM" },
      { "expr": "ds_d35ac6f3910c.gross_profit_percent", "alias": "f_avg_margin", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.refund_percent", "alias": "f_avg_refund", "aggregation": "AVG" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["{start_date}", "{end_date}"] }
      ]
    },
    "groupBy": ["f_category"],
    "orderBy": [{ "field": "f_total_sales", "direction": "DESC" }],
    "limit": 100
  }
}
```

## 品类扫描 - 爬虫数据（`ds_pdTYjvLRCadv`）

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "{table}",
      "alias": "ds_pdTYjvLRCadv",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "ds_pdTYjvLRCadv.category", "alias": "f_category" },
      { "expr": "COUNT(DISTINCT ds_pdTYjvLRCadv.asin)", "alias": "f_competitor_count" },
      { "expr": "ds_pdTYjvLRCadv.star", "alias": "f_avg_rating", "aggregation": "AVG" },
      { "expr": "ds_pdTYjvLRCadv.reviews_qty", "alias": "f_avg_reviews", "aggregation": "AVG" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_pdTYjvLRCadv.date_id", "operator": "between", "value": ["{start_date}", "{end_date}"] }
      ]
    },
    "groupBy": ["f_category"],
    "limit": 100
  }
}
```

## BSR 健康度筛选（`ds_pdTYjvLRCadv`）

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "{table}",
      "alias": "ds_pdTYjvLRCadv",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "ds_pdTYjvLRCadv.asin", "alias": "f_asin" },
      { "expr": "ds_pdTYjvLRCadv.product_name", "alias": "f_product_name" },
      { "expr": "ds_pdTYjvLRCadv.price", "alias": "f_price" },
      { "expr": "ds_pdTYjvLRCadv.star", "alias": "f_star" },
      { "expr": "ds_pdTYjvLRCadv.reviews_qty", "alias": "f_reviews" },
      { "expr": "ds_pdTYjvLRCadv.subclass_rank", "alias": "f_rank" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_pdTYjvLRCadv.subclass_rank", "operator": "between", "value": [100, 5000] },
        { "field": "ds_pdTYjvLRCadv.reviews_qty", "operator": "between", "value": [300, 1000] },
        { "field": "ds_pdTYjvLRCadv.star", "operator": "between", "value": [3.5, 4.3] },
        { "field": "ds_pdTYjvLRCadv.price", "operator": "between", "value": [15, 50] }
      ]
    },
    "limit": 1000
  }
}
```

## 库存周转查询（`ds_97zj6R0KDKpB`）

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "{table}",
      "alias": "ds_97zj6R0KDKpB",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "ds_97zj6R0KDKpB.asin", "alias": "f_asin" },
      { "expr": "ds_97zj6R0KDKpB.ed_sku", "alias": "f_sku" },
      { "expr": "ds_97zj6R0KDKpB.inventory_qty", "alias": "f_inventory", "aggregation": "SUM" },
      { "expr": "ds_97zj6R0KDKpB.turnover_days", "alias": "f_turnover", "aggregation": "AVG" },
      { "expr": "ds_97zj6R0KDKpB.sell_qty_days", "alias": "f_daily_sales", "aggregation": "AVG" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_97zj6R0KDKpB.date_id", "operator": "between", "value": ["{start_date}", "{end_date}"] }
      ]
    },
    "groupBy": ["f_asin", "f_sku"],
    "limit": 10000
  }
}
```

## 数据集类型判断

本 Skill 涉及的所有数据集（`ds_d35ac6f3910c`、`ds_pdTYjvLRCadv`、`ds_97zj6R0KDKpB`）均为**非子查询类型**（`inner_where_enabled=false`），所有过滤条件直接放在 `where` 中。

## 字段别名规范

- 维度/指标字段别名格式：`f_[随机哈希]`，如 `f_754ed2fb474f09f9`
- dataComparison 裂变字段：`last_f_xxx`, `diff_f_xxx`, `pct_f_xxx`
- **禁止在业务逻辑中硬编码 alias**，应通过字段映射关系识别

## 公式指标查询规范

公式指标必须使用完整表达式格式：

```json
// 正确
{
  "expr": "ROUND(SUM(dsp)/SUM(price), 4)",
  "alias": "f_yZZfW7cNu8nYMGCS"
}

// 错误：额外传 aggregation 会导致二次聚合
{
  "expr": "sell_qty_days",
  "alias": "f_xxx",
  "aggregation": "SUM"
}
```

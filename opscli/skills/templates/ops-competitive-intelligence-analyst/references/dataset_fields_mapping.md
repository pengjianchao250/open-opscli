# 数据集字段映射与 Payload 模板

> **注意**：以下 payload 模板为简化示例，实际使用时请通过 `opscli query build` 命令自动生成完整 payload。
>
> ```bash
> opscli query build \
>   --dataset ds_d35ac6f3910c \
>   --dimension category --dimension asin \
>   --metric original_price --metric order_qty --metric gross_profit_percent \
>   --output payload.json
> ```

## 数据集映射表

| 数据集名称 | dataset_alias | inner_where_enabled | 权限字段 |
|-----------|--------------|-------------------|---------|
| `order_sale_trend_adv_traffic_inv_set` | `ds_d35ac6f3910c` | `false` | `{permission}` |
| `custom_crawler_listing_snapshot` | `ds_pdTYjvLRCadv` | `false` | `{permission}` |
| `custom_brand_search_query_set` | `ds_xsTOkHIpr3ad` | `false` | `{permission}` |
| `custom_brand_search_catalog_set` | `ds_I13gHlcdwevS` | `false` | `{permission}` |

## 品类销售集中度查询（`ds_d35ac6f3910c`）

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
      { "expr": "ds_d35ac6f3910c.asin", "alias": "f_asin" },
      { "expr": "ds_d35ac6f3910c.original_price", "alias": "f_sales", "aggregation": "SUM" },
      { "expr": "ds_d35ac6f3910c.order_qty", "alias": "f_qty", "aggregation": "SUM" },
      { "expr": "ds_d35ac6f3910c.gross_profit_percent", "alias": "f_margin", "aggregation": "AVG" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.category", "operator": "eq", "value": "{category}" },
        { "field": "ds_d35ac6f3910c.country_name", "operator": "eq", "value": "{country}" },
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["{start_date}", "{end_date}"] }
      ]
    },
    "groupBy": ["f_category", "f_asin"],
    "limit": 10000
  }
}
```

## 竞品 Listing 查询（`ds_pdTYjvLRCadv`）

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
      { "expr": "ds_pdTYjvLRCadv.subclass_rank", "alias": "f_rank" },
      { "expr": "ds_pdTYjvLRCadv.category", "alias": "f_category" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_pdTYjvLRCadv.category", "operator": "eq", "value": "{category}" },
        { "field": "ds_pdTYjvLRCadv.date_id", "operator": "between", "value": ["{start_date}", "{end_date}"] }
      ]
    },
    "limit": 10000
  }
}
```

## 品牌搜索查询（`ds_xsTOkHIpr3ad`）

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "{table}",
      "alias": "ds_xsTOkHIpr3ad",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "ds_xsTOkHIpr3ad.search_term", "alias": "f_term" },
      { "expr": "ds_xsTOkHIpr3ad.search_volume", "alias": "f_volume", "aggregation": "SUM" },
      { "expr": "ds_xsTOkHIpr3ad.brand_share", "alias": "f_brand_share", "aggregation": "AVG" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_xsTOkHIpr3ad.date_id", "operator": "between", "value": ["{start_date}", "{end_date}"] }
      ]
    },
    "groupBy": ["f_term"],
    "limit": 1000
  }
}
```

## 品牌搜索目录查询（`ds_I13gHlcdwevS`）

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "{table}",
      "alias": "ds_I13gHlcdwevS",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "ds_I13gHlcdwevS.category", "alias": "f_category" },
      { "expr": "ds_I13gHlcdwevS.brand_name", "alias": "f_brand" },
      { "expr": "ds_I13gHlcdwevS.search_volume", "alias": "f_volume", "aggregation": "SUM" },
      { "expr": "ds_I13gHlcdwevS.share_percent", "alias": "f_share", "aggregation": "AVG" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_I13gHlcdwevS.category", "operator": "eq", "value": "{category}" },
        { "field": "ds_I13gHlcdwevS.date_id", "operator": "between", "value": ["{start_date}", "{end_date}"] }
      ]
    },
    "groupBy": ["f_category", "f_brand"],
    "limit": 1000
  }
}
```

## 数据集类型判断

本 Skill 涉及的所有数据集（`ds_d35ac6f3910c`、`ds_pdTYjvLRCadv`、`ds_xsTOkHIpr3ad`、`ds_I13gHlcdwevS`）均为**非子查询类型**（`inner_where_enabled=false`），所有过滤条件直接放在 `where` 中。

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
  "expr": "gross_profit_percent",
  "alias": "f_xxx",
  "aggregation": "AVG"
}
```

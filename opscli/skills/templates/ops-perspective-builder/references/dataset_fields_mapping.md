# 数据集字段映射与 Payload 模板

> **注意**：以下 payload 模板为简化示例，实际使用时请通过 `opscli query build` 命令自动生成完整 payload。
>
> ```bash
> opscli query build \
>   --dataset ds_d35ac6f3910c \
>   --dimension date_id --dimension dept_name \
>   --metric original_price --metric orders \
>   --output payload.json
> ```

## 数据集映射表

| 数据集名称 | dataset_alias | inner_where_enabled | 权限字段 |
|-----------|--------------|-------------------|---------|
| `order_sale_trend_adv_traffic_inv_set` | `ds_d35ac6f3910c` | `false` | `{permission}` |
| `custom_inventory_turnover_wk_set` | `ds_97zj6R0KDKpB` | `false` | `{permission}` |
| `custom_crawler_listing_snapshot` | `ds_pdTYjvLRCadv` | `false` | `{permission}` |
| `advertising_list_set` | `ds_0759e20F0DrG` | `true` | `{permission}` |
| `custom_asin_sales_traffic_set` | `ds_x40rpZlLlo0j` | `true` | `{permission}` |
| `custom_refund_place_set` | `ds_y5EoxUyLf6Aq` | `false` | `{permission}` |
| `custom_brand_search_query_set` | `ds_xsTOkHIpr3ad` | `false` | `{permission}` |
| `custom_brand_search_catalog_set` | `ds_I13gHlcdwevS` | `false` | `{permission}` |

## 通用 Payload 模板（非子查询类型）

适用于 `ds_d35ac6f3910c`、`ds_97zj6R0KDKpB`、`ds_pdTYjvLRCadv`、`ds_xsTOkHIpr3ad`、`ds_I13gHlcdwevS`、`ds_y5EoxUyLf6Aq` 等非子查询数据集。

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "{table}",
      "alias": "{dataset_alias}",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "{dataset_alias}.{dimension_1}", "alias": "f_{hash_1}" },
      { "expr": "{dataset_alias}.{dimension_2}", "alias": "f_{hash_2}" },
      { "expr": "{dataset_alias}.{metric_1}", "alias": "f_{hash_3}", "aggregation": "SUM" },
      { "expr": "{dataset_alias}.{metric_2}", "alias": "f_{hash_4}", "aggregation": "SUM" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "{dataset_alias}.date_id", "operator": "between", "value": ["{start_date}", "{end_date}"] },
        { "field": "{dataset_alias}.{filter_field}", "operator": "eq", "value": "{filter_value}" }
      ]
    },
    "groupBy": ["f_{hash_1}", "f_{hash_2}"],
    "orderBy": [{ "field": "f_{hash_3}", "direction": "DESC" }],
    "limit": 10000
  }
}
```

## 子查询类型 Payload 模板

适用于 `ds_0759e20F0DrG`、`ds_x40rpZlLlo0j` 等子查询类型数据集。

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "{table}",
      "alias": "{dataset_alias}",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "{dataset_alias}.{dimension_1}", "alias": "f_{hash_1}" },
      { "expr": "{dataset_alias}.{metric_1}", "alias": "f_{hash_2}", "aggregation": "SUM" }
    ],
    "innerWhere": [
      { "operator": "AND", "conditions": [] },
      { "operator": "AND", "conditions": [] }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "{dataset_alias}.date_id", "operator": "between", "value": ["{start_date}", "{end_date}"] }
      ]
    },
    "groupBy": ["f_{hash_1}"],
    "limit": 10000
  }
}
```

## 按透视图类型的 Payload 示例

### 1. 销售趋势多维透视（`ds_d35ac6f3910c`）

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
      { "expr": "DATE_TRUNC('week', ds_d35ac6f3910c.date_id)", "alias": "f_week" },
      { "expr": "ds_d35ac6f3910c.dept_name", "alias": "f_dept" },
      { "expr": "ds_d35ac6f3910c.large_team_name", "alias": "f_large_team" },
      { "expr": "ds_d35ac6f3910c.platform_name", "alias": "f_platform" },
      { "expr": "ds_d35ac6f3910c.country_name", "alias": "f_country" },
      { "expr": "ds_d35ac6f3910c.original_price", "alias": "f_sales", "aggregation": "SUM" },
      { "expr": "ds_d35ac6f3910c.orders", "alias": "f_orders", "aggregation": "SUM" },
      { "expr": "ds_d35ac6f3910c.order_qty", "alias": "f_qty", "aggregation": "SUM" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["{start_date}", "{end_date}"] },
        { "field": "ds_d35ac6f3910c.level_name", "operator": "in", "value": ["A", "B"] }
      ]
    },
    "groupBy": ["f_week", "f_dept", "f_large_team", "f_platform", "f_country"],
    "limit": 10000
  }
}
```

### 2. 库存周转健康度（`ds_97zj6R0KDKpB`）

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
      { "expr": "DATE_TRUNC('week', ds_97zj6R0KDKpB.date_id)", "alias": "f_week" },
      { "expr": "ds_97zj6R0KDKpB.dept_name", "alias": "f_dept" },
      { "expr": "ds_97zj6R0KDKpB.team_name", "alias": "f_team" },
      { "expr": "ds_97zj6R0KDKpB.platform_name", "alias": "f_platform" },
      { "expr": "ds_97zj6R0KDKpB.warehouse_name", "alias": "f_warehouse" },
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
    "groupBy": ["f_week", "f_dept", "f_team", "f_platform", "f_warehouse"],
    "limit": 10000
  }
}
```

### 3. ASIN 健康度（`ds_pdTYjvLRCadv`）

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
      { "expr": "ds_pdTYjvLRCadv.product_name", "alias": "f_product" },
      { "expr": "ds_pdTYjvLRCadv.price", "alias": "f_price" },
      { "expr": "ds_pdTYjvLRCadv.star", "alias": "f_star" },
      { "expr": "ds_pdTYjvLRCadv.reviews_qty", "alias": "f_reviews" },
      { "expr": "ds_pdTYjvLRCadv.subclass_rank", "alias": "f_rank" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_pdTYjvLRCadv.date_id", "operator": "between", "value": ["{start_date}", "{end_date}"] },
        { "field": "ds_pdTYjvLRCadv.category", "operator": "eq", "value": "{category}" }
      ]
    },
    "limit": 10000
  }
}
```

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

## `translate` 枚举映射

跨表关联查询时，可能需要使用 translate 翻译枚举：

| 过滤字段 | translate 枚举值 | 含义 |
|---------|-----------------|------|
| `platform_name` | `PLATFORM_TO_SKU` | 平台 → 公司 SKU |
| `country_name` | `COUNTRY_TO_SKU` | 国家 → 公司 SKU |
| `channel_name` | `CHANNEL_TO_SKU` | 渠道 → 公司 SKU |
| `team_name` | `TEAM_TO_SKU` | 销售小组 → 公司 SKU |
| `ed_sku` | `SKU_TO_ASIN` | 公司 SKU → ASIN |
| `asin` | `ASIN_TO_SKU` | ASIN → 公司 SKU |

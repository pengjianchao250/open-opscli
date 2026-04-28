# ASIN Health Diagnoser — 数据集字段映射

## 主数据集：order_sale_trend_adv_traffic_inv_set (ds_d35ac6f3910c)

| 指标 | 字段名 | 数据类型 | 聚合方式 | 说明 |
|------|--------|---------|---------|------|
| ASIN | `asin` | STRING | GROUP BY | 亚马逊标准识别号 |
| 产品名称 | `product_name` | STRING | GROUP BY | 产品标题 |
| 毛利率 | `gross_profit_percent` | DECIMAL | AVG / 公式 | 毛利 / 销售额 |
| 转化率 | `convert_percent` | DECIMAL | AVG | 订单数 / 访问量 |
| ACOS | `ads_acos` | DECIMAL | AVG / 公式 | 广告费 / 广告销售额 |
| 退款率 | `refund_percent` | DECIMAL | AVG | 退款金额 / 销售额 |
| 周转天数 | `sell_qty_days` | DECIMAL | AVG | 可售库存 / 日均销量 |

## 辅助数据集：custom_crawler_listing_snapshot (ds_pdTYjvLRCadv)

| 指标 | 字段名 | 数据类型 | 聚合方式 | 说明 |
|------|--------|---------|---------|------|
| ASIN | `asin` | STRING | GROUP BY | 亚马逊标准识别号 |
| 星级 | `star` / `rating` | DECIMAL | AVG | 产品评分（1-5） |
| 评论数 | `reviews_qty` | INT | SUM | 评论总数 |
| 排名 | `subclass_rank` | INT | MIN | 类目排名 |

## 数据查询 Payload 模板

> ⚠️ **构造查询时使用 `opscli query build` 命令自动生成完整 payload**，不要手写 `userEmail`、`from.table`、`from.permission` 等字段，这些由 opscli 自动填充。

### 主数据集查询（ds_d35ac6f3910c，非子查询类型）

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
      { "expr": "ds_d35ac6f3910c.product_name", "alias": "f_product_name" },
      { "expr": "ds_d35ac6f3910c.gross_profit_percent", "alias": "f_gross_profit", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.convert_percent", "alias": "f_convert", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.ads_acos", "alias": "f_acos", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.refund_percent", "alias": "f_refund", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.sell_qty_days", "alias": "f_inventory_days", "aggregation": "AVG" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.asin", "operator": "eq", "value": "B08XXXXXX" },
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_asin", "f_product_name"],
    "limit": 1000
  }
}
```

### 辅助数据集查询（ds_pdTYjvLRCadv，非子查询类型）

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
      { "expr": "ds_pdTYjvLRCadv.star", "alias": "f_star", "aggregation": "AVG" },
      { "expr": "ds_pdTYjvLRCadv.reviews_qty", "alias": "f_reviews", "aggregation": "SUM" },
      { "expr": "ds_pdTYjvLRCadv.subclass_rank", "alias": "f_rank", "aggregation": "MIN" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_pdTYjvLRCadv.asin", "operator": "eq", "value": "B08XXXXXX" }
      ]
    },
    "groupBy": ["f_asin"],
    "limit": 1000
  }
}
```

### 批量 ASIN 查询（ds_d35ac6f3910c）

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
      { "expr": "ds_d35ac6f3910c.product_name", "alias": "f_product_name" },
      { "expr": "AVG(ds_d35ac6f3910c.gross_profit_percent)", "alias": "f_gross_profit" },
      { "expr": "AVG(ds_d35ac6f3910c.convert_percent)", "alias": "f_convert" },
      { "expr": "AVG(ds_d35ac6f3910c.ads_acos)", "alias": "f_acos" },
      { "expr": "AVG(ds_d35ac6f3910c.refund_percent)", "alias": "f_refund" },
      { "expr": "AVG(ds_d35ac6f3910c.sell_qty_days)", "alias": "f_inventory_days" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.asin", "operator": "in", "value": ["B08XXXXXX", "B09YYYYYY", "B07ZZZZZZ"] },
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_asin", "f_product_name"],
    "orderBy": [{ "expr": "f_gross_profit", "desc": true }],
    "limit": 1000
  }
}
```

## 注意事项

1. **数据集类型**：`ds_d35ac6f3910c` 和 `ds_pdTYjvLRCadv` 均为**非子查询类型**（`inner_where_enabled=false`），所有过滤条件直接放在 `where` 中。
2. **公式指标**：`gross_profit_percent`、`ads_acos` 等为公式指标，聚合时直接使用 `AVG()` 或走完整表达式。
3. **权限字段**：`ds_d35ac6f3910c` 使用 `channel_uuid, listing_uuid`；`ds_pdTYjvLRCadv` 使用 `asin_ps_uuid`。
4. **字段别名**：返回结果中字段别名为 `f_[随机哈希]`，业务逻辑中应通过映射关系识别，禁止硬编码。
5. **自动生成字段**：`userEmail`、`from.table`、`from.permission`、`from.database` 等字段由 `opscli query build` 命令根据当前登录用户和数据集 metadata 自动生成，**禁止在 Skill 文档或脚本中手写这些字段**。

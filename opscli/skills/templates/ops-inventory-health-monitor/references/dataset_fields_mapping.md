# 库存健康监控数据集字段映射

## 主数据集：custom_inventory_turnover_wk_set (ds_97zj6R0KDKpB)

| 指标 | 字段名 | 数据类型 | 聚合方式 | 说明 |
|------|--------|---------|---------|------|
| 公司SKU | `ed_sku` | STRING | GROUP BY | 跨数据集关联键 |
| 产品名称 | `product_name` | STRING | GROUP BY | 产品标题 |
| 可售周转天数 | `sell_qty_days` | DECIMAL | AVG | 可售库存 / 日均销量 |
| 可售+在途天数 | `sell_intransit_qty_days` | DECIMAL | AVG | (可售+在途) / 日均销量 |
| 平台仓库存 | `platform_qty` | INT | SUM | 平台仓（FBA等）库存数量 |
| 海外仓库存 | `transfer_qty` | INT | SUM | 海外仓总库存 |
| 海外仓可售 | `transfer_available_qty` | INT | SUM | 海外仓可用库存 |
| 海外仓锁定 | `transfer_lock_qty` | INT | SUM | 海外仓锁定库存 |
| 在途库存 | `intransit_qty` | INT | SUM | 运输途中库存 |
| 日均销量 | `average_daily_sales_volume` | DECIMAL | AVG | 平均日销量 |
| 日期 | `date_id` | DATE | FILTER | 数据日期 |

## 辅助数据集：order_sale_trend_adv_traffic_inv_set (ds_d35ac6f3910c)

| 指标 | 字段名 | 数据类型 | 聚合方式 | 说明 |
|------|--------|---------|---------|------|
| 公司SKU | `ed_sku` | STRING | GROUP BY | 跨数据集关联键 |
| 总库存 | `total_qty` | INT | SUM | 全渠道总库存 |
| FBA库存 | `fba_qty` | INT | SUM | FBA仓库库存 |
| 日期 | `date_id` | DATE | FILTER | 数据日期 |

## 数据查询 Payload 模板

> ⚠️ **构造查询时使用 `opscli query build` 命令自动生成完整 payload**，不要手写 `userEmail`、`from.table`、`from.permission` 等字段，这些由 opscli 自动填充。

### 库存周转数据查询（ds_97zj6R0KDKpB，非子查询类型）

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
      { "expr": "ds_97zj6R0KDKpB.ed_sku", "alias": "f_ed_sku" },
      { "expr": "ds_97zj6R0KDKpB.product_name", "alias": "f_product_name" },
      { "expr": "ds_97zj6R0KDKpB.sell_qty_days", "alias": "f_sell_days" },
      { "expr": "ds_97zj6R0KDKpB.sell_intransit_qty_days", "alias": "f_intransit_days" },
      { "expr": "ds_97zj6R0KDKpB.platform_qty", "alias": "f_platform_qty" },
      { "expr": "ds_97zj6R0KDKpB.transfer_qty", "alias": "f_transfer_qty" },
      { "expr": "ds_97zj6R0KDKpB.transfer_available_qty", "alias": "f_transfer_avail" },
      { "expr": "ds_97zj6R0KDKpB.transfer_lock_qty", "alias": "f_transfer_lock" },
      { "expr": "ds_97zj6R0KDKpB.intransit_qty", "alias": "f_intransit" },
      { "expr": "ds_97zj6R0KDKpB.average_daily_sales_volume", "alias": "f_avg_daily_sales" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_97zj6R0KDKpB.ed_sku", "operator": "eq", "value": "ED-12345" },
        { "field": "ds_97zj6R0KDKpB.date_id", "operator": "eq", "value": "2025-01-31" }
      ]
    },
    "limit": 1000
  }
}
```

### 断货风险预警查询（ds_97zj6R0KDKpB，非子查询类型）

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
      { "expr": "ds_97zj6R0KDKpB.ed_sku", "alias": "f_ed_sku" },
      { "expr": "ds_97zj6R0KDKpB.product_name", "alias": "f_product_name" },
      { "expr": "ds_97zj6R0KDKpB.platform_qty", "alias": "f_platform_qty" },
      { "expr": "ds_97zj6R0KDKpB.average_daily_sales_volume", "alias": "f_avg_daily_sales" },
      { "expr": "ds_97zj6R0KDKpB.platform_qty / NULLIF(ds_97zj6R0KDKpB.average_daily_sales_volume, 0)", "alias": "f_stock_days" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_97zj6R0KDKpB.date_id", "operator": "eq", "value": "2025-01-31" },
        { "field": "ds_97zj6R0KDKpB.platform_qty / NULLIF(ds_97zj6R0KDKpB.average_daily_sales_volume, 0)", "operator": "lt", "value": 14 }
      ]
    },
    "orderBy": [{ "field": "f_stock_days", "direction": "ASC" }],
    "limit": 1000
  }
}
```

### 辅助库存数据查询（ds_d35ac6f3910c，非子查询类型）

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
      { "expr": "ds_d35ac6f3910c.ed_sku", "alias": "f_ed_sku" },
      { "expr": "SUM(ds_d35ac6f3910c.total_qty)", "alias": "f_total_qty" },
      { "expr": "SUM(ds_d35ac6f3910c.fba_qty)", "alias": "f_fba_qty" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.ed_sku", "operator": "eq", "value": "ED-12345" },
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2025-01-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_ed_sku"],
    "limit": 1000
  }
}
```

## 注意事项

1. **数据集类型**：`ds_97zj6R0KDKpB` 和 `ds_d35ac6f3910c` 均为**非子查询类型**（`inner_where_enabled=false`），所有过滤条件直接放在 `where` 中。
2. **字段别名**：返回结果中字段别名为 `f_[随机哈希]`，业务逻辑中应通过映射关系识别，禁止硬编码。
3. **自动生成字段**：`userEmail`、`from.table`、`from.permission`、`from.database` 等字段由 `opscli query build` 命令根据当前登录用户和数据集 metadata 自动生成，**禁止在 Skill 文档或脚本中手写这些字段**。
4. **公式指标**：`sell_qty_days` 等字段为公式指标，聚合时直接使用 `AVG()` 或走完整表达式，禁止额外传 `aggregation` 导致二次聚合。
5. **断货预警**：建议每日定时查询 `platform_qty / average_daily_sales_volume < 14` 的 SKU，提前触发补货流程。

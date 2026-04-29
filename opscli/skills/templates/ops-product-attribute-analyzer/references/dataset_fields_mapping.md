# 产品属性分析器数据集字段映射

## 产品属性源数据集：query_product_set (ds_8f24440d149b)

| 指标 | 字段名 | 数据类型 | 聚合方式 | 说明 |
|------|--------|---------|---------|------|
| 公司SKU | `ed_sku` | STRING | GROUP BY | 跨数据集关联键 |
| 开发类型 | `development_type` | CHAR | GROUP BY | 自主研发/OEM贴牌/外采成品 |
| SKU等级 | `sku_type` | CHAR | GROUP BY | A级/B级/C级 |
| 风格 | `style_name` | CHAR | GROUP BY | 风格化名称 |
| 保护等级 | `protection_level` | CHAR | GROUP BY | 高/中/低 |
| 一级品类 | `category` | STRING | GROUP BY | 一级品类 |
| 二级品类 | `sec_category` | STRING | GROUP BY | 二级品类 |
| 产品型号 | `model` | STRING | GROUP BY | 产品型号 |
| 产品等级 | `level_name` | STRING | GROUP BY | 普通/精品/旗舰 |
| 平台 | `platform_name` | STRING | GROUP BY | Amazon/Walmart |
| 国家 | `country_name` | STRING | GROUP BY | 美国/英国/德国 |
| 渠道 | `channel_name` | STRING | GROUP BY | FBA/FBM |

## 销量数据源数据集：order_sale_trend_adv_traffic_inv_set (ds_d35ac6f3910c)

| 指标 | 字段名 | 数据类型 | 聚合方式 | 说明 |
|------|--------|---------|---------|------|
| ASIN | `asin` | STRING | GROUP BY | 亚马逊标准识别号 |
| 公司SKU | `ed_sku` | STRING | GROUP BY | 跨数据集关联键 |
| 销量 | `order_qty` | INT | SUM | 订单数量 |
| 销售额 | `original_price` | DECIMAL | SUM | 销售额（原价） |
| 日期 | `date_id` | DATE | FILTER | 数据日期 |

## 数据查询 Payload 模板

> ⚠️ **构造查询时使用 `opscli query build` 命令自动生成完整 payload**，不要手写 `userEmail`、`from.table`、`from.permission` 等字段，这些由 opscli 自动填充。

### 产品属性查询（ds_8f24440d149b，非子查询类型，查询组件）

```json
{
  "dataSource": "doris_analytics",
  "query": {
    "from": {
      "table": "{table}",
      "alias": "ds_8f24440d149b",
      "database": "",
      "permission": "{permission}"
    },
    "select": [
      { "expr": "ds_8f24440d149b.ed_sku", "alias": "f_ed_sku" },
      { "expr": "ds_8f24440d149b.development_type", "alias": "f_dev_type" },
      { "expr": "ds_8f24440d149b.sku_type", "alias": "f_sku_type" },
      { "expr": "ds_8f24440d149b.style_name", "alias": "f_style" },
      { "expr": "ds_8f24440d149b.category", "alias": "f_category" },
      { "expr": "ds_8f24440d149b.sec_category", "alias": "f_sec_category" },
      { "expr": "ds_8f24440d149b.level_name", "alias": "f_level_name" },
      { "expr": "ds_8f24440d149b.country_name", "alias": "f_country" },
      { "expr": "ds_8f24440d149b.channel_name", "alias": "f_channel" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_8f24440d149b.category", "operator": "eq", "value": "Kitchen Gadgets" }
      ]
    },
    "limit": 10000
  }
}
```

### 销量数据查询（ds_d35ac6f3910c，非子查询类型）

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
      { "expr": "ds_d35ac6f3910c.asin", "alias": "f_asin" },
      { "expr": "SUM(ds_d35ac6f3910c.order_qty)", "alias": "f_order_qty" },
      { "expr": "SUM(ds_d35ac6f3910c.original_price)", "alias": "f_revenue" },
      { "expr": "COUNT(DISTINCT ds_d35ac6f3910c.asin)", "alias": "f_asin_count" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2024-11-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_ed_sku"],
    "limit": 10000
  }
}
```

### 属性组合销量分析（ds_d35ac6f3910c，非子查询类型）

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
      { "expr": "ds_d35ac6f3910c.development_type", "alias": "f_dev_type" },
      { "expr": "ds_d35ac6f3910c.sku_type", "alias": "f_sku_type" },
      { "expr": "SUM(ds_d35ac6f3910c.order_qty)", "alias": "f_total_sales" },
      { "expr": "COUNT(DISTINCT ds_d35ac6f3910c.asin)", "alias": "f_asin_count" },
      { "expr": "SUM(ds_d35ac6f3910c.original_price)", "alias": "f_revenue" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.category", "operator": "eq", "value": "Kitchen Gadgets" },
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2024-11-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_dev_type", "f_sku_type"],
    "limit": 1000
  }
}
```

## 注意事项

1. **数据集类型**：`ds_8f24440d149b` 和 `ds_d35ac6f3910c` 均为**非子查询类型**（`inner_where_enabled=false`），所有过滤条件直接放在 `where` 中。
2. **关联方式**：两个数据集通过 `ed_sku` 字段关联。建议先分别查询，再在脚本中做内存关联，避免复杂 JOIN 影响性能。
3. **字段别名**：返回结果中字段别名为 `f_[随机哈希]`，业务逻辑中应通过映射关系识别，禁止硬编码。
4. **自动生成字段**：`userEmail`、`from.table`、`from.permission`、`from.database` 等字段由 `opscli query build` 命令根据当前登录用户和数据集 metadata 自动生成，**禁止在 Skill 文档或脚本中手写这些字段**。
5. **公式指标**：`gross_profit_percent`、`ads_acos` 等为公式指标，聚合时直接使用 `AVG()` 或走完整表达式，禁止额外传 `aggregation` 导致二次聚合。

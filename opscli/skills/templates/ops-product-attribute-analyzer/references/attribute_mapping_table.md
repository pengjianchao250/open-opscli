# 属性→数据集字段映射表

## 主数据源：query_product_set (ds_8f24440d149b)

| 分析维度 | 字段名 | 数据类型 | 备注 |
|---------|--------|---------|------|
| 开发类型 | development_type | CHAR | 自主研发/OEM贴牌/外采成品 |
| SKU等级 | sku_type | CHAR | A级/B级/C级 |
| 风格 | style_name | CHAR | 风格化名称 |
| 保护等级 | protection_level | CHAR | 高/中/低 |
| 品类 | category | STRING | 一级品类 |
| 二级品类 | sec_category | STRING | 二级品类 |
| 型号 | model | STRING | 产品型号 |
| 产品等级 | level_name | STRING | 普通/精品/旗舰 |

## 销量数据源：order_sale_trend_adv_traffic_inv_set (ds_d35ac6f3910c)

| 指标 | 字段名 | 聚合方式 |
|------|--------|---------|
| 销量 | order_qty | SUM |
| 销售额 | original_price | SUM |
| ASIN 数量 | asin | COUNT DISTINCT |

## 关联方式

通过 `ed_sku` 字段跨数据集关联查询。先分别查询两个数据集，再在脚本中关联：

### 产品属性查询（ds_8f24440d149b）

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
      { "expr": "ds_8f24440d149b.sec_category", "alias": "f_sec_category" }
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

### 销量数据查询（ds_d35ac6f3910c）

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
      { "expr": "SUM(ds_d35ac6f3910c.order_qty)", "alias": "f_order_qty" },
      { "expr": "SUM(ds_d35ac6f3910c.original_price)", "alias": "f_revenue" },
      { "expr": "COUNT(DISTINCT ds_d35ac6f3910c.asin)", "alias": "f_asin_count" }
    ],
    "where": {
      "operator": "AND",
      "conditions": [
        { "field": "ds_d35ac6f3910c.category", "operator": "eq", "value": "Kitchen Gadgets" },
        { "field": "ds_d35ac6f3910c.date_id", "operator": "between", "value": ["2024-11-01", "2025-01-31"] }
      ]
    },
    "groupBy": ["f_ed_sku"],
    "limit": 10000
  }
}
```

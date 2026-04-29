# 成本项说明与占比基准

## 成本项明细

| 字段名 | 中文名 | 计算方式 | 可优化性 | 优化难度 |
|--------|--------|---------|---------|---------|
| purchase_cost_percent | 采购成本占比 | purchase_cost / original_price | 高 | 中 |
| first_leg_percent | 头程运费占比 | first_leg / original_price | 高 | 低 |
| freight_percent | 运费占比 | freight / original_price | 中 | 低 |
| storage_charges_percent | 仓租占比 | storage_charges / original_price | 高 | 低 |
| advertising_fee_percent | 广告费占比 | advertising_fee / original_price | 高 | 中 |
| fee_percent | 平台手续费占比 | fee / original_price | 无 | — |
| tax_fee_percent | 税金占比 | tax_fee / original_price | 无 | — |
| fixed_cost_percent | 固定成本占比 | fixed_cost / original_price | 无 | — |
| refund_percent | 退款占比 | refund / original_price | 高 | 高 |
| compensate_percent | 物料赔偿占比 | compensate / original_price | 高 | 高 |

## 内部基准值（全公司均值，需定期更新）

| 成本项 | 健康线 | 团队均值 | Top 10% 最优 |
|--------|--------|---------|-------------|
| 采购成本占比 | 25% | 27% | 22% |
| 头程运费占比 | 6.5% | 7.5% | 5.0% |
| 广告费占比 | 18% | 22% | 15% |
| 仓租占比 | 4% | 6% | 2% |
| 退款占比 | 3.5% | 6% | 2% |

## 数据集字段映射

> **注意**：构造查询时请使用 `opscli query build` 命令自动生成完整 payload，以下模板仅展示字段映射关系。

### order_sale_trend_adv_traffic_inv_set（`ds_d35ac6f3910c`）

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
      { "expr": "ds_d35ac6f3910c.original_price", "alias": "f_sales", "aggregation": "SUM" },
      { "expr": "ds_d35ac6f3910c.purchase_cost_percent", "alias": "f_purchase_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.first_leg_percent", "alias": "f_first_leg_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.freight_percent", "alias": "f_freight_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.storage_charges_percent", "alias": "f_storage_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.advertising_fee_percent", "alias": "f_ad_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.fee_percent", "alias": "f_fee_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.tax_fee_percent", "alias": "f_tax_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.fixed_cost_percent", "alias": "f_fixed_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.refund_percent", "alias": "f_refund_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.compensate_percent", "alias": "f_compensate_pct", "aggregation": "AVG" },
      { "expr": "ds_d35ac6f3910c.gross_profit_percent", "alias": "f_gross_profit", "aggregation": "AVG" }
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

### 查询构造命令示例

```bash
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension asin --dimension product_name \
  --metric original_price --metric purchase_cost_percent --metric first_leg_percent \
  --metric advertising_fee_percent --metric fee_percent --metric tax_fee_percent \
  --metric fixed_cost_percent --metric refund_percent --metric gross_profit_percent \
  --output payload.json
```

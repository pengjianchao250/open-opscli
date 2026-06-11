# Keepa 格式化实现状态

本目录中的 `*_FORMATTING.md` 是 Keepa 对象格式化方案文档。实现状态如下：

| 文档 | 对象 | 状态 | 实现位置 | 默认导出行为 |
| --- | --- | --- | --- | --- |
| `PRODUCT_OBJECT_FORMATTING.md` | Product Object | 已接入 | `opscli/keepa/product_formatter.py` | `product` 场景 XLSX 默认派生金额、时间、图片、类目、变体摘要、stats 当前值，并按需追加 `csv_history`、`offers`、`variations` sheet。 |
| `SEARCH_INSIGHTS_OBJECT_FORMATTING.md` | Search Insights Object | 已接入 | `opscli/keepa/search_insights_formatter.py` | `product-finder` 携带 `stats=1` 且返回 `searchInsights` 时，XLSX 默认追加 `search_insights`、`search_insight_brands`、`search_insight_sellers`、`search_insight_categories` sheet。 |
| `STATISTICS_OBJECT_FORMATTING.md` | Statistics Object | 已接入 | `opscli/keepa/stats_formatter.py` | `product` 场景返回 `stats` 时，XLSX 默认派生 stats 主表字段，并按需追加 `stats_price_types`、`stats_extremes`、`stats_buy_box_sellers`、`stats_offer_snapshot` sheet。 |
| `BEST_SELLERS_OBJECT_FORMATTING.md` | Best Sellers Object | 已接入 | `opscli/keepa/best_sellers_formatter.py` | `bestsellers` 场景 XLSX 主表默认输出带 `bestSellerRank` 的 ASIN 明细，并追加 `best_sellers_list` 汇总 sheet。 |
| `CATEGORY_OBJECT_FORMATTING.md` | Category Object | 待接入 | - | 暂未实现独立 formatter。 |
| `DEAL_OBJECT_FORMATTING.md` | Deal Object | 待接入 | - | 暂未实现独立 formatter。 |

约定：

- `raw.json` 始终保留 Keepa 原始返回，不覆盖原字段。
- 默认 XLSX 是用户可读导出，已接入 formatter 的对象会自动生成派生字段和明细 sheet。
- 用户明确要求原始 JSON、后端比对或结果过大时，才跳过默认 XLSX 友好导出。

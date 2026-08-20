# Keepa 格式化实现状态

本目录中的 `*_FORMATTING.md` 记录 Keepa Response Object 的格式化合同。`raw.json` 始终保留完整原始响应；XLSX 和格式化 JSON 共用同一组主表/明细表。

| 对象 | 状态 | 实现位置 | 默认导出行为 |
| --- | --- | --- | --- |
| Product Object | 已接入 | `product_formatter.py` | `product`、返回 Product Object 的 `product-search` 共用格式化；大数组和历史序列拆成图片、类目、排名、Offer、变体、列表值与历史 Sheet。 |
| Statistics Object | 已接入 | `stats_formatter.py` | 派生当前指标，拆出价格类型、极值、Buy Box 卖家和 Offer 快照。 |
| Marketplace Offer Object | 已接入 | `product_formatter.py` | `offers` 为标量主表；价格/库存/Prime 专享价/优惠券历史及重复报价分别拆表。 |
| Category Object | 已接入 | `category_formatter.py` | Category 主表派生金额、评分与 URL；children、relatedCategories、topBrands、两组 Top Seller ID/名称及 Lookup 父级对象/父子关系分别拆表。 |
| Deal Object | 已接入 | `deal_formatter.py` | 派生图片、时间、成色、价格等指标，并追加 `deal_metrics`。 |
| Best Sellers Object | 已接入 | `best_sellers_formatter.py` | 主表输出带排名的 ASIN，另有榜单元数据汇总。 |
| Seller Object | 已接入 | `seller_formatter.py` | 评分窗口、评分历史、反馈、storefront、类目、品牌、竞对分别拆表。 |
| Lightning Deal Object | 已接入 | `lightning_deal_formatter.py` | 主表派生金额、时间、评分、图片；variation 维度拆表。 |
| Search Insights Object | 已接入 | `search_insights_formatter.py` | `product-finder stats=1` 时拆出主指标、品牌、卖家和类目。 |
| Tracking Object | 未接入 | - | Tracking Endpoint 尚未提供正式只读 API。 |
| Tracking Creation Object | 未接入 | - | 属于状态变更请求对象，需单独的输入校验、权限和审计设计。 |
| Notification Object | 未接入 | - | 依赖 Tracking notification/webhook 接口及已读副作用设计。 |

当前为 9/12 类官方 Response Object 提供友好格式化；剩余 3 类全部属于尚未接入的 Tracking 域。Graph Image 返回二进制图片，不属于 Response Object formatter。

## Product 明细 Sheet

| Sheet | 内容 |
| --- | --- |
| `csv_history` | 36 类价格、排名、评分与计数历史 |
| `images` | 图片 variant、尺寸、文件名和 URL |
| `category_tree` | 有序类目路径 |
| `sales_ranks` | 各类目的销售排名历史 |
| `offers` | Offer 标量字段和当前排序 |
| `offer_history` | Offer 价格、库存、Prime 专享价和优惠券历史 |
| `offer_duplicates` | 重复报价明细 |
| `variations` | 变体标量摘要 |
| `variation_attributes` | 变体 dimension/value |
| `product_list_values` | features、materials、categories 等多值字段 |
| `product_history` | monthlySold、parentAsin、salesRankReference 等顶层历史 |
| `product_nested_values` | 尚无专用规则的新版嵌套字段，按 JSON path 展开标量叶子 |

未知字段继续保留在 `raw.json`。格式化层不会用截断后的 Excel 单元格替代原始数据。

## 真实响应验证

2026-08-20 使用本地 Key 调用真实接口验证：Category Lookup 返回 1 个对象，Seller Information 返回 1 个对象，完整 Lightning Deals 返回 23,788 个对象及 45,374 条 variation。三个 formatter 的主表和附加表均不再包含 `dict/list` 单元格；完整原始响应仍只保存在工作区外的本地验证目录。

## 场景参数与格式化边界

11 个已接入 JSON 场景在 `opscli/keepa/api/scenarios.py` 统一完成请求参数归一化和边界校验：布尔值、整数、CSV ID、别名冲突和 Best Sellers 历史月份均在调用 Keepa 前处理。Product Finder、Seller Finder、Deals 的 `selection` 保持开放字段，只要求 JSON 对象；未知响应字段仍保留在 `raw.json`，不因 formatter 未声明而丢失。

Graph Image 的二进制结果和 Tracking 域的状态变更对象不属于当前 formatter 范围；它们仍需独立的文件结果模型、权限、确认和审计设计。

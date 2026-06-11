# Keepa Search Insights Object 字段格式化方案

> 参考：Keepa Search Insights Object 官方讨论文档 `https://keepa.com/#!discuss/t/search-insights-object/18199`。本文用于指导 `opscli keepa` 后续对 Product Finder `searchInsights` 的展示、导出与结构化解析；原始响应仍应完整保留。

## 1. 总体原则

- `raw.json` 保持 Keepa 原始返回，不改字段、不改单位、不丢结构。
- Search Insights Object 是 Product Finder 查询结果集合的聚合指标，仅在 Product Finder Request 携带 `&stats=1` 时作为 `searchInsights` 字段返回。
- 该对象描述“符合当前 Product Finder 条件的所有商品集合”的平均价格、卖家/品牌分布、履约方式、评论评分和类目范围，不代表单个 ASIN。
- 金额字段使用 Amazon 站点最小货币单位整数，展示层再按站点币种派生十进制金额。
- 百分比字段按 Keepa 返回的百分比值处理，范围通常为 `0.0` 到 `100.0`；不要再乘以 100。
- `avgRating` 使用评分 x10 的整数格式，例如 `45` 表示 `4.5` 星。
- `relatedCategories`、`topBrandsWithCounts`、`topSellersWithCounts` 是集合分布信息，建议保留 JSON，并在需要做 BI/Excel 分析时额外展开为明细表。
- 所有未知字段、未知 map key 和新增指标保留原值，不因 Keepa 扩展字段导致解析失败。

## 2. 返回位置

| 来源 | 字段 | 触发条件 | 说明 |
| --- | --- | --- | --- |
| Product Finder Request | `searchInsights` | 请求参数包含 `stats=1` | 返回当前 Product Finder 查询匹配商品集合的聚合洞察。 |

Search Insights Object 与 Product Finder 返回的商品列表是同一次查询的不同视角：商品列表用于逐个 ASIN 分析，`searchInsights` 用于快速判断该筛选条件下的市场概况。

## 3. 字段结构

| 字段 | 原始类型 | 语义 | 格式化策略 |
| --- | --- | --- | --- |
| `avgDeltaPercent30BuyBox` | `Float` | 最近 30 天 Buy Box 价格平均百分比变化，按商品等权计算 | 保留原浮点值，派生百分号展示；正数表示典型商品变便宜，负数表示变贵。 |
| `avgDeltaPercent90BuyBox` | `Float` | 最近 90 天 Buy Box 价格平均百分比变化，按商品等权计算 | 同上。 |
| `avgDeltaPercent30Amazon` | `Float` | 最近 30 天 Amazon 自营价格平均百分比变化，按商品等权计算 | 同上。 |
| `avgDeltaPercent90Amazon` | `Float` | 最近 90 天 Amazon 自营价格平均百分比变化，按商品等权计算 | 同上。 |
| `avgBuyBox` | `Integer` | 当前 Buy Box 平均价格 | 保留最小货币单位整数，派生十进制金额。 |
| `avgBuyBox90` | `Integer` | 近 90 天 Buy Box 平均价格 | 保留原值，派生金额。 |
| `avgBuyBox365` | `Integer` | 近 365 天 Buy Box 平均价格 | 保留原值，派生金额。 |
| `avgBuyBoxDeviation` | `Integer` | 近 30 天 Buy Box 价格平均波动/偏差 | 保留原值，派生金额，用于短期价格波动判断。 |
| `avgReviewCount` | `Integer` | 匹配商品的平均评论数量 | 保持整数。 |
| `avgRating` | `Integer` | 匹配商品的平均评分，评分 x10 | 派生真实评分 `avgRatingStars = avgRating / 10`。 |
| `isFBAPercent` | `Float` | 当前 Buy Box offer 由 FBA 履约的商品占比 | 保留 `0.0-100.0` 百分比值，派生 `%` 展示。 |
| `soldByAmazonPercent` | `Float` | 当前由 Amazon 自营销售的商品占比 | 同上。 |
| `hasCouponPercent` | `Float` | 当前有 active coupon 的商品占比 | 同上。 |
| `avgOfferCountNew` | `Float` | 每个商品平均 New offer 数，不含缺货 offer | 保留浮点值。 |
| `avgOfferCountUsed` | `Float` | 每个商品平均 Used offer 数，不含缺货 offer | 保留浮点值。 |
| `sellerCount` | `Integer` | 至少有一个 live offer 的去重卖家总数 | 保持整数。 |
| `brandCount` | `Integer` | 匹配结果中出现的去重品牌总数 | 保持整数。 |
| `highestRank` | `Integer` | 匹配商品中的最差 Sales Rank，数值最大 | 保持整数，字段名中的 `highest` 指数值最高而非排名最好。 |
| `lowestRank` | `Integer` | 匹配商品中的最佳 Sales Rank，数值最小 | 保持整数。 |
| `relatedCategories` | `Long[]` | 相关 Amazon 类目节点 ID 列表 | 保留 JSON；导出时可追加逗号拼接文本，类目 ID 按文本处理。 |
| `topBrandsWithCounts` | `Map<String,Integer>` | 最常见品牌及商品数，最多 5 个，按数量降序 | 保留 JSON；可展开为品牌排行明细表。 |
| `topSellersWithCounts` | `Map<String,Integer>` | Buy Box 出现次数最多的 seller ID 及次数，最多 5 个，按数量降序 | 保留 JSON；seller ID 按文本导出。 |

## 4. 通用值格式化

| 数据类型 | 典型字段 | 原始格式 | 展示/导出格式 |
| --- | --- | --- | --- |
| 金额 | `avgBuyBox`、`avgBuyBox90`、`avgBuyBox365`、`avgBuyBoxDeviation` | 站点最小货币单位整数 | 保留原值，派生十进制金额；币种由 Keepa domain/站点决定。 |
| 百分比 | `avgDeltaPercent*`、`isFBAPercent`、`soldByAmazonPercent`、`hasCouponPercent` | 浮点百分比值 | 保留数值，追加展示字段如 `78.3%`；不要二次乘以 100。 |
| 评分 | `avgRating` | 评分 x10 整数 | 派生 `avgRatingStars = value / 10`，例如 `45 -> 4.5`。 |
| 计数 | `avgReviewCount`、`sellerCount`、`brandCount`、`top*WithCounts` 的 value | 整数或浮点 | 保留数值；平均 offer 数允许小数。 |
| 排名 | `highestRank`、`lowestRank` | 整数 | 保持整数；Sales Rank 数值越小通常排名越好。 |
| 类目 ID | `relatedCategories` | long array | 保留数组；导出时按文本处理，避免 Excel 科学计数法。 |
| Map 分布 | `topBrandsWithCounts`、`topSellersWithCounts` | 字符串 key 到整数 count | 主表保留 JSON；明细表按 rank/key/count 展开。 |
| 缺失值 | `null`、字段缺失、空 map/array | 依字段而定 | 不强制填 0；保留缺失语义，避免和真实 0 混淆。 |

## 5. 百分比方向说明

### 5.1 `avgDeltaPercent*`

- `avgDeltaPercent30BuyBox`、`avgDeltaPercent90BuyBox`、`avgDeltaPercent30Amazon`、`avgDeltaPercent90Amazon` 表示价格变化百分比的集合平均。
- 官方说明：每个商品等权参与计算，不因商品价格高低改变权重。
- 正值表示典型商品变便宜，负值表示典型商品变贵。
- 示例：`-0.12` 表示 `-0.12%`，不是 `-12%`。

### 5.2 占比字段

- `isFBAPercent`、`soldByAmazonPercent`、`hasCouponPercent` 是实际占比百分比值。
- 示例：`78.3` 表示 `78.3%`。
- 导出字段建议同时保留数值字段和展示字段，便于 Excel 继续计算。

## 6. 建议输出结构

Search Insights Object 建议支持一个“洞察主表”和两个“排行明细表”。如果 XLSX 只允许单 sheet，优先输出洞察主表，并把 map/list 字段保留为 JSON 字符串。

### 6.1 洞察主表

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `queryName` | 上下文派生 | 可选，Product Finder 查询或场景名称。 |
| `domainId` | 请求上下文 | Keepa domain ID。 |
| `avgBuyBoxRaw` | `avgBuyBox` | 当前 Buy Box 平均价原始整数。 |
| `avgBuyBoxAmount` | 派生 | 当前 Buy Box 平均价十进制金额。 |
| `avgBuyBox90Raw` | `avgBuyBox90` | 90 天 Buy Box 平均价原始整数。 |
| `avgBuyBox90Amount` | 派生 | 90 天 Buy Box 平均价十进制金额。 |
| `avgBuyBox365Raw` | `avgBuyBox365` | 365 天 Buy Box 平均价原始整数。 |
| `avgBuyBox365Amount` | 派生 | 365 天 Buy Box 平均价十进制金额。 |
| `avgBuyBoxDeviationRaw` | `avgBuyBoxDeviation` | 30 天 Buy Box 价格波动原始整数。 |
| `avgBuyBoxDeviationAmount` | 派生 | 30 天 Buy Box 价格波动金额。 |
| `avgDeltaPercent30BuyBox` | 原字段 | 30 天 Buy Box 价格变化百分比值。 |
| `avgDeltaPercent90BuyBox` | 原字段 | 90 天 Buy Box 价格变化百分比值。 |
| `avgDeltaPercent30Amazon` | 原字段 | 30 天 Amazon 自营价格变化百分比值。 |
| `avgDeltaPercent90Amazon` | 原字段 | 90 天 Amazon 自营价格变化百分比值。 |
| `avgReviewCount` | 原字段 | 平均评论数。 |
| `avgRatingRaw` | `avgRating` | 平均评分 x10 原始值。 |
| `avgRatingStars` | 派生 | 平均星级。 |
| `isFBAPercent` | 原字段 | FBA Buy Box 占比。 |
| `soldByAmazonPercent` | 原字段 | Amazon 自营占比。 |
| `hasCouponPercent` | 原字段 | 有优惠券商品占比。 |
| `avgOfferCountNew` | 原字段 | 平均 New offer 数。 |
| `avgOfferCountUsed` | 原字段 | 平均 Used offer 数。 |
| `sellerCount` | 原字段 | 去重卖家数。 |
| `brandCount` | 原字段 | 去重品牌数。 |
| `highestRank` | 原字段 | 最差 Sales Rank。 |
| `lowestRank` | 原字段 | 最佳 Sales Rank。 |
| `relatedCategories` | 原字段 | 类目 ID 数组 JSON。 |
| `topBrandsWithCounts` | 原字段 | 品牌分布 JSON。 |
| `topSellersWithCounts` | 原字段 | 卖家分布 JSON。 |
| `searchInsightsRaw` | 原始对象 | 完整 Search Insights Object JSON，便于追溯。 |

### 6.2 品牌排行明细表

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `rank` | map 顺序派生 | 品牌排行序号，从 1 开始。 |
| `brand` | `topBrandsWithCounts` key | 品牌名称。 |
| `productCount` | `topBrandsWithCounts` value | 该品牌在匹配结果中的商品数量。 |

### 6.3 卖家排行明细表

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `rank` | map 顺序派生 | 卖家排行序号，从 1 开始。 |
| `sellerId` | `topSellersWithCounts` key | seller ID，按文本导出。 |
| `buyBoxOccurrenceCount` | `topSellersWithCounts` value | 该 seller ID 在匹配结果中持有 Buy Box 的出现次数。 |

### 6.4 相关类目明细表

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `index` | 数组下标 | 类目序号。 |
| `categoryId` | `relatedCategories[]` | Amazon 类目节点 ID，按文本导出。 |

## 7. 与 Product / Deal Object 的差异

- Search Insights Object 是查询集合级别聚合数据；Product Object 是单个 ASIN 的完整商品详情。
- Search Insights Object 不包含 `asin`、`csv`、`stats`、`offers`、`variations` 等单品结构。
- Search Insights Object 的价格字段是集合平均值，不是单品当前价或历史序列。
- `avgDeltaPercent*` 是每个商品等权后的平均百分比变化；`avgBuyBox*` 是平均价格，高价商品对价格平均值影响更大。
- `topSellersWithCounts` 的 key 是 seller ID，不是店铺展示名；如需店铺名，需要额外 seller 查询或外部映射。
- `relatedCategories` 只有类目 ID，不含类目树名称；如需可读类目名，需要结合 Keepa category 数据或外部类目表。

## 8. 与当前 `opscli` 实现的对应关系

- Product Finder 场景在请求层需要支持 `stats=1`，并把顶层 `searchInsights` 从结果中识别出来。
- `raw_response_to_export_rows` 如遇 `searchInsights`，应保留原始对象并可追加 `rowSource = searchInsights` 的聚合行。
- 当前 XLSX 导出对 dict/list 做 JSON 字符串化；Search Insights 友好导出应在 formatter 层先展开金额、评分、百分比和 top map。
- `searchInsights` 不应和商品行逐 ASIN 合并，避免把集合级指标误绑定到某个商品。

## 9. 后续实现建议

1. 新增 `search_insights_formatter.py`，输入 Search Insights Object 和请求上下文，输出 `main_row`、`brand_rows`、`seller_rows`、`category_rows`。
2. 复用 Keepa domain 到币种/金额缩放的工具函数，避免金额字段各自处理。
3. 百分比字段保留原浮点值，另派生展示字符串；不要对 `avgDeltaPercent*` 做 `* 100`。
4. 对 `avgRating` 派生 `avgRatingStars`，保留 `avgRatingRaw` 便于追溯。
5. `topBrandsWithCounts`、`topSellersWithCounts` 展开时保持 Keepa 返回顺序；如果运行时 map 顺序不可靠，则按 count 降序重新排序。
6. 类目 ID 和 seller ID 导出为文本，避免 Excel 自动转科学计数或丢前导字符。
7. 聚合行与 Product Finder 商品明细行分 sheet 或分 `rowSource` 输出，避免分析时误把聚合指标当单品字段。
8. 文档与实现都必须保留未知字段，避免 Keepa 新增字段造成解析失败。

# Keepa Category Object 字段格式化方案

> 实现状态：已接入 `category-lookup` 与 `category-search`。实现文件：`opscli/keepa/category_formatter.py`；多值字段分别导出到 `category_children`、`category_related`、`category_brands`、`category_top_sellers`、`category_top_sellers_any`；`parents=true` 的 `categoryParents` 输出到 `category_parents` 与 `category_parent_children`。

> 参考：Keepa Category Object 官方讨论文档 `https://keepa.com/#!discuss/t/category-object/115`。本文用于指导 `opscli keepa` 后续对 Category Object 的展示、导出与结构化解析；原始响应仍应完整保留。

## 1. 总体原则

- `raw.json` 保持 Keepa 原始返回，不改字段、不改单位、不丢结构。
- Category Object 是 Amazon 类目节点信息，用于描述类目名称、父子节点、是否 browse node 以及该类目下商品集合的聚合统计。
- Category Object 通常变化不频繁，可以按 `domainId + catId` 做较长时间缓存；但统计字段仍应保留更新时间上下文或请求时间。
- `catId`、`parent`、`children`、`relatedCategories` 都是 Amazon category node ID，导出时建议按文本处理，避免 Excel 科学计数法或精度问题。
- `catId = 9223372036854775807` 表示空白类目，`name = "?"`，用于商品无类目或类目不存在的场景。
- `parent = 0` 表示根类目；`children = null` 或 `[]` 表示没有子类目。
- 金额字段使用 Amazon 站点最小货币单位整数，展示层再按站点币种派生十进制金额。
- 百分比字段按 Keepa 返回的百分比值处理，范围通常为 `0.0` 到 `100.0`；不要再乘以 100。
- `avgRating` 使用评分 x10 的整数格式，例如 `45` 表示 `4.5` 星。
- `highestRank`、`lowestRank`、`productCount` 等统计值来自 Keepa 商品数据库估算，不是 Amazon 官方实时值。
- 所有未知字段、未知枚举值和 Keepa 后续新增字段保留原值，不因字段扩展导致解析失败。

## 2. 返回位置

| 来源 | 字段/结构 | 说明 |
| --- | --- | --- |
| Category Searches | Category Object 列表或映射 | 按关键词或条件搜索类目时返回匹配类目。 |
| Category Lookups | Category Object 列表或映射 | 按 `catId` 查询指定类目及其节点信息。 |
| Product Object 辅助解析 | `categories`、`rootCategory`、`categoryTree` 的外部映射 | Product Object 只给类目 ID 或路径片段时，可结合 Category Object 补类目名称、父子关系和统计指标。 |

Category Object 与 Product Object 的 `categories`、`rootCategory` 存在 ID 关联，但 Category Object 本身不是单品数据，也不包含 ASIN 明细。

## 3. 字段结构

| 字段 | 原始类型 | 语义 | 格式化策略 |
| --- | --- | --- | --- |
| `domainId` | `Integer` | Amazon 站点 ID | 保留原值，按站点映射派生 `domain`、`amazonHost`、`currency`。 |
| `catId` | `Long` | Amazon category node ID | 按文本导出；可派生 Amazon 类目链接。特殊值 `9223372036854775807` 表示空白类目。 |
| `name` | `String` | 类目名称 | 原文保留；空白类目通常为 `?`。 |
| `websiteDisplayGroup` | `String` | Amazon 网站展示分组，多见于根类目 | 原文保留；缺失时不回填。 |
| `children` | `Long[]` | 子类目 ID 列表 | 保留 JSON；导出明细时拆成一行一个 child category ID。`null` 和 `[]` 都表示无子类目，但原始语义需保留。 |
| `parent` | `Long` | 父类目 ID | 按文本导出；`0` 表示根类目。 |
| `isBrowseNode` | `Boolean` | 是否标准 browse node，而非促销/专题类 meta category | 保留布尔值，可派生 `browseNodeType`。 |
| `highestRank` | `Integer` | 该类目下商品观察到的最差 root category sales rank，数值最大 | 保持整数；字段名中的 `highest` 指数值最高，不是排名最好。 |
| `lowestRank` | `Integer` | 该类目下商品观察到的最佳 root category sales rank，数值最小 | 保持整数。 |
| `productCount` | `Integer` | 该类目下估算商品数量 | 保持整数；标注为 Keepa 估算值。 |
| `avgBuyBox` | `Integer` | 当前 Buy Box 平均价格 | 保留最小货币单位整数，派生十进制金额。 |
| `avgBuyBox90` | `Integer` | 近 90 天 Buy Box 平均价格 | 保留原值，派生金额。 |
| `avgBuyBox365` | `Integer` | 近 365 天 Buy Box 平均价格 | 保留原值，派生金额。 |
| `avgBuyBoxDeviation` | `Integer` | 近 30 天 Buy Box 价格平均波动/偏差 | 保留原值，派生金额，用于短期价格波动判断。 |
| `avgReviewCount` | `Integer` | 类目下商品的平均评论数量 | 保持整数。 |
| `avgRating` | `Integer` | 类目下商品的平均评分，评分 x10 | 派生真实评分 `avgRatingStars = avgRating / 10`。 |
| `isFBAPercent` | `Float` | FBA 履约商品占比 | 保留 `0.0-100.0` 百分比值，派生 `%` 展示。 |
| `soldByAmazonPercent` | `Float` | Amazon 自营销售商品占比 | 同上。 |
| `hasCouponPercent` | `Float` | 当前有 active coupon 的商品占比 | 同上。 |
| `avgOfferCountNew` | `Float` | 每个商品平均 New offer 数，不含缺货 offer | 保留浮点值。 |
| `avgOfferCountUsed` | `Float` | 每个商品平均 Used offer 数，不含缺货 offer | 保留浮点值。 |
| `sellerCount` | `Integer` | 至少有一个 active offer 的去重卖家总数 | 保持整数。 |
| `brandCount` | `Integer` | 类目下出现的去重品牌总数 | 保持整数。 |
| `avgDeltaPercent30BuyBox` | `Float` | 最近 30 天 Buy Box 价格平均百分比变化，按商品等权计算 | 保留原浮点值，派生百分号展示；正数表示典型商品变便宜，负数表示变贵。 |
| `avgDeltaPercent90BuyBox` | `Float` | 最近 90 天 Buy Box 价格平均百分比变化，按商品等权计算 | 同上。 |
| `avgDeltaPercent30Amazon` | `Float` | 最近 30 天 Amazon 自营价格平均百分比变化，按商品等权计算 | 同上。 |
| `avgDeltaPercent90Amazon` | `Float` | 最近 90 天 Amazon 自营价格平均百分比变化，按商品等权计算 | 同上。 |
| `relatedCategories` | `Long[]` | 常与该类目商品共同出现的相关类目 ID 列表，通常按共现频次排序 | 完整数组保留在 `raw.json`；友好导出拆成 related category 表。 |
| `topBrands` | `String[]` | 最常见品牌列表，真实响应可返回 5 个，按出现频次降序 | 从主表移除，明细表按 rank 展开。 |
| `topSellers` | `String[]` | 当前有活跃 Offer 的 Top Seller ID | 与 `relatedSellerNames` 按索引配对，拆到 `category_top_sellers`。 |
| `relatedSellerNames` | `String[]` | `topSellers` 对应的卖家展示名 | 与 Seller ID 按索引配对；长度不一致时保留较长一侧并将缺项留空。 |
| `topSellersAny` | `String[]` | 不限定当前活跃 Offer 的 Top Seller ID | 与 `relatedSellerNamesAny` 按索引配对，拆到 `category_top_sellers_any`。 |
| `relatedSellerNamesAny` | `String[]` | `topSellersAny` 对应的卖家展示名 | 与 Seller ID 按索引配对；长度不一致时不丢行。 |

## 4. 通用值格式化

| 数据类型 | 典型字段 | 原始格式 | 展示/导出格式 |
| --- | --- | --- | --- |
| 站点 | `domainId` | 整数枚举 | 保留原值，派生站点简称、Amazon 域名和币种。 |
| 类目 ID | `catId`、`parent`、`children`、`relatedCategories` | long / long array | 按文本导出；数组保留 JSON，并可拆明细表。 |
| 金额 | `avgBuyBox`、`avgBuyBox90`、`avgBuyBox365`、`avgBuyBoxDeviation` | 站点最小货币单位整数 | 保留原值，派生十进制金额；币种由 `domainId` 决定。 |
| 百分比 | `avgDeltaPercent*`、`isFBAPercent`、`soldByAmazonPercent`、`hasCouponPercent` | 浮点百分比值 | 保留数值，追加展示字段如 `78.3%`；不要二次乘以 100。 |
| 评分 | `avgRating` | 评分 x10 整数 | 派生 `avgRatingStars = value / 10`，例如 `45 -> 4.5`。 |
| 计数 | `productCount`、`avgReviewCount`、`sellerCount`、`brandCount`、`avgOfferCount*` | 整数或浮点 | 保留数值；平均 offer 数允许小数。 |
| 排名 | `highestRank`、`lowestRank` | 整数 | 保持整数；Sales Rank 数值越小通常排名越好。 |
| 布尔 | `isBrowseNode` | `true` / `false` / 缺失 | 保留布尔值；缺失和 `false` 区分处理。 |
| 列表 | `children`、`relatedCategories`、`topBrands`、Top Seller ID/名称数组 | array / `null` | 主表保留计数，明细表按顺序展开；完整数组只在 `raw.json` 保留。 |
| 缺失值 | `null`、字段缺失、空数组 | 依字段而定 | 不强制填 0；保留缺失语义，避免和真实 0 混淆。 |

## 5. `domainId` 映射

| `domainId` | Amazon 站点 | 常用域名 | 导出建议 |
| --- | --- | --- | --- |
| `1` | US | `amazon.com` | `domain = com`，币种通常为 `USD`。 |
| `2` | UK | `amazon.co.uk` | `domain = co.uk`，币种通常为 `GBP`。 |
| `3` | DE | `amazon.de` | `domain = de`，币种通常为 `EUR`。 |
| `4` | FR | `amazon.fr` | `domain = fr`，币种通常为 `EUR`。 |
| `5` | JP | `amazon.co.jp` | `domain = co.jp`，币种通常为 `JPY`。 |
| `6` | CA | `amazon.ca` | `domain = ca`，币种通常为 `CAD`。 |
| `8` | IT | `amazon.it` | `domain = it`，币种通常为 `EUR`。 |
| `9` | ES | `amazon.es` | `domain = es`，币种通常为 `EUR`。 |
| `10` | IN | `amazon.in` | `domain = in`，币种通常为 `INR`。 |
| `11` | MX | `amazon.com.mx` | `domain = com.mx`，币种通常为 `MXN`。 |
| `12` | BR | `amazon.com.br` | `domain = com.br`，币种通常为 `BRL`。 |

实现时不要把映射写死为唯一真相；Keepa 可能新增站点或调整支持范围，未知 `domainId` 应保留原值并输出 `unknown` 派生字段。

## 6. 类目层级解析

### 6.1 父子关系

- `parent = 0`：根类目。
- `children = null` 或 `[]`：无子类目。
- `children` 只提供子节点 ID，不提供子节点名称；需要结合额外 Category Lookup 结果补齐。
- 构建类目树时以 `catId` 为节点主键，以 `parent` 和 `children` 做双向校验；如二者不一致，优先保留原始字段并记录异常。

### 6.2 Browse Node 与 Meta Category

- `isBrowseNode = true`：标准 Amazon browse node，适合做常规类目筛选、榜单和商品归因。
- `isBrowseNode = false`：可能是促销、专题、Specialty Stores 等 meta category，不一定适合当作常规类目层级。
- 同一分支下的 child 通常共享相同 `isBrowseNode` 值，但实现不应强依赖该假设。

### 6.3 空白类目

- `catId = 9223372036854775807` 且 `name = "?"` 表示空白类目。
- 该类目用于商品无类目或类目不存在的场景，不应作为真实可导航类目。
- 导出时建议派生 `isBlankCategory = true`，并避免生成 Amazon 类目链接。

## 7. 百分比方向说明

### 7.1 `avgDeltaPercent*`

- `avgDeltaPercent30BuyBox`、`avgDeltaPercent90BuyBox`、`avgDeltaPercent30Amazon`、`avgDeltaPercent90Amazon` 表示类目内商品价格变化百分比的平均值。
- 官方说明：每个商品等权参与计算，不因商品价格高低改变权重。
- 正值表示典型商品变便宜，负值表示典型商品变贵。
- 示例：`2.1` 表示 `2.1%`，不是 `210%`；`-0.12` 表示 `-0.12%`，不是 `-12%`。

### 7.2 占比字段

- `isFBAPercent`、`soldByAmazonPercent`、`hasCouponPercent` 是实际占比百分比值。
- 示例：`65.5` 表示 `65.5%`。
- 导出字段建议同时保留数值字段和展示字段，便于 Excel 继续计算。

## 8. 建议输出结构

Category Object 输出一个“类目主表”和多个“关系明细表”。主表只保留标量和列表计数，完整数组保存在 `raw.json`，明细 Sheet 保留每个数组元素。

### 8.1 类目主表

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `domainId` | `domainId` | Keepa 站点 ID。 |
| `domain` | 派生 | 站点简称。 |
| `amazonHost` | 派生 | Amazon 域名。 |
| `currency` | 派生 | 金额字段展示币种。 |
| `catId` | `catId` | 类目节点 ID，按文本导出。 |
| `categoryUrl` | 派生 | Amazon 类目页面链接，空白类目不生成。 |
| `name` | `name` | 类目名称。 |
| `websiteDisplayGroup` | `websiteDisplayGroup` | 网站展示分组。 |
| `parent` | `parent` | 父类目 ID，按文本导出。 |
| `isRootCategory` | 派生 | `parent == 0`。 |
| `isBlankCategory` | 派生 | `catId == 9223372036854775807`。 |
| `isBrowseNode` | `isBrowseNode` | 是否标准 browse node。 |
| `childrenCount` | `children` | 子类目数量。 |
| `highestRank` | `highestRank` | 最差 Sales Rank。 |
| `lowestRank` | `lowestRank` | 最佳 Sales Rank。 |
| `productCount` | `productCount` | Keepa 估算商品数量。 |
| `avgBuyBoxRaw` | `avgBuyBox` | 当前 Buy Box 平均价原始整数。 |
| `avgBuyBoxAmount` | 派生 | 当前 Buy Box 平均价十进制金额。 |
| `avgBuyBox90Raw` | `avgBuyBox90` | 90 天 Buy Box 平均价原始整数。 |
| `avgBuyBox90Amount` | 派生 | 90 天 Buy Box 平均价十进制金额。 |
| `avgBuyBox365Raw` | `avgBuyBox365` | 365 天 Buy Box 平均价原始整数。 |
| `avgBuyBox365Amount` | 派生 | 365 天 Buy Box 平均价十进制金额。 |
| `avgBuyBoxDeviationRaw` | `avgBuyBoxDeviation` | 30 天 Buy Box 价格波动原始整数。 |
| `avgBuyBoxDeviationAmount` | 派生 | 30 天 Buy Box 价格波动金额。 |
| `avgReviewCount` | `avgReviewCount` | 平均评论数。 |
| `avgRatingRaw` | `avgRating` | 平均评分 x10 原始值。 |
| `avgRatingStars` | 派生 | 平均星级。 |
| `isFBAPercent` | `isFBAPercent` | FBA 履约占比。 |
| `soldByAmazonPercent` | `soldByAmazonPercent` | Amazon 自营占比。 |
| `hasCouponPercent` | `hasCouponPercent` | 有优惠券商品占比。 |
| `avgOfferCountNew` | `avgOfferCountNew` | 平均 New offer 数。 |
| `avgOfferCountUsed` | `avgOfferCountUsed` | 平均 Used offer 数。 |
| `sellerCount` | `sellerCount` | 去重卖家数。 |
| `brandCount` | `brandCount` | 去重品牌数。 |
| `avgDeltaPercent30BuyBox` | 原字段 | 30 天 Buy Box 价格变化百分比值。 |
| `avgDeltaPercent90BuyBox` | 原字段 | 90 天 Buy Box 价格变化百分比值。 |
| `avgDeltaPercent30Amazon` | 原字段 | 30 天 Amazon 自营价格变化百分比值。 |
| `avgDeltaPercent90Amazon` | 原字段 | 90 天 Amazon 自营价格变化百分比值。 |
| `relatedCategoryCount` | `relatedCategories` | 相关类目数量。 |
| `topBrandCount` | `topBrands` | Top 品牌数量。 |
| `topSellerCount` | `topSellers` / `relatedSellerNames` | 当前活跃 Offer Top Seller 配对行数。 |
| `topSellerAnyCount` | `topSellersAny` / `relatedSellerNamesAny` | 不限活跃 Offer Top Seller 配对行数。 |

### 8.2 子类目明细表

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `domainId` | 父对象 | Keepa 站点 ID。 |
| `parentCatId` | `catId` | 当前类目 ID，按文本导出。 |
| `parentName` | `name` | 当前类目名称。 |
| `childIndex` | `children` 下标 | 子类目顺序，从 0 开始。 |
| `childCatId` | `children[index]` | 子类目 ID，按文本导出。 |
| `rowSource` | 派生 | 建议固定为 `categoryChildren`。 |

### 8.3 相关类目明细表

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `domainId` | 父对象 | Keepa 站点 ID。 |
| `catId` | `catId` | 当前类目 ID，按文本导出。 |
| `categoryName` | `name` | 当前类目名称。 |
| `relatedRank` | `relatedCategories` 下标 + 1 | 相关类目序号。 |
| `relatedCatId` | `relatedCategories[index]` | 相关类目 ID，按文本导出。 |
| `rowSource` | 派生 | 建议固定为 `categoryRelatedCategories`。 |

### 8.4 Top 品牌明细表

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `domainId` | 父对象 | Keepa 站点 ID。 |
| `catId` | `catId` | 当前类目 ID，按文本导出。 |
| `categoryName` | `name` | 当前类目名称。 |
| `brandRank` | `topBrands` 下标 + 1 | 品牌排行序号。 |
| `brand` | `topBrands[index]` | 品牌名称。 |
| `rowSource` | 派生 | 建议固定为 `categoryTopBrands`。 |

### 8.5 Top Seller 明细表

`category_top_sellers` 配对 `topSellers` 与 `relatedSellerNames`；`category_top_sellers_any` 配对 `topSellersAny` 与 `relatedSellerNamesAny`。

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `catId` | 父对象 | 类目 ID，按文本导出。 |
| `categoryRole` | 派生 | `result` 表示主查询对象，`parent` 表示 Lookup 父级对象。 |
| `sellerRank` | 数组下标 + 1 | Keepa 返回顺序。 |
| `sellerId` | `topSellers*` | Seller ID，按文本导出。 |
| `sellerName` | `relatedSellerNames*` | 同索引的卖家展示名。 |

## 9. 与 Product / Best Sellers / Search Insights Object 的差异

- Category Object 是类目节点数据；Product Object 是单个 ASIN 商品详情。
- Category Object 不包含 `asin`、`csv`、`stats`、`offers`、`variations` 等单品结构。
- Category Object 的 `avgBuyBox*`、`avgRating`、`sellerCount`、`brandCount` 等是类目集合级统计，不应绑定到某个 ASIN。
- Best Sellers Object 是某个类目的 ASIN 榜单快照；Category Object 只描述类目节点及聚合概况，不返回热销 ASIN 列表。
- Search Insights Object 是 Product Finder 查询条件下的集合聚合；Category Object 是固定类目节点下的集合聚合。
- Product Object 的 `categories` / `rootCategory` 可以用 Category Object 补名称和层级，但两者返回结构不同。

## 10. 与当前 `opscli` 实现的对应关系

- Category Search / Category Lookup 已识别 Category Object，不按 Product Object 的 `csv` 或 Deal Object 的数组索引规则解析。
- `raw.json` 保留完整原始对象；友好导出在 formatter 层展开站点、类目链接、金额、评分和列表明细。
- 类目 ID 应按文本导出，尤其是 `9223372036854775807`，避免 Excel 精度损失。
- 所有已知多值字段从主表移除并输出独立明细表；未知字段继续由 `raw.json` 完整保留。

## 11. 实现约束

1. `category_formatter.py` 输入 Category Object 和请求上下文，输出主表以及 children、related category、brand、Top Seller 明细。
2. 复用 Keepa domain 到币种、金额缩放、Amazon host 的工具函数，避免金额字段各自处理。
3. 对 `avgRating` 派生 `avgRatingStars`，保留 `avgRatingRaw` 便于追溯。
4. 百分比字段保留原浮点值，另派生展示字符串；不要对 `avgDeltaPercent*` 或占比字段做 `* 100`。
5. `catId`、`parent`、`children`、`relatedCategories` 全部按文本导出，避免 Excel 自动转科学计数或丢精度。
6. 空白类目单独派生 `isBlankCategory`，不要生成 Amazon 类目链接，也不要参与正常类目树导航。
7. 构建树结构时不要假设一次响应包含所有父子节点；缺失节点应允许后续补查。
8. 文档与实现都必须通过 `raw.json` 保留未知字段，避免 Keepa 新增字段造成解析失败。

# 卖家精灵场景参数手册

本文件是 `ops-seller-sprite` 的唯一参数参考。`SKILL.md` 和 `SKILL_MCP.md` 只保留入口和执行规则；场景映射、参数词典、默认值、别名和类目口径统一以本文件为准。

## 场景映射

| 用户表达 | `scenario` |
| --- | --- |
| 查竞品 / 查产品 / 选竞品 / competitor lookup | `competitor-lookup` |
| 选产品 / product research | `product-research` |
| 关键词挖掘 / keyword mining | `keyword-miner` |
| 关键词反查 / reverse ASIN | `keyword-reverse` |
| 查流量来源 / traffic source | `traffic-source` |
| 选市场 / market research | `market-research` |
| Listing panorama / listing analysis | `listing-analysis` |

## 公共参数与默认值

- `site`：站点，如 `US`、`JP`、`DE`、`UK`、`FR`、`IT`、`ES`、`CA`、`IN`、`MX`
- `period`：周期，如 `30d`、`nearly`、`2026-03`
- `page_size`：每页数量，默认 `100`
- `export_format`：默认 `xls`

默认值：

| 字段 | 默认值 |
| --- | --- |
| `site` | `US` |
| `period` | `30d` |
| `page_size` | `100` |
| `export_format` | `xls` |

关键注意：

- `product-research` 里的“月份 / 数据月份 / 2026-04”应传顶层 `period`，不是 `putawayMonth`。
- `putawayMonth` 只表示上架月数，如 `1`、`3`、`6`、`12`。
- `competitor-lookup` 收到 Amazon 商品链接时，应先提取 ASIN，再传 `params.asins`。
- `competitor-lookup` 如果用户只给了单个 `asin`，也应先归一化成 `params.asins` 再执行。
- `listing-analysis` 结果通常 3 分钟以上才生成，推荐使用 `listing-analysis-submit/status/result` 三段式；不要让 `seller_sprite_run` 同步阻塞等待 `listing-analysis` 完整结果。

## 缺参澄清规则

- 场景不明确时先澄清，不要直接跑。
- 只问必填，不问可选。
- `competitor-lookup` 至少需要 `keyword`、`brand`、`sellerName`、`asins` 或 Amazon 商品链接中的一种。
- `competitor-lookup` 缺少上述主筛选条件时，应在本地快速报错或继续澄清，不要把无效请求拖成 MCP 30 秒超时。
- `keyword-reverse` 必须有 `asin`。
- `traffic-source` 必须有关键词或 ASIN。
- `product-research`、`market-research` 虽然没有硬性必填，但用户只说“跑一下”“看下市场”时仍应先确认意图。

## 场景参数速查

| `scenario` | 必填 | 常用可选参数 | 默认重点 |
| --- | --- | --- | --- |
| `competitor-lookup` | `keyword` / `brand` / `sellerName` / `asins` / 商品链接 五选一；单个 `asin` 需先转成 `asins` | `node` / `category` / `nodeIdPath` / `nodeIdPaths` | `page=1`，按销量倒序，`lowPrice=N` |
| `product-research` | 无 | `recommendationMode`、类目参数、销量/价格/评分/卖家/关键词筛选 | `page=1`，`selectType=2`，按 `total_units` 倒序，`smallAndLight=N`，`lowPrice=N` |
| `keyword-miner` | `keyword` | `filterRootWord`、`amazonChoice`、`includeHighFrequency` | `pageNum=1`，`orderBy=5`，`desc=true` |
| `keyword-reverse` | `asin` | `badges` | `page=1`，`order=12`，`desc=true` |
| `traffic-source` | 关键词或 ASIN | `keyword`、`asin`、`asins`、`order`、`desc` | `pageNo=1`，`order=10`，`desc=true` |
| `market-research` | 无 | `departmentKeyword` / `category`、`node` / `nodeIdPath`、`newReleaseNum`、`topn`、市场指标筛选 | `sampleNumber=1`，`topn=10`，`newReleaseNum=6`，按 `total_sales` 倒序 |
| `listing-analysis` | `asin` | `station` | `station=GLOBAL`；用 submit/status/result 三段式续查 |

## `product-research` 重点参数

### 推荐模式

`recommendationMode` 可用值：

`低价长尾选品`、`研发新品榜`、`潜力单变体`、`销量飙升`、`潜力市场`、`未被满足的市场`、`不压库存的市场`、`投机市场`、`高需求低要求市场`、`全品类铺货`、`精品铺货`、`低价商品`、`新手推荐`

推荐模式会展开为一组筛选条件；如果用户同时显式给出同名筛选条件，以用户条件为准。

### 常用中文字段

| 中文含义 | `params` 字段 |
| --- | --- |
| 类目 | `nodeIdPaths` / `node` / `category` / `nodeIdPath` |
| 月销量 | `minSales` / `maxSales` |
| 月销售额 | `minAmount` / `maxAmount` |
| 子体销量 | `minAmzUnit` / `maxAmzUnit` |
| 月销量增长率 | `minTotalUnitsGrowth` / `maxTotalUnitsGrowth` |
| 大类 BSR | `minRanking` / `maxRanking` |
| 小类 BSR | `minSubBsrRank` / `maxSubBsrRank` |
| BSR 增长数 / 增长率 | `minRankingCv` / `maxRankingCv`、`minRankingCr` / `maxRankingCr` |
| 变体数 | `minVariations` / `maxVariations` |
| Q&A | `minQuestions` / `maxQuestions` |
| 月评新增 / 留评率 | `minReviewsGrouth` / `maxReviewsGrouth`、`minReviewsRate` / `maxReviewsRate` |
| 毛利率 / LQS | `minProfit` / `maxProfit`、`lqsFrom` / `lqsTo` |
| 价格 | `minPrice` / `maxPrice` |
| 评分数 / 评分 | `minReviews` / `maxReviews`、`minReviewRating` / `maxReviewRating` |
| FBA 运费 | `minFba` / `maxFba` |
| 上架月数 | `putawayMonth` |
| 包装重量 | `minWeights` / `maxWeights`，配合 `weightUnit` |
| 买家运费 | `minDeliveryPrice` / `maxDeliveryPrice` |
| 卖家数 | `minSellers` / `maxSellers` |
| 卖家所属地 | `sellerNationList` |
| 包含 / 排除品牌 | `includeBrands` / `excludeBrands` |
| 包含 / 排除卖家 | `includeSellers` / `excludeSellers` |
| 包含 / 排除关键词 | `keywords` / `outOfKeywords` |

### 枚举参数

- `productTags`：`BestSeller`、`AmazonChoice`、`NewRelease`、`A+`、`NonA+`
- `sellerTypes`：`AMZ`、`FBA`、`FBM`
- `pkgDimensionTypeList`：`SS`、`LS`、`SB`、`LB`、`ELO`、`EL5O`、`EL7O`、`EL15O`、`O`
- `sellerNationList`：如 `CN`、`US`、`JP`、`GB`、`DE`
- `video`：`Y` / `N`
- `lowPrice`：`Y` / `N`
- `smallAndLight`：常用 `N` 或 `lowPrice`
- `filterSub`：是否只看所选子类目排名
- `matchType`：`0` 模糊匹配，`1` 词组匹配，`2` 精准匹配

关于 `A+` / `NonA+`：

- 仅勾选 A+：传 `"A+"`
- 仅勾选不含 A+：传 `"NonA+"`
- 两者都勾选或都不勾选：都不要传

### 官方别名

如果同时给了官方别名和内部字段，以内部字段为准。

| 官方别名 | 内部字段 |
| --- | --- |
| `minUnits` / `maxUnits` | `minSales` / `maxSales` |
| `minRevenue` / `maxRevenue` | `minAmount` / `maxAmount` |
| `minUnitsCr` / `maxUnitsCr` | `minTotalUnitsGrowth` / `maxTotalUnitsGrowth` |
| `minRatings` / `maxRatings` | `minReviews` / `maxReviews` |
| `minRatingsCv` / `maxRatingsCv` | `minReviewsGrouth` / `maxReviewsGrouth` |
| `minStar` / `maxStar` | `minReviewRating` / `maxReviewRating` |
| `availableMonth` | `putawayMonth` |
| `fulfillment` | `sellerTypes` |
| `badgeBS=true` | 向 `productTags` 添加 `BestSeller` |
| `badgeAC=true` | 向 `productTags` 添加 `AmazonChoice` |
| `badgeNR=true` | `productTags=["NewRelease"]` |
| `variation` | `maxVariations` |
| `minBsr` / `maxBsr` | `minRanking` / `maxRanking` |
| `minBsrCv` / `maxBsrCv` | `minRankingCv` / `maxRankingCv` |
| `minBsrCr` / `maxBsrCr` | `minRankingCr` / `maxRankingCr` |
| `minLqs` / `maxLqs` | `lqsFrom` / `lqsTo` |
| `dimensionType` | `pkgDimensionTypeList` |
| `sellerNation` | `sellerNationList` |
| `excludeKeywords` | `outOfKeywords` |

## `market-research` 常用字段

| 中文含义 | `params` 字段 |
| --- | --- |
| 类目关键词搜索 | `departmentKeyword` / `category` |
| 精确类目节点 | `node` / `nodeIdPath` |
| 样本数量 | `sampleNumber` |
| 头部 Listing 数量 | `topn` / `topNSelect` |
| 新品定义月份 | `newReleaseNum` / `newReleaseMonths` / `newReleaseNumSelect` |
| 月均销量 | `minAvgSales` / `maxAvgSales` |
| 平均 BSR | `minAvgBsr` / `maxAvgBsr` |
| 平均重量 | `minAvgWeight` / `maxAvgWeight` |
| 头部 Listing 平均 BSR | `minHeadListingAvgBsr` / `maxHeadListingAvgBsr` |
| 商品总数 | `minTotalProducts` / `maxTotalProducts` |
| 月均销售额 | `minAvgRevenue` / `maxAvgRevenue` |
| 平均价格 | `minAvgPrice` / `maxAvgPrice` |
| 平均体积 | `minAvgVolume` / `maxAvgVolume` |
| 头部 Listing 月均销量 | `minHeadListingAvgSales` / `maxHeadListingAvgSales` |
| 平均评分数 / 平均星级 | `minAvgReviews` / `maxAvgReviews`、`minAvgRating` / `maxAvgRating` |
| 平均毛利率 | `minAvgProfit` / `maxAvgProfit` |
| 头部 Listing 月均销售额 | `minHeadListingAvgRevenue` / `maxHeadListingAvgRevenue` |
| 品牌数量 | `minBrands` / `maxBrands` |
| 商品集中度 | `minHeadListingProductCrn` / `maxHeadListingProductCrn` |
| A+ 数量占比 | `minEbcRatio` / `maxEbcRatio` |
| Amazon 自营占比 | `minAmzRatio` / `maxAmzRatio` |
| 卖家数量 | `minSellers` / `maxSellers` |
| 品牌集中度 | `minHeadListingBrandCrn` / `maxHeadListingBrandCrn` |
| FBA 占比 | `minFbaRatio` / `maxFbaRatio` |
| 卖家所属地 | `sellerNations` |
| 平均卖家数 | `minAvgSellers` / `maxAvgSellers` |
| 卖家集中度 | `minHeadListingSellerCrn` / `maxHeadListingSellerCrn` |
| FBM 占比 | `minFbmRatio` / `maxFbmRatio` |
| 新品数量占比 | `minNewRatio` / `maxNewRatio` |
| 新品平均价格 | `minNewAvgPrice` / `maxNewAvgPrice` |
| 新品月均销售额 | `minNewAvgRevenue` / `maxNewAvgRevenue` |
| 新品数量 | `minNewCount` / `maxNewCount` |
| 新品平均星级 / 评分数 / 月均销量 | `minNewAvgRating` / `maxNewAvgRating`、`minNewAvgReviews` / `maxNewAvgReviews`、`minNewAvgSales` / `maxNewAvgSales` |

## 类目规则

### `product-research` / `competitor-lookup`

- 可以直接传自然语言类目，如 `bath`、`bed frames`、`Home & Kitchen:Bedding:Bed Skirts`
- 也可以直接传数值节点路径，如 `1055398:1063236`
- 后端会通过卖家精灵类目接口解析类目文本
- 如果只返回一个候选，后端会直接继续查询
- 如果返回多个候选且其中有一个和用户输入完全匹配，后端会优先使用完全匹配项
- 如果返回多个候选但无法唯一确认，必须停下来让用户选，不要猜
- `product-research` 在用户确认类目后，优先传 `nodeIdPaths: ["..."]`，不要丢掉类目条件

### `market-research`

- 优先用 `departmentKeyword` 做类目 / 市场关键词搜索
- `category` 只是 `departmentKeyword` 的别名
- 只有用户明确给出 SellerSprite 节点路径并要求精确节点筛选时，才使用 `node` / `nodeIdPath`

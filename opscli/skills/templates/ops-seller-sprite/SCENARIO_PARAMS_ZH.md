# 卖家精灵场景参数说明

## 公共参数

- `site`：站点，如美国站 `US`、日本站 `JP`、德国站 `DE`、英国站 `UK`、法国站 `FR`、意大利站 `IT`、西班牙站 `ES`、加拿大站 `CA`、印度站 `IN`、墨西哥站 `MX`
- `period`：周期，如近 30 天 `30d`、最近 `nearly`、指定月份 `2026-03`
- `page_size`：每页数量，默认 `100`
- `export_format`：导出格式，默认 `xls`，也支持 `xlsx`、`json`

## 查竞品 `competitor-lookup`

必填，任选一种：

- `keyword`：关键词
- `brand`：品牌名
- `sellerName`：卖家名称
- `asins`：ASIN 列表
- Amazon 商品链接：亚马逊商品链接，程序会提取 ASIN

可选：

- `node` / `category`：类目名称、完整类目路径或节点 ID 路径

## 选产品 `product-research`

必填：无

可选：

- `recommendationMode`：推荐模式
- `node` / `category`：类目名称、完整类目路径或节点 ID 路径
- `productTags`：商品标识，数组，如 `BestSeller`、`AmazonChoice`、`NewRelease`
- `sellerTypes`：配送方式，数组，如 `AMZ`、`FBA`、`FBM`
- `sellerNationList`：卖家所属地，数组，如 `CN`、`US`、`JP`
- `pkgDimensionTypeList`：包装尺寸分段，数组，如 `SS`、`LS`、`SB`、`LB`、`ELO`、`EL5O`、`EL7O`、`EL15O`、`O`
- `video`：主图视频，`Y` 表示含视频，`N` 表示不含视频
- `lowPrice`：低价商品，`Y` / `N`
- `smallAndLight`：商品资格，常用 `N` 或 `lowPrice`
- `filterSub`：是否只看所选子类目排名
- `matchType`：关键词匹配方式，`0` 模糊匹配，`1` 词组匹配，`2` 精准匹配

销售表现：

- `minSales` / `maxSales`：最低月销量 / 最高月销量
- `minAmount` / `maxAmount`：最低月销售额 / 最高月销售额
- `minAmzUnit` / `maxAmzUnit`：最低子体销量 / 最高子体销量
- `minTotalUnitsGrowth` / `maxTotalUnitsGrowth`：最低月销量增长率 / 最高月销量增长率
- `minRanking` / `maxRanking`：最低大类 BSR / 最高大类 BSR
- `minSubBsrRank` / `maxSubBsrRank`：最低小类 BSR / 最高小类 BSR
- `minRankingCv` / `maxRankingCv`：最低 BSR 增长数 / 最高 BSR 增长数
- `minRankingCr` / `maxRankingCr`：最低 BSR 增长率 / 最高 BSR 增长率

产品信息：

- `minVariations` / `maxVariations`：最低变体数 / 最高变体数
- `minQuestions` / `maxQuestions`：最低 Q&A / 最高 Q&A
- `minReviewsGrouth` / `maxReviewsGrouth`：最低月评新增 / 最高月评新增
- `minReviewsRate` / `maxReviewsRate`：最低留评率 / 最高留评率
- `minProfit` / `maxProfit`：最低毛利率 / 最高毛利率
- `lqsFrom` / `lqsTo`：最低 LQS / 最高 LQS
- `minPrice` / `maxPrice`：最低价 / 最高价
- `minReviews` / `maxReviews`：最低评分数 / 最高评分数
- `minReviewRating` / `maxReviewRating`：最低评分 / 最高评分
- `minFba` / `maxFba`：最低 FBA 运费 / 最高 FBA 运费
- `putawayMonth`：上架月数，如 `1` 表示近 30 天，`3` 表示近 3 个月，`6` 表示近半年
- `minWeights` / `maxWeights`：最低包装重量 / 最高包装重量
- `weightUnit`：重量单位，如 `g`、`kg`、`oz`、`lb`
- `minDeliveryPrice` / `maxDeliveryPrice`：最低买家运费 / 最高买家运费
- `minSellers` / `maxSellers`：最低卖家数 / 最高卖家数

竞品筛选：

- `includeBrands` / `excludeBrands`：包含品牌 / 排除品牌
- `includeSellers` / `excludeSellers`：包含卖家 / 排除卖家
- `keywords`：包含关键词
- `outOfKeywords`：排除关键词

推荐模式可选：

`低价长尾选品`、`研发新品榜`、`潜力单变体`、`销量飙升`、`潜力市场`、`未被满足的市场`、`不压库存的市场`、`投机市场`、`高需求低要求市场`、`全品类铺货`、`精品铺货`、`低价商品`、`新手推荐`

官方别名：

- `minUnits` / `maxUnits`：最低销量 / 最高销量
- `minRevenue` / `maxRevenue`：最低销售额 / 最高销售额
- `minUnitsCr` / `maxUnitsCr`：最低销量增长率 / 最高销量增长率
- `minRatings` / `maxRatings`：最低评分数 / 最高评分数
- `minRatingsCv` / `maxRatingsCv`：最低月评新增 / 最高月评新增
- `minStar` / `maxStar`：最低星级 / 最高星级
- `availableMonth`：上架月数
- `fulfillment`：配送方式
- `badgeBS` / `badgeAC` / `badgeNR`：Best Seller / Amazon's Choice / New Release 标记
- `variation`：变体数
- `minBsr` / `maxBsr`：最低 BSR / 最高 BSR
- `minBsrCv` / `maxBsrCv`：最低 BSR 增长数 / 最高 BSR 增长数
- `minBsrCr` / `maxBsrCr`：最低 BSR 增长率 / 最高 BSR 增长率
- `minLqs` / `maxLqs`：最低 LQS / 最高 LQS
- `dimensionType`：包装尺寸分段
- `sellerNation`：卖家所属地
- `excludeKeywords`：排除关键词

## 关键词挖掘 `keyword-miner`

必填：

- `keyword`：关键词

可选：

- `filterRootWord`：是否过滤同根词
- `amazonChoice`：是否只看 Amazon's Choice
- `includeHighFrequency`：是否包含高频词

## 关键词反查 `keyword-reverse`

必填：

- `asin`：ASIN

可选：

- `badges`：流量词类型标签

## 查流量来源 `traffic-source`

必填：

- `keywordOrAsin`：关键词或 ASIN

可选：

- `keyword`：关键词
- `asin`：单个 ASIN
- `asins`：ASIN 列表
- `order`：排序字段
- `desc`：是否倒序

## 选市场 `market-research`

必填：无

可选：

- `node` / `category`：类目名称、完整类目路径或节点 ID 路径
- `departmentKeyword`：市场 / 类目关键词
- `newReleaseNum` / `newReleaseMonths`：新品月份数
- `topn`：取 Top N 数据

常用中文字段：

| 中文含义 | params 字段 |
| --- | --- |
| 类目 | `node` / `category` / `nodeIdPath` |
| 市场 / 类目关键词 | `departmentKeyword` |
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
| 平均评分数 | `minAvgReviews` / `maxAvgReviews` |
| 平均星级 | `minAvgRating` / `maxAvgRating` |
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
| 新品平均星级 | `minNewAvgRating` / `maxNewAvgRating` |
| 新品平均评分数 | `minNewAvgReviews` / `maxNewAvgReviews` |
| 新品月均销量 | `minNewAvgSales` / `maxNewAvgSales` |

## 类目参数注意

`product-research`、`competitor-lookup` 和 `market-research` 可以直接传自然语言类目，后端会通过卖家精灵类目接口 `/v2/competitor-lookup/nodes` 解析。

- 可传：`bath`、`bed frames`、`Home & Kitchen:Bedding:Bed Skirts`
- 可传节点路径：`1055398:1063236`
- 如果接口返回多个候选，但其中有一个候选与输入的完整类目路径或叶子类目名完全匹配，后端会直接使用该候选继续查询。
- 如果接口返回多个候选，任务会暂停并返回候选 `nodeIdPath` / 完整类目路径，需要用户补充后再查。
- 不要猜测节点 ID。

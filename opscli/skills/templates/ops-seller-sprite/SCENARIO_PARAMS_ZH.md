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
- `minPrice` / `maxPrice`：最低价 / 最高价
- `minSales` / `maxSales`：最低月销量 / 最高月销量
- `minReviews` / `maxReviews`：最低评分数 / 最高评分数
- `minReviewRating` / `maxReviewRating`：最低评分 / 最高评分

推荐模式可选：

`低价长尾选品`、`研发新品榜`、`潜力单变体`、`销量飙升`、`潜力市场`、`未被满足的市场`、`不压库存的市场`、`投机市场`、`高需求低要求市场`、`全品类铺货`、`精品铺货`、`低价商品`、`新手推荐`

官方别名：

- `minUnits` / `maxUnits`：最低销量 / 最高销量
- `minRatings` / `maxRatings`：最低评分数 / 最高评分数
- `minStar` / `maxStar`：最低星级 / 最高星级
- `availableMonth`：上架月数
- `fulfillment`：配送方式
- `badgeNR`：新品榜标记
- `variation`：变体数
- `minBsr` / `maxBsr`：最低 BSR / 最高 BSR

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

## 类目参数注意

`product-research`、`competitor-lookup` 和 `market-research` 可以直接传自然语言类目，后端会通过卖家精灵类目接口 `/v2/competitor-lookup/nodes` 解析。

- 可传：`bath`、`bed frames`、`Home & Kitchen:Bedding:Bed Skirts`
- 可传节点路径：`1055398:1063236`
- 如果接口返回多个候选，任务会暂停并返回候选 `nodeIdPath` / 完整类目路径，需要用户补充后再查。
- 不要猜测节点 ID。

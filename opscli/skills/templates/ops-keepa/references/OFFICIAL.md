# Keepa 官方口径明细

本文件保存 Keepa 官方讨论页/API 页口径细节；`SKILL_MCP.md` 只保留 Agent 执行必需的摘要、默认值和限制。

当用户追问字段、token、分页、响应结构、接口限制或需要后端对比依据时，先查本文件；普通业务回复仍不要主动展示 API Key、账号来源、token 消耗或内部请求参数。

## Product Search (`/search`)

官方参考：`https://keepa.com/#!discuss/t/product-searches/109`。

- 官方查询格式：`/search?key=<yourAccessKey>&domain=<domainId>&type=product&term=<searchTerm>`。
- 必填请求参数：`domain`、`type=product`、`term`；`term` 是要搜索的关键词，官方要求 URL encoded。
- Token Cost：10，单个搜索词最多返回 20 条结果；结果顺序与 Amazon 搜索一致，但排除 sponsored content。
- 默认响应字段为 `products`，包含有序 product objects；传 `asins-only=1` 时响应字段为 `asinList`，只返回有序 ASIN 字符串数组。
- 官方可选参数包括 `asins-only`、`stats`、`update`、`history`、`rating`；本地 MCP 同步支持这些参数，`asins_only`/`asinsOnly` 映射为 `asins-only`。当前官方参数表已无 `page`，本地不会透传。

## Product Deal 与价格字段 (`/product`)

官方参考：`https://keepa.com/api-docs/product-object.html`。

- `offers` 可选参数的有效范围为 20-100；提供 `offers` 时 `buybox` 已隐含启用。
- Product `deals` 只包含当前 Buy Box 活动的 `accessType`、`dealType`、`badge`，没有独立价格。该字段仅在使用 `offers` 时更新。
- Limited Time Deal 应组合展示活动徽标与 `stats.buyBoxPrice`、`stats.buyBoxShipping`、`stats.buyBoxSavingBasis`、`stats.buyBoxSavingBasisType`、`stats.buyBoxSavingPercentage`，组合价格必须标记为派生关联值。
- Lightning Deal 与 Prime Exclusive 的原生 price type 分别为 `stats.current[8]` 和 `stats.current[33]`。
- `csv[8]` 最后一组可能是未来结束时间和 `-1`；当前 Lightning 价格优先使用 `stats.current[8]`，历史回退必须处理该哨兵。

## Browsing Deals (`/deal`)

官方参考：`https://keepa.com/api-docs/deal-object.html`。

- `selection.domainId` 必填；本地根据 `site` 自动填充并允许 selection 显式覆盖。
- `selection.priceTypes` 必填且只能包含一个 price type 索引，例如 Amazon `0`、New `1`、Lightning Deal `8`、Buy Box `18`、Prime Exclusive `33`。
- Deal Object 表示最近约 12 小时发生价格或排名变化的商品摘要，不是全部当前活动目录。
- `current`、`avg`、`delta`、`deltaPercent` 按 price type 索引解释；`deltaPercent` 不是 Amazon 页面活动折扣率。

## Best Sellers (`/bestsellers`)

官方参考：`https://keepa.com/#!discuss/t/best-sellers/1298`；Keepa API 页面说明 Best Sellers lists 可包含 up to 500k ASINs。

- 必填请求参数：`domain`、`category`。
- 本地 MCP 允许用户传 `category`、`productGroup` 或 `product_group`，最终都会映射到 Keepa 原始参数 `category`。
- `category` 可传 Amazon/Keepa category node id；如用户传 `productGroup`，仅作为本地兼容别名处理。
- 原始响应主字段为 `bestSellersList`；其中 `asinList` 是热销 ASIN 列表，导出层会将每个 ASIN 展开为一行。
- 支持 `range=0/30/90/180`，或成对的 `month`/`year` 历史月份；历史月份必须是过去 36 个完整自然月且不能与 `range`/`sublist` 同时使用。`variations` 控制变体展开，`sublist` 使用子类目排名。
- Token Cost 固定为 50。
- 该接口返回指定类目/产品组的 Best Sellers ASIN 列表，不返回完整商品详情；如需标题、价格、评分等详情，应再用 `product` 场景按 ASIN 查询。

## Product Finder (`/query`)

官方参考：`https://keepa.com/#!discuss/t/product-finder/5473`；Keepa API 页面说明 Product Finder 可在整个商品库中按任意条件筛选商品。

- 官方 GET 格式：`/query?key=<yourAccessKey>&domain=<domainId>&selection=<queryJSON>[&stats=1]`；也支持 POST，POST payload 为 `queryJSON`。
- 必填请求参数：`domain`、`selection`；`selection` 是 Product Finder 的 query JSON，GET 使用时必须 URL encoded。
- Token Costs：`10 + 1 per 100 ASINs`；传 `stats=1` 时官方说明为 `30 tokens + 1 token for every 1,000,000 products returned by the query as a whole`，并返回 `searchInsights`。
- 响应只返回 ASIN 列表，不返回 product objects；主字段为 `asinList`，同时包含 `totalResults`，传 `stats=1` 时包含 `searchInsights`。
- 默认最多返回 50 个结果；`perPage` 默认/最小为 50，`page=0` 时 `perPage` 最大可到 10000；分页请求中 `page` 与 `perPage` 的组合不得超过 10000 个结果。
- 筛选条件之间是 AND；数组类筛选字段内部是 OR，最多 50 个值；字符串筛选大小写不敏感，可用 `✜` 前缀做排除；`_gte`/`_lte` 分别表示大于等于/小于等于。
- 官方常用 selection 字段包括 `rootCategory`、`categories_include`、`categories_exclude`、`title`、`brand`、`productGroup`、`monthlySold_gte`、`current_*_gte/lte`、`avg*_*_gte/lte`、`sort`、`page`、`perPage` 等。
- 本地 MCP 建议传 `params={"selection":{...}}`；也兼容把筛选字段直接放在 `params`，运行时会整体 JSON 编码为 Keepa 原始参数 `selection`。

## Seller Information (`/seller`)

官方参考：`https://keepa.com/#!discuss/t/seller-information/790`；Keepa API 页面说明 third party sellers metrics 包括 rating/rating count history、top seller lists，以及 storefront access with up to 100k ASINs。

- 官方查询格式：`/seller?key=<yourAccessKey>&domain=<domainId>&seller=<sellerId>`。
- 必填请求参数：`domain`、`seller`；`seller` 是 merchant seller ID，可从 offer object 或 Amazon seller profile URL 的 `seller` 参数中获取。
- 支持批量请求：`seller` 可传逗号分隔 seller ID，最多 100 个；Token Cost 为每个 requested seller 1 token。若 seller 不在 Keepa 数据库中，不消耗 token，也不返回数据。
- 可选参数 `storefront`：有效值 `0`/`1`；传 `storefront=1` 时 seller object 会包含店铺 ASIN 信息，包括 `asinList` 和 `asinListLastSeen`。
- `storefront=1` 额外 Token Cost 为 9；若 storefront 数据可用且至少包含 2 个 ASIN，总成本为 seller object 1 token + storefront data 9 tokens = 10 tokens；无数据时不额外消耗。
- storefront 表示该卖家当前在 Amazon 上架、以及过去 7 天内曾上架的商品；Keepa 通过数据库扫描每日采集，ASIN 列表可能不完整或过期。
- storefront ASIN 列表最多 100,000 个 ASIN，按 Keepa 最近验证到该 seller 活跃 offer 的时间倒序排列；每个 ASIN 带 last-seen timestamp。
- 官方重要限制：请求 `storefront=1` 时不允许批量 seller ID，否则会报错。本地 MCP 默认 `storefront=false`；如要店铺 ASIN 列表，必须单个 seller 显式开启。
- 响应字段为 `sellers` map：key 是 `sellerId`，value 是 seller object；无结果时 map 为空，seller ID 无效时错误会在 error field 中体现。

## Seller Finder (`/sellerquery`)

- 必填参数：`domain`、`selection`；selection 为 Seller Finder JSON。
- 响应字段为 `sellerIdList`。
- Token Cost 为 10 + 每 100 个返回 seller ID 1 token（向上取整）。
- 本地场景名为 `seller-finder`，推荐把 `perPage`、`sort` 和筛选条件放入 `params.selection`。

# Keepa API 接口与响应对象支持度调研

> 调研日期：2026-08-20
> 调研范围：Keepa 官方 API 文档中的 **Endpoints**、**Response objects** 与 API Changelog；对照 `opscli/keepa` 当前实现。
> 本文先记录调研基线，并在 2026-08-20 同步独立 worktree 的补充实现结果。

## 0. 补充实现结果

本次实现后，正式场景从 10 个增至 **11 个**，覆盖 13 个官方 Endpoint 中的 **84.6%**；12 类官方 Response Object 中 **9 类**已有友好格式化。未接入部分收敛为两个需要独立抽象的 Endpoint，以及 Tracking 域的 3 类对象。

| 范围 | 本次结果 |
| --- | --- |
| Seller Finder | 新增 `seller-finder`，调用 `/sellerquery`，selection 使用 JSON，返回 `sellerIdList`。 |
| Product Request | 支持 `code-limit`、`historical-variations`；ASIN/code 与 offers 组合仍允许最多 100 个商品；按 Offer 页及 buybox/stock/rating/update 等估算 token。 |
| Product Search | 移除已废弃 `page` 透传，新增 `rating`；基础成本按 10 token；返回 Product Object 时复用 Product formatter。 |
| Product Finder | 按 `10 + ceil(perPage/100)` 估算，`stats=1` 另计 30 token 基础成本。 |
| Best Sellers | 支持 `range`、成对 `month/year`、`variations`、`sublist`，并校验合法值、互斥关系和过去 36 个完整自然月；按 50 token 估算。 |
| Category | Lookup 显式发送 `parents=false`，Search 不再发送无效 `parents`；新增 Category formatter。 |
| Seller | 默认 `storefront=false`，批量 seller 禁止 storefront，移除 `update`；新增 Seller formatter。 |
| Deals / Top Seller | token 分别按 5 / 50 估算。 |
| Lightning Deals | 新增 `state`；指定 ASIN 按 1 token，完整列表按 500 token；新增 Lightning Deal formatter。 |
| Product 大字段 | 图片、类目树、销售排名、Offer 历史、Offer 重复项、变体属性、简单列表和顶层历史全部拆到独立 Sheet；主表不再保留嵌套 `dict/list` 单元格。 |

仍未接入：

- Graph Image `/graphimage`：返回二进制图片，需要下载、MIME 和文件结果模型，不能复用 JSON 场景。
- Tracking `/tracking`：包含读写操作、POST 请求体、通知已读副作用和 webhook，需要独立权限、确认与审计设计。
- Tracking Object、Tracking Creation Object、Notification Object：随 Tracking 域一起实施。

### 0.1 真实响应验证

- 使用用户提供的本地 Keepa Key 于 2026-08-20 完成线上验证；Key 仅从工作区外文件读取，未写入仓库、请求记录或文档。调用 Category Lookup、Seller Information、指定 ASIN Lightning Deals 和完整 Lightning Deals，分别消耗 1、1、1、500 token。
- Category Lookup `1055398` 返回 1 个真实 Category Object。除既有 `children`、`topBrands` 外，确认新版对象还返回 `relatedSellerNames`、`relatedSellerNamesAny`、`topSellers`、`topSellersAny` 四个并行数组；现已拆到 `category_top_sellers` 与 `category_top_sellers_any`，主表不再保留复杂单元格。
- Seller Information `ATVPDKIKX0DER` 返回 1 个真实 Seller Object，确认时间字段为 `trackedSince`，并取得 10 条类目统计、10 条品牌统计和 10 条竞对记录；主表剩余嵌套字段数为 0。
- 指定 ASIN 的 Lightning Deals 返回空结果；完整列表返回 23,788 个 Lightning Deal Object 和 45,374 条 variation 明细，真实字段与 formatter 合同一致，主表和明细表剩余嵌套字段数均为 0。
- 真实验证同时发现 `OPSCLI_KEEPA_API_KEY` 会被 OPS 登录态 401 提前阻断；已让账号提供器捕获认证异常后继续使用显式本地 Key，并增加回归测试。
- 使用本机 5 份历史真实 Product 响应验证，均为 ASIN `B0B56CHMSC`；测试代码不读取这些用户文件，仓库 fixture 使用脱敏固定值。
- 单个真实 Product 约有 97 个顶层字段、8 张图片、41 个变体、82 条变体属性、36 个 CSV 槽位和 4 组销售排名。
- 一次样本格式化产生约 7,867 条 `csv_history`、8,223 条 `sales_ranks`、833 条 `product_history`；格式化主表剩余嵌套字段数为 0。
- 线上原始响应和 XLSX 仅保存在工作区外的本地验证目录，不纳入 Git；仓库测试继续使用脱敏固定 fixture，避免测试访问真实网络或用户文件。

### 0.2 现有场景参数加固（2026-08-20）

在上述接口和 formatter 覆盖基础上，现有 11 个 JSON 场景已统一在请求构建层做参数归一化：

- 布尔参数接受 `true/false`、`1/0`、`yes/no`、`on/off`，输出统一为 Python `bool`；非法字符串直接返回配置错误。
- `stats`、`offers`、`update`、`days`、`code-limit`、Best Sellers 的 `range/month/year` 统一转换为整数并校验下限/范围，不再把非法数字静默透传给 Keepa。
- `asin/asins`、`code/codes`、`category/categories`、`seller/sellers`、`term/keyword` 和 `productGroup/product_group` 的别名同时出现时，只有语义一致才接受；冲突值明确拒绝。
- Product Finder、Seller Finder、Deals 的 `selection` 同时支持 JSON 对象和 JSON 字符串；对象内部字段保持开放透传，避免因 Keepa 新增筛选字段而被本地白名单阻断。
- Lightning Deals 的 `state` 只做非空校验，不预设未从官方页面确认的枚举；`asin` 统一清理为 CSV 字符串。

该层只负责请求参数的类型、边界和别名一致性，不改变 `raw.json` 的原始响应保留策略，也不对 selection 做推测性完整 schema 限制。

### 0.3 现有对象格式化补充（2026-08-20）

- Product Marketplace Offer 明细新增 condition 文本、价格/运费金额和币种；Offer `couponHistory` 依据 Keepa 规则拆为优惠金额或折扣百分比。
- Product、Deal、Statistics、Search Insights 对 `-1/-2` 缺失哨兵统一按空值处理，避免生成负金额或负折扣。
- Category Lookup 的父级 Category Object 现在与结果类目共享金额、评分、计数和空类目派生字段；Seller 评分窗口/历史新增百分比展示列。
- Search Insights 的品牌和卖家明细按计数降序、名称稳定排序，导出排名不再依赖 API map 的原始插入顺序。
- Lightning Deal 主表新增按秒杀价/当前价计算的折扣率、活动时长，以及 `percentOff/percentClaimed` 的展示字段。

以下第 1-6 节保留实施前调研问题及决策依据；当前状态以本节和 `opscli/keepa/reference/FORMATTERS_STATUS.md` 为准。

## 1. 实施前结论摘要

Keepa 新版官方文档目前列出 **13 个 Endpoint**、**12 类 Response object**。逐项复核后，本文列出的数量与名称均与 2026-08-20 官方导航一致。

- 实施前 `opscli keepa` 公开 **10 个场景**，对应 10/13 个 Endpoint，按“有正式场景可调用”计算覆盖率为 **76.9%**。
- 实施前尚未提供正式场景的 Endpoint 是：**Seller Finder**（`/sellerquery`，2026-08-09 新增）、**Graph Image API**（`/graphimage`）、**Tracking API**（`/tracking`）。
- 现有 10 个场景并非全部参数都与最新版文档同步。已确认 Product Request 缺 `code-limit`、`historical-variations`，且在 `offers` 场景额外限制为最多 20 个商品，而当前官方页仍说明 Product Request 可批量最多 100 个商品；Product Search 仍透传当前官方参数表已经移除的 `page`，并缺 `rating`；Best Sellers、Category、Seller、Lightning Deals 也存在具体参数或组合校验缺口。
- 当前 token 估算不能可靠保护额度：Product Search、Product Finder、Browsing Deals、Best Sellers、Most Rated Sellers 均按 1 token 估算，实际基础成本分别为 10、10、5、50、50；Lightning Deals 不传 ASIN 时实际为 500 token，当前仍估算为 1。Seller 默认请求 storefront 时也没有计入额外 9 token。
- 所有现有 JSON Endpoint 的原始对象都能保存在任务 `raw.json` 中；通用导出也能把多数未知字段以 JSON 单元格或普通列保留下来。因此“原始数据不丢”覆盖面大于“对象已结构化支持”。
- 12 类 Response object 中，当前只有 **5 类具有明确的独立友好格式化实现**：Product、Statistics、Marketplace Offer（作为 Product 子表）、Deal、Best Sellers；Search Insights 也已有专用附加表，但只在 Product Finder 返回 `searchInsights` 时接入。若把它计入专用格式化，则为 **6/12（50%）**。
- Category 已有详细格式化方案但尚未接入；Seller、Lightning Deal、Tracking、Tracking Creation、Notification 尚无专用格式化方案或实现。
- 最新 changelog 的 2026-08-18、08-09、08-06、07-28、04-20、02-23 条目均已覆盖，没有漏掉更晚条目。需要修正的是对 04-20 Product Search 变化的解释：当前 Product Search 页面已经不再列出 `page`，并明确单次最多返回 20 条，不应继续描述为“即将移除”。

## 2. 判定口径

为避免把“能收到 JSON”误判成“完整支持”，本文区分三层：

| 层级 | 含义 | 当前实现依据 |
| --- | --- | --- |
| Endpoint 场景支持 | 用户可通过 `keepa_run` / `opscli keepa run <scenario>` 构造合法请求 | `opscli/keepa/api/scenarios.py` 中存在场景及参数 builder |
| 原始响应保留 | Keepa 返回的 JSON 可完整追溯 | `KeepaApiManager.run()` 把原始响应写入 `raw.json`；未知对象不会先被模型裁剪 |
| Response object 友好格式化 | 对象字段按业务语义展开，包含金额、时间、嵌套子表、列名或派生字段 | 独立 formatter + `KeepaApiManager` 显式接入 + 测试 |

“Endpoint 已支持”不等于其所有官方参数都已暴露；“原始响应保留”也不等于 XLSX/格式化 JSON 已可直接分析。

## 3. Endpoint 支持矩阵

官方总览来源：[Keepa API Documentation - Endpoints](https://keepa.com/api-docs/#endpoints)。

| 官方 Endpoint | 路径 | 当前场景 | 状态 | 主要缺口或风险 |
| --- | --- | --- | --- | --- |
| Product Request | `/product` | `product` | 部分支持 | 已支持 asin/code、stats、offers、update、history、buybox、rating、videos、aplus、stock、days、only-live-offers；缺 `code-limit`、`historical-variations`。当前代码在传 `offers` 时把商品批量上限降为 20；当前官方页说明 asin/code 批量最多 100 个，未列出该 20 商品限制，`offers` 的 20-100 是“每个商品尝试获取的 offer 数”，不是商品批量数。token 估算也未计入 offers、buybox、stock、rating、update 等附加成本。 |
| Product Search | `/search?type=product` | `product-search` | 部分支持 | 支持 term、stats、update、history、asins-only；缺官方 `rating`。当前仍透传 `page`，但官方当前参数表已无 `page`，并明确单次最多 20 条。token 估算固定为 1，低于实际基础成本 10，且未计 update/rating 附加成本。 |
| Product Finder | `/query` | `product-finder` | 已支持主流程 | `selection` 基本透传，并单独传 `stats`；需用官方 selection schema 做完整参数/类型校验。当前估算恒为 1，实际为 10 + 每返回 100 个 ASIN 1 token（向上取整）。 |
| Browsing Deals | `/deal` | `deals` | 已支持主流程 | selection 基本透传。2026-07-28 起 `priceTypes` 会拒绝无 deal 数据的类型，当前无本地校验；当前估算 1，实际每页固定 5 token。 |
| Best Sellers | `/bestsellers` | `bestsellers` | 部分支持 | 当前只传 category/productGroup，缺 `range`、成对的 `month`/`year`、`variations`、`sublist` 及互斥/日期边界校验。当前估算 1，实际固定 50 token。2026-07-28 起当前月和越界 month 会报错。 |
| Category Lookup | `/category` | `category-lookup` | 部分支持 | category 已支持，一次最多 10 个 ID；官方当前参数表把 `parents` 标为必填，当前 builder 仅在用户显式传入时才发送，缺默认值或必填校验。Category Object 尚无友好 formatter。 |
| Category Search | `/search?type=category` | `category-search` | 部分支持 | term 已支持；当前仍允许透传 `parents`，但官方当前 Category Search 参数表没有该参数。Category Object 尚无友好 formatter。 |
| Seller Information | `/seller` | `seller` | 部分支持 | seller、storefront 已支持，但 builder 默认强制 `storefront=true`：单卖家请求可能额外消耗 9 token，且多 seller 批量请求会违反官方“storefront 不允许批量”的限制。当前仍发送官方 2026-02-23 已移除的 `update`。token 估算只按 seller 数量计算，未计 storefront；Seller Object 无友好 formatter。 |
| Seller Finder | `/sellerquery` | 无 | **不支持** | 2026-08-09 新增。需新增场景、selection builder、分页/排序/范围/search 支持，并处理 `sellerIdList` 响应。通用 row extractor 已认识 `sellerIdList`，可复用。 |
| Most Rated Sellers | `/topseller` | `top-seller` | 已支持接口 | 仅 domain；返回卖家 ID 列表可通用导出，但没有榜单或 Seller Object 友好格式化。当前估算 1，实际固定 50 token。 |
| Lightning Deals | `/lightningdeal` | `lightning-deals` | 部分支持 | 当前只传 domain 和可选 asin，缺官方示例使用的 `state` 过滤。响应可提取 `lightningDeals`，但无 Lightning Deal formatter。指定 asin 时 1 token；不指定 asin 获取完整列表时为 500 token，当前两者都估算为 1。 |
| Graph Image API | `/graphimage` | 无 | **不支持** | 返回图片而非 JSON。现有 `KeepaApiClient.get_json()` 强制 JSON，不能直接复用；需要二进制下载、MIME/文件导出模型。2026-07-28 新增 `types`、`legend`、`lw` 和三类图表支持。 |
| Tracking API | `/tracking` | 无 | **不支持** | 包含 add/remove/removeAll/get/list/notification/listNames/webhook 等多种操作，且含写操作。官方说明所有操作都可用 GET，Add Tracking 另支持 POST；现有 GET JSON 客户端可复用部分传输能力，但仍需独立服务接口、写操作权限/确认、批量 POST JSON、分页及 webhook 安全设计。 |

### 3.1 Token 估算复核

当前多数场景复用 `_estimate_one()`，会让运行前额度预警失真，尤其是 50/500 token 的接口。按官方当前页，明显差异如下：

| 场景 | 当前估算 | 官方基础成本或规则 |
| --- | --- | --- |
| Product Request | 商品数 | 1/商品，但 offers 会替代基础成本并按 offer page 计费；buybox、stock、rating、update、historical-variations 可加费 |
| Product Search | 1 | 10/次，update/rating 可能额外计费 |
| Product Finder | 1 | 10 + 每 100 个返回 ASIN 1 token（向上取整） |
| Browsing Deals | 1 | 5/页 |
| Best Sellers | 1 | 50/次 |
| Seller Information | seller 数量 | 1/seller；`storefront=1` 在有数据时额外 9 token，且不能批量 seller |
| Most Rated Sellers | 1 | 50/次 |
| Lightning Deals | 1 | 指定 ASIN 为 1；完整列表为 500 |

### 3.2 端点层优先级建议

1. **P0：兼容性与额度保护**：移除 Seller `update`；移除 Product Search `page` 并补 `rating`；修复 Seller 默认 storefront/批量冲突；补 Product `code-limit`、`historical-variations`；取消或重新确认 Product+offers 的 20 商品限制；按上表更新 token 估算。
2. **P1：Seller Finder**：这是 2026-08 新增且与现有架构最接近的纯查询 JSON Endpoint。现有 `sellerIdList` 抽取逻辑已预留，实施成本最低。
3. **P1：Response formatter 补全**：先完成现有 Endpoint 已经返回的 Category、Seller、Lightning Deal，提升当前 10 个场景的可用性。
4. **P2：Graph Image API**：需要新增二进制响应能力，宜与 JSON 场景解耦。
5. **P2/P3：Tracking API**：读操作和写操作分阶段；优先 get/list/notification，再评估 add/remove/webhook。Tracking 会改变 Keepa 账户状态，不宜直接塞进现有只读 `run scenario` 抽象。

## 4. Response object 支持矩阵

官方总览来源：[Keepa API Documentation - Response objects](https://keepa.com/api-docs/#response-objects)。仓库现状来源：`opscli/keepa/reference/FORMATTERS_STATUS.md`、各 formatter 和 `KeepaApiManager` 的显式接入逻辑。

| 官方 Response object | 主要来源 Endpoint | 原始响应可保留 | 友好格式化状态 | 当前缺口 |
| --- | --- | --- | --- | --- |
| Product Object | Product Request；Product Search（非 asins-only） | 是 | **已接入** | 新增 `images[].variant` 未显式展开；Product Search 返回 Product Object 时当前 formatter 只对 `product` 场景启用，需确认是否也应复用。 |
| Statistics Object | Product Request / Product Search 的 `stats` | 是 | **已接入 Product 子对象** | Product Request 主链已格式化；Product Search 未复用 Product formatter。Product Finder 的 `stats=1` 返回的是独立的 Search Insights Object，不属于 Statistics Object。 |
| Marketplace Offer Object | Product Request `offers` | 是 | **已接入 Product 子表** | 已生成 offers sheet，但字段覆盖需按新版 Offer Object 全量对表；官方已移除 `isScam`。 |
| Category Object | Category Lookup / Category Search | 是 | **待接入** | 已有 `CATEGORY_OBJECT_FORMATTING.md` 方案，尚无 `category_formatter.py` 和 manager 接入。 |
| Deal Object | Browsing Deals | 是 | **已接入** | 需按新版字段和 `priceTypes` 规则做回归。 |
| Best Sellers Object | Best Sellers | 是 | **已接入** | 已展开榜单 ASIN；可补 month/历史榜单元数据。 |
| Seller Object | Seller Information | 是 | **未接入** | 当前只做通用行与 Keepa Time 转换；无 rating history、storefront、Buy Box、业务信息等子表。官方已移除 `feedback`、`isScammer`。 |
| Lightning Deal Object | Lightning Deals | 是 | **未接入** | 当前通用导出，缺状态、开始/结束时间、价格、库存/进度等语义化字段。 |
| Search Insights Object | Product Finder `stats=1` | 是 | **已接入附加表** | 已有 brands/sellers/categories 子表；应按新版官方字段做全量差异测试。 |
| Tracking Object | Tracking API | Endpoint 未支持 | **未接入** | 需先实现 Tracking 读接口；再设计阈值、通知方式、列表名等嵌套结构。 |
| Tracking Creation Object | Tracking API add 请求体 | Endpoint 未支持 | **未接入** | 它是请求对象而非普通响应对象；需要输入模型、验证、批量上限和敏感写操作边界。 |
| Notification Object | Tracking API notification / webhook | Endpoint 未支持 | **未接入** | 2026-08-06 新增 `notificationId`；需兼容拉取与 webhook 两种来源，并处理“读取后标记已读”的副作用。 |

### 4.1 对“全部 Response objects 支持”的建议定义

建议把目标定义为以下可验收标准，而不是仅增加类名或字段表：

- 官方对象页面中的字段有版本化清单；字段新增时原始数据不丢。
- 每个对象有独立 formatter 或明确声明复用哪个 formatter。
- 嵌套数组/字典进入独立 sheet，不被截断在单个 Excel 单元格中。
- Keepa Time、Unix 时间、金额最小单位、百分比、枚举和值为 `-1` 的缺失语义统一处理。
- formatter 同时驱动 XLSX 和格式化 JSON，避免两套字段合同漂移。
- 每个对象至少有官方示例/固定 fixture 的字段保留、列顺序、嵌套表和空值测试。
- `raw.json` 继续作为不可变追溯源；友好格式化只新增派生字段，不覆盖官方原字段。

## 5. 新版 Changelog 对当前实现的影响

官方来源：[Keepa API Changelog](https://keepa.com/api-docs/changelog.html)。

| 日期 | 官方变化 | 当前影响 |
| --- | --- | --- |
| 2026-08-18 | Product `images[]` 新增 `variant`，标明 MAIN、PT01-PT08、SWCH 等图片含义 | 当前只提取图片 URL，建议新增 `mainImageVariant`、图片明细 sheet 或保留 variant 到展开结果。 |
| 2026-08-09 | 新增 Seller Finder `/sellerquery`，返回 `sellerIdList` | Endpoint 缺失；通用 extractor 已支持 `sellerIdList`，新增场景后导出底座可复用。 |
| 2026-08-06 | Notification Object 新增 `notificationId` | Tracking 尚未支持；未来模型必须包含稳定 ID，不能继续靠 asin/createDate/csvType/cause 组合去重。 |
| 2026-07-28 | Graph Image 新增 `types`、三类图表、`legend`、`lw`；最大尺寸 1800px | Graph Image 整体未支持，实施时应直接以新参数面为准。 |
| 2026-07-28 | Deals `priceTypes` 开始拒绝不产生 deal 数据的类型 | 当前 selection 直接透传，无本地验证；需补白名单或至少透出清晰错误。 |
| 2026-07-28 | Best Sellers 当前月/越界 `month` 改为报错 | 当前 builder 未支持 month；扩展历史榜单时必须加入边界校验。 |
| 2026-04-20 | Product、Statistics、Category 多个旧字段移除；Product legacy 字段迁移 | formatter/文档应清理 `imagesCSV` 等旧字段的主路径，同时保留对历史 fixture 的兼容读取。 |
| 2026-04-20 | Product Search `page` 将移除，单次结果从 10 增至 20 | 当前 Product Search 页面已经不再列出 `page`，并明确单次最多 20 条；当前 builder 和 Skill 示例仍传 page，属于当前合同偏差，不再只是生效前准备。 |
| 2026-02-23 | Seller Lookup `update` 参数移除 | 当前 `_seller_params` 仍透传 `update`，属于明确兼容性缺口。 |
| 2026-02-23 | Product/Statistics/Offer/Seller 字段移除与价格定义变化 | 需按官方对象页刷新 formatter 字段合同与测试；特别是 2026-02-23 前后 NEW/USED 等价格口径不同。 |

## 6. 推荐实施拆分（后续开发）

### 阶段 A：官方合同同步

- 建立 `Endpoints` 与 `Response objects` 的版本化清单和测试 fixture。
- 修正已删除或已不在当前官方参数表中的参数，补 Product 参数缺口。
- 把场景 token estimator 从粗略常量更新为可解释估算；复杂 Endpoint 允许返回“无法准确预估”，不要给出错误的低估值。
- 更新 `ops-keepa` Skill 的参数和示例，移除 Product Search `page`。

### 阶段 B：现有 Endpoint 的 Response objects 全覆盖

- 新增 Category formatter（已有方案可直接落地）。
- 新增 Seller formatter、Lightning Deal formatter。
- 把 Product formatter 复用于 Product Search 的 Product Object 返回形态。
- 全量核对 Marketplace Offer、Search Insights 和 2026 新增/移除字段。

### 阶段 C：查询类新 Endpoint

- 新增 Seller Finder 场景，返回 seller ID 主表；可选串联 Seller Information 作为显式二阶段操作，避免隐式消耗大量 token。
- 新增 Graph Image 独立客户端方法与图片导出结果，避免让 JSON parser 接管二进制响应。

### 阶段 D：Tracking 域

- 将 Tracking 视为独立子域，而不是普通查询场景。
- 先实现只读 get/list/listNames；notification 明确 `readOnly` 默认策略，避免查询即改变已读状态。
- add/remove/removeAll/webhook 作为显式写命令和 MCP Tool，加入参数模型、权限、确认、审计和测试。
- Notification 以 `notificationId` 为业务键；保留旧通知无 ID 时的兼容键。

## 7. 代码证据索引

- 场景注册与参数 builder：`opscli/keepa/api/scenarios.py:89-329`
- 当前 10 个场景：`opscli/keepa/api/scenarios.py:238-329`
- JSON-only GET 客户端：`opscli/keepa/api/client.py:44-52`、`:69-104`
- 原始响应落盘：`opscli/keepa/services/api_manager.py:131-145`
- 通用结果提取（已预留 sellerIdList、trackings、notifications）：`opscli/keepa/services/api_manager.py:281-320`
- 通用导出行提取：`opscli/keepa/services/api_manager.py:323-390`
- formatter 显式接入：`opscli/keepa/services/api_manager.py:393-499`
- 已接入对象状态：`opscli/keepa/reference/FORMATTERS_STATUS.md:5-18`
- Marketplace Offer 子表：`opscli/keepa/product_formatter.py:301-331`
- 图片 URL 提取（未处理 `variant` 语义）：`opscli/keepa/product_formatter.py:417-449`

## 8. 官方来源

- [Keepa API Overview](https://keepa.com/api-docs/)
- [Endpoints 总览](https://keepa.com/api-docs/#endpoints)
- [Response objects 总览](https://keepa.com/api-docs/#response-objects)
- [API Changelog](https://keepa.com/api-docs/changelog.html)
- [Product Request](https://keepa.com/api-docs/product.html)
- [Product Search](https://keepa.com/api-docs/product-search.html)
- [Product Finder](https://keepa.com/api-docs/product-finder.html)
- [Browsing Deals](https://keepa.com/api-docs/deals.html)
- [Best Sellers](https://keepa.com/api-docs/best-sellers.html)
- [Category Lookup](https://keepa.com/api-docs/category-lookup.html)
- [Category Search](https://keepa.com/api-docs/category-search.html)
- [Seller Information](https://keepa.com/api-docs/seller.html)
- [Seller Finder](https://keepa.com/api-docs/seller-finder.html)
- [Most Rated Sellers](https://keepa.com/api-docs/most-rated-sellers.html)
- [Lightning Deals](https://keepa.com/api-docs/lightning-deals.html)
- [Graph Image API](https://keepa.com/api-docs/graph-image.html)
- [Tracking API](https://keepa.com/api-docs/tracking.html)

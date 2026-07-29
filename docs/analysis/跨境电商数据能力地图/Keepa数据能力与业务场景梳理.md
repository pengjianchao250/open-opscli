# Keepa 数据能力与业务场景梳理

**文档版本**：v0.1
**梳理日期**：2026-07-20
**适用范围**：`open-opscli` 当前 Keepa 正式 CLI/MCP 接入
**关联文档**：[跨境电商全链路数据能力地图](./跨境电商全链路数据能力地图.md)、[卖家精灵数据能力与业务场景实测](./卖家精灵数据能力与业务场景实测.md)

---

## 一、结论摘要

当前 `open-opscli` 已正式接入 **10 个 Keepa 数据场景**，覆盖商品详情与历史、关键词搜商品、Product Finder、类目、卖家、Top Sellers、Best Sellers、Deals 和 Lightning Deals。

Keepa 当前最强的数据价值不是“再做一套卖家精灵选品”，而是提供以下历史和竞争事实：

1. 商品价格、BSR、Buy Box、Offer 数量、评分和评论数等时间序列。
2. 当前 Buy Box、卖家、FBA/FBM、Prime、商品成色及 Offer 竞争结构。
3. 商品基础属性、类目树、父子变体、图片、内容、尺寸重量及部分费用字段。
4. Product Finder 全库筛选及匹配集合的价格、品牌、卖家、评分、履约和优惠聚合洞察。
5. 类目热销榜、卖家店铺商品、折扣商品和秒杀机会。

但 Keepa 不是第一方经营数据源。它不能提供真实广告花费与归因、自有 Sessions/CVR、准确订单销量、内部库存与在途、采购物流成本、退货原因或评论正文。BSR、`salesRankDrops`、`monthlySold`、Offer stock 等字段必须按代理信号使用，不能直接等同于内部经营事实。

---

## 二、评估口径

为避免把“Keepa 平台可能支持”“opscli 已经接入”和“已经形成运营产品”混在一起，本文采用三层口径。

| 层级 | 判定问题 | 本文完成标准 |
|---|---|---|
| Keepa 平台能力 | Keepa 官方 API 是否存在对应数据对象或接口 | 官方接口说明或正式对象契约有明确证据 |
| opscli 接入能力 | 当前公开 CLI/MCP 是否能够稳定查询 | 已在 `SCENARIOS` 注册，参数可构造，结果可保存和导出 |
| 业务场景能力 | 数据是否已经形成可执行决策 | 有固定输入、分析规则、输出、监控周期和验收指标 |

当前实现的主要证据：

- [Keepa 场景注册表](../../../opscli/keepa/api/scenarios.py)
- [Keepa API 管理与结果处理](../../../opscli/keepa/services/api_manager.py)
- [Keepa MCP 工具](../../../opscli/mcp/tools/keepa.py)
- [Keepa MCP 使用规范](../../../opscli/skills/templates/ops-keepa/SKILL_MCP.md)
- [Keepa 官方口径摘录](../../../opscli/skills/templates/ops-keepa/references/OFFICIAL.md)
- [Keepa 格式化实现状态](../../../opscli/keepa/reference/FORMATTERS_STATUS.md)

> 本文梳理的是当前代码契约和已验证的格式化能力，没有消耗 Keepa token 逐个执行真实查询。实时权限、账号额度、数据完整率和特定 ASIN 返回情况仍需后续抽样验证。

---

## 三、当前正式接入的 10 个数据场景

当前公开数据场景登记于 `opscli/keepa/api/scenarios.py:238-329`。公开 MCP 另有规范、场景列表、额度、执行、任务状态和导出 6 个控制工具；它们是调用基础设施，不能与 10 个业务数据场景相加。

| 场景 | Keepa 接口 | 输入 | 当前可取得的数据 | 关键限制 | 当前成熟度 |
|---|---|---|---|---|---|
| `product` 商品详情 | `/product` | ASIN，或 UPC/EAN/ISBN-13 | Product Object、价格/排名/评分等历史、stats、Offer、Buy Box、变体、内容和属性 | 默认 `history=true`；普通最多 100 个 item，带 `offers` 最多 20 个 | **强**：已有完整 Product、Stats、历史、Offer、变体友好格式化 |
| `product-search` 关键词搜商品 | `/search?type=product` | 关键词 | 按 Amazon 搜索顺序返回 Product Object 或 ASIN 列表 | 官方单词最多 20 条，排除 sponsored content；Token 成本较高 | **中**：可查询和通用导出，暂无独立 Product Search formatter |
| `product-finder` 条件筛商品 | `/query` | Product Finder `selection` | 匹配 ASIN、总结果数；`stats=1` 时有 Search Insights | 主响应是 ASIN 列表，不是完整商品对象；复杂分页和 token 规则需控制 | **强**：Search Insights 已友好格式化，商品详情需再查 `product` |
| `category-search` 类目搜索 | `/search?type=category` | 类目关键词 | Keepa/Amazon 类目对象和候选节点 | 结果是类目，不是商品市场统计 | **中**：可查询和通用导出，Category formatter 尚未接入 |
| `category-lookup` 类目详情 | `/category` | category id | 类目名称、层级、父节点等类目对象 | 单次最多 10 个 category id | **中**：可查询和通用导出，Category formatter 尚未接入 |
| `seller` 卖家详情 | `/seller` | seller id | 卖家指标、评分/评分数历史、店铺 ASIN 和 last-seen 时间 | 最多 100 个 seller；`storefront=true` 时不能批量 seller，店铺数据可能不完整或过期 | **中**：有正式场景，暂无独立 Seller formatter |
| `top-seller` 头部卖家 | `/topseller` | 站点 | 指定站点评分数较多的 marketplace seller ID 列表 | 不是销量榜，也不直接返回完整卖家详情 | **中**：可导出 seller ID，详情需再查 `seller` |
| `bestsellers` 热销榜 | `/bestsellers` | category 或 productGroup | 按顺序返回 Best Sellers ASIN 列表 | 不返回完整商品详情；需再查 `product` | **强**：已派生 `bestSellerRank` 和榜单明细 sheet |
| `deals` 折扣商品 | `/deal` | Deals selection | 最近价格变化和折扣商品、当前价格/排名/评分/评论数、Warehouse 和 Lightning 标记 | 单次最多约 150 条；筛选和数组口径需按官方规则使用 | **强**：已有 Deal 主表和指标展开 sheet |
| `lightning-deals` 秒杀 | `/lightningdeal` | 站点，可选 ASIN | 当前及即将开始的 Lightning Deals | 当前没有独立 formatter，实际字段完整率需抽样 | **中**：有正式查询和通用导出 |

当前支持的站点为 `US`、`GB/UK`、`DE`、`FR`、`JP`、`CA`、`IT`、`ES`、`IN`、`MX`、`BR`。站点会决定 Keepa domain、币种和金额小数位。

### 3.1 不能按“10 个场景”直接理解覆盖率

- `product` 一个场景包含多个 Keepa 数据对象，是当前最深的单品能力。
- `product-finder` 只返回候选 ASIN 和聚合洞察，通常必须再组合 `product` 才能形成选品结果。
- `bestsellers`、`top-seller` 也是名单入口，完整分析分别需要追加 `product` 或 `seller`。
- `category-search` 和 `category-lookup` 是类目解析底座，不是完整的市场研究报告。
- 当前 10 个正式场景是数据接口，不等于已经形成 10 个运营业务产品。

---

## 四、Keepa 当前能够取得的主要数据

### 4.1 商品身份、内容和物理属性

`product` 返回的 Product Object 可以覆盖：

- ASIN、父 ASIN、UPC/EAN/GTIN、品牌、制造商、型号和商品类型。
- 标题、Features、描述、短描述、图片、A+、视频及内容数量代理字段。
- 类目树、根类目、Sales Rank Reference 和历史类目变化。
- 父子变体、变体属性、变体图片和子 ASIN 列表。
- 包装与商品尺寸、重量，以及部分 FBA/Referral Fee 相关字段。
- Coupon、促销、危险品、成人品、Subscribe & Save 等商品标识，具体以响应是否返回为准。

当前导出层会把 Keepa 时间转为 UTC，把金额按站点币种转为十进制，把毫米/克派生为厘米/千克，并生成图片 URL、类目路径和变体摘要。原始字段仍保留，不用派生值覆盖源数据。

**实现证据**：`opscli/keepa/product_formatter.py:22-149,233-269,356-544`；`opscli/keepa/reference/PRODUCT_OBJECT_FORMATTING.md:15-64`。

### 4.2 价格、排名、评分和评论数历史

Product Object 的 `csv` 历史数组当前可解析 0—35 共 36 种序列，主要包括：

| 数据组 | 可取得的历史信号 |
|---|---|
| 价格 | Amazon、New、Used、List Price、Collectible、Refurbished、Warehouse、New FBA、Prime Exclusive、Trade-in、Rental 等价格 |
| Buy Box | New Buy Box、Used Buy Box、价格与运费 |
| 履约价格 | New FBM、各成色 Used/Collectible、Refurbished 的价格与运费 |
| 排名 | Sales Rank 历史 |
| Offer 数 | New、Used、Refurbished、Collectible、New FBA、New FBM Offer 数量历史 |
| 口碑代理 | Rating 历史、Review Count 历史 |
| 活动 | Lightning Deal 价格、Offer 数据更新时间 |

其他 Product Object 历史还可能包括父 ASIN、Sales Rank Reference、`monthlySold`、Coupon、Buy Box Seller 等变化。当前 `raw.json` 保留这些原始字段，但不是每个历史数组都已有独立友好 sheet。

**实现证据**：`opscli/keepa/product_formatter.py:96-149,272-299,522-641`；`opscli/keepa/reference/PRODUCT_OBJECT_FORMATTING.md:66-138`。

### 4.3 Stats 时间窗口统计

请求 `stats` 后，可取得当前、区间起点、平均值和极值等统计：

- Amazon/New/Used/FBA/Buy Box 等当前价格。
- 30、90、180、365 天平均价格和平均 Sales Rank。
- 区间内最小、最大及发生时间。
- 30、90、180、365 天 `salesRankDrops`。
- Amazon/New 等价格类型的缺货时间占比。
- 当前 Offer 总数、FBA/FBM Offer 数、最低价 Seller。
- 当前 Buy Box Seller、Buy Box 价格与运费、到手价、配送时长。
- Buy Box seller 历史份额、平均价和 last-seen 时间。
- Amazon/Buy Box 的部分 stock 快照字段，以及 Lightning Deal 状态。

当前会生成 `stats_price_types`、`stats_extremes`、`stats_buy_box_sellers`、`stats_offer_snapshot` 等明细 sheet。

**实现证据**：`opscli/keepa/stats_formatter.py:48-140,151-261,263-398`。

### 4.4 Offer 与 Buy Box 竞争

请求 `offers` 后，可以分析：

- Seller ID、商品成色、FBA/FBM、Prime、Amazon 自营、MAP 和是否从中国发货等标识。
- 当前 live Offer 顺序和 Offer 页竞争位置。
- New/Used/Collectible/Refurbished 在 FBA/FBM 下的 Buy Box eligible 数量。
- Buy Box 当前卖家、赢得比例、历史价格和最近出现时间。
- 当前最低 FBA/FBM 卖家、Offer 数和部分 stock 快照。

这些数据适合做竞争结构和 Buy Box 稳定性分析，但不是卖家后台库存。Offer 抓取失败或请求没有带 `offers` 时，缺失数据不能解释为“没有竞争”。

**实现证据**：`opscli/keepa/product_formatter.py:301-331`；`opscli/keepa/stats_formatter.py:227-244,348-398`；`opscli/keepa/reference/PRODUCT_OBJECT_FORMATTING.md:160-170`。

### 4.5 Product Finder 与 Search Insights

`product-finder` 支持使用 Keepa selection 对商品库做组合筛选。主结果是 ASIN 列表和 `totalResults`；带 `stats=1` 时，Search Insights 可提供：

- 当前、90 天、365 天平均 Buy Box 价格。
- 30/90 天 Buy Box 和 Amazon 价格平均变化。
- 平均评分、平均评论数、平均 New/Used Offer 数。
- FBA Buy Box 占比、Amazon 自营占比、有 Coupon 商品占比。
- 匹配集合的去重卖家数、品牌数、最佳/最差 Sales Rank。
- Top Brands、Top Buy Box Sellers 和相关类目。

当前会生成 `search_insights`、`search_insight_brands`、`search_insight_sellers`、`search_insight_categories` 四类明细 sheet。

**实现证据**：`opscli/keepa/search_insights_formatter.py:9-80,91-171`；`opscli/keepa/reference/SEARCH_INSIGHTS_OBJECT_FORMATTING.md:18-64`。

### 4.6 卖家、店铺和类目榜单

| 数据入口 | 可取得的数据 | 推荐组合 |
|---|---|---|
| `seller` | 卖家评分、评分数历史、店铺 ASIN、ASIN last-seen 等 | 单卖家查询 storefront 后，用 `product` 批量补商品详情 |
| `top-seller` | 站点头部 seller ID | 用 `seller` 补卖家画像，再做类目/品牌分布 |
| `category-search` | 类目关键词候选 | 确认 category id 后进入榜单或 Product Finder |
| `category-lookup` | 类目对象、父级和层级 | 建立稳定的类目树和跨场景类目主键 |
| `bestsellers` | 类目热销 ASIN 和顺序 | 用 `product` 补价格、BSR、口碑、Offer 和历史 |

Keepa 官方说明 seller storefront 是数据库扫描结果，可能不完整或已过期；Best Sellers 也只返回 ASIN 名单，不能直接当成完整商品表。

### 4.7 Deals 与 Lightning Deals

`deals` 可以按 selection 筛选近期变动和折扣商品，并取得：

- ASIN、标题、类目、图片和更新时间。
- 当前 Amazon/New/Used/Buy Box 等价格。
- Sales Rank、评分、评论数和 Offer 数。
- 相对日、周、月、90 天均值的价格变化和变化百分比。
- Warehouse 成色、Lightning Deal 标记和结束时间。

当前 `deal_metrics` sheet 会把多时间窗口、多价格类型指标展开，适合做促销强度和价格异常分析。`lightning-deals` 已接入查询，但目前只做通用导出。

**实现证据**：`opscli/keepa/deal_formatter.py:14-108,116-230`；`opscli/keepa/reference/DEAL_OBJECT_FORMATTING.md`。

---

## 五、当前格式化、导出和调用底座

### 5.1 对象格式化状态

| 对象 | 状态 | 当前用户可读产物 |
|---|---|---|
| Product Object | 已接入 | 商品主表、`csv_history`、`offers`、`variations`、Stats 多明细表 |
| Statistics Object | 已接入 | 当前/均值/极值、Buy Box Seller、Offer 快照 |
| Search Insights Object | 已接入 | 洞察主表、品牌、卖家、相关类目明细 |
| Best Sellers Object | 已接入 | 带 `bestSellerRank` 的 ASIN 和榜单汇总 |
| Deal Object | 已接入 | Deal 主表和 `deal_metrics` |
| Category Object | 待接入 | 当前仍使用通用 JSON 展平导出 |
| Seller、Top Seller、Product Search、Lightning Deal | 无独立 formatter | 当前使用通用导出和 Keepa 时间转换 |

### 5.2 工程能力

- 公开 CLI 与远端 MCP 共用正式场景契约。
- 支持任务 ID、任务状态续查和导出文件获取。
- 执行前进行 Keepa token 预估和额度检查，普通用户只看到 MCP 每日调用额度。
- 原始响应、规范化结果和 XLSX 分层保存，便于后端核对。
- 当前面向普通用户只支持 XLS/XLSX；`xls` 和 `xlsx` 都生成 `.xlsx`。
- MCP 成功结果只预览最多 20 行，完整结果以导出文件为准。
- XLSX 中文表头和可读字段是本地派生，不是 Keepa 官方原始字段。

**实现证据**：`opscli/mcp/tools/keepa.py:1-22,83-208,213-231`；`opscli/keepa/services/api_manager.py:63-202,274-459`；`opscli/keepa/reference/FORMATTERS_STATUS.md`。

---

## 六、从选品到运营可支撑的业务场景

### 6.1 现有数据可直接组合的场景

| 业务场景 | Keepa 数据组合 | 输出 | 当前缺少的产品化能力 |
|---|---|---|---|
| ASIN 历史体检 | `product` + history + stats | 价格、BSR、Buy Box、评分、评论数、Offer 和促销时间线 | 异常识别规则、阶段标签和统一评分 |
| 竞品价格策略 | 竞品 ASIN 批量 `product` | 当前/均价/极值、促销频率、价格稳定性 | 竞品池维护、自动复查和变价原因 |
| Buy Box 与 Offer 竞争 | `product` + offers + buybox + stats | Buy Box 稳定性、FBA/FBM、卖家数、最低价和竞争强度 | 连续监控、丢失预警和责任归因 |
| Product Finder 机会筛选 | `product-finder` + Search Insights + `product` | 候选池、价格带、口碑门槛、履约和品牌/卖家集中度 | 选品规则模板、父 ASIN 去重、GO/NO-GO |
| 类目热销榜验证 | 类目解析 + `bestsellers` + `product` | 热销榜商品画像及历史稳定性 | 榜单周期快照、上升/下降/新进入识别 |
| 卖家/店铺监控 | `seller` storefront + `product` | 店铺商品池、上新/下架线索、价格和排名变化 | 店铺快照、变更检测和品牌归属清洗 |
| 促销与 Deal 机会 | `deals` + `lightning-deals` + `product` | 折扣深度、促销时间、价格异常和竞品活动 | 折扣真实性、活动前后效果和日历化 |
| 变体与生命周期 | `product` 的 parent/variations + 历史 | 主力变体、变体扩张、父体变化和生命周期 | 子体销量分配仍需其他来源或估算 |
| 数据可信度校验 | Keepa + 卖家精灵 + 内部订单 | 第三方估算与历史事实差异、字段可信等级 | 统一主键、时间粒度和冲突处理规则 |

### 6.2 建议建设优先级

#### P0：先把 Keepa 的历史优势产品化

| 建议正式场景 | 数据输入 | 核心输出 |
|---|---|---|
| `asin-history-intelligence` ASIN 历史情报 | Product、Stats、历史、变体 | 商品生命周期、价格/BSR/口碑/Offer 时间线和异常点 |
| `buybox-offer-competition` Buy Box 竞争 | Offers、Stats、Buy Box Seller | 当前竞争结构、Buy Box 稳定性、FBA/FBM 和卖家集中度 |
| `product-finder-opportunity` 条件选品 | Product Finder、Search Insights、Product | 候选池、集合画像、父体去重和机会评分 |
| `category-bestseller-tracker` 类目榜单跟踪 | Category、Best Sellers、Product | 榜单快照、新进入、上升、下滑和长期稳定商品 |
| `seller-storefront-tracker` 店铺商品跟踪 | Seller storefront、Product | 店铺商品池、上新/下架线索、价格和排名变化 |

#### P1：补价格、促销和数据校验

| 建议场景 | 业务价值 |
|---|---|
| `pricing-promotion-intelligence` | 区分常态价、促销价、虚假折扣和价格战，输出建议价格区间 |
| `deal-opportunity` | 发现真实降价、Warehouse 和 Lightning Deal，形成促销日历 |
| `variant-lifecycle` | 识别父子关系变化、主力变体和新品变体机会 |
| `keepa-sellersprite-crosscheck` | 用 Keepa 历史验证卖家精灵销量、价格、排名和上架时间代理数据 |

#### P2：持续监控与更广接口

- 为 P0/P1 场景增加定时快照、变化检测和预警，而不是把单次查询命名为监控。
- 评估 Keepa 官方其他接口时，先确认是否值得接入；未进入当前 `SCENARIOS` 的官方能力不能写成 opscli 已可用。
- 为 Category、Seller、Product Search 和 Lightning Deal 增加专用 formatter 和业务字段字典。
- 建立 token 成本预算、批量分片、缓存和重复查询去重策略。

---

## 七、Keepa 与卖家精灵的重合和互补

| 数据问题 | Keepa 更强 | 卖家精灵更强 | 推荐使用方式 |
|---|---|---|---|
| 商品价格和 BSR 历史 | 长时间序列、均值、极值、变价 | 当前选品表和销量估算 | Keepa 作为历史验证层 |
| Buy Box 与 Offer | 卖家、FBA/FBM、价格、份额和历史 | 流量、关键词及市场竞争代理 | Keepa 判断供给竞争，卖家精灵判断需求竞争 |
| 关键词需求 | 仅商品搜索和 Product Finder，无搜索量体系 | 搜索量、购买量、PPC、流量词和 ABA | 关键词决策以卖家精灵为主，Keepa补商品历史 |
| 市场与类目 | 榜单、商品库筛选、集合聚合 | 市场规模、集中度、增长和销量估算 | 卖家精灵发现市场，Keepa验证头部和历史稳定性 |
| 评论 | 评分和评论数历史 | 可补评论正文/VOC（接入后） | Keepa看口碑变化，评论源看内容和根因 |
| 卖家与店铺 | Seller 指标、storefront ASIN、last-seen | 卖家筛选和商品表现 | Keepa做店铺资产与变化，卖家精灵做市场表现 |
| 促销 | 历史价格、Deals、Lightning、Coupon | 当前价格和利润代理 | Keepa识别折扣真实性，内部利润确定可做价格 |

推荐建立三层事实体系：

1. **Keepa**：价格、排名、Offer、Buy Box、评分/评论数和榜单的历史验证。
2. **卖家精灵**：市场、产品、关键词、流量、评论和竞争情报。
3. **第一方及内部系统**：订单、广告、利润、库存、物流、退货和执行效果。

---

## 八、Keepa 无法单独补齐的数据

| 运营数据 | Keepa 能提供 | 仍需补充的数据源 |
|---|---|---|
| 真实销量与转化 | BSR、`salesRankDrops`、`monthlySold` 等代理信号 | Amazon SP-API、VC/SC、内部订单和 Sessions/CVR |
| 广告营销 | 无关键词广告活动、花费和归因 | Amazon Ads、Google、Meta、TikTok Ads |
| 评论 VOC | 评分和评论数历史 | 评论正文、Q&A、客服和退货原因 |
| 自有库存与补货 | Offer/Buy Box/Amazon 的部分 stock 快照 | ERP、WMS、FBA 库存、在途、库龄和预测 |
| 真实利润 | 价格、部分费用和尺寸重量 | 采购、头程、关税、平台结算、广告、退货和汇率 |
| 物流时效 | Buy Box 配送时长和履约标识 | 承运商、仓网、物流报价和真实签收数据 |
| 合规与风险 | 部分危险品/商品标识 | 专利、商标、认证、危险品审核和法规库 |
| 多平台趋势 | 少量 eBay 价格历史索引不等于多平台经营 | Walmart、eBay、TikTok Shop、Temu、独立站和社媒数据 |
| 供应链与采购 | 无供应商、MOQ、产能和质量数据 | 1688/Alibaba、SRM、质检和供应商履约 |

---

## 九、数据使用限制与风险

### 9.1 销量代理不等于真实订单

- Sales Rank 是排名，不是销量。
- `salesRankDrops` 是排名下降事件计数，不应直接一比一映射为订单。
- `monthlySold` 也不能替代卖家后台真实 Units；必须标记来源和口径。
- 用 Keepa 估算销量时，需要类目模型、时间窗口和第一方样本校准。

### 9.2 评论数不等于评论内容

Keepa 能记录评分值和评论数变化，但不能回答用户为什么好评或差评。产品缺陷、购买动机、场景和情感分析仍需要评论正文及其他 VOC 数据。

### 9.3 Offer 和库存存在快照边界

- 请求没有带 `offers`、Offer 拉取失败或数据未刷新时，缺失不能解释为零。
- `stockAmazon`、`stockBuyBox` 和 Offer stock 是外部观测快照，不是内部库存台账。
- Seller storefront 是扫描结果，官方说明可能不完整或过期。

### 9.4 时间、金额和缺失值不能直接读原始数字

- Keepa Time 常用从 2011-01-01 起计算的分钟数，当前统一派生 UTC 时间。
- 金额通常以站点最小货币单位返回；JPY 等币种小数位不同。
- Rating 常以乘 10 的整数出现，需要按字段转换。
- `-1`、`0`、`null` 和字段缺失语义不同，不能统一填 0。
- XLSX 派生金额、时间和中文表头用于阅读，后端核对应以原始响应和官方口径为准。

### 9.5 Token、分页和结果规模

- Product Search 官方 Token Cost 为 10，单个搜索词最多 20 条，且不含 sponsored content。
- Product Finder 有单独的基础、分页和 `stats=1` 成本；不能按本地保守估算值替代官方账单。
- Product 普通最多 100 个 item，带 Offers 最多 20 个。
- Category Lookup 单次最多 10 个 ID；Seller 最多 100 个 ID，但 storefront 模式不能批量 seller。
- MCP 公共结果只预览最多 20 行，完整结果应读取 XLSX。

官方接口参考：

- [Product Search](https://keepa.com/#!discuss/t/product-searches/109)
- [Product Finder](https://keepa.com/#!discuss/t/product-finder/5473)
- [Best Sellers](https://keepa.com/#!discuss/t/best-sellers/1298)
- [Seller Information](https://keepa.com/#!discuss/t/seller-information/790)

---

## 十、推荐建设顺序

| 阶段 | 建设重点 | 验收结果 |
|---|---|---|
| 第一阶段 | ASIN 历史情报、Buy Box/Offer 竞争、Product Finder 机会筛选 | 从原始查询升级为可解释的商品和竞品历史报告 |
| 第二阶段 | 类目榜单、卖家店铺和促销跟踪 | 建立周期快照、变化检测和预警 |
| 第三阶段 | Keepa × 卖家精灵交叉校验 | 统一 ASIN、父子体、类目、时间和第三方估算可信度 |
| 并行建设 | 第一方订单、广告、库存、利润、退货和物流 | 用真实经营结果校准 Keepa 代理信号并形成执行闭环 |

下一轮真实数据验证建议按以下顺序执行：

1. 选一个有较长历史、多个 Offer 和变体的 ASIN，验证 `product + stats + offers + buybox`。
2. 用一个明确类目跑 Product Finder `stats=1`，检查 ASIN、`totalResults` 和 Search Insights 完整率。
3. 用同一类目跑 Best Sellers，再批量补 Product，验证榜单顺序与商品历史。
4. 用一个竞品 seller 跑 storefront，核对 ASIN 和 last-seen 时效。
5. 跑 Deals 与 Lightning Deals，检查折扣、活动时间和当前指标口径。
6. 将同一 ASIN 的 Keepa、卖家精灵和内部订单按日期对齐，确定哪些指标可以进入正式评分模型。

---

## 十一、证据索引

| 证据主题 | 文件与行号 |
|---|---|
| 10 个正式场景和接口 | `opscli/keepa/api/scenarios.py:238-329` |
| Product 参数与批量限制 | `opscli/keepa/api/scenarios.py:83-123` |
| Search、Finder、Category、Seller 参数 | `opscli/keepa/api/scenarios.py:126-191` |
| 场景原始结果抽取与格式化分发 | `opscli/keepa/services/api_manager.py:274-459` |
| Product 和 36 种历史序列 | `opscli/keepa/product_formatter.py:22-149,151-225` |
| Offer 和变体明细 | `opscli/keepa/product_formatter.py:272-354` |
| Stats、Buy Box 和 Offer 快照 | `opscli/keepa/stats_formatter.py:48-140,151-398` |
| Product Finder Search Insights | `opscli/keepa/search_insights_formatter.py:9-171` |
| Best Sellers 格式化 | `opscli/keepa/best_sellers_formatter.py` |
| Deals 格式化 | `opscli/keepa/deal_formatter.py:14-230` |
| 格式化接入状态 | `opscli/keepa/reference/FORMATTERS_STATUS.md` |
| 公开 MCP 工具和预览限制 | `opscli/mcp/tools/keepa.py:1-22,83-231` |
| 当前 Skill 场景与口径 | `opscli/skills/templates/ops-keepa/SKILL_MCP.md:112-125` |
| 官方接口限制摘录 | `opscli/skills/templates/ops-keepa/references/OFFICIAL.md:7-51` |

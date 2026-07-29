# Sorftime 数据能力与业务场景调研

> **文档定位**：盘点本地 `sorftime-cli` Skill 包及 Sorftime 官方 API/CLI 页面，判断其对跨境电商全链路数据地图的补充价值，并给出接入优先级与验收边界。
> **盘点日期**：2026-07-21
> **本地基线**：`C:\Users\AuGroup\Downloads\sorftime-cli`
> **验证状态**：已完成文档、字段和辅助脚本静态审阅；尚未使用真实 Account-SK 调用接口，未确认当前账号权限、套餐、余额、实时完整率和数据精度。

---

## 一、结论摘要

Sorftime 值得进入后续数据源候选，但不建议首先重复接入 Amazon 的基础商品、类目和关键词查询。相较已经接入的卖家精灵与 Keepa，它最有价值的增量是：

1. **多平台商品与市场数据**：Shopee、Walmart、Temu、TikTok 的类目、商品、店铺和趋势，可直接补当前 S17 多平台扩张空白。
2. **TikTok 内容电商数据**：商品、店铺、达人、视频、标签、带货销量/销售额代理及互动指标，可补 S01 趋势热点、S13 站外营销和 S17 多平台扩张。
3. **1688 货源线索**：标题、图片、价格、批发阶梯、店铺、服务评分、30 日销量、复购率和发货地，可补 S08 供应商采购与 S09 成本初筛，但仍不是完整供应商管理数据。
4. **Amazon 评论 API 链路**：外部服务完成实时采集、状态查询和评论读取。由于卖家精灵浏览器插件不纳入服务端处理，该能力可作为独立候选数据源；是否使用必须先通过合规、授权、成本和完整率验收。
5. **Amazon 持续监控**：关键词排名、Best Seller 榜单、跟卖/Buy Box/库存监控字段较具体，但积分消耗高且文档称结果最多保留 30 日，只适合精选对象，不适合无边界全量采集。

建议第一批只验证 `TikTok 内容趋势`、`多平台市场对比`、`1688 货源搜索` 三组独有能力；Amazon 基础数据继续以卖家精灵和 Keepa 为主。

---

## 二、来源与能力范围

### 2.1 官方页面确认

Sorftime 官方页面将 API/CLI 定位为结构化原始数据服务，并列出产品、类目市场、关键词和数据监控能力；官方 CLI 页面说明 CLI 与 API 的方法名、请求参数和返回结构一致：

- [Sorftime 官方 API 页面](https://www.sorftime.com/zh-CN/api)
- [Sorftime 官方 CLI 页面](https://www.sorftime.com/zh-CN/cli)

官方页面还展示了 Shopee、Walmart、TikTok 等平台的数据服务范围，因此“多平台”不是仅由本地 Skill 推测出的能力。

### 2.2 本地 Skill 包结构

本地目录不是 `sorftime-cli` npm 包源码，而是一套面向 Agent 的 Skill 文档、接口字段说明和辅助脚本：

```text
sorftime-cli/
├── SKILL.md
├── README.md
├── resources/    # 接口、字段、Domain、错误码与用例
└── scripts/      # 调用、批量、缓存、监控、趋势等包装脚本
```

真实请求仍由全局 npm CLI 执行：`sorftime api <Endpoint> '<json>' --domain <N> --profile <name>`。辅助 Python 脚本通过 `subprocess` 调用 `sorftime`，自身不实现 HTTP API 客户端，也不持有 Account-SK。

### 2.3 文档宣称的接口规模

| 平台 | Skill 宣称数量 | 主要能力 |
|---|---:|---|
| Amazon | 47 | 类目、商品、实时采集、关键词、评论、关键词/榜单/跟卖监控 |
| Shopee | 13 | 类目、商品、趋势、店铺、关键词和词库 |
| Walmart | 14 | 类目、商品、趋势、销量、关键词和词库 |
| 1688 | 1 | 按名称搜索货源 |
| Temu | 9 | 类目、商品、趋势、店铺 |
| TikTok | 14 | 类目、商品、趋势、店铺、达人、视频和标签 |
| 合计 | 98 | Skill 总览宣称值 |

该数量不能直接作为接入范围，原因见第七节的文档漂移与实现风险。

---

## 三、平台数据能力地图

### 3.1 Amazon

| 能力组 | 关键接口 | 关键数据 | 主要业务场景 | 与现有能力关系 |
|---|---|---|---|---|
| 类目与趋势 | `CategoryRequest`、`CategoryProducts`、`CategoryTrend` | Best Seller、类目热销商品、最长两年回看、销量/价格/集中度等趋势 | S01、S02、S06 | 与卖家精灵选市场、Keepa 榜单重合较多；趋势指标可抽样补充 |
| 商品与变体 | `ProductRequest`、`ProductSearch`、`AsinSalesVolume`、`ProductVariationHistory` | 当前商品、销量/销额/价格/BSR/Deal/Coupon 趋势、Amazon 公布销量、变体变化 | S04、S06、S14、S18 | 基础历史与 Keepa 重合；公布销量和变体变化可作为校验源 |
| 评论 | `ProductReviewsCollection`、状态查询、`ProductReviewsQuery` | 评论正文、星级、时间、VP、变体、Helpful、图片和视频 | S05、S07、S11、S16 | 独立的服务端候选数据源；不承接卖家精灵插件数据，需单独合规和完整率验收 |
| 关键词 | `KeywordRequest`、`KeywordExtends`、`CategoryRequestKeyword`、`ASINRequestKeywordv2` | 搜索量、排名、趋势、CPC、转化代理、Top 3 份额、自然/广告位置 | S03、S11、S12、S13 | 与卖家精灵高度重合；不作为首批接入方向 |
| 搜索结果趋势 | `KeywordSearchResults`、`KeywordSearchResultTrend` | 搜索页商品、销量/销售额、商品/品牌/卖家数、均价和评论门槛趋势 | S02、S03、S04、S12 | 可形成“关键词市场结构趋势”，但成本较高，先做样本比较 |
| 关键词排名监控 | `KeywordBatchSubscription` 等 5 个接口 | PC/手机、地区、前 1/3/5/7 页、自然/广告位置和完整搜索结果商品 | S11、S12、S13 | 比卖家精灵前 50 监控范围更灵活，但积分成本和 30 日保存是硬约束 |
| 榜单监控 | `BestSellerListSubscription` 等 4 个接口 | Best Sellers、New Releases、Most Wished For、Gift Ideas 定时快照 | S01、S02、S04、S12、S18 | Keepa 可提供榜单和历史；只有更高频或榜单类型更全时才有增量 |
| 跟卖与库存监控 | `ProductSellerSubscription` 等 5 个接口 | 卖家、Buy Box、FBA/FBM、价格、库存和限购，最多前 30 个卖家 | S04、S14、S15、S18 | 可补具体库存/限购监控；需与 Keepa Offer 历史比较准确度与成本 |

Amazon 商品摘要还包含售价、Coupon 后售价、月销量/销额估算、卖家数、FBA、A+、视频、品牌店、尺寸重量、FBA 费和平台佣金等字段。利润和销量仍属于第三方估算或平台公布代理，不能替代第一方销售与财务事实。

### 3.2 Shopee

覆盖 8 个站点 Domain，文档包含：

- 类目树、Top 500 类目商品和近两年类目趋势。
- 商品详情、名称搜索、商品趋势和多条件商品筛选。
- 店铺类型、本土/跨境店、Top 500 商品数、销量和销额。
- 搜索量、搜索排名、CPC、旺季、关键词关联商品和词库。

商品侧可提供 7/30 日销量、销量环比、累计销量、价格、店铺类型、本土/跨境属性、评分、好差评率和变体数，主要补 S02、S04、S06、S14、S17。

### 3.3 Walmart

仅美国站，主要提供：

- 类目树、类目 Best Seller Top 80。
- 商品详情、产品趋势、官方公布销量。
- 关键词搜索、关键词详情、商品反查词、延伸词、搜索结果和词库。

Walmart 的核心价值是直接填补 S17 的商品、类目和关键词数据，而不是增强 Amazon。

### 3.4 Temu

覆盖美国和欧洲两个 Domain，主要字段包括：

- 类目 Top 100/Top 600 销量份额、月销环比、销额、价格、评论门槛、品牌/卖家集中度和新品占比。
- 商品月销量、销额、环比、价格、全托管/半托管、评论、星级和上架时间。
- 商品销量/销额/价格/评论/星级趋势，以及店铺的 Top 500 商品表现。

Temu 可直接支撑 S01、S02、S04、S06、S14、S17，尤其适合验证托管模式、新品和类目集中度。

### 3.5 TikTok Shop

覆盖美国、马来西亚、菲律宾、越南、泰国、印度尼西亚、英国和日本；达人、视频和标签三个接口仅限美国站。

| 对象 | 关键字段 | 可支撑场景 |
|---|---|---|
| 类目 | 周/月销量与销额、环比、均价、评论、店铺数、Top 10 商品/卖家集中度、新品占比 | S01、S02、S06、S17 |
| 商品 | 周/月/累计销量与销额、价格、评分、发货地、达人数量、带货视频数量 | S04、S06、S14、S17 |
| 商品趋势 | 销量、销额、价格、评论、星级、新增视频和新增达人趋势 | S01、S04、S13、S14、S17、S18 |
| 店铺 | 粉丝、商品数、销量/销额、评分和经营类目 | S04、S14、S17 |
| 达人 | 粉丝与 30 日增长、内容量、带货商品、近 15 视频播放/互动、类目、MCN/店铺关系 | S01、S13、S17 |
| 视频 | 播放、点赞、评论、分享、互动率、预估带货销量/销额和关联商品 | S01、S13、S17 |
| 标签 | 相关视频数、月播放、月点赞、新标签、关联商品数和类目 | S01、S13、S17 |

TikTok 的销量和销额应按第三方估算处理，不能等同 TikTok Shop 第一方订单或广告归因。

### 3.6 1688

`ProductSearchFromName` 最多返回 100 条货源，字段包括标题、图片、链接、价格、店铺、服务评分、上架日期、30 日销量、批发阶梯、复购率、发货地、评论、评分和 SKU 数。

这可以形成“货源线索与采购价代理”，但缺少 MOQ 之外的正式询报价、产能、交期、良率、质检、合同和履约数据，因此不能直接把 S08 标记为完整覆盖。

---

## 四、建议新增的业务场景

| 优先级 | 场景 | Sorftime 数据 | 对应环节 | 推荐理由 |
|---|---|---|---|---|
| P0 | `cross-platform-market-intelligence` 多平台市场机会 | Shopee/Walmart/Temu/TikTok 类目、商品、店铺和趋势 | S01、S02、S04、S06、S17 | 当前卖家精灵和 Keepa 以 Amazon 为主，这是最明显的独有增量 |
| P0 | `tiktok-commerce-trend` TikTok 内容电商趋势 | 类目、商品趋势、达人、视频、标签 | S01、S04、S13、S17 | 把搜索趋势扩展为内容热度、达人传播和带货代理 |
| P0 | `sourcing-lead-search` 1688 货源线索 | 名称搜索、价格、批发阶梯、店铺、服务评分、销量和复购率 | S08、S09 | 可快速验证供给可得性和采购价区间，但不代替供应商管理 |
| P1 | `amazon-review-voc-provider` Amazon 评论 VOC 外部数据源 | 评论采集、任务状态、评论正文/媒体/变体 | S05、S07、S11、S16 | 独立于卖家精灵浏览器插件；上线前必须通过合规、授权、完整率和成本验收 |
| P1 | `amazon-search-rank-monitoring` Amazon 搜索排名监控 | 关键词、地区、设备、自然/广告位置和搜索结果商品 | S11、S12、S13 | 比“前 50 商品”限制更灵活，但只监控精选关键词并设置积分上限 |
| P1 | `amazon-seller-stock-monitoring` 跟卖与库存监控 | Seller、Buy Box、FBA/FBM、价格、库存和限购 | S04、S14、S15、S18 | 与 Keepa Offer 历史做样本对比后决定是否接入 |
| P2 | `cross-platform-product-match` 跨平台同款与价差 | 各平台名称搜索、商品详情、图片和 1688 货源 | S04、S06、S09、S17 | 文档模板只有“按名称搜索”，需增加图片/属性匹配与置信度，不能直接认定同款 |

### 不建议优先接入

- Amazon 基础商品详情、BSR、价格和 Offer 历史：Keepa 已有更强历史能力。
- Amazon 常规选产品、选市场和关键词挖掘：卖家精灵已经覆盖主要决策字段。
- 词库管理：属于运营资产管理，不是新的外部数据能力。
- 全量高频监控：积分成本与数据保存期限不适合无边界抓取。

---

## 五、与卖家精灵、Keepa 的分工

| 数据源 | 推荐事实层 | 最适合承担 | 不应承担 |
|---|---|---|---|
| 卖家精灵 | Amazon 市场与搜索竞争情报 | 选品、市场、关键词、流量、Listing 和 ABA 代理 | 真实订单、广告、库存、利润和多平台经营 |
| Keepa | Amazon 商品历史事实/代理 | 价格、BSR、Offer、Buy Box、促销、变体和榜单历史 | 搜索需求、评论正文、广告活动和多平台数据 |
| Sorftime | 多平台外部情报与精选监控 | Shopee/Walmart/Temu/TikTok/1688、TikTok 内容、Amazon 评论与监控候选 | 自有订单、真实广告归因、ERP 库存、供应商履约和完整财务利润 |

同一 Amazon 字段若三方都提供，应先通过 30—100 个 ASIN 的样本对照确定主数据源、更新时间、空值、历史深度、成本和偏差，再决定是否保留备用源。

---

## 六、调用与成本边界

- Domain 覆盖：Amazon 14 站、Shopee 8 站、Walmart 1 站、Temu 2 站、1688 1 站、TikTok 8 站；不同接口有站点例外。
- 通用限流：本地文档写明单 profile 不超过 200 QPM。
- 商品详情通常最多一次 10 个 ASIN；不同接口还存在 20/30/100 个对象上限。
- 关键词监控示例中，“每天 24 小时、每小时、前 3 页”每周消耗 504 积分，日本站为 1008。
- Best Seller Top 100/200/300/400 每天分别消耗 10/20/30/40 积分。
- 跟卖监控每个 ASIN 每次 2 积分，日本站 4；查库存额外加积分。
- 实时商品、图搜相似和评论采集使用积分并采用异步状态查询。
- 文档称监控结果最多保存 30 日，因此必须由本系统持续落库才能形成更长历史。

上述数值均来自本地 Skill 文档，正式采购前需要在当前 Sorftime 控制台重新确认套餐和计费规则。

---

## 七、Skill 包质量与接入风险

### 7.1 明显的版本与数量漂移

- `SKILL.md` 写 npm 包版本 `0.1.1` 和 98 个 endpoint；官方 CLI 页面展示“全新发布 v1.0”。
- `README.md` 仍写 66 个接口，仅列 Amazon、Shopee 和 Walmart。
- `SKILL.md` 写 Shopee 13 个 endpoint，但同一表格实际列出 15 个名称，`shopee-api.md` 也有 15 个编号章节。

因此不能把 Skill 中的总数直接固化为生产契约；接入前应从当前 CLI 或官方接口控制台生成真实 endpoint 清单。

### 7.2 辅助脚本错误码映射与文档冲突

本地 `resources/_common.md` 的 Amazon 错误码定义为：

- `4`：积分不足
- `97`：ASIN 不存在
- `98`：采集失败
- `401`：接口未开放
- `500`：月请求量耗尽

但 `scripts/_sf_lib.py` 将 `4` 解释成参数错误、`97` 解释成配额耗尽、`98` 解释成接口未授权。这会导致错误恢复策略和用户提示错误，正式复用辅助脚本前必须修正并按平台维护错误码表。

### 7.3 监控历史说明冲突

`amazon-monitoring.md` 写所有监控结果最多保存 30 日；`amazon-monitoring-bestseller.md` 又称榜单查询最长两年。接入前必须用真实任务确认“平台保存期限”和“queryDate 可查询跨度”的实际口径。

### 7.4 未做实时权限与数据质量验证

本轮没有配置或使用 Account-SK，以下均未确认：

- 当前安装的 CLI 版本及实际 endpoint 列表。
- 当前账号已开通的平台、站点、月请求量和积分。
- 响应大小、分页、压缩、编码和字段空值。
- 销量、销额、CPC、转化、利润和带货数据的估算方法与准确度。
- 评论实时采集的深度、增量去重、变体覆盖和合规边界。

---

## 八、推荐验收顺序

1. **契约预检**：确认 CLI 当前版本、`whoami`、余额、已开放 endpoint 和 Domain。
2. **独有能力小样本**：各取 1 个 TikTok 类目/商品/达人/视频、1 个 Temu/Shopee/Walmart 类目、3—5 个 1688 搜索词。
3. **跨源对照**：对 Amazon 30—100 个 ASIN 比较 Sorftime、卖家精灵与 Keepa 的价格、销量代理、BSR、变体和更新时间。
4. **成本压测**：记录每个 endpoint 的 request/积分消耗、耗时、分页和空值率。
5. **评论合规验收**：先确认授权和数据使用边界，再评估正文、媒体、变体、历史深度与去重。
6. **监控试运行**：只选少量关键词、榜单和 ASIN，运行 7—14 天后评估稳定性与单位成本。
7. **再决定接入形态**：生产系统优先建设统一 Provider Adapter；本地 Skill 脚本可作验证工具，不直接作为长期数据契约。

---

## 九、证据索引

以下本地路径均相对于 `C:\Users\AuGroup\Downloads\sorftime-cli`：

| 证据 | 文件位置 |
|---|---|
| Skill 总览、平台和接口清单 | `SKILL.md:1-4,170-220` |
| CLI 调用、Domain、错误码、限流 | `resources/_common.md:7-18,32-108,112-295` |
| Amazon 商品、评论、订阅 | `resources/amazon-product.md:11-312` |
| Amazon 类目与趋势 | `resources/amazon-category.md:7-188` |
| Amazon 关键词 | `resources/amazon-keyword.md:10-290` |
| Amazon 监控成本与保存 | `resources/amazon-monitoring.md:26-135` |
| Amazon 字段字典 | `resources/amazon-data-types.md:45-423` |
| Shopee 接口与字段 | `resources/shopee-api.md:10-361`、`resources/shopee-data-types.md:23-205` |
| Walmart 接口与字段 | `resources/walmart-api.md:10-102`、`resources/walmart-keyword.md:10-190` |
| 1688 货源字段 | `resources/1688-api.md:11-52` |
| Temu 接口与字段 | `resources/temu-api.md:14-200`、`resources/temu-data-types.md:23-133` |
| TikTok 接口与字段 | `resources/tiktok-api.md:14-340`、`resources/tiktok-data-types.md:23-234` |
| Python 调用、重试和错误映射 | `scripts/_sf_lib.py:73-121,175-376` |

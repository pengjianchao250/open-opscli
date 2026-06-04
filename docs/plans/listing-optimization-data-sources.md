# Listing 优化服务数据源 TODO

## 接入分期

| 分期 | 数据源 | 目标 | 接入方式 |
| --- | --- | --- | --- |
| MVP | Amazon Listing、Amazon Search、Amazon Review、Amazon Q&A、Google Trends、Reddit、SellerSprite | 跑通 Listing Audit 和关键词/竞品证据链 | 复用现有 MCP/公开数据/服务端账号 |
| 增强版 | Amazon PA API、TikTok Creative Center、AliExpress、eBay、Walmart | 补充趋势、供应链、跨平台价格与素材信号 | 申请账号或轻量采集 |
| 商业版 | Keepa、Rainforest、DataForSEO、Oxylabs、TikTok Shop、Temu | 降低维护成本并补齐历史/销量/平台级数据 | 采购商业 API 或企业代理服务 |

## MVP 数据源

### SellerSprite

- 价值：关键词挖掘、关键词反查、竞品、流量来源、市场研究。
- 现状：已有 `seller_sprite_*` MCP tools，服务端托管账号。
- 接入事项：确认 OPS 后端集成账号可用；确认默认站点、周期、导出格式；补齐 listing intelligence 对 seller_sprite 场景的调用映射。
- TODO：
  - 将 `keyword-miner` 映射到关键词机会、标题 SEO、Bullet 词库。
  - 将 `keyword-reverse` 映射到 ASIN 反查和竞品词覆盖。
  - 将 `traffic-source` 映射到流量来源判断。
  - 将 `competitor-lookup` / `product-research` 映射到竞品池。
  - 在 MCP Skill 中要求首次先读规范，避免直接猜参数。

### Amazon Listing

- 价值：标题、Bullet、A+、图片、价格、评分，是 Listing Audit 主体。
- 接入事项：不需要账号；需要稳定页面采集能力；Amazon 反爬强，优先复用现有 `opscli.amazon` 能力。
- TODO：
  - 确认现有 `amazon_*` MCP tools 是否启用或仍处于注册关闭状态。
  - 标准化字段：title、bullets、description、a_plus、images、price、rating、review_count。
  - 建立 ASIN 输入校验和站点 URL 规则。
  - 图片分析先只输出图片 URL/数量/位置，不做 OCR。

### Amazon Search

- 价值：关键词排名、广告位、竞品 ASIN、价格带、评分带。
- 接入事项：不需要账号；反爬强；一期只抓前 1-2 页，避免大批量。
- TODO：
  - 标准化字段：keyword、rank、asin、title、price、rating、review_count、sponsored、badges。
  - 支持按关键词生成竞品候选池。
  - 和 SellerSprite keyword-miner 结果做交叉验证。

### Amazon Review

- 价值：用户痛点、购买动机、差评聚类、转化障碍。
- 接入事项：不需要账号；反爬强；一期只取前几页或外部工具返回数据。
- TODO：
  - 标准化字段：star、title、body、date、country、verified、variant。
  - 建立正/负向主题聚类输入格式。
  - 不做全量历史评论抓取。

### Amazon Q&A

- 价值：购买前顾虑、FAQ、缺失信息。
- 接入事项：不需要账号；可和 Listing 页面采集一起做。
- TODO：
  - 标准化字段：question、answer、answered_by、date。
  - 映射到购买障碍和 Listing 信息缺口。

### Google Trends

- 价值：关键词趋势、季节性、地区热度。
- 接入事项：通常不需要账号；可先通过 Python 库或人工数据导入，后续再固化服务。
- TODO：
  - 确认是否允许引入 `pytrends` 或改走后端接口。
  - 标准化字段：keyword、time_range、region、interest_over_time、interest_by_region。
  - 输出季节性结论时必须带时间范围。

### Reddit

- 价值：真实需求、吐槽、JTBD、用户语言库。
- 接入事项：公开数据可抓；正式 API 需要 Reddit developer app。
- 账号申请：
  - 创建 Reddit 账号。
  - 在 Reddit Apps 创建 developer application。
  - 获取 `client_id`、`client_secret`、`user_agent`。
- TODO：
  - 标准化字段：subreddit、title、body、score、comments、created_at、url。
  - 建立关键词到 subreddit 的搜索策略。
  - 区分用户原话和 AI 总结，避免伪造引用。

## 增强版数据源

### Amazon PA API

- 价值：官方商品基础信息、图片、价格、品牌。
- 账号申请：Amazon Associate 账号；满足联盟 API 使用门槛；申请 PA API key。
- TODO：确认调用额度；确认是否能覆盖目标站点；只作为官方字段校验源，不替代搜索/评论洞察。

### TikTok Creative Center

- 价值：热门广告、素材、达人、趋势。
- 账号申请：TikTok 账号；必要时申请 Business/Ads 相关权限。
- TODO：先接 Creative Center 趋势与广告素材；不碰 TikTok Shop 交易数据。

### AliExpress

- 价值：供应链价格、销量、评论、变体。
- 接入事项：公开页面采集；维护成本中等。
- TODO：建立同款/相似款检索；标准化 price、sales、rating、reviews、shipping。

### eBay

- 价值：历史成交价格和二手/清仓价。
- 接入事项：部分数据可公开，正式 API 需要 eBay developer account。
- TODO：优先接 sold/completed 价格信号；作为价格带参考，不作为 Amazon 成交依据。

### Walmart

- 价值：美国本土竞品、价格、评论。
- 接入事项：公开页面采集或商业 API；维护成本中等偏高。
- TODO：用于美国市场横向竞品校验。

## 商业版数据源

### Keepa

- 价值：Amazon BSR 历史、价格历史、Review 变化、BuyBox。
- 账号申请：Keepa API 付费账号，获取 API key。
- TODO：作为历史趋势主数据源；明确 token 成本预算。

### Rainforest

- 价值：Amazon Search/Product/Review API，减少爬虫维护。
- 账号申请：Rainforest API 账号和 key。
- TODO：替换高风险 Amazon 采集链路；评估成本和字段覆盖。

### DataForSEO

- 价值：Amazon/Google 关键词、搜索量、趋势。
- 账号申请：DataForSEO 账号和 API key。
- TODO：补关键词搜索量和 Google 侧搜索意图。

### Oxylabs

- 价值：企业级采集代理，覆盖 Amazon、TikTok、Temu、Walmart。
- 账号申请：Oxylabs 企业账号。
- TODO：只在自建爬虫稳定性不足时采购。

### TikTok Shop

- 价值：销量、商品、达人、视频种草。
- 接入事项：反爬和登录依赖强。
- TODO：商业版再接，优先通过第三方 API 或企业采集服务。

### Temu

- 价值：供应链价格、销量、评论。
- 接入事项：Cloudflare 和动态接口维护成本高。
- TODO：商业版再接，避免一期消耗研发资源。

## 当前项目骨架任务

- 新增 `opscli/amazon_listing_intelligence` 服务模块，先承载数据源目录、分析目标和接入计划。
- 新增 `amazon_listing_intelligence_*` MCP tools，先开放规范读取、数据源清单、接入计划生成。
- 新增 `ops-amazon-listing-intelligence` MCP Skill，指导 Agent 如何组合 SellerSprite、Amazon、Google Trends、Reddit。
- 后续真实取数优先复用现有 `seller_sprite_*` MCP tools，再按数据源分期补充外部能力。

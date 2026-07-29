# 西柚找词项目实现与 OpenAPI 数据能力调研

**文档版本**：v0.2
**调研日期**：2026-07-21
**适用范围**：当前 `open-opscli` 西柚实现为主，西柚洞察 OpenAPI v2 官方公开文档作为扩展参考
**关联文档**：[跨境电商全链路数据能力地图](./跨境电商全链路数据能力地图.md)、[卖家精灵数据能力与业务场景实测](./卖家精灵数据能力与业务场景实测.md)、[Keepa 数据能力与业务场景梳理](./Keepa数据能力与业务场景梳理.md)

---

## 零、当前项目实现基线

### 0.1 判定结论

当前项目已经实现西柚洞察直连，不应再标记为“尚未实现的 OpenAPI 候选”。现有实现与公开 OpenAPI 是两条不同通道：

| 通道 | 当前项目状态 | 鉴权与接口特征 | 定位 |
|---|---|---|---|
| 项目现有西柚直连 | Provider、Client、任务、导出、CLI/MCP 包装均已实现；主入口暂关闭 | 使用西柚网页业务凭据 `authorization/cookie`，调用 `/v2`、`/v3`、`/v4` 页面业务接口和 resource 导出 | 当前代码能力基线 |
| 西柚公开 OpenAPI v2 | 当前 `opscli/xiyou` 未按此契约实现 | `X-Auth-Version: 2.0` + `X-Api-Key`，业务路径为 `/v1/...` | 后续补充独有字段或替换网页接口的候选 |

因此本文后续 18 个 OpenAPI 接口不能再代表“西柚当前全部能力”，只能用于判断公开 API 相对项目现有实现还有什么增量。

### 0.2 项目已实现的功能

项目注册 9 个顶层 function；其中 `ranking` 包含 4 个常用榜单意图，合计可形成 12 类直接业务调用。

| function | 已实现意图/视图 | 关键输入 | 输出模式 | 支撑环节 |
|---|---|---|---|---|
| `ranking` | ASIN 流量榜、ASIN 暴增榜、关键词 ABA 榜、搜索暴增榜 | target、site、period、rank pattern | JSON/XLSX 行数据 | S01、S02、S03、S04、S06 |
| `reverse-keyword` | ASIN 反查关键词；数据、趋势、Top 10 视图；自然/广告词筛选 | asin、周期、view mode、keyword type | 西柚 resource 全量 XLSX 或 JSON 资源元数据 | S03、S04、S11、S12、S13 |
| `asin-compare` | 多 ASIN 数据/Top 10 对比；自然/广告词筛选 | 至少 2 个 ASIN、周期 | resource 全量导出 | S03、S04、S06、S11、S12、S13 |
| `keyword-analysis` | 关键词对应商品的数据/趋势分析 | keyword、周期、view mode | JSON 列表或 resource XLSX | S02、S03、S04、S06 |
| `keyword-explorer` | 以词找词、关键词扩展 | keyword、周期 | resource 全量导出 | S01、S03、S06、S11 |
| `keyword-historical-traffic` | 关键词历史自然流量分析 | keyword、起止日期 | JSON/XLSX 行数据 | S01、S03、S12、S14 |
| `keyword-ad-replay` | 指定日期关键词广告放映机 | keyword、report date、replay type | resource 全量导出 | S04、S12、S13 |
| `keyword-organic-replay` | 指定日期关键词自然放映机 | keyword、report date、replay type | resource 全量导出 | S03、S04、S11、S12 |
| `keyword-ad-toppers` | 关键词广告金主榜 | keyword | resource 全量导出 | S04、S12、S13 |

项目支持 13 个站点：`US、CA、MX、BR、DE、UK、FR、IT、ES、JP、AE、SA、AU`；默认 `US`、第一页、50 条。resource 导出任务会提交 `resourceId`、轮询状态、下载西柚生成的 XLSX，并记录真实行数、任务参数、原始响应和导出链接。

### 0.3 工程实现与当前开放状态

| 层级 | 状态 | 证据与说明 |
|---|---|---|
| API Client/Provider | 已实现 | `opscli/xiyou/api`、`opscli/xiyou/services/api_manager.py` |
| 凭据管理 | 已实现 | 可从 OPS 集成账号接口取得最新凭据并缓存；支持过期检测和企微补登通知 |
| 任务与导出 | 已实现 | 生成 `params.json`、`raw.json`、`result.json`，支持 JSON/XLSX 和文件上传 |
| CLI 包装 | 已实现但未注册 | `opscli/xiyou/cli.py` 完整；`opscli/cli.py` 当前注释掉 `app.add_typer(xiyou_app)` |
| MCP 包装 | 已实现但未注册 | `xiyou_scenarios/run/job_status/export` 已存在；主 MCP Server 当前注释掉注册 |
| quota | 关闭 | `configs/mcp-quota.json` 中 `xiyou_run.enabled=false` |
| 当前 Agent 可调用性 | 不可用 | MCP 契约测试明确要求隐藏 SIF/西柚工具 |

准确状态是：**项目代码已实现、当前服务入口暂关闭、尚未计入正式对外可调用场景**。恢复入口后应先做真实账号冒烟和字段验收，再改为“正式接入”。

### 0.4 项目内部文档漂移

`ops-xiyou/SKILL.md` 的 Intent Map 目前只列出 `ranking`、`reverse-keyword`、`asin-compare`、`keyword-analysis`、`keyword-explorer`，遗漏代码已经实现的：

- `keyword-historical-traffic`
- `keyword-ad-replay`
- `keyword-organic-replay`
- `keyword-ad-toppers`

后续恢复入口时应以 `opscli/xiyou/api/scenarios.py` 和 `XiyouApiManager.scenarios()` 为真实场景注册表，同步更新 Skill，避免 Agent 看不到已实现能力。

---

## 一、公开 OpenAPI 扩展结论

西柚找词 OpenAPI 当前公开 **18 个 v2 可调用的业务接口**，分为 `asins`、`asinSearchTerms`、`searchTerms` 三组；另有一个仅适用于 v1 的余额接口。官方目录与逐接口页面见 [LLMs.txt](https://openapi-doc.xydc.com/llms.txt)。

它与卖家精灵、Keepa 的基础商品、BSR、价格、关键词反查和 ABA 指标存在明显重叠，但仍有四类值得优先验证的增量：

1. **ASIN 整体自然/广告流量得分与增长**：包括自然、广告、总流量得分、覆盖关键词数量、上周对比和流量占比。[官方接口](https://openapi-doc.xydc.com/312439564e0)
2. **ASIN × 关键词 × 展示位置的日级流量趋势**：可区分 `or`、`sp`、`sb`、`sbv`、`oor`、`sor` 等位置，并返回自然/广告流量和流量获取率。[官方接口](https://openapi-doc.xydc.com/327911125e0)
3. **ASIN × 关键词的日级和小时级排名轨迹**：返回不同展示位置的页码、页内排名和总排名；小时接口单次限定一天。[日级接口](https://openapi-doc.xydc.com/329420765e0)、[小时级接口](https://openapi-doc.xydc.com/332071833e0)
4. **竞品广告活动变动**：按日返回新增/移除的广告活动 ID、名称和 `sp` 等活动类型，适合形成竞品投放启停监控。[官方接口](https://openapi-doc.xydc.com/326115660e0)

因此，公开 OpenAPI 不应作为“另一套商品基础库”整体重复接入。应先与项目现有 9 个 function 做逐字段差异分析，只对现有网页直连无法稳定提供的日/小时词—品排名、竞品广告活动变化等接口做小样本 POC；商品基础、价格、BSR 和变体仍优先复用 Keepa，通用关键词需求和 ABA 能力先与卖家精灵及项目现有西柚场景逐字段、逐成本比较。

> **重要口径**：官方接口把部分字段命名为 `traffic`、`trafficScore`、`orders`，但公开文档没有披露估算模型、数据来源、置信区间或与 Amazon 第一方指标的校准方法。因此本文将它们视为第三方情报指标，不将其解释为 Amazon Ads 真实点击/花费/订单或卖家后台实际流量。这是基于官方字段说明缺少方法论的审慎判断，不是官方质量结论。[流量得分示例](https://openapi-doc.xydc.com/312439564e0)、[月订单量示例](https://openapi-doc.xydc.com/328160994e0)

---

## 二、接入与认证

### 2.1 v2 接入方式

| 项目 | 官方约定 | 来源 |
|---|---|---|
| 服务地址 | `https://openapi.xydc.com` | [v2 接入指引](https://openapi-doc.xydc.com/) |
| 业务路径 | 继续使用 `/v1/...`，通过请求头切换到 v2 鉴权 | [v2 接入指引](https://openapi-doc.xydc.com/) |
| 鉴权头 | `X-Auth-Version: 2.0`、`X-Api-Key: <API Key>` | [v2 接入指引](https://openapi-doc.xydc.com/) |
| 内容类型 | `Content-Type: application/json`，UTF-8 | [v2 接入指引](https://openapi-doc.xydc.com/) |
| v1 差异 | v2 不再传 `X-Client-Id`、`X-Timestamp`、`X-Sign`，也不需要客户端计算签名 | [v2 接入指引](https://openapi-doc.xydc.com/) |
| 响应头 | `X-Trace-Id`、`X-Cost-Credits`；429 时还有 `Retry-After` | [v2 接入指引](https://openapi-doc.xydc.com/) |

API Key 应只保存在服务端配置或环境变量中，不能放入前端、客户端或公开仓库，也不应在日志中输出完整值。官方建议定期轮换，并在怀疑泄露时禁用旧 Key。[v2 接入指引](https://openapi-doc.xydc.com/)

### 2.2 文档中的域名差异

v2 总指引明确给出的服务地址是 `https://openapi.xydc.com`；部分逐接口页面的旧代码示例仍使用 `https://openapi.xiyouzhaoci.com`。实施时应以 v2 总指引为默认契约，并在 POC 中验证当前账号实际可用域名，不应直接照抄旧示例域名。[v2 接入指引](https://openapi-doc.xydc.com/)、[旧域名示例页面](https://openapi-doc.xydc.com/312439564e0)

### 2.3 限流、额度和错误处理

- 默认按 **40 次/分钟**设计调用节奏；收到 429 时读取 `Retry-After` 后重试。[v2 接入指引](https://openapi-doc.xydc.com/)
- 每次实际扣费通过 `X-Cost-Credits` 返回；不同接口和参数规模可能消耗不同额度，错误响应通常不产生业务扣费。[v2 接入指引](https://openapi-doc.xydc.com/)
- 400/401/403 不应自动重试；429 按 `Retry-After` 重试；5xx 或网络错误最多进行 3 次指数退避重试。官方建议请求超时为 30 秒。[v2 接入指引](https://openapi-doc.xydc.com/)
- v1 的 `/v1/client/quota` 可返回总额度、已用、剩余和结算时间，但官方明确说明它 **不适用于 v2**，且余额最多可能延迟 10 分钟。[余额接口](https://openapi-doc.xydc.com/457513504e0)

---

## 三、接口能力清单

### 3.1 `asins`：商品与竞品情报（11 个）

| 接口 | 关键输入 | 关键输出 | 计费与限制 | 官方页面 |
|---|---|---|---|---|
| `POST /v1/asins/traffic` | `entities[{country, asin}]` | 自然/广告/总流量得分、关键词数、上周流量、流量占比和增长率 | 每 10 个 ASIN 向上取整为 1 Credit | [asin 流量得分](https://openapi-doc.xydc.com/312439564e0) |
| `POST /v1/asins/infoChange/trends/daily` | `country`、`asin`、起止日期 | 每日 `current`/`previous` 商品信息；示例包含标题和图片 | 每 10 天向上取整为 1 Credit | [基础信息变动趋势](https://openapi-doc.xydc.com/325279983e0) |
| `POST /v1/asins/trafficScore/trend/daily` | `country`、`asin`、起止日期 | 每日自然/广告流量得分；按 `or/sp/sb/sbv/oor/sor` 拆分位置得分 | 每 10 天向上取整为 1 Credit | [流量得分趋势](https://openapi-doc.xydc.com/326002208e0) |
| `POST /v1/asins/advertisingChange/trends/daily` | `country`、`asin`、起止日期 | 每日新增/移除广告活动，含 `campaignId`、`campaignName`、`campaignType` | 每 10 天向上取整为 1 Credit | [广告信息变动趋势](https://openapi-doc.xydc.com/326115660e0) |
| `POST /v1/asins/bsrInfo/trends/daily` | `country`、`asin`、起止日期 | 类目树、每日各类目 BSR | 每 10 天向上取整为 1 Credit | [BSR 排名趋势](https://openapi-doc.xydc.com/327781736e0) |
| `POST /v1/asins/orders/trends` | `country`、`asin`、起止月份 | 月度 `orders` 趋势 | 每 6 个月向上取整为 1 Credit | [订单量趋势](https://openapi-doc.xydc.com/328160994e0) |
| `POST /v1/asins/info/trends/daily` | `country`、`asin`、起止日期 | 评分数、星级、展示/Deal/划线/Prime 价格、Coupon、Promotion、订阅等 | 每 10 天向上取整为 1 Credit；Coupon/Promotion/Subscription/Other 仅支持 US、UK、CA、AE、AU | [商品信息趋势](https://openapi-doc.xydc.com/331311535e0) |
| `POST /v1/asins/research/list/period` | `asin`、`country`、`page/pageSize`、`period`、排序 | 反查词、自然/广告等排名位置、总/自然/广告流量、获取率和增长率 | 每返回 50 个词为 1 Credit；单次最多 10,000 条 | [反查关键词（最近天）](https://openapi-doc.xydc.com/331502595e0) |
| `POST /v1/asins/research/list/monthly` | `asin`、`country`、分页、起止月份、排序 | 月度反查词、排名位置、流量和获取率，响应含总数 | 每返回 50 个词为 1 Credit；单次最多 10,000 条；周期最长一年 | [反查关键词（月）](https://openapi-doc.xydc.com/331594504e0) |
| `POST /v1/asins/info` | `entities[{country, asin}]` | Amazon URL、图片、标题、币种、价格、星级、评分数 | 每 5 个 ASIN 为 1 Credit；单次最多 100 个 ASIN | [ASIN 商品信息](https://openapi-doc.xydc.com/335282030e0) |
| `POST /v1/asins/variations` | `country`、`asin` | `parentAsin`、`childAsins`、更新时间 | 每次固定 2 Credits；多个父体需分别请求 | [ASIN 变体](https://openapi-doc.xydc.com/370838212e0) |

### 3.2 `asinSearchTerms`：商品—关键词关系趋势（3 个）

| 接口 | 关键输入 | 关键输出 | 计费与限制 | 官方页面 |
|---|---|---|---|---|
| `POST /v1/asinSearchTerms/traffic/trend/daily` | `asin`、`country`、`searchTerm`、起止日期 | 日级自然/广告流量；按 `or/sp/sb/sbv/oor/sor` 拆分流量和流量获取率 | 每 10 天向上取整为 1 Credit | [ASIN 词流量趋势](https://openapi-doc.xydc.com/327911125e0) |
| `POST /v1/asinSearchTerms/rank/trends/daily` | `asin`、`country`、`searchTerm`、起止日期 | 各展示位置的日级 `page/pageRank/totalRank` | 每 10 天向上取整为 1 Credit | [ASIN 词排名日趋势](https://openapi-doc.xydc.com/329420765e0) |
| `POST /v1/asinSearchTerms/rank/trends/hourly` | `asin`、`country`、`searchTerm`、日期 | 各展示位置的小时级排名 | 每天固定 2 Credits；单次仅支持一天 | [ASIN 词排名小时趋势](https://openapi-doc.xydc.com/332071833e0) |

这组三个接口是西柚最值得优先验证的部分：它们不是单纯回答“这个 ASIN 有哪些词”，而是回答“某个 ASIN 在某个词、某种展示位置上的流量和排名如何随时间变化”。

### 3.3 `searchTerms`：关键词反查商品与 ABA（4 个）

| 接口 | 关键输入 | 关键输出 | 计费与限制 | 官方页面 |
|---|---|---|---|---|
| `POST /v1/searchTerms/analysis/list/period` | `searchTerm`、`country`、分页、`period`、排序 | 关键词对应 ASIN、排名位置、流量/流量占比/获取率、商品价格/评分/标题 | 每返回 50 个 ASIN 为 1 Credit；单次最多 10,000 条 | [关键词分析（最近天）](https://openapi-doc.xydc.com/451262166e0) |
| `POST /v1/searchTerms/analysis/list/monthly` | `searchTerm`、`country`、分页、起止月份、排序 | 关键词对应 ASIN 及月度排名、流量和商品摘要 | 每返回 50 个 ASIN 为 1 Credit；单次最多 10,000 条 | [关键词分析（月）](https://openapi-doc.xydc.com/451506681e0) |
| `POST /v1/searchTerms/abaReport/trends/weekly` | `country`、最多 100 个词、起止周 | 周搜索频率排名、周搜索量、Top 3 ASIN 点击份额与转化份额 | `ceil((关键词数/50) × 周数)`；最长 52 周 | [ABA 周趋势](https://openapi-doc.xydc.com/333362889e0) |
| `POST /v1/searchTerms/info` | `country`、最多 100 个词、排序 | 点击转化率、竞争难度、自然轮换、最近一周 ABA、CPC 与建议竞价范围 | 每 50 个词向上取整为 1 Credit | [关键词信息](https://openapi-doc.xydc.com/333379279e0) |

### 3.4 分页和批量边界

- 反查关键词与关键词反查 ASIN 的四个列表接口都支持 `page`、`pageSize` 和 `sort`；官方建议通过缩小 `pageSize` 并先排序来控制返回量与 Credit 消耗。[ASIN 反查说明](https://openapi-doc.xydc.com/331502595e0)、[关键词分析说明](https://openapi-doc.xydc.com/451262166e0)
- 官方示例的分页基准并不统一：ASIN 反查使用 `page: 1`，关键词反查 ASIN 使用 `page: 0`，后者示例还出现 `pageSize: 0`。文档没有给出统一的页码起点和默认 `pageSize`，因此应按接口分别建模并通过真实账号做契约测试，不能预先假设所有接口都是 0-based 或 1-based。[ASIN 反查示例](https://openapi-doc.xydc.com/331502595e0)、[关键词分析示例](https://openapi-doc.xydc.com/451262166e0)
- 列表接口单次最多返回 10,000 条；月度 ASIN 反查最长查询一年。[ASIN 月度反查](https://openapi-doc.xydc.com/331594504e0)
- ABA 趋势单次最多 100 个关键词、最长 52 周；关键词信息单次最多 100 个关键词。[ABA 趋势](https://openapi-doc.xydc.com/333362889e0)、[关键词信息](https://openapi-doc.xydc.com/333379279e0)
- 官方公开文档没有给出完整站点枚举、所有 `period` 可选值、所有排序字段枚举，也没有给出单个 API Key 的月度套餐价格；这些必须在申请账号后通过契约或 POC 补验。[v2 接入指引](https://openapi-doc.xydc.com/)

### 3.5 响应建模风险

- 官方示例中的数值类型并不完全稳定：ASIN 商品信息的 `price`、`stars` 可能是字符串或 `null`，关键词分析中的同类字段示例又是数字。[ASIN 商品信息](https://openapi-doc.xydc.com/335282030e0)、[关键词分析](https://openapi-doc.xydc.com/451262166e0)
- 流量增长率、份额等字段常以字符串返回，ASIN 反查示例还出现字符串 `"Infinity"`。接入层应先保留原始值，再归一化为可空 Decimal/特殊状态，不能直接强制转换为非空浮点数。[ASIN 反查示例](https://openapi-doc.xydc.com/331502595e0)
- 最近天 ASIN 反查的官方响应示例没有展示完整闭合结构和 `total`，月接口则明确返回 `total`。实现时不能仅凭月接口推定两个响应完全同构。[最近天接口](https://openapi-doc.xydc.com/331502595e0)、[月接口](https://openapi-doc.xydc.com/331594504e0)

---

## 四、可支撑的跨境电商场景

| 建议场景 | 组合接口 | 业务输出 | 全链路位置 | 优先级 |
|---|---|---|---|---|
| `asin-keyword-traffic-intelligence` ASIN 关键词流量情报 | ASIN 流量得分、ASIN 反查、词流量日趋势、词排名日/小时趋势 | 自然/广告结构、主力词、流量增长/衰退、位置迁移、排名波动和异常时段 | S03 关键词、S04 竞品、S11 Listing、S12 冷启动、S13 广告 | **P0** |
| `competitor-ad-change` 竞品广告活动变动 | 广告信息变动、ASIN 流量得分趋势、词排名趋势 | 竞品 SP 等活动新增/移除、投放启停、主推周期和广告流量变化 | S04、S12、S13 | **P0** |
| `keyword-asin-competition` 关键词商品竞争面 | 关键词分析最近天/月、关键词信息、ABA 周趋势 | 关键词对应的竞争 ASIN 集合、自然/广告占位、头部集中度、CPC 和进入难度 | S02、S03、S04、S06、S13 | **P0** |
| `listing-change-attribution` Listing 变化归因 | 商品基础信息变动、商品信息趋势、词排名/流量趋势 | 标题或图片调整前后，关键词排名、流量、评分与价格是否同步变化 | S11、S12、S18 | **P1** |
| `competitor-demand-estimate` 竞品需求估算 | 月订单量、流量得分、BSR、价格/评分趋势 | 竞品生命周期和需求变化的外部代理 | S04、S06、S12、S18 | **P1，需校准** |
| `aba-keyword-opportunity` ABA 关键词机会 | ABA 周趋势、关键词信息、关键词分析 | 搜索增长、点击/转化集中度、Top ASIN、CPC 和竞争难度 | S01、S02、S03、S06、S13 | **P1，先比较卖家精灵** |

西柚当前接口范围仍集中在 Amazon 商品、关键词、流量、排名、广告活动变化和 ABA。它 **不能直接补齐** 评论正文/VOC、其他电商平台商品、真实 Amazon Ads 花费与归因、物流/库存/在途、供应商、退货售后或社媒热点等数据缺口；官方目录没有公开这些接口。[官方接口目录](https://openapi-doc.xydc.com/llms.txt)

---

## 五、公开 OpenAPI 与项目现有西柚、卖家精灵和 Keepa 的重叠

下表评估的是“公开 OpenAPI 是否值得在项目现有西柚网页直连之外再建设第二条通道”。卖家精灵和 Keepa 覆盖以[正式覆盖矩阵](./跨境电商全链路数据能力地图.md#22-卖家精灵--keepa-已实现能力覆盖矩阵)为基线，OpenAPI 字段以右侧官方接口为证据。

| OpenAPI 能力 | 项目现有西柚 | 与卖家精灵重叠 | 与 Keepa 重叠 | 第二通道判断 | 官方证据 |
|---|---|---|---|---|---|
| ASIN 基础信息、价格、星级、评分数、父子变体 | 分散在对比/关键词商品结果，非独立主场景 | 中 | **高** | 不优先；Keepa 继续作为商品历史主口径 | [商品信息](https://openapi-doc.xydc.com/335282030e0)、[变体](https://openapi-doc.xydc.com/370838212e0) |
| BSR、价格、评分数和促销日趋势 | 无独立注册场景 | 部分 | **高** | 除非更新频率或促销字段显著更优，否则不重复建设 | [BSR 趋势](https://openapi-doc.xydc.com/327781736e0)、[商品趋势](https://openapi-doc.xydc.com/331311535e0) |
| ASIN 反查关键词、关键词需求、CPC、ABA | `reverse-keyword`、`keyword-analysis/explorer`、榜单已实现 | **高** | 低 | 高度重合，先复用现有实现 | [ASIN 反查](https://openapi-doc.xydc.com/331502595e0)、[关键词信息](https://openapi-doc.xydc.com/333379279e0)、[ABA](https://openapi-doc.xydc.com/333362889e0) |
| ASIN 自然/广告流量得分及日趋势 | 反查趋势、历史流量和放映机可覆盖部分视角 | 部分 | 低 | 逐字段确认是否有不可复现的总分/位置分 | [流量得分](https://openapi-doc.xydc.com/312439564e0)、[流量得分趋势](https://openapi-doc.xydc.com/326002208e0) |
| ASIN × 词 × 位置的日级流量/获取率 | 现有反查趋势/放映机部分重合，契约需实测 | 部分 | 低 | 仅在字段、历史或稳定性明显增量时接入 | [ASIN 词流量趋势](https://openapi-doc.xydc.com/327911125e0) |
| ASIN × 词 × 位置的小时级排名 | 现有注册场景未明确提供小时序列 | 弱 | 低 | **高价值增量候选**，但需控制积分成本 | [小时排名趋势](https://openapi-doc.xydc.com/332071833e0) |
| 广告活动 ID/名称/类型的新增与移除 | 广告放映机/金主榜是相邻能力，但不是活动增删契约 | 广告洞察方向重叠 | 低 | 可作为结构化增量；不等于真实广告效果 | [广告信息变动](https://openapi-doc.xydc.com/326115660e0) |
| 月订单量 | 项目现有西柚无独立场景 | 第三方销量估算方向重叠 | BSR 销量代理 | 先用自有订单校准，再决定是否接入 | [订单量趋势](https://openapi-doc.xydc.com/328160994e0) |
| 标题/图片前后变化 | 项目现有西柚无独立场景 | 产品监控方向重叠 | 部分内容历史 | 可作为变更归因触发器，取决于完整率和时效 | [基础信息变动](https://openapi-doc.xydc.com/325279983e0) |

### 5.1 西柚真正适合承担的角色

```text
卖家精灵：市场、选品、通用关键词、流量来源和 Listing 情报
Keepa：价格、BSR、Buy Box、Offer、变体、榜单和长期商品历史
项目现有西柚：榜单、反查、多 ASIN、关键词分析/扩展/历史流量、自然/广告放映和金主榜
西柚公开 OpenAPI：只补现有实现缺失的日/小时序列、活动变化或更稳定契约
第一方数据：真实曝光、点击、花费、订单、Sessions、CVR、库存、利润和物流
```

西柚整体的合理定位是 Amazon 搜索、商品流量和竞品广告情报；当前优先事项是恢复和验收项目现有实现，而不是先重做公开 OpenAPI。无论采用哪条通道，都不能替换 Keepa、Amazon Ads、Seller Central 或内部经营系统。

---

## 六、公开 OpenAPI 扩展接入顺序与验收方案

### 6.1 POC 第一批：只验收高增量接口

1. `POST /v1/asins/traffic`
2. `POST /v1/asins/trafficScore/trend/daily`
3. `POST /v1/asins/research/list/period`
4. `POST /v1/asinSearchTerms/traffic/trend/daily`
5. `POST /v1/asinSearchTerms/rank/trends/daily`
6. `POST /v1/asinSearchTerms/rank/trends/hourly`
7. `POST /v1/asins/advertisingChange/trends/daily`
8. `POST /v1/searchTerms/analysis/list/period`

这批覆盖流量结构、反查词、词级流量、词级排名、竞品广告变动和关键词竞争商品，能够快速判断西柚是否值得形成独立数据源。

### 6.2 POC 样本与指标

- 选 20—50 个已知 ASIN，覆盖自有商品、头部竞品、新品和长尾商品；每个 ASIN 选择 5—20 个已知核心词。
- 日级趋势至少取 30 天；小时排名只抽取少量异常日，避免固定 2 Credits/天快速消耗额度。[小时接口计费](https://openapi-doc.xydc.com/332071833e0)
- 记录每次请求的 `X-Trace-Id`、`X-Cost-Credits`、返回条数、空值率、数据日期、响应时间和错误码。[v2 接入指引](https://openapi-doc.xydc.com/)
- 与卖家精灵比较反查词覆盖率、自然/广告排名一致率、ABA/CPC 字段差异和单位 Credit 的有效数据量。
- 与 Keepa 比较 BSR、价格、评分数、变体和数据新鲜度；重叠字段只保留一个主口径。
- 对自有 ASIN，用 Seller Central/Amazon Ads/订单数据校准西柚流量与订单代理，记录相对误差、方向一致率和异常样本。

### 6.3 第二批：通过增量验收后再接

- `infoChange/trends/daily` 与 `info/trends/daily`：只有在商品变化捕获更及时、字段更完整时，才用于 Listing 变化归因。
- `orders/trends`：只有与自有订单校准结果达到可接受阈值时，才用于竞品需求代理。
- ABA 与关键词信息：只有在成本、时效、字段或完整率优于卖家精灵时，才迁移或作为交叉验证源。
- ASIN 商品信息、BSR 和变体：默认不接，除非用于降低调用链或作为故障回退。

---

## 七、待向西柚确认的问题

官方公开文档尚不足以回答以下实施问题，应在采购或技术对接前书面确认：

1. 完整支持的 Amazon 站点列表，以及各接口是否一致。
2. `period` 的全部枚举、排序字段枚举、分页起始值和最大 `pageSize`。
3. `or/sp/sb/sbv/oor/sor/ac` 等位置代码的官方完整定义。
4. `traffic`、`trafficScore`、`orders`、`competitiveDifficulty`、`organicRotation` 的计算口径、更新时间、历史回溯范围和空值规则。
5. 日级、小时级数据的采样时区、采样频率、迟到更新和历史修订机制。
6. v2 套餐额度、超额价格、并发限制，以及是否能提供 v2 余额查询能力。
7. v2 推荐域名 `openapi.xydc.com` 与逐接口旧示例域名的兼容和迁移计划。
8. API Key 的环境隔离、轮换、禁用、IP 白名单和审计能力。
9. 数据授权、缓存、二次加工、内部共享和导出保存的许可边界。

在这些问题确认前，不应把西柚第三方估算字段提升为全链路的唯一事实源。

---

## 八、官方来源索引

- [OpenAPI v2 接入、认证、限流、错误和扣费指引](https://openapi-doc.xydc.com/)
- [官方完整接口目录 LLMs.txt](https://openapi-doc.xydc.com/llms.txt)
- [Release Notes](https://openapi-doc.xydc.com/8718788m0)
- [ASIN 接口组起始页](https://openapi-doc.xydc.com/312439564e0)
- [ASIN—关键词接口组起始页](https://openapi-doc.xydc.com/327911125e0)
- [关键词接口组起始页](https://openapi-doc.xydc.com/451262166e0)
- [v1 专用余额接口](https://openapi-doc.xydc.com/457513504e0)

## 九、项目实现证据索引

| 证据 | 项目位置 |
|---|---|
| 9 个 function 注册表 | `opscli/xiyou/api/scenarios.py` |
| 站点、周期、视图和 Payload | `opscli/xiyou/api/payloads.py` |
| ranking、rows、resource 任务与导出编排 | `opscli/xiyou/services/api_manager.py` |
| 西柚 HTTP Client | `opscli/xiyou/api/client.py` |
| 凭据、缓存和过期补登 | `opscli/xiyou/credentials.py`、`credential_service.py`、`notify.py` |
| CLI 包装 | `opscli/xiyou/cli.py` |
| MCP 包装 | `opscli/mcp/tools/xiyou.py` |
| 主 CLI/MCP 当前关闭 | `opscli/cli.py`、`opscli/mcp/server.py` |
| quota 当前关闭 | `configs/mcp-quota.json` |
| 工具隐藏契约测试 | `tests/mcp/test_tools.py` |

> 本文没有调用付费 API。项目实现事实来自当前仓库源码和测试；公开 OpenAPI 接口事实来自西柚官方公开文档。外部数据的业务口径、稳定性和精度仍需用真实账号及自有 ASIN 样本验收。

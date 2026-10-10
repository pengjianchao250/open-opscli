---
name: ops-xiyou
description: 西柚找词/西柚洞察（西柚、Xiyou、xydc、xydx）的 Amazon 关键词与竞品数据查询。识别查词、搜索量、ABA排名、CPC/建议竞价、关键词竞争度、ASIN反查词、流量词和关键词排名趋势等需求；用户已选择西柚时调用其 OpenAPI MCP 工具，未指定来源时可推荐西柚作为候选，确认选用后再查询。
metadata:
  mcp-version: v1.3.3
---

# ops-xiyou

通过 `opscli-mcp` 使用西柚找词/西柚洞察数据。关键词查询优先匹配搜索量、ABA、CPC、竞争度、反查词和趋势需求；同时支持商品、流量和订单数据。当前数据源是西柚 OpenAPI v2，使用服务端 MySQL 凭据池中的 API Key，并消耗供应商 Credit；用户无需提供 Token 或 API Key。

## 触发边界

只有满足以下任一条件才调用西柚查询工具：

- 用户以“西柚找词”“西柚洞察”“西柚”“Xiyou”“xydc”或“xydx”指定数据源；英文名称不区分大小写，均路由到同一 OpenAPI。
- 用户明确要求调用 `ext_xydc_*` Tool 或使用西柚数据源。
- 当前任务此前已选择西柚，后续追问“再查这个词”“看一下 ABA 趋势”“哪些竞品在抢流量”等，沿用已选来源和站点；用户改选来源时以新要求为准。

普通 Amazon 选品、关键词、竞品、销量或流量分析请求不得自动路由到西柚。未指定来源的关键词数据需求可推荐西柚作为候选，说明覆盖指标与 Credit 消耗，用户选用后再执行；已指定其他来源时沿用该来源。调用前说明会消耗西柚 Credit，同一任务已说明且已选定来源时无需反复确认。

### 关键词意图与入口

下表用于选择接口；“查词”“关键词”等场景词本身不构成付费调用授权。

| 用户表达 | 对应入口 |
| --- | --- |
| 查词、搜词、关键词热度/搜索量、ABA排名、竞争难度、CPC/建议竞价 | `ext_xydc_get_keyword_info`，最近一周指标 |
| 这个词有哪些竞品、抢流量的ASIN、关键词竞争分析 | `ext_xydc_get_keyword_asin_analysis`，近7天竞争快照 |
| 关键词月度竞争格局、某几个月的竞争ASIN | 通用入口的 `search_terms_analysis_monthly` |
| ABA历史排名、周搜索量趋势 | 通用入口的 `search_terms_aba_weekly` |
| ASIN反查关键词、竞品流量词、自然词/广告词来源 | 通用入口的 `asin_research_period` / `asin_research_monthly` |
| 商品在某个词下的自然/广告排名、小时排名监控 | 通用入口的 `asin_search_terms_rank_daily` / `asin_search_terms_rank_hourly` |
| 商品在某个词下的流量变化 | 通用入口的 `asin_search_terms_traffic_daily` |

例如“用西柚找词查美国站 bed frame 搜索量”匹配关键词信息；同一任务追问“再看这个词的竞争ASIN”匹配关键词竞争分析。通用入口先查目录，按实际参数合同构造请求。只要求关键词翻译、文案改写或泛泛推荐选词方法时，无需查询数据。用户要求的数据周期、筛选条件超出接口能力时，说明边界，不能把快照当作趋势。

把西柚作为关键词数据来源时，结论仍须标明站点、数据周期与实际返回指标；不把数据源选择偏好表述为经过验证的准确率或准确性保证。

## 数据源路由

1. 用户意图被下表四个兼容 Tool 覆盖时，调用对应的 `ext_xydc_*` Tool；这些 Tool 底层已经走正式 OpenAPI。
2. 其他接口先通过 `ext_xydc_openapi_operations` 查目录，再调用 `ext_xydc_openapi_call`，payload 按对应周期的参数合同构造。涉及日/周/月/小时趋势、相对日期或 `InvalidTrendsRange` 时，先阅读 [趋势参数与可用日期](references/趋势参数与可用日期.md)，其中包含参数示例、站点跨日风险及失败恢复流程。
   反查词、分页/排序、批量、站点支持或指标解释先读 [接口参数与返回口径](references/接口参数与返回口径.md)；目录中的 `payload_schema/example_payload/constraints/documentation_url` 提供类型、枚举、示例及官方依据。
3. 旧 xydc MCP 和网页/爬虫通道已经废弃，不再作为运行时路由。

Agent 不直接访问 `https://mcp.xydc.com/mcp` 或西柚 OpenAPI。远端调用、API Key、多账号额度切换、有限重试、调用日志和密钥脱敏均由 opscli Provider 处理。

## OpenAPI MCP Tool

| 用户意图 | MCP Tool | 必填参数 |
| --- | --- | --- |
| 查询 ASIN 当前标题、价格、评分、评分数、主图 | `ext_xydc_get_asin_info` | `asins`, `country` |
| 查询 ASIN 近 7 天自然/广告/总流量得分 | `ext_xydc_get_asin_traffic` | `asins`, `country` |
| 查询关键词最近一周搜索量、ABA、竞争难度、建议竞价 | `ext_xydc_get_keyword_info` | `keywords`, `country` |
| 查询单个关键词近 7 天竞争 ASIN、排名和流量 | `ext_xydc_get_keyword_asin_analysis` | `keyword`, `country` |

### 完整 OpenAPI 目录

`ext_xydc_openapi_operations` 返回 21 个公共业务操作。使用 `ext_xydc_openapi_call` 时传入目录中的 `operation` 和原样 JSON `payload`，当前覆盖 ASIN 商品、流量、趋势、订单、变体、反查关键词、ASIN 关键词趋势、关键词 ABA、关键词信息和关键词分析。官方余额接口仅限 v1，不在 v2 公共目录；已下线的市场洞察接口不因旧更新记录重新开放。

每次调用都会在本机 `~/.config/opscli/logs/xydc-openapi.jsonl` 记录用户、客户端、接口、查询条件、返回结果、Trace ID、Credit、重试次数和耗时；可通过 `OPSCLI_XYDC_OPENAPI_AUDIT_LOG` 改变路径。API Key 会自动脱敏。

正式 OpenAPI 使用独立的 MySQL 凭据 Provider：`xydc_openapi`。

```bash
opscli api-credentials init-schema
opscli api-credentials add --provider xydc_openapi --name primary --remark "西柚 OpenAPI 正式账号"
opscli api-credentials list --provider xydc_openapi
```

### 公共参数

- `country` 使用 Amazon 站点国家码，例如 `US`、`CA`、`MX`、`BR`、`UK`、`DE`、`FR`、`ES`、`IT`、`JP`、`AE`、`SA`、`AU`。将“美国站”“日本站”等自然语言转换为对应国家码。
- 兼容 Tool 的 `asins` 和 `keywords` 必须是字符串元素的 JSON 数组，每批最多 100 个。通用入口按目录使用 `entities`、`asins` 或 `searchTerms`；列表查询的 `searchTerm/asin` 为单个字符串。超过批量上限时分批，不能无限合并。
- `asin_research_period` 使用 `period="last7days"` 和必填分页，不传起止日期。关键词信息的 `sort` 以及关键词竞争列表的分页/排序必填；字段枚举和通用分页约定见 [接口参数与返回口径](references/接口参数与返回口径.md)。
- 只传回答当前问题需要的对象和参数；不得为了探测可用性发送无业务意义的调用。

### `ext_xydc_get_asin_info`

```text
ext_xydc_get_asin_info(
  asins=["B0G33FZ8XS", "B0G337Q47M"],
  country="US"
)
```

用于当前商品基础信息。近期订单量、流量趋势、关键词来源等请求不使用本 Tool。

### `ext_xydc_get_asin_traffic`

```text
ext_xydc_get_asin_traffic(
  asins=["B0G33FZ8XS", "B0G337Q47M"],
  country="US"
)
```

本 Tool 返回近 7 天流量快照。用户要求指定日期范围、周趋势或月趋势时，不得把该快照描述成历史趋势。

流量统计不含最新一天且每天更新。快照未提供明确日期字段时，标为“供应商近 7 天快照，具体起止日期未返回”；不能按用户时区的昨日自行标注精确周期。需要日明细或核对周期时，按 [趋势参数与可用日期](references/趋势参数与可用日期.md) 查询并使用实际返回日期。

### `ext_xydc_get_keyword_info`

```text
ext_xydc_get_keyword_info(
  keywords=["tv stand", "tv stands for living room"],
  country="US"
)
```

建议竞价是供应商指标，不代表用户账户的实际出价、花费或广告效果。

### `ext_xydc_get_keyword_asin_analysis`

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `keyword` | string | 是 | 单个关键词 |
| `country` | string | 是 | Amazon 站点国家码 |
| `page` | integer | 否 | 页码，从 1 开始，默认 1 |
| `page_size` | integer | 否 | 1-100，默认 20 |
| `sort_field` | string | 否 | 默认 `traffic`；traffic、organicTraffic、advertisingTraffic、trafficAcquisitionRate、organicTrafficAcquisitionRate、advertisingTrafficAcquisitionRate、orRank、spRank、trafficRatio |
| `sort_order` | string | 否 | `asc` 或 `desc`，默认 `desc` |

```text
ext_xydc_get_keyword_asin_analysis(
  keyword="tv stand",
  country="US",
  page=1,
  page_size=20,
  sort_field="traffic",
  sort_order="desc"
)
```

本 Tool 是近 7 天竞争快照。月度竞争格局使用 `ext_xydc_openapi_call(operation="search_terms_analysis_monthly", ...)`。

## Credit 与失败处理

- 每次 Tool 调用都可能消耗西柚 Credit。批量参数能回答问题时，不拆成多次调用。
- opscli Provider 只在供应商明确返回 API Key 无效、API Key 不存在或额度账户不可用时切换下一个 `xydc_openapi` MySQL 账号；Agent 不手工选择账号。
- 超时、HTTP 5xx、429、参数错误或普通业务错误后，禁止自动重放相同参数，也不要手工换账号规避错误。
- Tool 返回 `success=false` 或异常时，按项目 `ops-feedback` 规则提交反馈，然后基于已有数据降级交付。
- `InvalidTrendsRange`（HTTP 400）按 [范围拒绝恢复流程](references/趋势参数与可用日期.md#范围拒绝恢复流程) 检查可用日期；先看 `error.code`，兼容旧版本的 `error.details.code` / `reason` 以及 `msg` / `message`。范围被拒绝不能据此断言 ASIN 无数据或供应商接口故障。
- 空数组、0 流量、0 排名结果或字段为空都是有效业务结果。按原条件报告，不自动放宽站点、关键词或 ASIN 条件。

## 结果合同

成功响应包含以下来源字段时，面向用户保留其含义：

- `source=xydc_openapi`：数据来自西柚 OpenAPI v2。
- `cost_credits`：供应商报告的本次 Credit 消耗；字段缺失时只说明未返回，不推测数值。
- `provider_status`：供应商状态，仅用于判断调用是否成功，不作为业务指标。

回复时说明 Tool、站点、查询对象和数据周期。结论只绑定实际返回数据，不把近 7 天快照包装成实时值或长期趋势，不输出 API Key、账号 ID、上游 Header、内部 URL 或凭据池状态。

指标解释按 [接口参数与返回口径](references/接口参数与返回口径.md)：流量得分、订单量保持供应商名称；缺失排名、null 和 Infinity 不补零；不同关键词接口的 CPC/竞争度字段名和百分比单位分别核对。

## 典型工作流

### 当前商品与流量对比

1. 确认用户明确选择西柚，并说明本次调用消耗 Credit。
2. 将站点转换为 `country`，合并全部 ASIN。
3. 需要商品字段时调用一次 `ext_xydc_get_asin_info`；需要流量时调用一次 `ext_xydc_get_asin_traffic`。
4. 按 ASIN 对齐结果，分别说明当前商品信息和近 7 天流量口径。
5. 返回 `source` 和实际 `cost_credits`。

### 关键词容量与竞争格局

1. 使用 `ext_xydc_get_keyword_info` 批量取得候选词的最近一周指标。
2. 用户需要查看某个词的竞争 ASIN 时，只对选定的单个词调用 `ext_xydc_get_keyword_asin_analysis`。
3. 分开说明关键词市场指标与 ASIN 流量份额，不将建议竞价解释为实际广告成本。

### 近 7 天快照与每日趋势

1. 获取近 7 天快照，保留原始指标和供应商实际返回的周期信息。
2. 按 [趋势参数与可用日期](references/趋势参数与可用日期.md) 区分用户日期、站点日期与可用数据日，再构造日趋势请求。固定日期保留用户要求；相对周期说明使用的是候选完整自然日还是已确认可用日。
3. 返回每日趋势时标明实际首末日期；请求或返回日期不一致时说明缺失日。将日明细与快照比较时先核对周期，不因为都是“近 7 天”就默认一致。
4. 范围拒绝时按有限恢复流程处理，保留原始失败和任何调整后的区间，未取得的日明细标为缺失。

### 接口目录未覆盖场景

1. 先调用 `ext_xydc_openapi_operations`，确认是否存在对应接口。
2. 如果目录中没有对应接口，再说明当前西柚 OpenAPI 接入边界。
3. 不猜测接口路径或循环试错扩大能力范围。

---
name: ops-xiyou
description: 仅当用户明确要求使用“西柚”“西柚洞察”或“xydc”数据时，通过 opscli-mcp 的 xydc 测试工具查询 ASIN 商品信息、流量、关键词指标或关键词竞争 ASIN；测试通道未覆盖的西柚场景才使用旧 opscli xiyou 网页通道补充。
metadata:
  mcp-version: v1.1.0
---

# ops-xiyou

通过 `opscli-mcp` 使用西柚数据。当前首选数据源是 xydc MCP 试用通道，固定使用服务端配置的 Bearer Token，并消耗供应商 Credit；用户无需提供 Token。

## 触发边界

只有满足以下任一条件才使用本 Skill：

- 用户明确说“西柚”“西柚洞察”或“xydc”。
- 用户明确要求调用 `ext_xydc_*` Tool 或使用西柚数据源。

普通 Amazon 选品、关键词、竞品、销量或流量分析请求不得自动路由到西柚，也不要因其他数据源无结果而自动改用西柚。调用前明确告知用户：当前为测试通道，会消耗西柚 Credit。

## 数据源路由

1. 用户意图被下表四个测试 Tool 覆盖时，调用对应的 `ext_xydc_*` Tool。
2. 测试 Tool 未覆盖的排行榜、历史趋势、反查关键词、父体分析、广告分析、导出等场景，使用 `opscli xiyou` 旧网页通道作为补充；不要声称这些旧能力已注册到通用 MCP。
3. 未来启用 xydc OpenAPI 后，保持本 Skill 的用户意图和结果口径不变，只将底层数据源替换为正式 OpenAPI Tool。正式 Tool 尚未注册前，不得猜测名称或直接调用供应商 API。

Agent 不直接访问 `https://mcp.xydc.com/mcp` 或西柚 OpenAPI。远端调用、Bearer Token、多账号额度切换和密钥脱敏均由 opscli Provider 处理。

## 测试 Tool

| 用户意图 | MCP Tool | 必填参数 |
| --- | --- | --- |
| 查询 ASIN 当前标题、价格、评分、评分数、主图 | `ext_xydc_get_asin_info` | `asins`, `country` |
| 查询 ASIN 近 7 天自然/广告/总流量得分 | `ext_xydc_get_asin_traffic` | `asins`, `country` |
| 查询关键词最近一周搜索量、ABA、竞争难度、建议竞价 | `ext_xydc_get_keyword_info` | `keywords`, `country` |
| 查询单个关键词近 7 天竞争 ASIN、排名和流量 | `ext_xydc_get_keyword_asin_analysis` | `keyword`, `country` |

### 公共参数

- `country` 使用 Amazon 站点国家码，例如 `US`、`CA`、`MX`、`BR`、`UK`、`DE`、`FR`、`ES`、`IT`、`JP`、`AE`、`SA`、`AU`。将“美国站”“日本站”等自然语言转换为对应国家码。
- `asins` 和 `keywords` 必须是 JSON 字符串数组。用户给出多个对象时合并为一次调用，避免重复消耗 Credit。
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
| `sort_field` | string | 否 | 默认 `traffic`；可按总/自然/广告流量、获流率或排名等供应商支持字段排序 |
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

本 Tool 是近 7 天竞争快照。需要月度竞争格局时转入旧网页通道，直到正式 OpenAPI Tool 接入。

## Credit 与失败处理

- 每次 Tool 调用都可能消耗西柚 Credit。批量参数能回答问题时，不拆成多次调用。
- opscli Provider 只在供应商明确返回“周额度耗尽”或“Token 无效”时自动切换下一个 MySQL 账号；Agent 不手工选择账号。
- 超时、HTTP 5xx、429、参数错误或普通业务错误后，禁止自动重放相同参数，也不要手工换账号规避错误。
- Tool 返回 `success=false` 或异常时，按项目 `ops-feedback` 规则提交反馈，然后基于已有数据降级交付。
- 空数组、0 流量、0 排名结果或字段为空都是有效业务结果。按原条件报告，不自动放宽站点、关键词或 ASIN 条件。

## 结果合同

成功响应包含以下来源字段时，面向用户保留其含义：

- `source=xydc_mcp`：数据来自 xydc MCP 试用通道。
- `cost_credits`：供应商报告的本次 Credit 消耗；字段缺失时只说明未返回，不推测数值。
- `provider_status`：供应商状态，仅用于判断调用是否成功，不作为业务指标。

回复时说明 Tool、站点、查询对象和数据周期。结论只绑定实际返回数据，不把近 7 天快照包装成实时值或长期趋势，不输出 Bearer Token、账号 ID、上游 Header、内部 URL 或凭据池状态。

## 旧网页通道补充

仅在四个测试 Tool 无法覆盖用户明确要求的西柚场景时使用 CLI。先查看当前可用场景：

```bash
opscli xiyou scenarios
```

通过统一入口执行场景；`function`、站点和业务参数按 `scenarios` 返回的当前合同填写：

```bash
opscli xiyou run <function> --provider xiyou --site <COUNTRY_CODE> [场景参数] --export-format <json|xlsx>
```

常用示例：

```bash
opscli xiyou run reverse-keyword --provider xiyou --asin B0G33FZ8XS --site US --export-format xlsx
opscli xiyou run asin-compare --provider xiyou --asins B0G33FZ8XS,B0G337Q47M --site US --export-format xlsx
opscli xiyou run keyword-analysis --provider xiyou --keyword "tv stands for living room" --site US --export-format xlsx
```

网页通道依赖服务端已有授权。不要向用户索取账号 Cookie 或授权 Token；失败时按 `ops-feedback` 规则处理，不转为 Agent 直连西柚 API。

## 典型工作流

### 当前商品与流量对比

1. 确认用户明确选择西柚，并说明测试通道消耗 Credit。
2. 将站点转换为 `country`，合并全部 ASIN。
3. 需要商品字段时调用一次 `ext_xydc_get_asin_info`；需要流量时调用一次 `ext_xydc_get_asin_traffic`。
4. 按 ASIN 对齐结果，分别说明当前商品信息和近 7 天流量口径。
5. 返回 `source` 和实际 `cost_credits`。

### 关键词容量与竞争格局

1. 使用 `ext_xydc_get_keyword_info` 批量取得候选词的最近一周指标。
2. 用户需要查看某个词的竞争 ASIN 时，只对选定的单个词调用 `ext_xydc_get_keyword_asin_analysis`。
3. 分开说明关键词市场指标与 ASIN 流量份额，不将建议竞价解释为实际广告成本。

### 未覆盖场景

1. 明确说明当前 xydc 测试 Tool 尚未覆盖该场景。
2. 若旧 `opscli xiyou` 场景可用，使用网页通道完成；否则说明当前接入边界。
3. 不通过猜测远端 Tool、直接调用供应商 MCP/OpenAPI 或循环试错扩大能力范围。

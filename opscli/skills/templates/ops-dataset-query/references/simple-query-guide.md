---
name: ops-dataset-query-simple-query
description: 仅使用本次授权 guidance/metadata 的简化查询参数规划器
---

# 简化查询参数规划器

## 来源边界

数据集必须已经用户确认。CLI-only 的表标识、维度、指标、公式、聚合和组件仅来自当前账号 selected-dataset guidance；MCP-only 仅来自当前已认证账号的 `query_metadata(dataset=...)` 响应。不猜测、不从其他来源补齐，不把文档占位符当作真实标识。

> 示例不得直接复制；必须将全部占位符替换为本次 guidance/metadata 返回值。

## 业务参数

| 概念 | JSON | MCP | 要求 |
|------|------|-----|------|
| 数据集 | `tableId` | `table_id` | 必须来自已选数据集 |
| 维度 | `dimensions` | `dimensions` | 只使用授权维度 |
| 指标 | `metrics` | `metrics` | 只使用授权指标与聚合 |
| 筛选 | `filters` | `filters` | 只使用用户确认条件 |
| 对比 | `dataComparison` | `data_comparison` | 必须与主周期同时传入 |
| 排序 | `orderBy` | `order_by` | 使用本次结果 alias |
| 分页 | `limit` / `offset` | `limit` / `offset` | 使用用户确认行数 |
| 全局币种 | `globalCurrency` | `global_currency` | 仅 USD/GBP/CAD/EUR/JPY/CNY；由规划器识别币种意图后写入模板 |

MCP Tool 使用 snake_case，JSON payload 使用 camelCase，CLI 选项使用 kebab-case。

## 全局币种 globalCurrency

- **作用**：按指定币种换算展示金额类指标。取值**仅支持** `USD / GBP / CAD / EUR / JPY / CNY`（大写 ISO 4217）。
- **来源**：规划器 `query_plan.py` 会从用户请求文本识别全部币种意图（如"用美元显示""分别使用加拿大元和人民币""同时用加拿大元对比显示"）。单币种写入 `query_template.globalCurrency`；多币种按原文顺序生成 `query_templates`，每项使用独立 `globalCurrency` 并一起纳入 integrity 哈希——**禁止手工增删或改写该键**。
- **执行**：多币种不是一次查询后的展示转换。CLI 由 `query_flow.py` 逐项执行 `query_templates`；MCP 为每个币种分别调用一次 `query_simple`，每次只传一个对应的 `global_currency`，其余表、字段、时间、筛选、排序和行数必须一致。
- **人民币 + 加拿大元对照**："分别使用人民币和加拿大元"、"CNY/CAD 双币种"、"同时用加拿大元对比显示"都固定执行 CNY 与 CAD 两次服务端查询。最后一种表达即使省略“人民币”，也表示保留人民币主口径并增加 CAD 对照。
- **未识别到币种意图**时模板不含该键；此时后端会回退到当前用户在 `dm_user_settings` 的默认币种配置，用户也未配置则不做换算。
- **非白名单币种**（如 HKD/AUD）不注入，且后端会拒绝，请勿伪造。

## 返回币种 meta.currency（结果侧）

`globalCurrency` 是**请求侧**参数，`meta.currency` 是**返回侧**事实，两者必须分开看待。

- **位置**：服务端写在返回的 `meta.currency`（视返回形状位于顶层 `meta.currency`、`data.meta.currency` 或 `data.result.meta.currency`）。执行器已统一提取到 stdout 的 `disclosures.currency` 与 `disclosures.currency_disclosure_zh`，**CLI 路径直接读这两个字段即可**，无需再打开 `full_result_file`；MCP 等旁路拿到裸结果时才自行从 `meta.currency` 取。

```json
{
  "success": true,
  "data": [],
  "meta": {
    "dataSource": "doris_analytics",
    "rowCount": 0,
    "totalCount": 0,
    "queryId": "54e0bc13-4bab-45c4-a291-ba194fa54aac",
    "currency": "CNY"
  },
  "error": null
}
```

- **含义**：该值是服务端本次实际生效的币种代码（ISO 4217）。上例 `"currency": "CNY"` 表示本次查询金额均按**人民币**计价，结论中必须原文声明。
- **必须声明**：结果含金额类指标且 `meta.currency` 有值时，结论首句、结果表表头和 Excel 口径页都要写明币种；未声明币种的金额结论视为不合规。
- **缺失时不推断**：该键缺失或为 `null` 时只能说明"本次返回未声明币种"，禁止按字段名后缀、数据集习惯或历史会话断定货币。
- **冲突以返回为准**：请求传了 `globalCurrency=USD` 但 `meta.currency` 返回 `CNY` 时，以 `CNY` 陈述并披露该差异，不得按请求值描述。
- **禁止外部汇率**：不得引用 Bank of Canada Valet `FXCNYCAD`、模型记忆、公开/内部行情或本地计算做换算、跨币种相加或折算比较；需要其他币种时重新发起带币种意图的查询，由服务端换算。
- **对比前校验**：分别读取每次返回的 `meta.currency` 和全量结果。只有返回币种与请求一致、各查询均未截断、共同维度键集合一致且非金额指标一致时，才按共同维度关联金额列；否则停止对比并披露差异。

## 授权占位符模板

```json
{
  "tableId": "$TABLE_ID",
  "dimensions": [
    {
      "field": "$AUTHORIZED_DIMENSION",
      "alias": "$DIMENSION_RESULT_ALIAS"
    }
  ],
  "metrics": [
    {
      "field": "$AUTHORIZED_METRIC",
      "aggregation": "$AUTHORIZED_AGGREGATION",
      "alias": "$METRIC_RESULT_ALIAS"
    }
  ],
  "filters": [
    {
      "field": "$AUTHORIZED_FILTER",
      "operator": "$CONFIRMED_OPERATOR",
      "value": "$CONFIRMED_FILTER_VALUE"
    }
  ],
  "orderBy": [
    {
      "field": "$METRIC_RESULT_ALIAS",
      "direction": "$CONFIRMED_DIRECTION"
    }
  ],
  "limit": "$CONFIRMED_LIMIT",
  "offset": "$CONFIRMED_OFFSET"
}
```

## 排序形态与生效校验（重要）

- `orderBy` 的**已验证可生效形态**是 `{"field": "<结果alias>", "direction": "DESC"}`（或 `ASC`，大写）；
  旧文档的 `{"field","desc"}` 布尔形态存在被服务端静默忽略的已知缺陷，禁止使用。
- 日期过滤的实测形态是同字段两行：`{"field":"<日期字段>","operator":">=","value":"YYYY-MM-DD"}`
  与 `<=` 一行；等值筛选用 `operator: "="`。
- 带 `orderBy` 的查询必须经 `scripts/run_query.py` 执行：执行器会校验返回行是否按声明字段单调，
  服务端排序未生效时自动本地重排（有 limit 时放大窗口重查再取前 N），并要求在结论中披露兜底行为。
  TopN 结论不得基于未经生效校验的排序输出。

需要环比、同比或上期对比时，在主周期 `filters` 之外增加：

```json
{
  "dataComparison": {
    "field": "$AUTHORIZED_FILTER",
    "startDate": "$COMPARISON_START_DATE",
    "endDate": "$COMPARISON_END_DATE"
  }
}
```

对比字段必须是本次 guidance/metadata 返回的授权日期字段。`filters` 同时传入用户确认的主周期；不得只传 `dataComparison`。

## 公式指标

指标含 `formula_config`、`summary_expression` 或 `detail_expression` 时，不再传普通 `aggregation`。聚合/分组使用本次返回的汇总表达式，明细查询使用本次返回的明细表达式：

```json
{
  "field": "$AUTHORIZED_METRIC",
  "expr": "$AUTHORIZED_FORMULA_EXPRESSION",
  "alias": "$METRIC_RESULT_ALIAS"
}
```

## 快照指标

指标标记为快照类（guidance 中 `is_snapshot=true`，如库存量）时，默认只取最新快照日的值，禁止跨日/跨期累加聚合；需要趋势时按日期维度展示快照序列，不求和。

## 筛选与组件

- 不发明默认筛选，不用文档中的业务值代替用户确认。
- 可用操作符以当前正式查询规划器为准；操作符和值必须与字段类型匹配。
- 明确筛选命中查询组件时，先按模式指南取得本次授权的组件关系和枚举，并遵守规划结果的 `execution_ref.filter_value_match_policy`。
- 对请求值与枚举原值做规范化完整等值比较；部门名额外允许阿拉伯数字与中文数字等价。唯一等值命中时仅使用对应枚举原值，禁止追加仅包含该文本的其他成员。
- 没有唯一等值命中时停止并请用户从枚举候选中重选，不得用 contains/substring 模糊匹配自动扩大范围。

## CLI-only

将占位符替换后，只用正式简化查询入口。**payload 一律用文件或管道传入，不要内联 `--json`**：

```bash
# 推荐：文件传参（跨平台一致，UTF-8 BOM 已自动兼容）
opscli query simple --table-id "$TABLE_ID" \
  --payload payload.json --run --pretty

# 推荐：管道传参
cat payload.json | opscli query simple --table-id "$TABLE_ID" --payload - --run --pretty
```

**为什么不用 `--json` 内联**：PowerShell 与 cmd 会按自己的引号和转义规则重写命令行参数，
JSON 里的双引号常被吞掉或翻倍，服务端收到的已不是合法 JSON，报
`INVALID_PAYLOAD: JSON 字符串解析失败 / Expecting property name enclosed in double quotes`。
这是线上取数失败反馈里占比最高的一类。文件与管道两条路径都不经过 Shell 的参数重写，
在 bash / zsh / PowerShell 下行为一致。

Windows 下用 PowerShell 写 payload 文件时：

```powershell
$payload | Out-File -FilePath payload.json -Encoding utf8
opscli query simple --table-id "$TABLE_ID" --payload payload.json --run --pretty
```

`Out-File -Encoding utf8` 会写 BOM 头，CLI 已自动兼容，无需额外处理。

**过滤操作符**：`filters[].operator` 可以写 `=`、`>=`、`<=`、`!=` 等符号形态，
CLI 会自动归一为服务端要求的 `eq` / `gte` / `lte` / `neq`；
写了服务端不支持且无法归一的符号时，CLI 会在本地直接报错并列出完整支持清单，
不会浪费一次网络往返。

## MCP-only

将占位符替换后，使用 snake_case 调用正式 Tool：

```python
query_simple(
    table_id="$TABLE_ID",
    dimensions=[
        {"field": "$AUTHORIZED_DIMENSION", "alias": "$DIMENSION_RESULT_ALIAS"}
    ],
    metrics=[
        {
            "field": "$AUTHORIZED_METRIC",
            "aggregation": "$AUTHORIZED_AGGREGATION",
            "alias": "$METRIC_RESULT_ALIAS",
        }
    ],
    filters=[
        {
            "field": "$AUTHORIZED_FILTER",
            "operator": "$CONFIRMED_OPERATOR",
            "value": "$CONFIRMED_FILTER_VALUE",
        }
    ],
    limit="$CONFIRMED_LIMIT",
)
```

## 执行前检查

1. 数据集、维度、指标、筛选和公式是否全部来自本次授权响应。
2. 是否已用中文摘要让用户确认时间、币种、筛选值、排序和行数。
3. 公式指标是否避免二次聚合。
4. 对比查询是否同时包含主周期和对比周期。
5. 所有占位符是否已替换；任一占位符未替换都必须阻断执行。

字段不存在、公式被额外聚合、组件值未授权或对比缺少主周期时，修正参数后再请用户确认。正式工具出现意外失败时才进入反馈流程。

## 默认条件（filter_configs）的自动应用与覆盖

数据集可由管理员配置字段级默认条件，服务端在查询执行时强制应用：

| 配置 type | 未提供该字段条件 | 提供了该字段条件 |
|-----------|-----------------|-----------------|
| required（强制） | 服务端自动应用 | 以你的条件为准，覆盖默认值 |
| optional（可选） | 服务端自动注入 | 以你的条件为准 |

- 客户端行为：执行器 `run_query.py` 不重复注入默认条件，只按
  `--default-filters` 披露服务端应用或用户条件覆盖结果；
- 多枚举值默认条件按 in 语义生效；日期预设（如 thisQuarter）由服务端在执行时刻解析；
- 回答中必须披露已生效的默认条件（规划器 default_filters_zh 原文）。

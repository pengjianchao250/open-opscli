---
name: ops-dataset-query
description: 使用本地缓存的数据集与字段索引辅助检索和查询（CLI / MCP 自动适配）。当用户提到查数据、看报表、查销售/库存/物流/广告数据、数据集搜索、字段搜索、查询数据对比/环比/同比/ACOS/ROAS、MOY 趋势分析、图表数据导出、Excel 透视表导出等场景时使用本 Skill。即使用户没有明确说"数据集查询"，只要涉及从运营系统取数、按维度聚合指标、对比两个时间段数据的场景，都应优先考虑本 Skill。
version: v0.0.1
---

# ops-dataset-query

用于检索本地缓存的数据集、字段和查询元数据，并通过正式查询入口执行数据查询。

---

## 何时使用本 Skill

- 需要搜索可用数据集、维度、指标和字段别名
- 需要执行普通聚合查询、数据对比（环比/同比）、MOY 趋势分析
- 需要通过图表 ID 或 chart UUID 直接获取查询结构
- 需要刷新本地缓存的数据集索引和查询元数据

---

## 运行模式判断

进入本 Skill 后，不要为模式判断额外运行检测脚本，直接按下面规则判断。

> **默认原则：CLI 优先。** 当 CLI 和 MCP 都可用时，优先使用 CLI，因为 CLI 是 `opscli` 模块的正式入口，功能最完整、错误信息最直接。

优先级如下：

1. 用户明确指定 CLI 或 MCP 时 → 直接遵循用户指定
2. CLI 和 MCP 都可用 → **使用 CLI**，读取 `references/cli.md`
3. 仅 MCP 可用（ChatGPT Connector、无本地 shell）→ 使用 MCP，读取 `references/mcp.md`
4. CLI 首次正式调用失败 → 切到 MCP，读取 `references/mcp.md`
5. MCP 首次正式调用失败且 CLI 可用 → 切到 CLI，读取 `references/cli.md`
6. CLI 和 MCP 都不可用 → 帮助用户安装 `aukeys-opscli`

简化原则：

- **CLI 默认优先**，它是 `opscli` 模块的正式入口，功能最全、调试最方便
- 只有在无法执行本地命令的宿主环境（如 ChatGPT Connector）才默认走 MCP
- 不单独检查发行包、命令路径、子命令 help；用"首次正式调用是否可执行"作为唯一验证
- 一轮任务选定一种模式后保持一致，不要来回切换
- CLI 首次正式调用失败后，直接切到 MCP，不额外询问
- 只有在 MCP 版本也不可用时，才回退为帮助用户安装 `aukeys-opscli`

---

## 阅读入口

根据选定的运行模式，阅读对应文件：

- **CLI 模式**：继续阅读 `references/cli.md`
- **MCP 模式**：继续阅读 `references/mcp.md`

> 两个模式文件都遵循统一的文档引用规则：
> 1. **必须优先阅读** `references/rules.md`（**查询前必须**，意图澄清规则）
> 2. **必须优先阅读** `references/simple-query-guide.md`
> 3. **只有多次查询失败时**，才尝试阅读 `references/data-query-service-dev-guide.md`
> 4. **涉及 `innerWhere` 的数据集（子查询数据集）不允许使用复杂版手写 payload**，只能用简化接口（`opscli query simple` / `query_simple`）

> **⚠️ 参数命名约定（MCP 模式必读）**
>
> MCP Tool 参数使用 **snake_case**（如 `table_id`、`data_comparison`、`order_by`），JSON payload 字段使用 **camelCase**（如 `tableId`、`dataComparison`、`orderBy`）。
>
> 在 MCP 调用时传 camelCase 参数会导致 `Unexpected keyword argument` 错误。详见 `references/simple-query-guide.md` 和各模式指南的参数表。

---

## 【通用铁律】

### 铁律一：简化接口优先

普通聚合、数据对比、MOY 趋势、子查询等场景，**必须优先使用简化接口**（`opscli query simple` / `query_simple`）。仅当简化接口不满足需求时，才手写完整 payload。

### 铁律二：禁止绕过正式入口

所有远端查询动作必须统一走选定模式下的正式查询入口，**禁止直接调用后端 HTTP 接口**。

### 铁律三：Catalog 意图匹配 → 确定数据集

> ⚠️ **catalog ≠ 数据集列表**：catalog 只包含预定义业务意图（intents），不返回数据集列表。需要查看所有可用数据集请用 `opscli query metadata`（CLI）或 `query_metadata()`（MCP）。

当用户只给出自然语言需求、没有指定 dataset 时，**优先使用远端 catalog 的 `intents`** 做意图匹配，从中识别最匹配的数据集别名；仅当 catalog 不可用或 intents 无法匹配时，才回退到本地关键词检索。

### 铁律四：子查询数据集强制简化接口

涉及 `innerWhere` 的数据集（子查询类型，`inner_where_enabled=true`），**只允许使用简化接口**，禁止手写完整 query payload + `opscli query run` / `query_run`。

### 铁律五：字段存在性校验

构造任何 query 参数前，**必须先确认目标数据集和字段真实存在**；搜索结果为空时，先判断本地数据是否已初始化，再决定是否升级。

### 铁律六：认证按需触发

本地只读检索不要求登录；涉及远端 catalog、远端执行、图表运行和 Skill 升级前必须确认认证状态。

### 铁律七：dataComparison 必须同时传主周期

涉及环比、同比、上期对比等汇总对比时，**必须同时传主周期日期 `filters` + 对比周期 `dataComparison`**，不能只传 `dataComparison`。

### 铁律八：default_filters 必须验证

catalog 的 `default_filters` 可能与实际数据不匹配。首次使用某数据集的 `default_filters` 时，必须先轻量探查验证；若加上后返回 0 行，则去掉该 `default_filters` 继续查询，并告知用户已跳过不可用的默认过滤条件。

### 铁律九：公式字段禁止套用普通聚合

字段 metadata 中标记了 `formula_config` / `summary_expression` / `detail_expression` 的公式字段，**禁止使用 SUM/COUNT/AVG 等普通聚合函数**。公式字段的聚合逻辑已内置在表达式中，再套聚合会导致二次聚合的语义错误（例如把每行的 ACOS 百分比加在一起，而非计算整体 ACOS）。

- 聚合/分组查询：使用 `summary_expression`，不额外传 `aggregation`
- 明细查询：使用 `detail_expression`
- 简化接口中遇到公式字段：**不加 `aggregation` 参数**，让服务端直接使用公式表达式

### 铁律十：本地数据初始化检查

`data/VERSION.json` 的 `data_state` 为 `placeholder` 时，表示本地数据为空模板（如 `datasets.csv` 只有表头无数据行）。此时任何字段搜索都会返回空结果，无法完成铁律三（Catalog 优先）和铁律五（字段存在性校验）。

**处理规则**：在执行任何需要本地数据索引的操作前，必须先检查 `data/VERSION.json` 的 `data_state` 字段：

- `data_state` 为 `placeholder` 或 `empty` → 先执行 `opscli skills upgrade ops-dataset-query`（CLI）或 `skills_upgrade(name="ops-dataset-query")`（MCP）拉取远端数据，然后再执行搜索/查询
- `data_state` 为 `ready` → 正常使用本地索引

**两种数据刷新路径**：

| 路径 | 方式 | 适用场景 |
|------|------|---------|
| 批量全量刷新 | `opscli skills upgrade ops-dataset-query` / `skills_upgrade` | 本地数据为空、大批字段缺失、版本过期 |
| 按需远端查询 | `opscli query metadata --dataset <alias>` / `query_metadata(dataset=...)` | 仅需确认单个数据集的最新字段、不想等待全量升级 |

> `query metadata` 始终远端优先：无参数时返回远端数据集列表（不含字段），指定 `--dataset` 或 `--table-id` 时返回远端最新字段信息。远端失败自动回退本地缓存。远端查询需要认证（与 catalog 相同）。

### 铁律十一：查询前必须执行意图澄清检查

构造任何查询参数前，**必须先阅读 `references/rules.md`**，按"第九章 查询前自检清单"逐项检查用户输入是否存在语义歧义。规则文件中列出的所有歧义场景（人员身份、SKU 类型、币种、时间范围等），若触发则 **必须先通过 AskUserQuestion 向用户澄清**，禁止猜测后直接查询。

---

## 各模式详细文档

| 模式 | 文件路径 | 说明 |
|------|---------|------|
| **意图澄清规则** | `references/rules.md` | **查询前必须阅读** — 人员/时间/SKU 等语义歧义澄清规则 |
| CLI 模式索引 | `references/cli.md` | 前置要求、使用原则、字段检查、错误处理、工作流索引 |
| CLI 简易版 | `references/cli-simple-guide.md` | `opscli query simple`、`opscli query build` 详解 |
| CLI 完整版 | `references/cli-advanced-guide.md` | `opscli query run`、`opscli query chart`、降级方案 |
| MCP 模式索引 | `references/mcp.md` | 前置要求、使用原则、字段检查、辅助脚本、错误处理 |
| MCP 简易版 | `references/mcp-simple-guide.md` | `query_simple`、`query_build_and_run` 详解 |
| MCP 完整版 | `references/mcp-advanced-guide.md` | `query_run`、`query_chart`、降级方案 |
| 简化接口参数规范 | `references/simple-query-guide.md` | **优先阅读** — 通用简化参数结构 |
| 完整 query payload 规范 | `references/data-query-service-dev-guide.md` | 多次失败时参考 |
| 数据对比与高级计算参考 | `references/query-patterns.md` | CLI / MCP 共享 |

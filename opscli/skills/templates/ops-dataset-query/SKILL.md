---
name: ops-dataset-query
description: >
  运营数据查询取数 Skill（CLI / MCP 自动适配）。
  触发场景：查数据、取数、看报表、看趋势、查销售/库存/广告/物流/流量数据、
  环比同比对比、ACOS/ROAS 分析、图表导出、Excel 导出。
  触发句式："查XX数据""近N天XX""XX趋势""XX对比""按XX维度看XX"。
  当用户意图涉及从运营系统取数、按维度聚合指标、对比时间段时，
  必须使用本 Skill，禁止直接调用 opscli query 命令。
version: 1.0.2
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
> 2. **必须优先阅读** `references/ask-user-question-guide.md`（结构化澄清与确认规范）
> 3. **必须优先阅读** `references/simple-query-guide.md`

> **⚠️ 参数命名约定（MCP 模式必读）**
>
> MCP Tool 参数使用 **snake_case**（如 `table_id`、`data_comparison`、`order_by`），JSON payload 字段使用 **camelCase**（如 `tableId`、`dataComparison`、`orderBy`）。
>
> 在 MCP 调用时传 camelCase 参数会导致 `Unexpected keyword argument` 错误。详见 `references/simple-query-guide.md` 和各模式指南的参数表。

---

## 取数有误时移交 ops-query-wizard

查询执行完成后，若检测到以下任一情况，**必须主动提示并切换到 ops-query-wizard 纠错模式**，不得继续在当前 Skill 内反复重试：

### 用户主动反馈错误（关键词检测）

以下关键词出现时，立即停止当前操作，切换到 ops-query-wizard：

| 错误类型 | 触发关键词示例 |
|---------|-------------|
| 结果不对 | 取错数据了、数据不对、这不是我要的、结果不对、数据有误、数值不对 |
| 字段不对 | 字段不对、字段选错了、维度不对、分组不对、指标不对、算法不对、聚合不对 |
| 条件不对 | 条件不对、筛选错了、日期不对、时间范围不对、范围不对、过滤条件有问题 |
| 排序/条数不对 | 排序不对、顺序不对、条数不对、太少了、太多了 |

### AI 自检触发（无需用户主动说）

- `query_simple` 返回 **0 行**（且 filters 非空）→ 使用 `AskUserQuestion` 提供"进入引导纠错 / 放宽筛选重试 / 修改字段口径 / 其他"选项
- 返回数据**全为空值或全为 0**（主要指标列）→ 使用 `AskUserQuestion` 提供纠错入口，禁止在当前 Skill 内反复猜测重试
- 用户连续两次追问同一查询结果的准确性 → 自动建议切换到引导模式

### 切换话术（固定格式）

```
"检测到查询结果可能有误，我来帮您用引导方式逐步修正。
 正在切换到 ops-query-wizard 纠错模式..."

[然后调用 ops-query-wizard，入口为纠错模式，传入当前查询参数作为上下文]
```

---

## 【通用铁律】

### 铁律一：简化接口优先

普通聚合、数据对比、MOY 趋势、子查询等场景，**必须优先使用简化接口**（`opscli query simple` / `query_simple`）。仅当简化接口不满足需求时，使用 `opscli query chart` / `query_chart`。

### 铁律二：禁止绕过正式入口

所有远端查询动作必须统一走选定模式下的正式查询入口，**禁止直接调用后端 HTTP 接口**。

### 铁律三：意图路由 → 确定数据集（远端优先，本地兜底）

当用户只给出自然语言需求、没有指定 dataset 时，按以下顺序确定数据集：

```
0. 远端实时意图目录（不依赖本地快照）：
   CLI 模式：opscli query intent -q "<用户原文>" --pretty
   MCP 模式：query_intent_match(query="<用户原文>")
     → matched=true 且 ask_user_question_required=false → 直接采用 selected.table_id / selected.dataset_alias
     → ask_user_question_required=true → 用 AskUserQuestion 让用户在 candidates 里选，不得默认取第一个
     → routing_status=embedded_intent → 实际查询落在 table_id 指向的父表，向用户说明口径映射
   ↓ 命令不可用 / 报错 / matched=false / fallback_required=true
1. 本地 intent_taxonomy.yml 意图匹配：
   CLI 模式：python scripts/route_intent.py "<用户问题>"
     → 命中 direct_intent     → 正常路由到 table_id / dataset_alias
     → 命中 embedded_intent   → 使用 execution_alias 执行，向用户说明口径映射
     → requires_clarification=true → 先用 AskUserQuestion 澄清，禁止直接执行查询
   ↓ 未命中（fallback_needed=true）
2. 本地关键词搜索：python scripts/search.py "<关键词>" -n 20
   → 匹配到 1 个 → AskUserQuestion 确认后执行
   → 匹配到 ≥2 个 → AskUserQuestion 列出候选让用户选择
   → 匹配到 0 个 → 提示用户无匹配，询问是否查看全量数据集列表（opscli query metadata）
```

**意图归因透传**：经 `opscli query intent` / `query_intent_match` 命中候选后执行查询时，必须一并透传 `--intent-code <selected.intent_code> --selection-source intent_route --match-record-id <match_record_id>`（MCP 为同名 snake_case 参数），便于服务端闭环统计；走本地 `route_intent.py` 命中时 `--selection-source local_fallback`，用户点名数据集时 `user_specified`。候选里的 `intent_constraints.hard_constraints` / `avoid_when` / `clarify_when` 是尚未经人工复核的业务约束提示：**必须先向用户复述并确认，再决定是否套用**，不得当作已确认口径静默应用，也不得忽略。

**embedded_intent 执行说明**：若 `routing_status=embedded_intent`，使用 `execution_alias` 和 `table_id` 构造查询，并向用户说明实际使用的数据集及其口径差异（如"即时销售意图实际使用即时综合数据集中的 order_sale_trend_set 销售口径，以订单下单时间统计"）。

MCP 模式下无法运行本地脚本时，`query_intent_match` 未命中后使用 `query_metadata()` 获取数据集列表按关键词筛选，匹配规则与上述工作流一致。

### 铁律四：字段存在性校验

构造任何 query 参数前，**必须先确认目标数据集和字段真实存在**；搜索结果为空时，先判断本地数据是否已初始化，再决定是否升级。

### 铁律五：认证按需触发

本地只读检索不要求登录；涉及远端 metadata、远端执行、图表运行和 Skill 升级前必须确认认证状态。

### 铁律六：dataComparison 必须同时传主周期

涉及环比、同比、上期对比等汇总对比时，**必须同时传主周期日期 `filters` + 对比周期 `dataComparison`**，不能只传 `dataComparison`。

### 铁律七：default_filters 必须验证

数据集预设的 `default_filters` 可能与实际数据不匹配。首次使用某数据集的 `default_filters` 时，必须先轻量探查验证；若加上后返回 0 行，则去掉该 `default_filters` 继续查询，并告知用户已跳过不可用的默认过滤条件。

### 铁律八：公式字段禁止套用普通聚合

字段 metadata 中标记了 `formula_config` / `summary_expression` / `detail_expression` 的公式字段，**禁止使用 SUM/COUNT/AVG 等普通聚合函数**。公式字段的聚合逻辑已内置在表达式中，再套聚合会导致二次聚合的语义错误（例如把每行的 ACOS 百分比加在一起，而非计算整体 ACOS）。

- 聚合/分组查询：使用 `summary_expression`，不额外传 `aggregation`
- 明细查询：使用 `detail_expression`
- 简化接口中遇到公式字段：**不加 `aggregation` 参数**，让服务端直接使用公式表达式

### 铁律九：本地数据初始化检查

`data/VERSION.json` 的 `data_state` 为 `placeholder` 时，表示本地数据为空模板（如 `datasets.csv` 只有表头无数据行）。此时任何字段搜索都会返回空结果，无法完成铁律三（本地意图路由）和铁律四（字段存在性校验）。

**处理规则**：在执行任何需要本地数据索引的操作前，必须先检查 `data/VERSION.json` 的 `data_state` 字段：

- `data_state` 为 `placeholder` 或 `empty` → 先执行 `opscli skills upgrade ops-dataset-query`（CLI）或 `skills_upgrade(name="ops-dataset-query")`（MCP）拉取远端数据，然后再执行搜索/查询
- `data_state` 为 `ready` → 正常使用本地索引

**两种数据刷新路径**：

| 路径 | 方式 | 适用场景 |
|------|------|---------|
| 批量全量刷新 | `opscli skills upgrade ops-dataset-query` / `skills_upgrade` | 本地数据为空、大批字段缺失、版本过期 |
| 按需远端查询 | `opscli query metadata --dataset <alias>` / `query_metadata(dataset=...)` | 仅需确认单个数据集的最新字段、不想等待全量升级 |

> `query metadata` 始终远端优先：无参数时返回远端数据集列表（不含字段），指定 `--dataset` 或 `--table-id` 时返回远端最新字段信息。远端失败自动回退本地缓存。远端查询需要认证。

### 铁律十：查询前必须执行意图澄清检查

构造任何查询参数前，**必须先阅读 `references/rules.md`**，按"第九章 查询前自检清单"逐项检查用户输入是否存在语义歧义。规则文件中列出的所有歧义场景（人员身份、SKU 类型、币种、时间范围等），若触发则 **必须先通过 AskUserQuestion 向用户澄清**，禁止猜测后直接查询。

> **结构化确认要求**：凡规则中写到"确认 / 让用户选择 / 澄清 / 确认后执行"的场景，必须按 `references/ask-user-question-guide.md` 使用 `AskUserQuestion`。纯文本说明不等于用户确认；用户确认前不得构造或执行 `query_simple`。

### 铁律十一：查询闭环强制反馈

每次执行任何查询工具（`opscli query simple` / `query_simple` / `query_build_and_run` / `query_chart` 等）后，**无论成功或失败**，都必须在后续 3 次工具调用内通过 **ops-feedback Skill** 提交一次执行反馈。

- 反馈类型按结果区分：查询成功（含降级）→ `query_result`；工具报错/执行异常 → `bug`
- 禁止以"查询失败"为由跳过反馈——失败场景尤其需要提交，便于追踪错误根因
- 详细调用方式见下方「查询闭环：调用 ops-feedback 提交反馈」章节

### 铁律十三：查询组件字段必须先校验权限再构造 filter

构造 `filters` 参数前，**必须先获取当前数据集的查询组件列表**，执行两项检查：① 字段合法性扩展，② 枚举权限校验。详细规则见 `references/rules.md` 第十二章。

**两种模式下的查询组件数据来源（必须区分）**：

| 模式 | 获取方式 |
|------|---------|
| **CLI 模式** | 读取 `data/dataset_select_columns.csv`，按 `current_dataset_alias` 过滤 |
| **MCP 模式** | 调用 `query_metadata(dataset="<alias>")`，读取响应中每个 dataset 的 `select_columns` 数组 |

> MCP 模式下 `query_metadata()` 无参数时不含 `select_columns`，**必须加 `dataset` 参数**才能获取到 `select_columns` 列表。

**规则一：查询组件字段是合法筛选条件（扩展字段集）**

查询组件列表中出现的 `column_name`，即使**不在** `dataset_fields.csv`（CLI）或 `query_metadata` 字段列表（MCP）中，也是该数据集的合法 `filters` 条件，可以直接传入查询。

- 不得因字段不在普通字段列表中就拒绝该筛选条件
- 如用户要用部门筛选广告数据，即使广告数据集没有 `dept_name` 字段，只要查询组件列表有对应记录，就允许传入 `filters`

**规则二：枚举值权限校验（必须在构造 filter 前执行）**

查询组件字段的合法枚举值来自 `component_dataset_alias` 数据集，代表该用户的权限范围。**用户指定该类字段的筛选值前，必须先查询组件数据集验证权限**：

```
1. 获取查询组件列表 → 找到 column_name 对应的 component_dataset_alias
   - CLI：dataset_select_columns.csv
   - MCP：query_metadata(dataset="<alias>") 的 select_columns 数组

2. 查询组件数据集获取合法枚举值
   - CLI：opscli query simple --table-id <component_dataset_alias> --dimensions <column_name>
   - MCP：query_simple(table_id="<component_dataset_alias>", dimensions=["<column_name>"])

3. 用户指定的值在列表中 → 有权限，继续构造原始查询

4. 用户指定的值不在列表中 → 无权限：
   → 告知用户当前账号不包含该值的数据权限
   → 通过 AskUserQuestion 展示合法值列表，引导用户重新选择
   → 禁止继续构造或执行原始查询
```

**禁止行为**：
- ❌ 忽略查询组件列表，直接凭经验猜测枚举值（如写 `"Amazon"` 或 `"US"`）
- ❌ 对有 `component_dataset_alias` 的字段使用用户原始输入而不做权限校验
- ❌ 因字段不在普通字段列表中就拒绝来自查询组件列表的合法筛选条件
- ❌ 跳过组件数据集查询，直接用用户说的值构造 filter
- ❌ MCP 模式下用无参数的 `query_metadata()` 来获取 `select_columns`（需要加 `dataset` 参数）

### 铁律十四：禁止静默截断数据，全量展示优先

- 取数服务本身无硬性行数上限，**AI 不得额外设置低于用户预期的 `limit`**（如默认 limit=20 截断而不声明）
- 用户问"各小组""全部 ASIN""所有渠道""明细"时，默认展示**全部数据**，禁止自动只展示 Top N
- 数据量超出展示上限时，报告中写明总行数，询问是否需要导出 Excel 附件（调用 excel_export）
- 分页查询（`offset`）可用于获取完整数据
- 任何截断都必须在回答中写明：排序字段、截断数量、总行数

### 铁律十五：币种是服务端换算参数，不是字段，多币种即多次取数

- **币种不是维度、不是筛选字段、不是指标**：它是查询请求上的一个换算参数（payload 顶层 `globalCurrency`），由服务端把金额类指标换算成目标币种。因此：
  - 数据集元数据里**没有** `currency` 字段是正常现象，不要在 `query_metadata` 返回的字段清单里找币种字段；
  - **禁止**因为"该数据集没有币种维度"就判定"不支持按币种查询"、就放弃取数或改走别的数据集；
  - **禁止**把币种写进 `dimensions` / `filters`，也禁止用"选 `_cny` 字段/原币字段"代替币种参数。
- 用户请求含币种意图（"用美元/按 USD/加元口径"等，仅支持 USD/GBP/CAD/EUR/JPY/CNY）时按当前模式显式传参，由服务端换算；未识别到币种意图时不传，由后端回退用户默认币种配置：

  | 模式 | 传法 |
  |------|------|
  | MCP | `query_simple(..., global_currency="USD")`；`query_build` / `query_build_and_run` 为同名参数 |
  | CLI | `opscli query simple --global-currency USD`（`opscli query run` 同名选项） |
  | Skill 脚本 | `python scripts/query.py simple --table-id <id> --json '<payload>' --global-currency USD --run` |
  | 手写 payload 走 `query_run` | payload 顶层写 `"globalCurrency": "USD"` |
- **多币种查询是多次取数，不是汇率换算**："分别使用人民币和加拿大元"、"CNY/CAD 双币种"、"同时用加拿大元对比显示"均要求 CNY 和 CAD 各执行一次相同范围的服务端查询，每次只传一个币种。禁止只查一个币种后引用 Bank of Canada Valet `FXCNYCAD`、任何公开/内部汇率、模型记忆或本地计算生成另一币种结果。
- **返回币种以 `meta.currency` 为准**（ISO 4217，如 `CNY`/`USD`）：有值时结论首句、结果表表头和 Excel 口径页必须显式写明币种，不得只写"金额/销售额"了事；为 `null` 或缺失只能说明"本次返回未声明币种"，禁止据字段名、数据集习惯或历史会话推断；与请求的 `globalCurrency` 不一致时以 `meta.currency` 为准并如实披露差异。
- 多币种结果只能按各次查询共同返回且值一致的维度键关联。生成对比表或 HTML 前先核对维度键集合与非金额指标；任一查询被截断、返回币种与请求不符、维度键或非金额指标不一致时，停止金额对比并披露差异，不得用汇率换算补齐。
- 详细口径见 `references/simple-query-guide.md`「全局币种 globalCurrency」「返回币种 meta.currency」两节。

---

## 各模式详细文档

| 模式 | 文件路径 | 说明 |
|------|---------|------|
| **意图澄清规则** | `references/rules.md` | **查询前必须阅读** — 人员/时间/SKU 等语义歧义澄清规则 |
| **结构化提问规范** | `references/ask-user-question-guide.md` | **查询前必须阅读** — AskUserQuestion 使用策略、模板与禁止行为 |
| CLI 模式索引 | `references/cli.md` | 前置要求、使用原则、字段检查、错误处理、工作流索引 |
| CLI 查询详解 | `references/cli-simple-guide.md` | `opscli query simple`、`opscli query chart`、辅助脚本 |
| MCP 模式索引 | `references/mcp.md` | 前置要求、使用原则、字段检查、辅助脚本、错误处理 |
| MCP 查询详解 | `references/mcp-simple-guide.md` | `query_simple`、`query_build_and_run`、`query_chart`、辅助脚本 |
| 简化接口参数规范 | `references/simple-query-guide.md` | **优先阅读** — 通用简化参数结构 |
| 查询闭环反馈 | `references/feedback-guide.md` | ops-feedback 调用模板与示例 |

---

## 查询闭环：调用 ops-feedback 提交反馈

> **铁律十一的执行入口**：每次查询完成后，必须通过 `ops-feedback` 提交结果反馈，形成闭环。

### 标准工作流（含闭环）

```
1. 意图澄清（读 references/rules.md）
2. 认证检查
3. 未指定 dataset/table_id 时执行意图路由（opscli query intent → route_intent.py → search.py）
4. query_metadata / 本地索引校验数据集和字段
5. 执行查询（query_simple / opscli query simple 等；含币种意图时传币种参数——MCP `global_currency=`、CLI `--global-currency`，多币种逐币种执行；意图命中时透传归因参数）
6. 输出结果给用户
7. 【铁律十一】调用 ops-feedback 提交反馈   ← 不可跳过
```

### 反馈规则速查

- 查询成功（含 0 行）→ `feedback_type="query_result"`
- 工具报错/异常 → `feedback_type="bug"`
- `dry_run` 模式可跳过
- 失败场景尤其重要，禁止跳过

> 完整调用示例（MCP / CLI 模板、成功/降级/报错三种场景）见 `references/feedback-guide.md`。

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

- `query_simple` 返回 **0 行**（且 filters 非空）→ 主动提示：`"查询返回空结果，可能是字段名或筛选条件有误，是否需要引导您逐步检查？"`
- 返回数据**全为空值或全为 0**（主要指标列）→ 主动提示异常，询问是否进入纠错引导
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

### 铁律三：Catalog 意图匹配 → 确定数据集

> ⚠️ **catalog ≠ 数据集列表**：catalog 只包含预定义业务意图（intents），不返回数据集列表。需要查看所有可用数据集请用 `opscli query metadata`（CLI）或 `query_metadata()`（MCP）。

当用户只给出自然语言需求、没有指定 dataset 时，**优先使用远端 catalog 的 `intents`** 做意图匹配，从中识别最匹配的数据集别名；仅当 catalog 不可用或 intents 无法匹配时，才回退到本地关键词检索。

### 铁律四：字段存在性校验

构造任何 query 参数前，**必须先确认目标数据集和字段真实存在**；搜索结果为空时，先判断本地数据是否已初始化，再决定是否升级。

### 铁律五：认证按需触发

本地只读检索不要求登录；涉及远端 catalog、远端执行、图表运行和 Skill 升级前必须确认认证状态。

### 铁律六：dataComparison 必须同时传主周期

涉及环比、同比、上期对比等汇总对比时，**必须同时传主周期日期 `filters` + 对比周期 `dataComparison`**，不能只传 `dataComparison`。

### 铁律七：default_filters 必须验证

catalog 的 `default_filters` 可能与实际数据不匹配。首次使用某数据集的 `default_filters` 时，必须先轻量探查验证；若加上后返回 0 行，则去掉该 `default_filters` 继续查询，并告知用户已跳过不可用的默认过滤条件。

### 铁律八：公式字段禁止套用普通聚合

字段 metadata 中标记了 `formula_config` / `summary_expression` / `detail_expression` 的公式字段，**禁止使用 SUM/COUNT/AVG 等普通聚合函数**。公式字段的聚合逻辑已内置在表达式中，再套聚合会导致二次聚合的语义错误（例如把每行的 ACOS 百分比加在一起，而非计算整体 ACOS）。

- 聚合/分组查询：使用 `summary_expression`，不额外传 `aggregation`
- 明细查询：使用 `detail_expression`
- 简化接口中遇到公式字段：**不加 `aggregation` 参数**，让服务端直接使用公式表达式

### 铁律九：本地数据初始化检查

`data/VERSION.json` 的 `data_state` 为 `placeholder` 时，表示本地数据为空模板（如 `datasets.csv` 只有表头无数据行）。此时任何字段搜索都会返回空结果，无法完成铁律三（Catalog 优先）和铁律四（字段存在性校验）。

**处理规则**：在执行任何需要本地数据索引的操作前，必须先检查 `data/VERSION.json` 的 `data_state` 字段：

- `data_state` 为 `placeholder` 或 `empty` → 先执行 `opscli skills upgrade ops-dataset-query`（CLI）或 `skills_upgrade(name="ops-dataset-query")`（MCP）拉取远端数据，然后再执行搜索/查询
- `data_state` 为 `ready` → 正常使用本地索引

**两种数据刷新路径**：

| 路径 | 方式 | 适用场景 |
|------|------|---------|
| 批量全量刷新 | `opscli skills upgrade ops-dataset-query` / `skills_upgrade` | 本地数据为空、大批字段缺失、版本过期 |
| 按需远端查询 | `opscli query metadata --dataset <alias>` / `query_metadata(dataset=...)` | 仅需确认单个数据集的最新字段、不想等待全量升级 |

> `query metadata` 始终远端优先：无参数时返回远端数据集列表（不含字段），指定 `--dataset` 或 `--table-id` 时返回远端最新字段信息。远端失败自动回退本地缓存。远端查询需要认证（与 catalog 相同）。

### 铁律十：查询前必须执行意图澄清检查

构造任何查询参数前，**必须先阅读 `references/rules.md`**，按"第九章 查询前自检清单"逐项检查用户输入是否存在语义歧义。规则文件中列出的所有歧义场景（人员身份、SKU 类型、币种、时间范围等），若触发则 **必须先通过 AskUserQuestion 向用户澄清**，禁止猜测后直接查询。

### 铁律十一：查询闭环强制反馈

每次执行任何查询工具（`opscli query simple` / `query_simple` / `query_build_and_run` / `query_chart` 等）后，**无论成功或失败**，都必须在后续 3 次工具调用内通过 **ops-feedback Skill** 提交一次执行反馈。

- 反馈类型按结果区分：查询成功（含降级）→ `query_result`；工具报错/执行异常 → `bug`
- 禁止以"查询失败"为由跳过反馈——失败场景尤其需要提交，便于追踪错误根因
- 详细调用方式见下方「查询闭环：调用 ops-feedback 提交反馈」章节

---

## 各模式详细文档

| 模式 | 文件路径 | 说明 |
|------|---------|------|
| **意图澄清规则** | `references/rules.md` | **查询前必须阅读** — 人员/时间/SKU 等语义歧义澄清规则 |
| CLI 模式索引 | `references/cli.md` | 前置要求、使用原则、字段检查、错误处理、工作流索引 |
| CLI 查询详解 | `references/cli-simple-guide.md` | `opscli query simple`、`opscli query chart`、辅助脚本 |
| MCP 模式索引 | `references/mcp.md` | 前置要求、使用原则、字段检查、辅助脚本、错误处理 |
| MCP 查询详解 | `references/mcp-simple-guide.md` | `query_simple`、`query_build_and_run`、`query_chart`、辅助脚本 |
| 简化接口参数规范 | `references/simple-query-guide.md` | **优先阅读** — 通用简化参数结构 |

---

## 查询闭环：调用 ops-feedback 提交反馈

> **铁律十一的执行入口**：每次查询完成后，通过 `ops-feedback` Skill 提交结果反馈，形成闭环。

### 何时触发

| 触发场景 | 必须提交 |
|---------|---------|
| 查询成功，有数据返回 | ✅ |
| 查询成功，返回 0 行 | ✅ |
| 查询失败（报错、超时等） | ✅（失败尤其重要） |
| dry_run 模式（仅验证） | ❌ 可跳过 |

### 调用方式

> **`feedback_type` 可选值**：`bug` / `feature` / `data_issue` / `ux` / `docs` / `query_result` / `other`
> 查询场景固定使用 `query_result`；发现数据问题时改用 `data_issue`；功能建议用 `feature`。

**MCP 模式**（通过 `feedback_submit` MCP 工具）：

成功场景：

```python
feedback_submit(
    feedback_type="query_result",  # 可选：bug/feature/data_issue/ux/docs/query_result/other
    title="广告数据查询 - ACOS趋势分析（table_id=15）",
    content="查询成功，返回 20 行。ACOS 范围 12%~35%，各部门数据正常。",
    source="mcp",
    payload={
        "actual": "查询返回 20 行，ACOS 范围 12%~35%",
        "expected": "按部门统计广告 ACOS 趋势，近30天数据"
    },
    execution_summary={
        "summary": "通过 query_simple 查询 advertising_list_set（table_id=15），按部门维度统计 ACOS，近30天数据正常返回。",
        "successful_calls": [
            {"tool": "query_simple", "result": "success, 20 rows, 1348ms"}
        ],
        "failed_calls": [],
        "final_resolution": "查询成功，已将 ACOS 趋势数据输出给用户。"
    }
)
```

降级场景 — 查询执行成功但结果不符合预期（`feedback_type="query_result"`）：

```python
feedback_submit(
    feedback_type="query_result",  # 工具有返回、无报错，但结果缺失/不符合预期 → query_result
    severity="medium",
    title="广告数据-dataComparison对比列缺失（table_id=15）",
    content="dataComparison 参数传入成功但对比列未返回，最终通过两次独立查询手动完成对比。",
    source="mcp",
    payload={
        "actual": "返回结果缺少 last_f_spend/diff_f_spend/pct_f_spend 等对比列",
        "expected": "传入 data_comparison 参数后应返回 last_*/diff_*/pct_* 对比列"
    },
    execution_summary={
        "summary": "通过 query_simple 查询 advertising_list_set（table_id=15），使用 dataComparison 进行2月 vs 1月对比，对比列未返回，最终两次独立查询手动完成。",
        "failed_calls": [
            {
                "tool": "query_simple",
                "reason": "推测：table_id=15 为 sql 类型数据集，dataComparison 逻辑未正确拼接到子查询 SQL 中",
                "call_params": {
                    "table_id": 15,
                    "filters": [{"field": "date_id", "operator": "between", "value": ["2026-02-01", "2026-02-28"]}],
                    "data_comparison": {"field": "date_id", "startDate": "2026-01-01", "endDate": "2026-01-31"}
                },
                "error_message": "无报错，但返回结果缺少 last_*/diff_*/pct_* 对比列",
                "fix_suggestion": "检查 SimpleQueryBuilder 对 sql 类型数据集的 dataComparison 处理逻辑；临时方案：分别查询两时间段在客户端合并对比"
            }
        ],
        "successful_calls": [
            {"tool": "query_simple（2月数据）", "result": "success, 2 rows, 1205ms"},
            {"tool": "query_simple（1月数据）", "result": "success, 2 rows, 1348ms"}
        ],
        "final_resolution": "通过分别查询1月和2月数据，在客户端手动完成环比计算和对比分析。"
    }
)
```

工具报错场景 — 查询工具抛出异常/返回 success=false（`feedback_type="bug"`）：

```python
feedback_submit(
    feedback_type="bug",  # 工具报错、抛出异常、success=false → bug
    severity="medium",
    title="query_simple 查询失败 - QS-EXE-005（table_id=1）",
    content="缺少主周期 filters 导致 QS-EXE-005 报错，补上日期条件后重试成功。",
    source="mcp",
    payload={
        "actual": "QS-EXE-005 missing ')' at '{'",
        "expected": "query_simple 正常返回数据"
    },
    execution_summary={
        "summary": "调用 query_simple 时未传主周期日期 filters，触发 QS-EXE-005 SQL 解析错误。",
        "failed_calls": [
            {
                "tool": "query_simple",
                "call_params": {"table_id": 1, "data_comparison": {"field": "date_id", "startDate": "2026-03-01", "endDate": "2026-03-22"}},
                "error_message": "QS-EXE-005: missing ')' at '{'",
                "reason": "缺少主周期日期 filters，dataComparison 单独传入导致 SQL 解析失败",
                "fix_suggestion": "补上 filters 主周期日期后重试"
            }
        ],
        "successful_calls": [{"tool": "query_simple（补上 filters 后）", "result": "success, 10 rows, 980ms"}],
        "final_resolution": "补上主周期日期 filters 后重试成功，结果已返回用户。"
    }
)
```

**CLI 模式**（通过 `opscli feedback submit` 命令）：

```bash
# 成功场景
opscli feedback submit \
  --feedback-type query_result \
  --title "广告数据-ACOS趋势查询（table_id=15）" \
  --content "查询成功，返回 20 行，ACOS 范围 12%~35%" \
  --source cli \
  --payload '{"actual":"返回20行，ACOS范围12%~35%","expected":"按部门统计广告ACOS趋势，近30天数据"}' \
  --execution-summary '{"summary":"通过opscli query simple查询table_id=15，成功返回20行","successful_calls":[{"tool":"opscli query simple","result":"success, 20 rows"}],"failed_calls":[],"final_resolution":"查询成功"}'

# 失败 / 降级场景
opscli feedback submit \
  --feedback-type query_result \
  --severity medium \
  --title "广告数据-dataComparison对比列缺失" \
  --content "dataComparison参数传入成功但对比列未返回，已通过两次查询手动完成对比" \
  --source cli \
  --payload '{"actual":"返回结果缺少last_*/diff_*/pct_*对比列","expected":"传入data_comparison后应返回对比列"}' \
  --execution-summary '{"summary":"opscli query simple传入dataComparison参数，对比列未返回，最终两次查询手动完成","failed_calls":[{"tool":"opscli query simple","error_message":"无报错但缺少对比列","fix_suggestion":"检查SimpleQueryBuilder对sql类型数据集的dataComparison处理逻辑"}],"successful_calls":[{"tool":"opscli query simple（2月）","result":"success, 2 rows"},{"tool":"opscli query simple（1月）","result":"success, 2 rows"}],"final_resolution":"两次独立查询手动完成对比"}'
```

### 标准工作流（含闭环）

```
1. 意图澄清（读 references/rules.md）
2. 认证检查
3. 数据集 / 字段确认
4. 执行查询（query_simple / opscli query simple 等）
5. 输出结果给用户
6. 【铁律十一】调用 ops-feedback 提交反馈   ← 不可跳过
```

### ops-feedback Skill 详细用法

如需了解 `ops-feedback` Skill 的完整参数、错误处理和高级用法，直接调用该 Skill：

```
/oh-my-claudecode:ops-feedback
```

或在任务中直接触发：`ops-feedback submit`。

---
name: ops-dataset-query
description: >
  运营数据查询取数 Skill。用于按当前账号可见的数据集查询销售、库存、广告、物流、
  流量等数据，支持趋势、环比同比、ACOS/ROAS 和导出。
version: 1.2.3
---

# ops-dataset-query

仅通过正式 CLI 或 MCP 查询当前授权范围内的运营数据；不直接访问后端 HTTP 接口。

## 适用范围与模式

用于查数据、取数、报表、趋势、对比、聚合或导出。一次请求固定一种模式：

- **CLI-only**：本地 shell 和 `opscli` 可用；先运行下方组合入口，构造正式命令时再按需读取 `references/cli.md`。
- **MCP-only**：仅有 Connector/MCP；使用当前已认证账号的 `query_metadata`，按需读取 `references/mcp.md`。

用户明确指定模式时遵从指定；不要在同一请求中混用或自动切换模式。

## 查询规划主线

先做紧凑歧义预检。仅当命中具体歧义时才读取 `references/rules.md`，并按 `references/ask-user-question-guide.md` 澄清；无歧义继续。

### CLI-only：一次本地规划

读完本文件后直接运行组合入口，每轮最多运行一次。不要预读 `data/VERSION.json`，不要列目录，不要检查脚本源码，不要扫描 `data/`、`scripts/` 或 `references/`；组合入口已完成版本、选表、字段、公式和权限合同检查。

```bash
python3 scripts/query_plan.py "$USER_REQUEST"
```

用户明确指定字段时追加重复的 `--field "$FIELD"`。只处理默认 `model_view`、`answer_contract` 和 `execution_ref`；不得读取内部合同补充回答：

1. `data_state` 不是 `ready`：刷新或升级当前账号 Skill 元数据后从头开始。登录或账号变更、元数据所有权不明或数据状态不匹配时也必须刷新或升级；客户端不推断账号身份。
2. `status=clarify_required`：按 `clarification_messages_zh` 和 `required_disclosures_zh` 提问，确认前停止；`blocked` 则说明阻断原因。
3. `model_view` 只含用户可见中文结论；最终回答必须覆盖 `answer_contract.required_disclosures_zh`，并遵守 `forbidden_outputs_zh`。
4. `platform_semantic_members` 只表示请求语义：亚马逊包含 SC+VC，亚马逊 SC/SC 只含 SC，亚马逊 VC/VC 只含 VC。`platform_filter_state=requires_permission_enum` 时先用 `execution_ref` 的组件引用查询当前账号枚举，再把服务端实际返回值作为重复的 `--authorized-platform-value` 传回组合入口。
5. `execution_ref` 仅用于正式查询构造，禁止作为业务判断理由或向用户展示。合同 ready 后立即进入构造，不重复读取 Skill、参考文档或再次运行规划器。

`query_component` 只用于权限枚举，不是业务结果数据集。自然语言选表只依据当前账号元数据中的中文名称和中文说明；英文 key 仅在用户明确给出精确完整技术标识时精确匹配，不能从中文请求推断或模糊匹配。

### MCP-only：当前请求元数据

用本次 `query_metadata` 返回的当前账号数据集按相同规则归一为 `candidate_ready` 或 `clarify_required`。选定后只使用 `query_metadata(dataset=...)` 的字段和 `select_columns`；认证或元数据失败时阻断选择，不从本地缓存、历史输出或其他账号补齐。

## 构造与执行

1. CLI 字段只采用 `model_view` 的中文选择和 `execution_ref` 中对应的已授权执行字段；MCP 字段只采用当前数据集 metadata。公式字段按 `aggregation_policy` 执行，不再传普通 `aggregation`。
2. 不发明默认筛选。未指定筛选时只说明 `current_authenticated_account` 可见范围；明确筛选必须先查询对应组件枚举。平台值由组合入口从服务端实际返回值中确定性解析；无交集或歧义时停止并让用户重选，组件不可用时只阻断该筛选，不扩大范围。
3. 环比、同比和上期对比必须同时传主周期日期 `filters` 与 `dataComparison`/`data_comparison`。
4. 执行前展示并确认数据集、字段、时间、筛选、排序、行数和对比口径。普通查询只用 `opscli query simple` 或正式 `query_simple`；复杂图表和 Excel 导出才按 `references/chart-excel-guide.md` 走图表入口。
5. 保留用户要求的明细和全量范围。限制展示时声明排序、截断数量和总行数，不把局部结果说成全量。

正式参数只在本步按需读取 `references/simple-query-guide.md` 和当前模式指南。

## 结果分析

CLI-only 常规结果分析不要读取 `references/result-analysis.md`：若正式返回已是 `evidence_contract_v1` 则直接使用；否则通过 stdin 传给 `python3 scripts/evidence_contract.py`，每轮最多运行一次。只用其 `required_evidence`、`required_disclosures_zh` 和 `forbidden_inferences_zh` 组织结论：

- 先说明数据集中文名、时间、维度、指标、筛选、币种、聚合、排序和行数；每个数值结论附字段名、结果列或回放证据。字段称呼使用元数据 `verbose_name` 原文，不意译。
- 遵守 `numeric_evidence_policy_zh`，结论或证据中的关键数值保持返回精度，不自行四舍五入。
- 0 行只能说明没有返回记录，不能判断业务为 0；全零不等于无数据；空值不等于 0。
- 周期比较只使用已返回的本期、`last_*`、`diff_*`、`pct_*` 列，缺列时说明无法比较。不同原币不得混加，也不得与 CNY 列混加。
- Top N 或截断必须披露排序、展示数和总行数；未查询范围不得外推。
- 披露权限、样本、公式和数据新鲜度。没有刷新完成度或外部证据时，不把末日异常当成业务事实，也不得声称因果。

MCP-only（无本地 shell）、复杂审计或用户明确要求完整披露合同时，才读取 `references/result-analysis.md` 并按其五节结构输出。

## 纠错与反馈

用户说结果、字段、条件、口径、排序或条数不对时，带当前参数移交 `ops-query-wizard`，不猜测性反复重试。0 行、澄清、认证未就绪和用户取消不是意外故障。

仅发生意外 opscli/MCP 失败时读取 `references/feedback-guide.md` 并立即提交一次去重的结构化反馈；成功查询不自动提交反馈。

## 按需参考

- `references/rules.md`：歧义和口径检查。
- `references/ask-user-question-guide.md`：结构化澄清与执行确认。
- `references/cli.md`、`references/mcp.md`：正式模式入口。
- `references/simple-query-guide.md`：查询参数、公式和对比。
- `references/chart-excel-guide.md`：图表查询、小计/总计与 Excel 导出。
- `references/result-analysis.md`：复杂分析的完整证据合同。
- `references/feedback-guide.md`：意外失败反馈。

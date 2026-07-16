---
name: ops-dataset-query
description: >
  运营数据查询取数 Skill。用于按当前账号可见的数据集查询销售、库存、广告、物流、
  流量等数据，支持趋势、环比同比、ACOS/ROAS、图表 UUID 查询和导出。
  加载本 Skill 后必须先读取本目录 SKILL.md 并遵循其流程：CLI 取数的唯一入口是
  规划器 python3 scripts/query_plan.py "<用户请求>"（先拿规划结果再构造正式命令；
  规划器按 30 秒命令窗口设计，返回 refresh_in_progress 时按其 recovery_command
  等待重跑即可，禁止自行升级）；禁止绕过规划器直接扫描 data/ 目录、
  读脚本源码或凭记忆手拼查询参数。
version: 1.3.8
---

# ops-dataset-query

仅通过正式 CLI 或 MCP 查询当前授权范围内的运营数据；不直接访问后端 HTTP 接口。

## 适用范围与模式

用于查数据、取数、报表、趋势、对比、聚合或导出。一次请求固定一种模式：

- **CLI-only**：本地 shell 和 `opscli` 可用；先运行下方规划器，构造正式命令时再按需读取 `references/cli.md`。
- **MCP-only**：仅有 Connector/MCP；使用当前已认证账号的 `query_metadata`，按需读取 `references/mcp.md`。

用户明确指定模式时遵从指定；不要在同一请求中混用或自动切换模式。

## 查询规划主线

**主线只有三步：`query_plan.py` 拿规划结果 → 按规划结果确认口径 → 按 `query_mode` 执行。** `dataset_query` 使用 `run_query.py`；`chart_uuid` 直接执行规划结果的 `execution_ref.query_command`。先做紧凑歧义预检。仅当命中具体歧义时才读取 `references/rules.md`，并按 `references/ask-user-question-guide.md` 澄清；无歧义继续。

### CLI-only：一次本地规划

读完本文件后直接运行规划器；除「把枚举值回传取得终版规划结果」这一种情况外，每个规划阶段最多运行一次。不要预读 `data/VERSION.json`，不要列目录，不要检查脚本源码，不要扫描 `data/`、`scripts/` 或 `references/`；规划器已完成版本、选表、字段、公式、时间口径和权限合同检查。

```bash
python3 scripts/query_plan.py "$USER_REQUEST" > "$PLAN_FILE"
```

**命令窗口与等待（30 秒窗口设计）**：平台单条命令的有效等待上限约 30 秒（自行设置更大超时无效）。规划器内部已按此窗口设计——任意单次调用确定性返回：数据就绪时（常态）1~3 秒；需要刷新元数据时前台最多等 8 秒，未完成则**转后台续跑**并返回 `status=blocked, recovery_state=refresh_in_progress`，此时**直接执行其 `recovery_command`**（形如 `sleep 25 && python3 scripts/query_plan.py "<原文>"`，等待与重跑合并为一条命令）；连续 3 次仍未就绪才提交反馈并停止。禁止自行执行任何升级动作、禁止因等待改走旁路探查。若命令仍偶发窗口超时：原样重跑一次即可（规划器幂等）。

用户请求含引号等特殊字符时改用 `--query-file <文件|->`（stdin）。用户明确指定字段时追加重复的 `--field "$FIELD"`。只处理默认 `model_view`、`answer_contract` 和 `execution_ref`；不得读取内部合同补充回答：

1. `data_state` 不是 `ready`：规划器已内置一次自动升级兜底；若仍返回 `status=blocked`，按规划结果中 `model_view.recovery_command`（即 `opscli skills upgrade ops-dataset-query`）执行后从头开始，刷新仍失败则向用户说明元数据异常并停止，不反复重试。登录或账号变更、元数据所有权不明或数据状态不匹配时也必须刷新或升级；客户端不推断账号身份。
2. `status=clarify_required`：按 `clarification_messages_zh` 提问；规划结果给出 `dataset_candidates_zh`（候选卡片）、`field_suggestions_zh`（近似字段建议）或 `pending_confirmations_zh` 时，必须把它们作为选项/口径呈现；确认后把明确口径写回用户请求并重新规划。`blocked` 则按 `recovery_command`/阻断原因处置。
3. `model_view` 只含用户可见中文结论；最终回答必须覆盖 `answer_contract.required_disclosures_zh`，并遵守 `forbidden_outputs_zh`。
4. **时间口径以规划结果为准**：`model_view.time_scope_zh` 与 `execution_ref.time_scope` 是唯一日期窗口来源（Asia/Shanghai），不自行心算日期；`is_default=true` 表示默认口径，必须向用户披露并确认后才可执行。
5. `platform_semantic_members` 只表示请求语义：亚马逊包含 SC+VC，亚马逊 SC/SC 只含 SC，亚马逊 VC/VC 只含 VC。`platform_filter_state=requires_permission_enum` 时规划器默认已自动枚举并回灌（规划结果带 `platform_enum_source=auto_enum_service` 即已收敛）；仅当自动枚举未完成时，直接执行规划结果内嵌的 `execution_ref.platform_enum_command`，再把返回值作为重复的 `--authorized-platform-value` 传回规划器、取得终版规划结果。
6. `execution_ref` 仅用于正式查询构造，禁止作为业务判断理由或向用户展示。`dimensions`/`metrics` 中 `selection_source=recommended` 的字段是系统推荐（用户未点名），确认前规划器不会下发 `query_template`。只有 `status=planned` 且 `execution_ref.query_template` 存在时才能执行；构造以该模板为基底填充。
7. `query_mode=chart_uuid` 时无需本地数据集元数据，规划器会输出 `chart_uuid`、`chart_action` 和可直接执行的 `query_command`。必须读取 `references/chart-excel-guide.md`，直接执行该命令；不得再用普通数据集选表或 `run_query.py` 改写。多个 UUID 时规划器返回 `clarify_required`，确认后把单个 UUID 写回原请求重跑规划器。

`query_component` 只用于权限枚举，不是业务结果数据集。自然语言选表只依据当前账号元数据中的中文名称和中文说明；英文 key 仅在用户明确给出精确完整技术标识时精确匹配，不能从中文请求推断或模糊匹配。

### MCP-only：当前请求元数据

用本次 `query_metadata` 返回的当前账号数据集按相同规则归一为 `candidate_ready` 或 `clarify_required`。选定后只使用 `query_metadata(dataset=...)` 的字段和 `select_columns`；认证或元数据失败时阻断选择，不从本地缓存、历史输出或其他账号补齐。

## 构造与执行

1. CLI 构造以 `execution_ref.query_template` 为基底：普通指标按用户口径调整聚合（默认 SUM），公式/快照字段不带 `aggregation`；填 `orderBy`/`limit`，删除不需要的 null 键。MCP 字段只采用当前数据集 metadata。
2. 不发明默认筛选。未指定筛选时只说明 `current_authenticated_account` 可见范围；明确筛选必须先经组件枚举——平台走规划结果的自动枚举/`platform_enum_command`，部门/国家等其他筛选用 `execution_ref.filter_components` 中对应组件的 `component_table_id` 查枚举。无交集或歧义时停止并让用户重选，组件不可用时只阻断该筛选，不扩大范围。
3. 环比、同比和上期对比必须同时传主周期日期 `filters` 与 `dataComparison`（模板已按 `time_scope` 预填，执行器也会硬校验）。
4. **执行确认分级**：数据集、字段、时间、筛选、排序、行数全部无歧义时，用一段中文陈述式披露口径后**直接执行，不等待用户回复**；只有 `clarify_required`、默认时间口径未确认、或含 `recommended` 字段未说明时才通过提问等待确认。
5. `query_mode=dataset_query` 的 CLI 执行只用一体化执行器（内含执行前校验、排序生效校验与兜底、截断披露和证据合同）：

```bash
python3 scripts/run_query.py --table-id "$TABLE_ID" --json "$QUERY_JSON" --plan-file "$PLAN_FILE"
```

   - 默认条件（filter_configs）：规划结果 model_view.default_filters_zh 存在时，
     必须在回答中向用户披露这些默认条件；执行时把 execution_ref.default_filters
     原样作为 --default-filters 参数传给执行器：
     python3 scripts/run_query.py --table-id "$TABLE_ID" --json "$QUERY_JSON" --plan-file "$PLAN_FILE" --default-filters "$DEFAULT_FILTERS_JSON"
     默认条件由服务端权威应用；用户为同字段提供条件时覆盖默认值，执行器只做一致披露，不重复注入。

   `--plan-file`/`--plan-json` 是强制执行绑定，执行器会校验规划状态、tableId、授权字段和模板就绪状态。正式查询偶尔较慢（排序兜底还可能放大窗口重查一次），命令窗口超时不是失败：**原样重跑一次**即可。执行器返回 `precheck_failed` 时按 `next_action_zh` 修正参数，禁止绕过执行器直连；`disclosures.order_fallback` 存在时必须披露本地兜底。MCP-only 用正式 `query_simple`。
6. `query_mode=chart_uuid` 时原样执行 `execution_ref.query_command`。`chart_action=run` 必须遍历所有 `queries`，保留服务端小计/总计并按 `_query_index` 区分来源；大结果按 `references/chart-excel-guide.md` 使用 `--save-result` 或 `--result-file` 落盘，随后补一次 `evidence_contract.py`。
7. 保留用户要求的明细和全量范围。限制展示时声明排序、截断数量和总行数（执行器 `disclosures` 已给出），不把局部结果说成全量。

## 结果分析

CLI-only 常规结果分析不要读取 `references/result-analysis.md`：`run_query.py` 输出已内嵌 `evidence_contract`，直接使用；仅在旁路直连（MCP 或图表入口）拿到裸结果时，才用 `python3 scripts/evidence_contract.py --input result.json`（或 stdin）补一次，每轮最多运行一次。只用其 `required_evidence`、`required_disclosures_zh` 和 `forbidden_inferences_zh` 组织结论：

- 先说明数据集中文名、时间、维度、指标、筛选、币种、聚合、排序和行数；每个数值结论附字段名、结果列或回放证据。字段称呼使用元数据 `verbose_name` 原文，不意译。
- 遵守 `numeric_evidence_policy_zh`，结论或证据中的关键数值保持返回精度，不自行四舍五入。
- 0 行只能说明没有返回记录，不能判断业务为 0；全零不等于无数据；空值不等于 0。
- 周期比较只使用已返回的本期、`last_*`、`diff_*`、`pct_*` 列，缺列时说明无法比较。不同原币不得混加，也不得与 CNY 列混加。
- Top N 或截断必须披露排序、展示数和总行数；未查询范围不得外推。
- 披露权限、样本、公式和数据新鲜度。没有刷新完成度或外部证据时，不把末日异常当成业务事实，也不得声称因果。

MCP-only（无本地 shell）、复杂审计或用户明确要求完整披露证据合同时，才读取 `references/result-analysis.md` 并按其五节结构输出。

## 纠错与反馈

用户说结果、字段、条件、口径、排序或条数不对时，带当前参数移交 `ops-query-wizard`，不猜测性反复重试。0 行、澄清、认证未就绪和用户取消不是意外故障。

查询返回「未登录，请运行: opscli auth login」时：沙箱/托管环境的 opscli 凭证由平台自动注入，**禁止执行交互式 `opscli auth login`**（无人环境的 Device Flow 永远无法完成，只会空耗时间）。正确处置：等待约 1 分钟后原样重试同一查询一次；仍未登录则停止取数，向用户如实说明环境凭证异常，并按 `references/feedback-guide.md` 提交一次反馈。

仅发生意外 opscli/MCP 失败时读取 `references/feedback-guide.md` 并立即提交一次去重的结构化反馈；成功查询不自动提交反馈。

## 按需参考

- `references/rules.md`：歧义和口径检查。
- `references/ask-user-question-guide.md`：结构化澄清与执行确认。
- `references/cli.md`、`references/mcp.md`：正式模式入口。
- `references/simple-query-guide.md`：查询参数、公式和对比（构造阶段仅在模板不足时读取）。
- `references/chart-excel-guide.md`：图表查询、小计/总计与 Excel 导出。
- `references/result-analysis.md`：复杂分析的完整证据合同。
- `references/feedback-guide.md`：意外失败反馈。
- `QUERY_SPEC.md`：仅 MCP 部署契约存档，CLI-only 会话不要读取。

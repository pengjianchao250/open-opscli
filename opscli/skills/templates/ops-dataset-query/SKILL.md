---
name: ops-dataset-query
description: >
  运营数据查询取数 Skill。用于按当前账号可见的数据集查询销售、库存、广告、物流、
  流量等数据，支持趋势、环比同比、ACOS/ROAS、图表 UUID 查询和导出。
  加载本 Skill 后必须先读取本目录 SKILL.md 并遵循其流程：CLI 取数默认且优先的入口是
  一体化流程 python3 scripts/query_flow.py "<用户请求>"（内部只规划一次并直接执行；
  规划器按 30 秒命令窗口设计，返回 refresh_in_progress 时按其 recovery_command
  等待重跑即可，禁止自行升级）；只有规划器客观不可用（澄清/阻断、脚本报错重跑仍失败、
  命令窗口连续超时、运行环境缺 python3）时才转 SKILL.md 的降级路径；
  任何路径都禁止凭记忆手拼查询参数或使用未经元数据核对的字段。
version: 1.3.18
---

# ops-dataset-query

仅通过正式 CLI 或 MCP 查询当前授权范围内的运营数据；不直接访问后端 HTTP 接口。

## 适用范围与模式

用于查数据、取数、报表、趋势、对比、聚合或导出。一次请求固定一种模式：

- **CLI-only**：本地 shell 和 `opscli` 可用；优先运行下方规划器（规划器客观不可用时按「规划器不可用时的降级路径」处置），构造正式命令时再按需读取 `references/cli.md`。
- **MCP-only**：仅有 Connector/MCP；使用当前已认证账号的 `query_metadata`，按需读取 `references/mcp.md`。

用户明确指定模式时遵从指定；不要在同一请求中混用或自动切换模式。

## 查询规划主线

**CLI 主线的优先入口是 `query_flow.py`。** 它内部只运行一次规划器；`dataset_query + planned` 直接按规划器原始 `query_template` 执行，其他状态或 `chart_uuid` 返回规划合同供 Agent 处置。仅当合同命中具体歧义时才读取 `references/rules.md`，并按 `references/ask-user-question-guide.md` 澄清；无歧义不拆分步骤。规划器命中「规划器不可用时的降级路径」中列举的客观失败条件时才改走降级，其余情况一律走本入口。

### CLI-only：一次规划并执行

读完本文件后直接运行一体化入口；除合同明确要求澄清、恢复或图表 UUID 分流外，不再单独调用 `query_plan.py` 或 `run_query.py`。**规划器路径下**不要预读 `data/VERSION.json`，不要列目录，不要检查脚本源码，不要扫描 `data/`、`scripts/` 或 `references/`；流程已完成版本、选表、字段、公式、时间口径、权限合同、完整性绑定和正式查询。（这些本地探索限制只在规划器可用时生效，降级态的放宽见文末降级章节。）

```bash
python3 scripts/query_flow.py "$USER_REQUEST" --result-dir "$RESULT_DIR"
```

**正常路径工具调用预算**：数据集、字段、筛选和时间均可确定时，Agent 从加载本 Skill 到拿到查询结果最多 3 次工具调用，且正式查询只调用一次 `query_flow.py`。包含一次澄清、一次恢复或图表结果证据补全的非正常路径最多 7 次。规划器路径下禁止为了“确认环境/字段/语法”调用 `opscli query catalog`、`opscli query metadata`、`--help`、`rg`、`ls`、`find` 或读取脚本源码；禁止重复加载同一 Skill；禁止生成临时 Python 查询脚本；禁止手工修改 plan、复制 `query_template` 后另拼 payload，或在一体化入口成功后再次查询相同范围。

**命令窗口与等待（30 秒窗口设计）**：平台单条命令的有效等待上限约 30 秒（自行设置更大超时无效）。规划器内部已按此窗口设计——任意单次调用确定性返回：数据就绪时（常态）1~3 秒；需要刷新元数据时前台最多等 8 秒，未完成则**转后台续跑**并返回 `status=blocked, recovery_state=refresh_in_progress`，此时**直接执行其 `recovery_command`**；连续 3 次仍未就绪即转「规划器不可用时的降级路径」，降级也走不通才提交反馈并停止。禁止自行执行任何升级动作、禁止在规划器仍可用时因等待改走旁路探查。若命令仍偶发窗口超时：原样重跑一次即可（流程幂等）；同一请求累计 3 次窗口超时按客观失败转降级。

用户请求含引号等特殊字符时改用 `--query-file <文件>`。用户明确指定字段时追加重复的 `--field "$FIELD"`。一体化入口返回查询结果时直接分析；返回规划合同时只处理默认 `model_view`、`answer_contract` 和 `execution_ref`，不得读取内部合同补充回答：

1. `data_state` 不是 `ready`：规划器已内置一次自动升级兜底；若仍返回 `status=blocked`，按规划结果中 `model_view.recovery_command`（即 `opscli skills upgrade ops-dataset-query`）执行后从头开始，刷新仍失败则向用户说明元数据异常并停止，不反复重试。登录或账号变更、元数据所有权不明或数据状态不匹配时也必须刷新或升级；客户端不推断账号身份。
2. `status=clarify_required`：按 `clarification_messages_zh` 提问；规划结果给出 `dataset_candidates_zh`（候选卡片）、`field_suggestions_zh`（近似字段建议）或 `pending_confirmations_zh` 时，必须把它们作为选项/口径呈现；确认后把明确口径写回用户请求并重新规划。`blocked` 则按 `recovery_command`/阻断原因处置。
   - 未明确指定数据集时，规划器优先检查当前账号已授权的“即时综合数据集”。如果已明确的业务和查询字段全部覆盖，`default_dataset_recommendation_zh.auto_selected=true`，直接按该数据集继续，不调用提问工具；如果请求没有命中任何具体查询字段、仍无法确定要查什么，则 `confirmation_required=true`，才询问是否采用推荐数据集及推荐字段。用户拒绝时让用户从 `dataset_candidates_zh` 选择其他数据集，不得循环推荐。
3. `model_view` 只含用户可见中文结论；最终回答必须覆盖 `answer_contract.required_disclosures_zh`，并遵守 `forbidden_outputs_zh`。
4. **时间口径以规划结果为准**：`model_view.time_scope_zh`、`model_view.time_resolution_zh` 与 `execution_ref.time_scope` 是唯一日期窗口来源。`本月/上月/近7天/近30天/近30tian` 等未显式年份的相对描述，由规划器直接调用 Python `datetime`，按 Asia/Shanghai 当前日期和当前年份确定绝对日期（`本月` 为整自然月：1 日至月末，月末未到只作数据更新进度披露）；跨年边界以 Python 日历结果为准。禁止自行心算、猜测年份、使用模型知识截止时间或改写规划结果。相对时间一旦被规划器唯一解析，展示绝对日期后直接执行，不再要求用户确认；只有 `is_default=true`（原文未给任何时间）才必须询问是否采用默认近 30 天。复杂任务拆成子步骤时，每次调用规划器都必须带上原请求或已锁定的绝对起止日期，禁止只传丢失时间范围的步骤摘要。
5. `platform_semantic_members` 表示请求语义：用户只说“亚马逊”且未指定 SC/VC 时默认包含亚马逊SC + 亚马逊VC；明确亚马逊SC/SC 时只含 SC，明确亚马逊VC/VC 时只含 VC。`platform_filter_state=requires_permission_enum` 时规划器默认已自动枚举并回灌（规划结果带 `platform_enum_source=auto_enum_service` 即已收敛）；仅当自动枚举未完成时，直接执行规划结果内嵌的 `execution_ref.platform_enum_command`，再把返回值作为重复的 `--authorized-platform-value` 传回规划器、取得终版规划结果。裸“亚马逊”只枚举到部分成员时，直接按 `platform_effective_members` 和 `resolved_platform_values` 查询可用部分，但必须原样披露 `platform_scope_disclosures_zh`，不得把部分结果表述为完整亚马逊范围。
6. `execution_ref` 仅用于正式查询构造，禁止作为业务判断理由或向用户展示。`dimensions`/`metrics` 中 `selection_source=recommended` 的字段是系统推荐（用户未点名），确认前规划器不会下发 `query_template`。`status=planned` 时一体化入口直接执行完整性摘要绑定的原始模板；Agent 不得提取、编辑或重新拼装该模板。
7. `query_mode=chart_uuid` 时无需本地数据集元数据，规划器会输出 `chart_uuid`、`chart_action` 和可直接执行的 `query_command`。必须读取 `references/chart-excel-guide.md`，直接执行该命令；不得再用普通数据集选表或 `run_query.py` 改写。多个 UUID 时规划器返回 `clarify_required`，确认后把单个 UUID 写回原请求重跑规划器。

`query_component` 只用于权限枚举，不是业务结果数据集。自然语言选表只依据当前账号元数据中的中文名称和中文说明；英文 key 仅在用户明确给出精确完整技术标识时精确匹配，不能从中文请求推断或模糊匹配。

### MCP-only：当前请求元数据

用本次 `query_metadata` 返回的当前账号数据集按相同规则归一为 `candidate_ready` 或 `clarify_required`。选定后只使用 `query_metadata(dataset=...)` 的字段和 `select_columns`；认证或元数据失败时阻断选择，不从本地缓存、历史输出或其他账号补齐。

### 多数据集计算与 Excel 交付

用户明确指定两个及以上 `table_id`，或要求跨表关联、派生计算、Excel 交付时，
这是**多数据集编排任务**，不是一次单表规划。前述“只调用一次 `query_flow`”与
3 次工具调用预算改为**对每个独立子查询分别生效**；禁止把整段请求交给一个单表
规划结果后，拿该表的字段、日期或筛选去替代其他表。

1. 先把请求拆成逐表查询清单，保留用户原文里的精确 `table_id`、字段、筛选和时间。
   平台口径按“正向集合减显式排除集合”解释：`platform_name=Amazon` 且排除
   `Amazon VC` 时，有效范围只能是当前账号授权枚举中的 Amazon 非 VC 成员；
   禁止把被排除项重新扩入。
2. **每张快照表独立**探查并锁定自己的最新有效快照日；库存、库龄、单价可能日期
   不同，不得用一张表的最大日期覆盖其他表。销售表使用用户指定日期；“当天”就是
   Asia/Shanghai 的**执行当天**，不得改成昨天。库龄“超6月”是 **181 天以上**
   的业务阈值，不是某年 6 月，也不得写入日历日期过滤。
3. 筛选只作用于用户指定的表；例如“未税单价必须过滤 `team_username=何子影`”
   只下推到单价表，除非用户也明确要求其他表同样过滤。各筛选字段和值仍须通过该表
   元数据与当前账号组件枚举验证。
4. 每个子查询都必须取到全量后才能关联或生成 Excel。检查 CLI 的
   `disclosures` 或 MCP 的 `result_disclosures` 中 `row_count_returned`、
   `total_count` 与 `truncated`；
   只有 `truncated=false` 才可进入计算。自动补齐仍被 5000 行硬上限截断或补齐失败时，
   继续按正式分页能力取全；无法取全则停止交付，不得拿默认 20 行或局部样本生成“全量”报表。
5. 关联键必须是各表元数据共同确认的业务键，不凭字段名猜测。以库存/库龄商品全集为
   保留侧，向销售表做 **LEFT JOIN**；无销售记录按 `order_qty=0` 处理，与
   `order_qty<=0` 一并标记为未售出。禁止改写成 `order_qty>0` 的服务端筛选，
   因为它会删除恰需保留的未售出商品。若用户只要未售出清单，必须在 LEFT JOIN 和
   空值补零后再在本地筛选。
6. 派生列只在全量关联后计算：可用库存采购金额 = 可用库存 × 未税单价；
   超6月数量 = 元数据核定的 181 天以上九个库龄分段之和；超6月采购金额 =
   超6月数量 × 未税单价。九个分段、连接键、缺失单价/库龄、各表快照日及行数必须写入
   Excel 的口径说明；缺失价格不得默认为 0。

CLI 与 MCP 均遵守此编排合同。每个单表子查询仍走本 Skill 的正式规划/元数据路径；
Excel 的格式、明细、口径页与校验按 `references/chart-excel-guide.md` 执行。

## 构造与执行

1. CLI 查询参数由规划器生成并由一体化入口原样执行；Agent 不再参与拼参。降级态下参数只能取自 `execution_ref.fallback_catalog` 或 `local_fallback.py` 候选目录，仍禁止凭记忆手拼。MCP 字段只采用当前数据集 metadata。
2. 不发明默认筛选。未指定筛选时只说明 `current_authenticated_account` 可见范围；明确筛选必须先经组件枚举——平台走规划结果的自动枚举/`platform_enum_command`，部门/国家等其他筛选用 `execution_ref.filter_components` 中对应组件的 `component_table_id` 查枚举，并严格遵守 `execution_ref.filter_value_match_policy`：先做规范化完整等值比较，部门名称额外允许阿拉伯数字与中文数字等价；唯一等值命中时只使用该枚举原值并直接执行，禁止再次询问用户是否采用，也禁止把仅包含请求文本的其他成员一并加入（`9部` 只匹配 `九部`，不匹配 `项目九部`；`范泰克` 只匹配 `范泰克`，不匹配 `范泰克体系外`）。无唯一等值命中时停止并让用户重选，不得用子串模糊扩展；组件不可用时只阻断该筛选，不扩大范围。
3. 环比、同比和上期对比必须同时传主周期日期 `filters` 与 `dataComparison`（模板已按 `time_scope` 预填，执行器也会硬校验）。
4. **执行确认分级**：数据集、字段、时间、筛选、排序、行数全部无歧义时，用一段中文陈述式披露口径后**直接执行，不等待用户回复**；只有 `clarify_required`、默认时间口径未确认、或含 `recommended` 字段未说明时才通过提问等待确认。
5. `query_mode=dataset_query` 的 CLI 正常路径只用一体化流程（内含规划、完整性校验、执行前校验、排序生效校验与兜底、截断披露和证据合同）：

```bash
python3 scripts/query_flow.py "$USER_REQUEST" --result-dir "$RESULT_DIR"
```

   - 默认条件（filter_configs）：规划结果存在 `default_filters` 时，流程自动传给执行器；最终回答必须披露 `default_filters_zh`。默认条件由服务端权威应用，用户为同字段提供条件时覆盖默认值，客户端不重复注入。

   `query_plan.py` + `run_query.py` 不是 Agent 的规划器正常路径（仅用于维护者复现审计，以及降级态的执行通道）。执行器会校验规划摘要、状态、tableId、授权字段、模板及时间范围。正式查询偶尔较慢（排序兜底还可能放大窗口重查一次），命令窗口超时不是失败：**原样重跑一次**即可。流程返回 `precheck_failed` 时按 `next_action_zh` 重新运行规划器，禁止编辑 plan 或绕过执行器直连；一体化入口返回 `status=flow_error` 或退出码 2 时原样重跑一次，仍失败即转「规划器不可用时的降级路径」；`disclosures.order_fallback` 存在时必须披露本地兜底。MCP-only 用正式 `query_simple`。
6. `query_mode=chart_uuid` 时原样执行 `execution_ref.query_command`。`chart_action=run` 必须遍历所有 `queries`，保留服务端小计/总计并按 `_query_index` 区分来源；大结果按 `references/chart-excel-guide.md` 使用 `--save-result` 或 `--result-file` 落盘，随后补一次 `evidence_contract.py`。
7. 保留用户要求的明细和全量范围。限制展示时声明排序、截断数量和总行数（执行器 `disclosures` 已给出），不把局部结果说成全量。
8. **预览只是抽样，行数口径以 `disclosures` 为准**：`preview_rows` 只展示前若干行，完整结果写在 `disclosures.full_result_file`。判断口径按下面三个字段，**不要**用预览行数下结论：
   - `row_count_returned` = 本次实际拿到的行数，`total_count` = 服务端报的总行数；结论里的"共 N 条"必须用 `row_count_returned`，并在两者不等时说明。
   - `truncated=true` 表示拿到的是**部分结果**，必须如实声明，禁止说成全量。
   - 出现 `server_paging` 时按 `server_paging_disclosure_zh` 披露：服务端不带 `limit` 时只回默认页，执行器已自动重查补齐；补齐失败（`auto_complete_applied=false`）时结论必须声明这是部分结果。

   需要逐行数据时直接读 `full_result_file`（该文件含补齐后的 `rows_after_auto_complete`）；`full_result_file` 为 null 时看 `full_result_file_error`。**禁止**为了凑齐剩余行而改写请求重查、分批排除已见值、或绕过执行器手拼 payload 直连 `opscli query simple`——那样既浪费调用预算，又丢掉执行器的授权字段校验。

## 结果分析

CLI-only 常规结果分析不要读取 `references/result-analysis.md`：`run_query.py` 输出已内嵌 `evidence_contract`，直接使用；仅在旁路直连（MCP 或图表入口）拿到裸结果时，才用 `python3 scripts/evidence_contract.py --input result.json`（或 stdin）补一次，每轮最多运行一次。只用其 `required_evidence`、`required_disclosures_zh` 和 `forbidden_inferences_zh` 组织结论：

- 先说明数据集中文名、时间、维度、指标、筛选、币种、聚合、排序和行数；每个数值结论附字段名、结果列或回放证据。字段称呼使用元数据 `verbose_name` 原文，不意译。
- 遵守 `numeric_evidence_policy_zh`，结论或证据中的关键数值保持返回精度，不自行四舍五入。
- 0 行只能说明没有返回记录，不能判断业务为 0；全零不等于无数据；空值不等于 0。
- 周期比较只使用已返回的本期、`last_*`、`diff_*`、`pct_*` 列，缺列时说明无法比较。不同原币不得混加，也不得与 CNY 列混加。
- 全局币种换算：用户请求含币种意图（"用美元/按 USD/加元口径"等，仅支持 USD/GBP/CAD/EUR/JPY/CNY）时，规划器自动把 `globalCurrency` 写入 `query_template` 并纳入 integrity 哈希——禁止手工增删改写该键，直接执行模板即可；结论中须披露金额已按该币种换算。未识别到币种意图时不注入，由后端回退用户默认配置。
- Top N 或截断必须披露排序、展示数和总行数；未查询范围不得外推。
- 披露权限、样本、公式和数据新鲜度。没有刷新完成度或外部证据时，不把末日异常当成业务事实，也不得声称因果。

MCP-only（无本地 shell）、复杂审计或用户明确要求完整披露证据合同时，才读取 `references/result-analysis.md` 并按其五节结构输出。

## 纠错与反馈

用户说结果、字段、条件、口径、排序或条数不对时，带当前参数移交 `ops-query-wizard`，不猜测性反复重试。0 行、澄清、认证未就绪和用户取消不是意外故障。

查询返回「未登录，请运行: opscli auth login」时：沙箱/托管环境的 opscli 凭证由平台自动注入，**禁止执行交互式 `opscli auth login`**（无人环境的 Device Flow 永远无法完成，只会空耗时间）。正确处置：等待约 1 分钟后原样重试同一查询一次；仍未登录则停止取数，向用户如实说明环境凭证异常，并按 `references/feedback-guide.md` 提交一次反馈。

仅发生意外 opscli/MCP 失败时读取 `references/feedback-guide.md` 并立即提交一次去重的结构化反馈；成功查询不自动提交反馈。

## 规划器不可用时的降级路径

规划器是**优先路径而非唯一路径**：命中下表任一**客观失败**条件才进入降级，其余情况一律走一体化入口。降级态同样**不要自行编造数据集或字段**。合同里的 `model_view.fallback_level`、`model_view.no_guess_policy_zh` 与 `execution_ref.fallback_catalog` 会指明当前处在哪一层。

### 降级触发条件（满足其一即可降级）

| 触发条件 | 判断依据 |
| --- | --- |
| 规划器要求澄清或阻断 | 返回 `status=clarify_required` / `blocked`：先按合同澄清或执行 `recovery_command`，仍无法进入 `planned` 才降级 |
| 一体化入口自身报错 | `query_flow.py` 返回 `status=flow_error` 或退出码 2，原样重跑一次仍失败 |
| 规划器不可重试地异常退出 | `query_plan.py` exit 2 且错误 JSON `retryable=false`，且 `next_action_zh` 无可执行动作 |
| 命令窗口连续超时 | 同一请求原样重跑后仍在 30 秒窗口内无返回，累计 3 次 |
| 运行环境不可用 | 无 `python3`、Skill 脚本缺失或依赖导入失败，规划器根本跑不起来 |

**不构成降级理由**：0 行结果、用户取消、预期内的未登录（按「纠错与反馈」处置）、主观觉得规划器不合适、想省一次工具调用。降级路径的最终回答必须说明本次取数走的是降级路径以及原因。

### 降级层级

| 层级 | 判断依据 | 动作 |
| --- | --- | --- |
| L1 | `execution_ref.fallback_catalog` 有 dimensions/metrics | 只用该目录里的 `table_id`、`dataset_alias`、`field_name` 构造查询；澄清点按 `clarification_messages_zh` 向用户提问 |
| L2 | 目录为空或选表失败 | 跑 `python3 scripts/local_fallback.py "<用户原文>"` 拿本地候选，按其 `next_action_zh` 处置 |
| L3 | `data_state` 为 `placeholder`/`empty`，或目录不存在 | 执行返回的 `recovery_command` 刷新元数据后重跑；**此前不得构造任何查询** |
| L4 | 上述都失败 | 停止取数，如实告知用户，按 `references/feedback-guide.md` 提交一次反馈 |

降级态下前述「禁止本地探索」的限制放宽为：**允许**读 `data/*.csv`、`data/dataset_profiles.json` 与运行 `scripts/local_fallback.py`；仍然**禁止** `rg`/`ls`/`find`、读脚本源码、生成临时查询脚本。降级路径额外预算 3 次工具调用。

`local_fallback.py` 常用形态：

```bash
python3 scripts/local_fallback.py "<用户原文>"                                  # 出候选
python3 scripts/local_fallback.py "<用户原文>" --field 渠道 --field ASIN         # 带点名字段
python3 scripts/local_fallback.py "<用户原文>" --dataset <alias> --emit-plan /tmp/fb-plan.json
```

拿到候选后：

1. `status=clarify_required` → 用 `AskUserQuestion` 让用户在候选里选，**不要默认取第一个**
2. `status=ready` → 两条执行通道并列可选，按环境选一条：
   - 带 `--emit-plan` 产出 plan，再走 `python3 scripts/run_query.py --plan-file <plan> --json '<payload>'`：保留执行器字段校验闸，payload 里出现目录之外的字段会被直接拒绝；
   - 直连 `opscli query simple`：不经执行器校验，适用于 `run_query.py` 也跑不起来的环境。此时字段仍只能取自候选目录，且必须在回答中说明本次查询未经执行器字段校验
3. 候选里的 `hard_constraints` / `avoid_when` 必须遵守（如库存快照字段只能用于明细表），`clarify_when` 命中时先问用户
4. 候选里的 `uncertified_hints_zh` 是**未经人工审核的业务约束提示**（当前多数画像 `certified=false`，其业务约束都落在这个键里而不是 `hard_constraints`）。处置方式与 `hard_constraints` 不同：**必须先向用户复述该条提示并确认，再决定是否套用**，不得当作已确认口径静默应用，也不得因为它不是 `hard_constraints` 就忽略——被降级的往往正是防错数的护栏（如「总库存、海外仓库存属于库存快照字段，只能用于明细表或无聚合过滤条件」「必须选择报告周期」）
5. `filter_components` 中字段的筛选值，必须先查 `component_dataset_alias` 组件表枚举当前账号授权原值，完整等值命中后才写入 `filters`；枚举不到就停止，**不得放大为全范围查询**

## 按需参考

- `references/rules.md`：歧义和口径检查。
- `references/ask-user-question-guide.md`：结构化澄清与执行确认。
- `references/cli.md`、`references/mcp.md`：正式模式入口。
- `references/simple-query-guide.md`：查询参数、公式和对比（构造阶段仅在模板不足时读取）。
- `references/chart-excel-guide.md`：图表查询、小计/总计与 Excel 导出。
- `references/result-analysis.md`：复杂分析的完整证据合同。
- `references/feedback-guide.md`：意外失败反馈。
- `QUERY_SPEC.md`：仅 MCP 部署契约存档，CLI-only 会话不要读取。

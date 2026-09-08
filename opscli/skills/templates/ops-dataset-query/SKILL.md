---
name: ops-dataset-query
description: >
  运营数据查询取数 Skill。用于按当前账号可见的数据集查询销售、库存、广告、物流、
  流量等数据，支持趋势、环比同比、ACOS/ROAS、图表 UUID 查询和导出。
  加载本 Skill 后必须先读取本目录 SKILL.md 并遵循其流程：CLI 取数默认且优先的入口是
  一体化流程 opscli query flow "<用户请求>"（内部只规划一次；单币种执行一次，
  多币种按币种分别调用取数服务；
  规划器按 30 秒命令窗口设计，返回 blocked 且带 recovery_command 时按其处置后重跑
  即可，合同未给出 recovery_command 时不得自行升级）；只有规划器客观不可用（澄清/阻断、命令报错重跑仍失败、
  命令窗口连续超时、opscli 命令无法启动）时才转 SKILL.md 的降级路径；
  任何路径都禁止凭记忆手拼查询参数或使用未经元数据核对的字段。
version: 1.4.6
---

# ops-dataset-query

仅通过正式 CLI 或 MCP 查询当前授权范围内的运营数据；不直接访问后端 HTTP 接口。

## 适用范围与模式

用于查数据、取数、报表、趋势、对比、聚合或导出。一次请求固定一种模式：

- **CLI-only**：本地 shell 和 `opscli` 可用；优先运行下方规划器（规划器客观不可用时按「规划器不可用时的降级路径」处置）。`references/cli.md` **不是主线必读**：只跑 `opscli query flow` 的正常路径不要读；仅在需要显式追加 `--limit` / `--order-by` / `--offset` / `--query-file`、走降级手工路线、或合同给出 `recovery_command` 需要核对命令形态时才读取。
- **MCP-only**：仅有 Connector/MCP；优先调用内核规划器工具 `query_flow`（需传输层已验证账号），不可用时按 `references/mcp.md` 用当前已认证账号的 `query_metadata` + `query_simple` 手工路线。

用户明确指定模式时遵从指定；不要在同一请求中混用或自动切换模式。

## 查询规划主线

**CLI 主线的优先入口是 `opscli query flow`。** 它内部只运行一次规划器；`dataset_query + planned` 的单币种请求直接执行原始 `query_template`，多币种请求逐项执行完整性绑定的 `query_templates`，其他状态或 `chart_uuid` 返回规划合同供 Agent 处置。仅当合同命中具体歧义时才读取 `references/rules.md`，并按 `references/ask-user-question-guide.md` 澄清；无歧义不拆分步骤。规划器命中「规划器不可用时的降级路径」中列举的客观失败条件时才改走降级，其余情况一律走本入口。

### CLI-only：一次规划并执行

读完本文件后直接运行一体化入口；除合同明确要求澄清、恢复或图表 UUID 分流外，不再单独调用 `opscli query plan`、`opscli query run`。**规划器路径下**不要预读 `data/VERSION.json`，不要列目录，不要检查脚本源码，不要扫描 `data/`、`scripts/` 或 `references/`；流程已完成版本、选表、字段、公式、时间口径、权限合同、完整性绑定和正式查询。（这些本地探索限制只在规划器可用时生效，降级态的放宽见文末降级章节。）

```bash
opscli query flow "$USER_REQUEST" --result-dir "$RESULT_DIR"
```

`--result-dir` 必须显式传入：内核入口只有传了该参数才会把全量结果落盘并把返回体中的结果收窄为预览行，不传则不做截断，大结果集会原样进入返回体、撑爆上下文。万一漏传且行数超过 20 行，`result_disclosures` 会出现 `large_result_warning_zh` 兜底提示，看到该键必须原样重跑并补上 `--result-dir`，不能忽略。

**合同都在 `data` 下**：CLI 输出固定为 `{"success", "command", "data", "error"}` 包裹体，全部合同键（`status` / `model_view` / `execution_ref` / `answer_contract` / `result` / `result_disclosures` / `evidence_contract`）都在 `data` 里，不在顶层；`success=false` 时看 `error.code` / `error.message`。MCP 工具返回同形。下文提到的合同键名一律指 `data` 内的路径。

**正常路径工具调用预算**：数据集、字段、筛选和时间均可确定时，Agent 从加载本 Skill 到拿到查询结果最多 3 次工具调用，且正式入口只调用一次 `opscli query flow`；多币种时由该入口在内部按币种分别调用取数服务，不额外消耗 Agent 工具调用。**图表路径同样是 3 次**：读本 SKILL.md + `opscli query flow`（分流出 `chart_uuid` 与可直接执行的 `query_command`）+ 执行该 `query_command`；图表结果已自带 `evidence_contract`，不需要补跑证据脚本。只有确实需要图表字段映射、异常检测或 Excel 导出时才读 `references/chart-excel-guide.md`，那次读取算第 4 次。包含一次澄清或一次恢复的非正常路径最多 7 次。规划器路径下禁止为了“确认环境/字段/语法”调用 `opscli query catalog`、`opscli query metadata`、`--help`、`rg`、`ls`、`find` 或读取脚本源码；禁止重复加载同一 Skill；禁止生成临时 Python 查询脚本；禁止手工修改 plan、复制 `query_template` 后另拼 payload，或在一体化入口成功后再次查询相同范围。

**命令窗口与等待（30 秒窗口设计）**：平台单条命令的有效等待上限约 30 秒（自行设置更大超时无效）。规划器内部按此窗口设计——数据就绪时常态数秒到 30 秒内返回；**首次调用会同步刷新一次用户级元数据缓存，整条命令可能耗时到 60 秒**：超过 30 秒不要中断，等命令自然返回即可。元数据未就绪时内核会**同步刷新一次**用户级元数据缓存（无前台/后台分段），仍不就绪即返回 `status=blocked, recovery_state=refresh_failed` 并附 `recovery_command`（即 `opscli skills upgrade ops-dataset-query`），此时**执行该命令后原样重跑**；重跑仍 `blocked` 即转「规划器不可用时的降级路径」，降级也走不通才提交反馈并停止。合同未给出 `recovery_command` 时禁止自行发起任何升级动作，也禁止在规划器仍可用时因等待改走旁路探查。若命令偶发窗口超时：原样重跑一次即可（流程幂等）；同一请求累计 3 次窗口超时按客观失败转降级。

用户请求含引号等特殊字符时改用 `--query-file <文件>`。用户明确指定字段时追加重复的 `--field "$FIELD"`。一体化入口返回查询结果时直接分析；返回规划合同时只处理默认 `model_view`、`answer_contract` 和 `execution_ref`，不得读取内部合同补充回答：

1. `data_state` 不是 `ready`（规划合同里只有 `ready` / `missing` / `not_required` 三种取值）：规划器已内置一次同步刷新兜底；若仍返回 `status=blocked, recovery_state=refresh_failed`，按规划结果中 `model_view.recovery_command`（即 `opscli skills upgrade ops-dataset-query`）执行后从头开始，刷新仍失败则向用户说明元数据异常并停止，不反复重试。登录或账号变更、元数据所有权不明或数据状态不匹配时也必须刷新或升级；客户端不推断账号身份。
2. `status=clarify_required`：按 `clarification_reason_codes` + `clarification_messages_zh` 提问；规划结果给出 `dataset_candidates_zh`（候选卡片）、`field_suggestions_zh`（近似字段建议，形态 `[{requested, candidates_zh[]}]`；`metric_not_in_dataset` 时指出当前数据集没有点名的指标，`dimension_not_in_dataset` 时指出「各X/每个X」点名的分组维度不在当前数据集，两类被点名却找不到的字段同时列在 `model_view.unknown_requested_fields`）、`component_candidates_zh`（筛选组件当前账号可见取值，`component_filter_*` 类澄清时下发）、`unsupported_currencies`（白名单外币种，`unsupported_currency` 时下发）或 `pending_confirmations_zh` 时，必须把它们作为选项/口径呈现；确认后把明确口径写回用户请求并重新规划。`blocked` 则按 `recovery_command`/阻断原因处置；`next_action=report_component_enum_defect` 表示组件枚举调用失败（网络/代理抖动或组件元数据异常）——原样重跑一次，仍失败按 `references/feedback-guide.md` 提交一次反馈并停止，不得放大为全范围查询。
   - 未明确指定数据集时，规划器优先检查当前账号已授权的“即时综合数据集”。该推荐表通过业务与字段指导校验后，`default_dataset_recommendation_zh.auto_selected=true` 且 `confirmation_required=false`，直接按该数据集继续，不调用提问工具，也不得因其他普通数据集的文本打分更高而改选。用户显式指定数据集、明确拒绝推荐表，或请求命中账单销售、流量转化等专用业务提示时，仍按对应数据集处理。请求没有命中任何具体查询字段、仍无法确定要查什么时，只询问采用哪些推荐字段，不再二次确认数据集；推荐表本身不满足业务或字段要求时仍按候选歧义正常澄清，不得强行使用。
3. `model_view` 只含用户可见中文结论；最终回答必须覆盖 `answer_contract.required_disclosures_zh`，并遵守 `forbidden_outputs_zh`。
4. **趋势/按日/每天类表述**（「按日趋势」「每天的」「趋势」等）规划器会自动把数据集主日期字段加为分组维度，并在 `answer_contract.required_disclosures_zh` 说明「按日期序列表述」；结论必须按日期序列讲，不得只报合计。原文含「不按日拆分」等否定语境时不加。**排序由规划器负责**：模板含时间粒度维度（日期/月份等）且用户未点名排序时，规划器已把 `orderBy: [{"field": <日期字段>, "desc": false}]`（按日期升序）写进模板；执行器若发现服务端未按此排序会本地重排，并在 `result_disclosures.order_fallback` / `order_disclosure_zh` 披露。Agent 不需要、也不得自行对趋势结果重新排序或改写模板排序。
5. **时间口径以规划结果为准**：`model_view.time_scope_zh`、`model_view.time_resolution_zh` 与 `execution_ref.time_scope` 是唯一日期窗口来源。`本月/上月/近7天/前7天/近30tian/Aug 2026/2026 Aug` 等相对或英文月份描述，由规划器直接调用 Python `datetime`，按 Asia/Shanghai 当前日期和当前年份确定绝对日期（`本月` 为整自然月：1 日至月末，月末未到只作数据更新进度披露）；跨年边界以 Python 日历结果为准。禁止自行心算、猜测年份、使用模型知识截止时间或改写规划结果。相对时间一旦被规划器唯一解析，展示绝对日期后直接执行，不再要求用户确认；只有 `is_default=true`（原文未给任何时间）才必须询问是否采用默认近 30 天。复杂任务拆成子步骤时，每次调用规划器都必须带上原请求或已锁定的绝对起止日期，禁止只传丢失时间范围的步骤摘要。
6. `platform_semantic_members` 表示请求语义，**一律是展示名**（亚马逊SC / 亚马逊VC / TikTok / Walmart / Wayfair / Temu / Shopify / SHEIN / 山姆），不是内部键，可直接向用户复述；内部枚举名保留在 `execution_ref.platform_semantic_keys`。用户只说“亚马逊”且未指定 SC/VC 时默认包含亚马逊SC + 亚马逊VC；明确亚马逊SC/SC 时只含 SC，明确亚马逊VC/VC 时只含 VC。**收敛判据**：`execution_ref.platform_filter_state=resolved` 且 `execution_ref.resolved_platform_values` 非空即已收敛，直接进入执行（`platform_enum_source=auto_enum_service` 只在自动枚举路径出现，不是唯一判据，没有它不代表未收敛）。仍为 `requires_permission_enum` 时说明自动枚举未完成（实时枚举与本地枚举缓存都不可用），规划器不会下发模板：先恢复登录态或等待组件服务可用后原样重跑，不得手工执行 `execution_ref.platform_enum_command` 后自行拼装平台值。裸“亚马逊”只枚举到部分成员时，直接按 `platform_effective_members` 和 `resolved_platform_values` 查询可用部分，但必须原样披露 `platform_scope_disclosures_zh`，不得把部分结果表述为完整亚马逊范围。
7. `execution_ref` 仅用于正式查询构造，禁止作为业务判断理由或向用户展示。需确认的合同里 `dimensions`/`metrics` 条目带 `selection_source=recommended`（系统推荐、用户未点名；`planned` 合同不带该键），确认前规划器不会下发 `query_template`。`status=planned` 时一体化入口直接执行完整性摘要绑定的原始模板；Agent 不得提取、编辑或重新拼装该模板。
8. `query_mode=chart_uuid` 时无需本地数据集元数据，规划器会输出 `chart_uuid`、`chart_action` 和可直接执行的 `query_command`。直接执行该命令（返回自带 `evidence_contract`），不得再用普通数据集选表或手工改写；只有需要图表字段映射、异常检测或 Excel 导出时才读 `references/chart-excel-guide.md`。多个 UUID 时规划器返回 `clarify_required`，确认后把单个 UUID 写回原请求重跑规划器。
9. **快照指标的时间窗口会被收敛**：指标带 `is_snapshot=true`（元数据 `snapshot_metric=1`，如总库存、平台库存）且本次没有按时间粒度维度分组时，多日窗口自动收敛为**最新完整快照日**（今天之前的最后一天）：`execution_ref.snapshot_policy = {policy: "latest_complete_snapshot_day", snapshot_day, requested_window: {start, end}, metrics[]}`，`model_view.time_scope_zh` 以「快照口径：最新完整快照日 …」开头，`answer_contract.required_disclosures_zh` 含「快照指标已按最新完整快照日 X 取值…未跨日累加」。结论必须说明这是该快照日的库存切面，不得表述为整个请求窗口的累计或平均。按日期维度分组（每天/趋势）时保留完整窗口不收敛，按日展示快照序列；环比/同比时主周期与对比周期各取该周期末日的快照。快照指标与流量指标（销售额等）混查且未按日分组时，规划器返回 `clarify_required` + 澄清码 `snapshot_metric_window_conflict`：提示用户改按日期维度分组，或把两类指标拆成两次查询，不得自行放行。
10. **字段称呼被映射时必须披露**：用户用稳定别名点名（订单量/单量 → 销量，销售金额/收入 → 销售额，广告花费 → 广告费，毛利额 → 毛利，采购费用 → 采购成本）而实际落到数据集口径字段时，`model_view.field_alias_mappings_zh = [{requested, field_zh, field_name}]`，且 `required_disclosures_zh` 含「字段称呼已按数据集口径对应：「订单量」对应「销量」…」。结论必须以数据集口径命名（用 `field_zh`），并说明该对应关系，不得沿用用户原词静默替换。完整授权字段标签优先于其中的稳定短别名：例如“主营业务收入”“市场总销量”中的“收入”“销量”不构成额外指标诉求；只有短别名在完整标签之外独立出现时才另算一项。已确认的数据集完整名称只用于选表，不得再次从名称中提取指标、维度或组件筛选值。

`query_component` 只用于权限枚举，不是业务结果数据集；只有用户明确请求枚举/可用值（“有哪些渠道可选”“列出当前可见部门”）时才可作为查询目标并生成可执行的维度查询模板，普通业务分析仍须阻断。自然语言选表只依据当前账号元数据中的中文名称和中文说明；英文 key 仅在用户明确给出精确完整技术标识时精确匹配，不能从中文请求推断或模糊匹配。组件筛选值必须来自用户点名值与当前账号授权枚举的完整等值匹配；“按部门”“各事业部”“中查看部门”“by 事业部”“group by 部门”等分组或句法片段只表示字段/分组，不得当作具体筛选值。组件筛选允许“只看字段值”“字段值除外”等省略系词的自然表达；同一字段后的 `、/逗号/和/与/或` 多值必须整体归属该字段，完整销售小组、渠道等复合值一旦命中，其内部部门、大组、品牌或国家片段不得再次消费。筛选表达中的字段标签只表示筛选，不得同时加入分组维度。

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
4. 每个子查询都必须取到全量后才能关联或生成 Excel。检查 CLI 与 MCP 共用的
   `result_disclosures` 中 `row_count_returned`、
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

1. CLI 查询参数由规划器生成并由一体化入口原样执行；Agent 不再参与拼参。降级态下参数只能取自 `execution_ref.fallback_catalog`、`opscli query intent` 候选或 `opscli query metadata --dataset` 返回的字段清单，仍禁止凭记忆手拼。MCP 字段只采用当前数据集 metadata。**TopN/排序由规划器解析**：「前3」「前十」「top5」这类**无行数单位**的写法现在也会被解析为 `limit`（唯一例外是数字后紧跟时间单位的时间表述，如「前7天」「前3个月」，那是时间范围不是行数）；本次只选了一个指标时按该指标降序，用户显式写了「按X降序/升序」时按 X 排。解析结果由规划器直接写入 `query_template` 的 `orderBy`/`limit`，Agent 不得改写。**多指标且用户未点名排序字段时规划器不下发排序**，改为强制披露（`order_unresolved` 口径：本次返回的是完整结果集、按服务端自然序排列，不得当作 Top N 汇报）——此时把该披露如实转述，或让用户点明排序字段后写回原文重跑。仅当用户确有该意图而合同确实未下发排序/行数时，才可在命令上追加 `--limit <N>` / `--order-by <结果字段>[:asc|desc]`（形态见 `references/cli.md`），显式参数会覆盖模板同名值；未识别到该类明确意图时不得凭空追加这两个参数。
2. 不发明默认筛选。未指定筛选时只说明 `current_authenticated_account` 可见范围；明确筛选必须先经组件枚举——平台走规划结果的自动枚举/`platform_enum_command`，部门/国家等其他筛选用 `execution_ref.filter_components` 中对应组件的 `component_table_id` 查枚举，并严格遵守 `execution_ref.filter_value_match_policy`：先做规范化完整等值比较，部门编号中的多位阿拉伯数字与中文数字统一归一，并保留 `项目` 前缀作为组织身份的一部分；`十二部`、`项目十一部`、`22部`、`项目二十二部` 等完整编号部门词优先于其他组件的子串匹配，不得截取其中的 `一部` 或 `二部` 作为销售小组，也不得用这些子串命中 `一部-B组` 等销售小组枚举的主段。唯一等值命中时只使用该枚举原值并直接执行，禁止再次询问用户是否采用，也禁止把仅包含请求文本的其他成员一并加入（`9部` 只匹配 `九部`，不匹配 `项目九部`；`范泰克` 只匹配 `范泰克`，不匹配 `范泰克体系外`）。筛选值处于“排除/剔除/去除/不含/不等于/除外/之外/以外/`!=`/`<>`/`not in`”语境时必须保留排除极性：单值用 `!=`，多值用 `not_in`，禁止反转成 `=`/`in`；同一值的正负极性冲突时停止并澄清。无唯一等值命中时停止并让用户重选，不得用子串模糊扩展；组件不可用时只阻断该筛选，不扩大范围。
3. 环比、同比和上期对比必须同时传主周期日期 `filters` 与 `dataComparison`（模板已按 `time_scope` 预填，执行器也会硬校验）。
   用户点名多个指标或使用稳定别名时，`model_view.metrics` 与 `query_template.metrics` 必须完整覆盖全部指标；例如“收入及毛利”必须同时落到数据集口径“销售额、毛利”，不得因已命中其中一个就静默忽略另一个。任一点名指标缺失时按 `metric_not_in_dataset` 澄清，不得执行残缺模板。
4. **执行确认分级**：数据集、字段、时间、筛选、排序、行数全部无歧义时，用一段中文陈述式披露口径后**直接执行，不等待用户回复**；只有 `clarify_required`、默认时间口径未确认、或含 `recommended` 字段未说明时才通过提问等待确认。
5. `query_mode=dataset_query` 的 CLI 正常路径只用一体化流程（内含规划、完整性校验、执行前校验、排序生效校验与兜底、截断披露和证据合同）：

```bash
opscli query flow "$USER_REQUEST" --result-dir "$RESULT_DIR"
```

   - 默认条件（filter_configs）：规划结果存在 `default_filters` 时，流程自动传给执行器；最终回答必须披露 `default_filters_zh`。默认条件由服务端权威应用，用户为同字段提供条件时覆盖默认值，客户端不重复注入。

   `opscli query plan`/`opscli query run` 都不是 Agent 的规划器正常路径（`opscli query plan` 仅用于维护者复现审计与降级态查看规划合同）。一体化入口内部会校验规划摘要、状态、tableId、授权字段、模板及时间范围。正式查询偶尔较慢（排序兜底还可能放大窗口重查一次），命令窗口超时不是失败：**原样重跑一次**即可。主线 `opscli query flow` 返回 `success=false`（`error.code`/`error.message`）或非零退出码时原样重跑一次，仍失败即转「规划器不可用时的降级路径」。`result_disclosures.order_fallback` 存在时必须披露本地兜底。多币种（`data.multi_currency=true`）时 `data` 顶层只有 `requested_global_currencies`、`currency_results[]` 与 `comparison_contract`，**没有** `result`/`result_disclosures`/`evidence_contract`；每个 `currency_results[i]` 含 `requested_currency`、`returned_currency`、`currency_matches_request` 和 `result`，其中 `result` 是一份完整的单币种子合同——它的 `result_disclosures` 与 `evidence_contract` 和 `result` 同级，**行数据在 `currency_results[i].result.result.data`**（比单币种多一层嵌套，不要少读一层）。对比规则在 `comparison_contract.rules_zh`。MCP-only 优先 `query_flow`，其次正式 `query_simple`。
6. `query_mode=chart_uuid` 时原样执行 `execution_ref.query_command`。`chart_action=run` 必须遍历所有 `queries`，保留服务端小计/总计并按 `_query_index` 区分来源；大结果用 `--save-result` 或 `--result-file` 落盘（两者仅与 `--run` 同用生效）。**图表结果已自带证据合同**：`opscli query chart --uuid … --run` 与 MCP `query_chart(run=True)` 的返回 `data` 里直接带 `evidence_contract`（只由 `merged` 段生成；构建失败时为 `evidence_contract_error`），直接使用，**不需要**再补跑任何证据脚本。只有需要图表字段映射、异常检测或 Excel 导出时才读 `references/chart-excel-guide.md`。
7. 保留用户要求的明细和全量范围。限制展示时声明排序、截断数量和总行数（`result_disclosures` 已给出），不把局部结果说成全量。
8. **预览只是抽样，行数口径以 `result_disclosures` 为准**：传了 `--result-dir` 后返回体中的结果只保留前若干行预览，完整结果写在 `result_disclosures.full_result_file`（未传 `--result-dir` 时不存在该键）。判断口径按下面三个字段，**不要**用预览行数下结论：
   - `row_count_returned` = 本次实际拿到的行数，`total_count` = 服务端报的总行数；结论里的"共 N 条"必须用 `row_count_returned`，并在两者不等时说明。
   - `truncated=true` 表示拿到的是**部分结果**，必须如实声明，禁止说成全量。
   - `auto_complete_applied` 表示是否发生过服务端默认分页补齐：`true`=服务端未按 limit 返回全量、已自动重查补齐；补齐后仍 `truncated=true`（如超 5000 行硬上限）时结论必须声明这是部分结果。

   需要逐行数据时直接读 `full_result_file`（该文件含补齐后的 `rows_after_auto_complete`）；`full_result_file` 为 null 时看 `full_result_file_error`。**禁止**为了凑齐剩余行而改写请求重查、分批排除已见值、或绕过执行器手拼 payload 直连 `opscli query simple`——那样既浪费调用预算，又丢掉执行器的授权字段校验。

## 结果分析

CLI-only 常规结果分析不要读取 `references/result-analysis.md`：`opscli query flow` 的输出已内嵌 `evidence_contract`（构建失败时改为 `evidence_contract_error`，与合同其余字段同级），直接使用；图表入口（`opscli query chart --run` / MCP `query_chart(run=True)`）的返回同样自带 `evidence_contract`，也直接使用，不再补跑证据脚本；`clarify_required`/`blocked` 合同不含这两个键。只用其 `required_evidence`、`required_disclosures_zh` 和 `forbidden_inferences_zh` 组织结论：

- 先说明数据集中文名、时间、维度、指标、筛选、币种、聚合、排序和行数；每个数值结论附字段名、结果列或回放证据。字段称呼使用元数据中文名原文（规划合同中为 `label_zh`，即元数据 `verbose_name`），不意译。
- 遵守 `numeric_evidence_policy_zh`，结论或证据中的关键数值保持返回精度，不自行四舍五入。
- 0 行只能说明没有返回记录，不能判断业务为 0；全零不等于无数据；空值不等于 0。
- 周期比较只使用已返回的本期、`last_*`、`diff_*`、`pct_*` 列，缺列时说明无法比较。不同原币不得混加，也不得与 CNY 列混加。
- **币种是服务端换算参数，不是维度、筛选字段或指标**：它写在请求上（payload 顶层 `globalCurrency`），由服务端换算金额指标。主线 `opscli query flow` **没有** `--global-currency` 参数——币种意图由规划器识别后直接写入完整性绑定模板的 `globalCurrency`，不用也不能在命令上追加；`--global-currency USD` 只属于手工路线的 `opscli query build` / `opscli query simple`，MCP 对应 `query_simple(..., global_currency="USD")` 以及 `query_build` / `query_build_and_run` 的同名参数。数据集元数据里**没有** `currency` 字段是正常现象——不要在字段清单里找币种字段，不要把币种写进 `dimensions` / `filters`，更不得因"该数据集没有币种维度"就判定不支持按币种查询或放弃取数；也不得用"选 `_cny`/原币字段"代替币种参数。
- 全局币种换算：用户请求含币种意图（"用美元/按 USD/加元口径"等，仅支持 USD/GBP/CAD/EUR/JPY/CNY）时，规划器自动把 `globalCurrency` 写入完整性绑定模板。单币种写入 `query_template`；明确要求多个币种时生成 `query_templates`，一体化入口必须逐币种调用取数服务。未识别到币种意图时不注入，由后端回退用户默认配置。白名单外币种（如港币 HKD）规划器返回 `clarify_required`（`unsupported_currency`，`model_view.unsupported_currencies` 列出识别到的代码）：告知用户仅支持 USD/GBP/CAD/EUR/JPY/CNY 并让其改选或确认按默认币种查询，确认后把口径写回原文重跑，不得直接执行后把结果当作该币种。
- **多币种查询是多次取数，不是汇率换算**："分别使用人民币和加拿大元"、"CNY/CAD 双币种"、"同时用加拿大元对比显示"均要求人民币（CNY）和加拿大元（CAD）各执行一次相同范围的服务端查询。MCP-only 也必须为每个币种分别调用 `query_simple` 并传对应 `global_currency`。禁止只查一个币种后引用 Bank of Canada Valet `FXCNYCAD`、任何公开/内部汇率、模型记忆或本地计算生成另一个币种结果。
- 多币种结果只能按各次查询共同返回且值一致的维度键关联。生成对比表或 HTML 前，先核对维度键集合与非金额指标；任一查询被截断、返回币种与请求不符、维度键不一致或非金额指标不一致时，停止金额对比并披露差异，不得用汇率换算补齐。
- **返回币种以 `result_disclosures.currency` 为准**：服务端在返回的 `meta.currency` 声明本次实际生效的币种代码（ISO 4217，如 `CNY`/`USD`），执行器已把它提取到 `result_disclosures.currency` 与 `result_disclosures.currency_disclosure_zh`——**直接用这两个字段，不需要为了拿币种去读 `full_result_file`**。
  - 有值：结论首句、结果表表头和 Excel 口径页必须显式写明币种，例如 `currency=CNY` 即声明"本次金额均为人民币（CNY）计价"，不得只写"金额/销售额"了事。
  - 为 `null`：只能说明"本次返回未声明币种"，禁止据字段名、数据集习惯或历史会话推断具体货币（与 `evidence_contract` 的 `currency_not_declared` 披露一致）。
  - 与请求的 `globalCurrency` 不一致时**以 `result_disclosures.currency` 为准**，并把差异如实披露。
- **禁止主动参考外部汇率**：不得使用 Bank of Canada Valet `FXCNYCAD`、模型记忆、外部行情或任何本次取数服务之外的汇率，把结果金额换算成其他币种，也不得跨币种相加或按汇率折算后比较。用户需要其他币种口径时，只能把币种意图写回请求重新查询，由服务端按 `globalCurrency` 换算后重新取 `meta.currency`。
- Top N 或截断必须披露排序、展示数和总行数；未查询范围不得外推。
- 披露权限、样本、公式和数据新鲜度。**新鲜度判据看 `result_disclosures.freshness_disclosure_zh`**：查询窗口包含今天（窗口末日不早于今天）且本次返回未声明新鲜度（`evidence_contract.freshness_status` 为空——后端目前一律为空）时该键会出现；出现即表示今日/末日数值偏低不得当作业务事实，结论必须说明该日数据可能尚未刷新完成。该键不出现时才可正常解读末日数值。任何情况下都不得声称因果。
- **排序披露看 `result_disclosures.order_disclosure_zh`**：排序正常生效时它是中文确认句（如「排序已生效：按「销售额」降序」，字段用中文标签而非技术名），可直接转述；同时出现 `order_fallback` 时说明服务端排序未生效、执行器已本地重排或按总行数加量重查后本地取前 N，必须按其文案披露该兜底行为。

MCP-only（无本地 shell）、复杂审计或用户明确要求完整披露证据合同时，才读取 `references/result-analysis.md` 并按其五节结构输出。

## 纠错与反馈

用户说结果、字段、条件、口径、排序或条数不对时，带当前参数移交 `ops-query-wizard`，不猜测性反复重试。0 行、澄清、认证未就绪和用户取消不是意外故障。

查询返回「未登录，请运行: opscli auth login」时：沙箱/托管环境的 opscli 凭证由平台自动注入，**禁止执行交互式 `opscli auth login`**（无人环境的 Device Flow 永远无法完成，只会空耗时间）。正确处置：等待约 1 分钟后原样重试同一查询一次；仍未登录则停止取数，向用户如实说明环境凭证异常，并按 `references/feedback-guide.md` 提交一次反馈。

仅发生意外 opscli/MCP 失败时读取 `references/feedback-guide.md` 并立即提交一次去重的结构化反馈；成功查询不自动提交反馈。

## 规划器不可用时的降级路径

规划器是**优先路径而非唯一路径**：命中下表任一**客观失败**条件才进入降级，其余情况一律走一体化入口。降级态同样**不要自行编造数据集或字段**。合同里的 `model_view.fallback_level`（只有 `L1_contract_catalog` / `L3_metadata_refresh` 两个取值，L2a/L2b/L4 由 Agent 按下表自行判定）、`model_view.no_guess_policy_zh` 与 `execution_ref.fallback_catalog` 指明当前起点。

「命令不可用」必须区分两种性质不同的失败：`opscli` 命令无法启动（command not found、未安装、不在 PATH、依赖导入失败等命令级环境异常）计入下表「opscli 命令无法启动」行；命令能启动但返回业务错误（`success=false` 或非零退出码）按「一体化入口自身报错」处置。

### 降级触发条件（满足其一即可降级）

| 触发条件 | 判断依据 |
| --- | --- |
| 规划器要求澄清或阻断 | 返回 `status=clarify_required` / `blocked`：先按合同澄清或执行 `recovery_command`，仍无法进入 `planned` 才降级 |
| 一体化入口自身报错 | `opscli query flow` 返回 `success=false`（`error.code`/`error.message`）或非零退出码，原样重跑一次仍报同一错误（网络/代理类错误如 `ProxyError`、超时可再多重跑一次；未登录/令牌无效等登录类错误按「纠错与反馈」的未登录边界处置，不计入） |
| 命令窗口连续超时 | 同一请求原样重跑后仍在 30 秒窗口内无返回，累计 3 次 |
| opscli 命令无法启动 | `opscli` 命令缺失、无法执行或依赖导入失败（命令级环境异常）。此时降级层级中依赖 `opscli` 的 L1~L3 同样不可用，直接进入 L4：停止取数并向用户说明 opscli 安装/PATH 异常 |

**不构成降级理由**：0 行结果、用户取消、预期内的未登录（按「纠错与反馈」处置）、主观觉得规划器不合适、想省一次工具调用。降级路径的最终回答必须说明本次取数走的是降级路径以及原因。

### 降级层级

| 层级 | 判断依据 | 动作 |
| --- | --- | --- |
| L1 | `execution_ref.fallback_catalog` 有 dimensions/metrics | 只用该目录里的 `table_id`、`dataset_alias`、`field_name` 构造查询；澄清点按 `clarification_messages_zh` 向用户提问 |
| L2a | 目录为空或选表失败 | 跑 `opscli query intent -q "<用户原文>"`（远端实时意图目录，不依赖本地快照）；`matched=true` 按 `selected` 构造查询并在执行时带 `--intent-code <intent_code> --selection-source intent_route --match-record-id <match_record_id>`；`ask_user_question_required=true` 用 `AskUserQuestion` 让用户在 candidates 里选 |
| L2b | `query intent` 不可用、报错或 `fallback_required=true` | 跑 `opscli query metadata --pretty`（远端优先，失败自动回退本地缓存）取当前账号数据集卡片：卡片列表在 `data.all_datasets`（**没有** `data.datasets` 这个键），中文名在 `description`、补充说明在 `remarks`，`dataset_name` 是英文技术名不用于选表；只按中文名称/说明选表，候选不唯一时用 `AskUserQuestion` 让用户选，不得默认取第一个。仍无法判断字段属于哪张表时可用 `opscli query metadata --all-fields --pretty` 跨表定位（该形态返回的是 `data.datasets` + `data.fields`，payload 较大，只在必要时用） |
| L3 | `data_state=missing`（元数据未就绪），或 `execution_ref.fallback_catalog` 为空 | 执行返回的 `recovery_command` 刷新元数据后重跑；**此前不得构造任何查询** |
| L4 | 上述都失败 | 停止取数，如实告知用户，按 `references/feedback-guide.md` 提交一次反馈 |

降级态下前述「禁止本地探索」的限制放宽为：**允许**调用 `opscli query intent`、`opscli query catalog`、`opscli query metadata`（含 `--dataset <alias>` 取字段清单、`--all-fields` 跨表定位字段）、`opscli query plan`（只读规划合同，不执行）与 `opscli query simple`（降级态的正式执行入口）；仍然**禁止** `rg`/`ls`/`find`、读 `data/`、读脚本源码、生成临时查询脚本。降级路径额外预算 3 次工具调用。

拿到候选后：

1. 候选不唯一（`ask_user_question_required=true`，或多张数据集卡片都合理）→ 用 `AskUserQuestion` 让用户选，**不要默认取第一个**
2. 选定数据集后跑 `opscli query metadata --dataset <alias> --pretty` 取字段清单，只用其中逐字存在的 `field_name` 构造 `opscli query simple --table-id <table_id> --payload payload.json --run` 参数（形态见 `references/simple-query-guide.md`）；报「字段不存在」时回到该清单重新核对，禁止换名盲试
3. 降级路径没有内核的完整性校验、排序生效校验和自动分页补齐：必须在回答中说明本次取数走的是降级路径及原因，TopN 结论不得基于未经校验的排序，`limit` 要显式传足并按返回的 `meta.rowCount`/`meta.totalCount` 披露截断
4. `query intent` 候选里的 `intent_constraints.hard_constraints` / `avoid_when` / `clarify_when` 是**未经人工审核的业务约束提示**：必须先向用户复述该条提示并确认，再决定是否套用，不得当作已确认口径静默应用，也不得忽略——被降级的往往正是防错数的护栏（如「总库存、海外仓库存属于库存快照字段，只能用于明细表或无聚合过滤条件」「必须选择报告周期」）
5. `select_columns` 中字段的筛选值，必须先查 `component_dataset_alias` 组件表枚举当前账号授权原值，完整等值命中后才写入 `filters`；枚举不到就停止，**不得放大为全范围查询**

## 按需参考

- `references/rules.md`：歧义和口径检查。
- `references/ask-user-question-guide.md`：结构化澄清与执行确认。
- `references/cli.md`、`references/mcp.md`：正式模式入口。
- `references/simple-query-guide.md`：查询参数、公式和对比（构造阶段仅在模板不足时读取）。
- `references/chart-excel-guide.md`：图表查询、小计/总计与 Excel 导出。
- `references/result-analysis.md`：复杂分析的完整证据合同。
- `references/feedback-guide.md`：意外失败反馈。
- `QUERY_SPEC.md`：未安装/已禁用本 Skill 时的 MCP 取数存档。**本 Skill 已启用的会话（含 MCP-only）不要读取**；MCP-only 走 `references/mcp.md`。

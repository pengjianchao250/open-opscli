# MCP 取数规范（query_spec_must_read）

> **AI Agent 必读**：本文档由 `query_spec_must_read()` 返回，是**未安装 / 已禁用 `ops-dataset-query` Skill** 时通过 MCP 取数的完整指南。执行任何 `query_*` 工具前必须先读完本文档。
>
> 已安装并启用该 Skill 的会话：改以 Skill 目录内 `SKILL.md` 为准，不要读本文档。
>
> 本次请求固定 MCP-only，不切换到 CLI 或其他执行模式。

---

## 一、核心铁律总览

| # | 铁律 | 核心要点 |
|---|------|---------|
| 1 | **鉴权两条等价路径** | **登录不是前置必需**：调用方可直接用工具参数显式传入 `session_id`（+可选 `jwt`）完成鉴权；留空时才使用平台注入或本地已保存的登录态。仅 `query_plan` / `query_flow` 需要已验证账号（见第二章） |
| 2 | **规划器优先** | 自然语言取数首选 `query_flow`（一次规划并执行）；手工构造 `query_simple` 是次选路线，不得跳过元数据凭记忆拼参 |
| 2.1 | **手工查询硬门禁** | 凡要调用 `query_simple` / `query_build` / `query_build_and_run` / `query_run`，无论出于什么原因（无规划器、规划器 `blocked`、需要二次查询），**必须先完成**：① 读完本规范；② 调用 `query_metadata(...)` 拿到目标数据集的真实字段清单。缺任一步禁止发起查询 |
| 3 | **元数据是唯一来源** | 数据集、字段、公式、聚合、`select_columns` 只能来自**本次请求链**中当前已认证账号的响应；禁止用本地文件、历史结果、其他账号响应或模型知识补齐 |
| 4 | **字段标识只用 `field_name`** | `query_simple` 各处 `field` 一律填 `field_name`；**不要填 `global_alias`**（后端不接受，报"字段不存在"） |
| 4.1 | **字段名禁止推断、失败禁止换名重试** | 每个 `field` 都必须**逐字**出现在本次 `query_metadata` 响应里；报"字段不存在"时**禁止换一个自己想的名字重试**，必须回到 `query_metadata` 重新核对（见第六章） |
| 5 | **公式字段禁止再聚合** | 含 `formula_config` / `summary_expression` / `detail_expression` 的字段（ACOS、ROAS、毛利率、均价等）不传普通 `aggregation`，改传 `expr` |
| 6 | **对比必带主周期** | 用 `data_comparison` 时 `filters` 必须同时含主周期日期，否则报 `QS-EXE-005` |
| 7 | **快照类指标不跨日累加** | 库存等快照指标默认取最新快照日的值；需要趋势时按日展示快照序列，不求和 |
| 8 | **参数命名 snake_case** | MCP 工具参数是 `table_id` / `data_comparison` / `order_by`；`tableId` 这类 camelCase 只存在于 JSON payload 内部，直接当参数名会报 `Unexpected keyword argument` |
| 9 | **不发明默认筛选** | 除用户明确指定外不加任何筛选。唯一例外是服务端 `filter_configs` 默认条件——由服务端强制应用，客户端**不重复注入**，但必须披露 |
| 10 | **筛选值必须过权限枚举** | 明确筛选命中 `select_columns` 时，先查 `component_dataset_alias` 取当前账号合法枚举值，值不在其中即为无权限，禁止继续执行 |
| 11 | **歧义必须澄清** | 数据集、字段、时间、人员/组织、币种、库存口径出现多个合理候选时停止并澄清，禁止静默选择 |
| 12 | **输出列名不意译** | 结果列名与结论中的字段称呼使用元数据 `verbose_name` 原文，禁止改写、简化或美化 |
| 13 | **结论必须带证据** | 每个数值结论附字段名或结果列；截断必须披露排序、展示数与总行数；不把局部说成全量 |
| 14 | **仅意外失败才反馈** | 工具抛异常、`success: false`、超时或无法解释的服务错误才提交一次结构化反馈；0 行、澄清、认证未就绪、用户取消都不是反馈事件 |

---

## 二、鉴权与身份

### 两条等价路径：登录不是前置必需

所有 `query_*` 工具都接受可选的 `session_id` 与 `jwt`。当前已认证账号既可由平台注入/本地已保存的登录态确立，也可由调用方**显式传参**确立——两者等价，**显式传参优先**：

| 路径 | 用法 | 适用 |
|------|------|------|
| **显式凭证** | 调用时直接传 `session_id`（+可选 `jwt`） | 调用方/编排方已持有凭证。**无需先调用 `auth_mcp_login` 或 `auth_is_authenticated`**，直接查即可 |
| **隐式登录态** | 两个参数都留空，自动加载 | 平台注入登录态或本地已保存凭证的默认 Agent 流程。此时**不应手填**这两个参数 |

`jwt` 为 ops 系统 JWT；留空时由服务端用 `session_id` 向后端换取。无论哪条路径，确立的都是同一个"当前已认证账号"；**本次请求内所有工具调用必须归属同一账号，不跨账号混用。**

```python
# 显式凭证路径：不需要任何前置登录调用
query_metadata(session_id="<SESSION_ID>", jwt="<OPS_JWT>")
query_simple(table_id=1, dimensions=[...], metrics=[...],
             session_id="<SESSION_ID>", jwt="<OPS_JWT>")

# 隐式路径：留空自动加载
query_metadata()
query_simple(table_id=1, dimensions=[...], metrics=[...])
```

### 各工具的凭证要求（重要差异）

| 工具 | 显式凭证是否够用 | 说明 |
|------|-----------------|------|
| `query_metadata`、`query_preferences` | 够用 | 无 `session_id` 非空校验，单传 `jwt` 也可 |
| `query_simple`、`query_run`、`query_build_and_run`、`query_chart`、`query_chart_doc` | 够用，但 **`session_id` 必填** | 有 `if not sid` 硬校验，只传 `jwt` 会报「无 session_id：请完成授权登录，或传入有效的 session_id」 |
| `query_build` | 不需要凭证 | 只构造 payload 不执行 |
| **`query_plan`、`query_flow`** | **不够用** | 这两个工具要用当前账号邮箱做元数据缓存隔离，身份只来自**传输层已验证账号**（remote 模式的 transport 邮箱 / fixed 模式的隔离凭证缓存 / stdio 默认 CredentialStore），**不读显式传入的 `session_id`·`jwt`**。无已验证账号时返回「无法确认当前登录账号：请先 auth_mcp_login 登录，或传入有效凭证」。此时改走 `auth_mcp_login()` 登录，或改用第五~七章的 `query_metadata` + `query_simple` 路线 |

### 登录与核验（仅在需要时调用）

```python
auth_is_authenticated()   # 检查隐式登录态；持有显式凭证时无需调用
auth_mcp_login()          # HTTP/SSE 模式一步登录，无需浏览器交互、无需 user_code
auth_me()                 # 可选：核验究竟以谁的账号取数，返回 username / id 等（同样接受 session_id / jwt）
```

- 走隐式路径且 `authenticated=false` 时：HTTP/SSE 模式执行 `auth_mcp_login()`，stdio 模式走 Device Flow。
- 显式凭证必须发往其签发的**同一后端环境**，否则后端返回 407（凭证无效 / 用户不存在），按认证失败处理。
- 鉴权或远程元数据失败时**阻断选择**，先恢复凭证或元数据，不得降级到其他数据来源。

---

## 三、两条取数路线

```
自然语言取数请求
  ├─ 路线 A（首选）：query_flow —— 一次调用完成规划 + 执行
  │    规划器自动完成：选表、字段/公式、时间口径、平台与组件权限枚举、完整性绑定
  │    适用：绝大多数"查 XX 数据"类请求
  │
  └─ 路线 B（次选）：query_metadata → query_simple —— 手工构造
       适用：规划器返回 clarify_required/blocked 后已澄清、需要精确控制 payload、
             组件枚举查询、或规划器不覆盖的场景（MOY 趋势等）

图表场景（已有 chart_uuid）→ query_chart
```

**路线 A 的前提**：需要传输层已验证账号（见第二章）。只持有显式 `session_id` / `jwt` 的调用方走不通路线 A，直接用路线 B。

不要为了"确认环境"在路线 A 之前额外调用 `query_metadata` 探路；也不要在路线 A 已返回结果后再用路线 B 查同一范围。

---

## 四、路线 A：query_plan / query_flow（规划器）

### 4.1 工具与参数

| 工具 | 作用 |
|------|------|
| `query_plan` | 只规划不执行，输出规划合同（`query_plan_model_contract_v2`） |
| `query_flow` | 一体化：规划 + `status=planned` 的数据集查询时按 `query_template` 执行一次并回传结果 |

| 参数 | 类型 | 说明 |
|------|------|------|
| `request` | string | **必填**，用户查询原文（自然语言，保留原始表述，不要自行改写成关键词） |
| `requested_fields` | list[str] | 可选，用户点名的字段 |
| `limit` | int | 仅 `query_flow`；不传时先接受后端默认页，若 `totalCount` 更大则自动按总数补查一次（最多 5000 行） |
| `order_by` | list[dict] | 仅 `query_flow`；形态 `[{"field": "<结果字段>", "desc": true}]` |
| `offset` | int | 仅 `query_flow`；不传沿用后端默认 0 |
| `top_n` | int | 仅 `query_plan`，选表候选上限 |
| `session_id` / `jwt` | string | 可选，用于后续查询执行；**但不能用它们确立身份**——这两个工具的账号身份只来自传输层已验证账号（见第二章），无已验证账号时直接失败 |

```python
query_flow(request="查近30天各部门的销售额和订单量", limit=100,
           order_by=[{"field": "sales_amount", "desc": True}])
```

> **排序只认 `desc` 布尔值**：`{"field": "x", "direction": "DESC"}` 会被后端忽略并恒按升序返回。

### 4.2 返回合同与处置

`query_flow` 返回 = 规划合同 + `result`（planned 时）+
`result_disclosures`（返回行数、总数、截断与自动补齐状态）+
`execution_notes`（按需）。按 `status` 分流：

| status | 含义 | 处置 |
|--------|------|------|
| `planned` | 规划完成，`query_flow` 已执行并回传 `result` | 直接分析结果，按 `answer_contract` 组织结论 |
| `clarify_required` | 需要用户澄清 | 按 `model_view.clarification_messages_zh` 提问；确认后把明确口径**写回请求原文**重新调用，不要手工拼 payload 绕过 |
| `blocked` | 被阻断（元数据未就绪、平台范围无授权、组件枚举缺陷等） | 按 `model_view.recovery_hint_zh` / `recovery_command` 处置，见 4.4 |

只使用 `model_view`、`answer_contract` 和 `execution_ref` 三部分，**不要读取内部合同字段补充回答**：

- `model_view`：只含用户可见中文结论。常见键：
  - `dataset_name_zh`、`dimensions`、`metrics`
  - `time_scope_zh` / `time_resolution_zh` —— **本次日期窗口的唯一来源**
  - `dataset_candidates_zh`（候选数据集卡片）、`field_suggestions_zh`（近似字段建议）、`pending_confirmations_zh`（待确认项）
  - `default_dataset_recommendation_zh`：`auto_selected=true` 时直接继续，不再提问；`confirmation_required=true` 时才询问是否采用推荐数据集
  - `platform_semantic_members` / `platform_effective_members` / `platform_scope_disclosures_zh`
  - `default_filters_zh`（服务端默认条件，必须披露）、`component_filter_disclosures_zh`
- `answer_contract`：最终回答必须覆盖 `required_disclosures_zh`，并遵守 `forbidden_outputs_zh`。`technical_identifiers_user_visible=false` 时不得向用户展示 alias、table_id 等技术标识。
- `execution_ref`：仅供构造使用，**禁止**作为业务判断理由或展示给用户。`selection_source=recommended` 的字段是系统推荐（用户未点名），未经说明不得直接采用。

### 4.3 结果被截断时

未显式传 `limit` 且服务端默认页少于 `totalCount` 时，`query_flow` 会按总数自动补查
一次，最多 5000 行。以 `result_disclosures` 为准：

- `row_count_returned`：最终实际返回行数；
- `total_count`：服务端报告总数；
- `truncated`：两者不等时为 `true`；
- `auto_complete_applied`：本次是否执行过默认页补查。
- 币种：本次实际生效币种取自返回的 `meta.currency`（ISO 4217）；有值必须在结论首句、结果表头写明，为 `null` 时只能声明"未声明"，禁止推断；与请求 `globalCurrency` 不一致时以返回为准并披露差异（详见第十五章「范围与口径」）。

只有 `truncated=false` 才可把结果称为全量。总数超过 5000、显式分页或自动补查失败时，
应通过正式分页能力继续取全；在拿到全量前必须声明“当前为前 N 行”，不得生成宣称全量的
Excel。

`execution_notes` 是按需披露的已知延后项，仅在本次真正用到相关能力时出现：

- 传了 `order_by` → 提示服务端 orderBy 缺陷的本地兜底/加量重查暂未内核化（orderBy 本身已正常下发）
- 无相关参数时**不会出现该键**，不要把它的缺失当成异常

### 4.4 元数据未就绪（blocked）

`recovery_state=refresh_in_progress` 表示元数据刷新已在后台进行：**等待约 25 秒后，用完全相同的参数原样重新调用同一工具**即可。

- 合同里的 `recovery_command` 是 CLI 形态（`sleep 25 && opscli query plan "..."`）——MCP-only 场景**不要试图执行该命令**，取其语义（等待后重跑）即可。
- 禁止自行执行任何升级动作，禁止因等待改走旁路探查。
- 连续 3 次仍未就绪才提交一次反馈并停止，不反复重试。

`recovery_state=refresh_failed` 时向用户如实说明元数据异常并停止，同时提交一次反馈。

### 4.5 时间口径以规划结果为准

`model_view.time_scope_zh`、`time_resolution_zh` 与 `execution_ref.time_scope` 是唯一日期窗口来源。规划器按 Asia/Shanghai 当前日期用 Python `datetime` 计算，禁止自行心算、猜测年份或使用模型知识截止时间改写。

相对时间被规划器唯一解析后，展示绝对日期即可直接执行，不再要求用户确认；只有 `is_default=true`（原文完全未给时间）才必须询问是否采用默认近 30 天。

### 4.6 多数据集计算与 Excel

两个及以上 `table_id`、跨表关联、派生计算或 Excel 交付必须拆成逐表正式查询，不能让
一次单表 `query_flow` 代表整项任务：

1. 每张快照表独立确定最新有效快照日；销售“当天”使用 Asia/Shanghai 执行当天。
2. “超6月”是 181 天以上业务阈值，不是日历月份。
3. `Amazon` 减去显式排除的 `Amazon VC` 后不得重新扩入 VC；人员等筛选只下推到
   用户指定的数据表。
4. 每表均须确认 `result_disclosures.truncated=false` 后再关联。
5. 以库存/库龄商品全集为保留侧向销售做 LEFT JOIN；无销售记录补
   `order_qty=0`，再把 `order_qty<=0` 标记为未售出。禁止改成
   `order_qty>0` 的服务端筛选。
6. 全量关联后才计算金额和库龄分段合计；缺失未税单价不得填 0，连接键、快照日、
   九个 181 天以上分段及缺失情况必须写入 Excel 口径说明。

---

## 五、路线 B 步骤 1：选择数据集

```python
query_metadata()                 # 无参数：返回当前账号授权数据集卡片
query_metadata(dataset="<alias>")  # 指定数据集：返回完整字段 + select_columns
query_metadata(table_id=1)
query_metadata(include_all_fields=True)  # 全量元数据（所有授权数据集的所有字段，经用户级缓存）
```

### 三种调用形态怎么选

| 形态 | 返回内容 | 何时用 |
|------|---------|--------|
| `query_metadata()`（不传参数） | 当前账号授权的**数据集卡片列表**（中文名称、说明、别名、`table_id`）；**不含** `select_columns` | 路线 B 步骤 1 选数据集。据此挑针对性数据集，避免默认落到综合大杂烩数据集 |
| `query_metadata(dataset="<alias>")` / `query_metadata(table_id=<id>)` | **该数据集的完整字段信息** + `select_columns` + `filter_configs` | **默认的取字段方式**（路线 B 步骤 2）。数据集确定后取精确 `field_name`，也用于取组件数据集的枚举字段 |
| `query_metadata(include_all_fields=True)` | **全量元数据**：全部授权数据集的全部字段 | **备选加速器，不是默认**。仅在不确定目标字段属于哪个数据集、或需跨数据集比对字段时用；payload 很大会挤占上下文 |

`include_all_fields=True` 需要已验证账号（无已验证账号时失败闭合、返回错误而非空结果），返回 `{datasets, fields, dataset_count, field_count, stale, from_cache}`；`field_count=0` 表示后端尚未上线该能力，此时退回上面的两步法。它忽略 `dataset` / `table_id` / `skills_dir`。

### 选择规则

1. 自然语言**只按卡片的中文名称和中文说明**选择；向用户展示中文名称、说明和业务粒度。
2. 用户明确给出精确完整的英文技术标识时，才在当前授权卡片中做精确匹配。**禁止**从中文口语推导英文 `dataset_name` / `field_name`，也禁止对英文 key 做近似检索。
3. 问句内嵌完整中文数据集名时，嵌套命中保留包含关系中**最长**的授权名称；独立命中多个名称或同名冲突时必须澄清。
4. 候选不唯一、粒度不清或无授权候选时停止并澄清，不自行选择。
5. 业务领域词（"广告数据""销售数据""库存数据"等）必须搜索**数据集列表本身**，不能因为字段搜索结果集中在某个 table_id 就判定数据集唯一。
6. `query_component` 类数据集**只用于权限枚举**，不是业务结果数据集。明确请求枚举/可用值时才可作为查询目标。
7. 候选为空不表示可以扩大数据范围；应报告当前授权元数据无可用候选。

---

## 六、路线 B 步骤 2：字段与公式

对确认的数据集调用 `query_metadata(dataset="<alias>")`，字段信息全部来自该响应：`field_name`、`verbose_name`、`global_alias`、`field_type`、`summary_expression`、`detail_expression`、`formula_config`，以及 `select_columns`（无参调用**不含** `select_columns`）。

### 字段标识

- **字段名唯一来源**：`query_simple` 里每一个 `field`（维度、指标、筛选、排序）都必须**逐字**出现在本次 `query_metadata` 响应中。**禁止**凭记忆、凭命名习惯（`amount` / `sale_amount` 之类）、凭其它数据集经验推断字段名——想不起来就再调一次 `query_metadata`，不要猜。
- **失败后禁止换名重试**：查询报"字段不存在"或参数非法时，**不得换一个自己想的字段名再试一次**（这只会变成猜名死循环）。必须回到 `query_metadata` 重新核对确切 `field_name`；不确定字段属于哪个数据集时用 `query_metadata(include_all_fields=True)` 定位。连续两次仍无法在元数据中找到对应字段，就如实说明该字段在当前授权范围内不可用并停止，不要无限重试。
- `query_simple` 各处 `field` **一律填 `field_name`**。后端不接受 `global_alias` 作查询字段标识，会报"字段不存在"。
- **同名双注册自动消歧**：同一物理字段可能出现同名双注册——「英中双名」（同 `field_name`、`verbose_name` 一中一英）或「公式 vs 裸指标」（同 `field_name`，一条带公式配置、一条为裸指标）。此时**仍按 `field_name` 传参即可**，后端与 `query_simple` 会稳定解析：**公式注册优先**（均值/比率类字段用其汇总表达式聚合，不会被误 `SUM`）。无需、也不应为区分同名字段改用 `global_alias`。

### 公式字段

字段含 `formula_config` / `summary_expression` / `detail_expression` 时是公式字段（ACOS、ROAS、毛利率、平均单价等），**不传普通 `aggregation`**，改传 `expr`：

- **聚合 / 分组查询**（默认）：`expr` 取该字段的 `summary_expression`
- **明细 / 行级查询**（用户提到"明细""详情""每一行"）：`expr` 取 `detail_expression`

```python
# 正确：公式字段传 expr
{"field": "acos", "alias": "f_acos", "expr": "ROUND(total_spend_cny / sales_cny, 4)"}

# 错误：公式字段套 SUM，把每行的 ACOS 百分比加在一起，指标失真
{"field": "acos", "aggregation": "SUM", "alias": "f_acos"}
```

表达式必须从 metadata 读取，**不能凭记忆写**。不传 `expr` 时服务端仍会尝试自动识别，但显式传可避免版本差异。

### 数据集默认条件（filter_configs）

`query_metadata` 返回的数据集对象含 `filter_configs` 数组（字段级默认条件，`required` 类型由服务端强制应用）。

- 服务端是默认条件注入的**唯一权威方**：客户端**禁止**把它重复写进 `filters`（会与服务端解析后的真实日期 AND 合并，导致恒 0 行）。
- 用户为同字段提供条件时覆盖默认值。
- 最终回答**必须披露**本次生效的默认条件。

### 用户字段偏好

```python
query_preferences()   # 返回当前用户已保存的图表字段偏好（各数据集的维度与指标）
```

字段选择优先级：**用户偏好 > 远端 metadata > 本地缓存**。偏好中存在对应数据集时优先采用其字段。

---

## 七、query_simple 参数规范

基于简化参数直接执行查询，服务端自动处理 `innerWhere`、`translate`、`MOY` 展开等技术细节。**需要凭证**：显式传 `session_id` 或使用已保存的登录态，二者任一即可（`session_id` 必须有值，见第二章）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `table_id` | int | **是** | 数据集 ID，须来自 `query_metadata` 返回 |
| `dimensions` | list[str \| dict] | 否 | 维度列表 |
| `metrics` | list[str \| dict] | 否 | 指标列表 |
| `filters` | list[dict] | 否 | 过滤条件 `{"field","operator","value"}` |
| `data_comparison` | dict | 否 | 对比周期 `{"field","startDate","endDate"}`，必须同时用 `filters` 传主周期 |
| `order_by` | list[dict] | 否 | `{"field": "<结果字段 alias>", "desc": true}` |
| `limit` | int | 否 | 默认 20 |
| `offset` | int | 否 | 默认 0 |
| `dry_run` | bool | 否 | 仅验证不执行 |
| `session_id` | string | 否 | 显式凭证；留空则自动加载登录态。两者都没有时报「无 session_id」 |
| `jwt` | string | 否 | 显式 ops JWT；留空时用 `session_id` 换取 |

### dimensions / metrics 双格式

```python
# 字符串格式
dimensions = ["dept_name", "date_id:f_date"]                    # field[:alias]
metrics    = ["price:SUM:f_price", "order_id:COUNT_DISTINCT:f_orders"]  # field:agg[:alias]

# Dict 格式（推荐，支持 format / comparison / expr 等扩展键）
dimensions = [{"field": "dept_name", "alias": "f_dept"},
              {"field": "date_id", "alias": "f_month", "format": "%Y-%m"}]
metrics    = [{"field": "price", "aggregation": "SUM", "alias": "f_price"},
              {"field": "acos", "alias": "f_acos", "expr": "<summary_expression>"}]
```

### filters 操作符

| 操作符 | 示例 |
|--------|------|
| `=` / `!=` | `{"field": "platform_name", "operator": "=", "value": "Amazon"}` |
| `>` `>=` `<` `<=` | `{"field": "date_id", "operator": ">=", "value": "2026-01-01"}` |
| `in` / `not in` | `{"field": "platform_name", "operator": "in", "value": ["Amazon", "Walmart"]}` |
| `between` | `{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-30"]}` |

### 示例 1：普通聚合

```python
query_simple(
    table_id=1,
    dimensions=[{"field": "dept_name", "alias": "f_dept"}],
    metrics=[{"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"}],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    order_by=[{"field": "f_fee_sum", "desc": True}],
    limit=10,
)
```

### 示例 2：环比 / 同比（data_comparison）

```python
query_simple(
    table_id=1,
    dimensions=[{"field": "dept_name", "alias": "f_dept"}],
    metrics=[{"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"}],
    # 主周期放 filters，对比周期放 data_comparison，两者缺一不可
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-04-01", "2026-04-22"]}],
    data_comparison={"field": "date_id", "startDate": "2026-03-01", "endDate": "2026-03-22"},
    limit=10,
)
# 额外返回列：last_f_fee_sum（上期）、diff_f_fee_sum（差值）、pct_f_fee_sum（变化率）
```

只传 `data_comparison` 而不传主周期 `filters` 会报 `QS-EXE-005 missing ')' at '{'`。

### 示例 3：MOY 月环比趋势

```python
query_simple(
    table_id=1,
    dimensions=[{"field": "dept_name", "alias": "f_dept"},
                {"field": "date_id", "alias": "f_month", "format": "%Y-%m"}],
    metrics=[
        {"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_sum"},
        # comparison=MOY：服务端展开为当期/上期/变化率三列
        {"field": "fi_first_leg_trailer_fee", "aggregation": "SUM", "alias": "f_fee_moy",
         "comparison": "MOY", "moyType": "MOM_MONTH"},
    ],
    filters=[{"field": "date_id", "operator": "between", "value": ["2026-03-01", "2026-04-22"]}],
    order_by=[{"field": "f_month", "desc": True}],
    limit=20,
)
# 额外返回列：f_fee_moy_prev、f_fee_moy_diff、f_fee_moy_pct
```

### 比较类查询优先级

| 优先级 | 场景 | 方案 |
|--------|------|------|
| 最优 | 汇总对比（环比/同比） | `data_comparison`（服务端一次 SQL） |
| 次优 | 按时间粒度的趋势对比 | `metrics.comparison=MOY`（服务端窗口函数） |
| 兜底 | 上述均不可用 | 两次 `query_simple` 分别取两期，在对话中按维度匹配合并 |

禁止跳过高优先级方案直接多次调用工具在客户端合并。

---

## 八、查询组件与权限枚举校验

`query_metadata(dataset="<alias>")` 返回的 `select_columns` 定义了该数据集的查询组件字段：

```json
{
  "dataset_alias": "ds_xxxx",
  "select_columns": [
    {"column_name": "platform_name", "verbose_name": "平台", "component_dataset_alias": "ds_aaaa"},
    {"column_name": "dept_name",     "verbose_name": "部门", "component_dataset_alias": "ds_bbbb"}
  ]
}
```

**规则一：组件字段是合法筛选条件。** `column_name` 即使不在普通字段列表（`fields`）中，也是该数据集的合法 `filters` / `dimensions`。仅因它不在 `fields` 里就拒绝，会漏掉合法查询维度。

**规则二：枚举值必须先过权限校验（构造 filter 之前）。**

```
1. 在 select_columns 中查找筛选字段
   找到  → 取其 component_dataset_alias
   未找到 → 按普通字段处理，跳过本校验
2. query_metadata(dataset="<component_dataset_alias>") 取组件的 table_id 与字段
3. query_simple(table_id=<组件 table_id>, dimensions=["<column_name>"])  # 不传 filters
   → 返回的即当前账号在该维度上的完整合法值
4. 用户指定的值在返回值中 → 有权限，继续构造原查询
   不在返回值中           → 无权限：展示合法值列表请用户重选，禁止执行原查询
```

**值匹配策略**：先做规范化（NFKC、去首尾空白、大小写归一）后的**完整等值**比较；部门名称额外允许阿拉伯数字与中文数字等价（"9部" = "九部"）。唯一等值命中时直接使用该枚举原值执行，不再询问；**禁止用子串模糊扩展**——"9部"只匹配"九部"，不匹配"项目九部"；"范泰克"只匹配"范泰克"，不匹配"范泰克体系外"。无唯一等值命中时停止并让用户重选。

组件 alias 缺失或组件枚举失败时**只阻断该筛选**，不得改为不加筛选的全范围查询。

### 禁止行为

- 跳过 `select_columns` 检查，凭经验猜测枚举值（如直接写 `"Amazon"`、`"US"`）
- 未查 `component_dataset_alias` 就使用用户输入的枚举值
- 因字段不在 `fields` 就拒绝 `select_columns` 中的合法筛选
- 用无参 `query_metadata()` 获取 `select_columns`（无参调用不含该字段）

---

## 九、时间口径规范

路线 A 由规划器给出唯一解析；路线 B 手工构造时按下列规则，并在执行前把绝对起止日期披露给用户。

| 表述 | 默认理解 | 必须澄清的场景 |
|------|---------|---------------|
| 近 N 天 | **包含今天**，即 `[今天-(N-1), 今天]` | 跨月对比天数不对等时 |
| 本月 | 本月 1 日至本月最后一天（整月口径） | 月末未到时只作数据更新进度披露，不改窗口 |
| 上月 | 上月 1 日至上月最后一天 | 跨年时 1 月的"上月"为去年 12 月 |
| 本周 / 上周 | 本周一至今天 / 上周一至上周日 | 用户可能想要完整周 |
| **最近一个月** | 歧义（近 30 天 vs 当月） | **必须澄清** |
| **最近一周** | 近 7 天滚动，与"上周"不同 | **必须澄清** |
| 上个月同期 | 上月 1 日至同日 | 需确认具体范围 |
| 未给时间 | 默认近 30 天（含今天） | 必须在确认摘要与结果说明中显式声明该默认口径 |

- **`近30tian` / `近30day` / `近30days` 与 `近30天` 同义**，必须识别为用户明确时间，不得回退成默认口径。
- "近 N 天"起算点是 `今天-(N-1)`；从 `今天-N` 起算是历史高频错误，多算一天。
- 整自然月窗口的环比固定为上一个自然月（整月对整月），大小月天数差异属正常口径，不需补齐也不需确认；其他窗口天数不等时不自行补齐，必要时澄清（用同期 N 天 / 用日均值）。
- 同一会话追问未重新指定时间时继承上一轮已确认的范围；调用规划器必须带原请求或已锁定的绝对起止日期，不能只传丢失时间范围的步骤摘要。

---

## 十、歧义澄清规则

**核心原则：不确定就问，禁止猜测。**

### 字段匹配两级优先级

```
第一级：精确匹配（verbose_name 或 field_name 完全等于用户术语）
  命中 1 个  → 直接使用，不再进入模糊匹配
  命中 ≥2 个 → 列出候选让用户选择
  命中 0 个  → 进入第二级
第二级：模糊匹配（verbose_name / field_name 包含用户术语）
  命中 0 个  → 告知无此字段，列出相近字段
  命中 1 个  → 使用并告知
  命中 ≥2 个 → 强制列出所有候选及各自含义，让用户选择
```

用户说"销售额"且恰有字段 `verbose_name` 就叫"销售额"时直接精确命中，**不需要**再罗列"交易额（自发货）"等模糊结果。候选超过 4 个时先完整列出，再让用户在最相关的 2~3 个与"其他"之间选择。

### 常见歧义类型

| 类型 | 检测方式 | 处理 |
|------|---------|------|
| 同名多角色（人员/组织） | `verbose_name` 含"人员/小组/团队/部门"且 ≥2 个 | 列出所有角色让用户确认 |
| 组织层级 | 存在多级组织维度（大组→小组→个人） | 确认查哪一层。小组（team）与部门（dept）相互独立，不得互相推导；店铺、渠道、平台不得混用 |
| 原币 vs CNY | 同时存在 `xxx` 与 `xxx_cny` | 元数据同时提供两者时必须澄清，不静默选择 |
| SKU/ASIN 多变体 | `field_name` 含 SKU/ASIN 且 ≥2 个 | 列出渠道 SKU / 公司 SKU / 父公司 SKU 等变体让用户选 |
| 缩写歧义（SP/SD/SB） | 用户使用缩写 | 只结合已选数据集的中文说明判断（广告指标→广告类型，产品管理→产品编码）；仍多义则澄清 |
| 公式口径跨数据集不同 | 同 `field_name` 出现在 ≥2 个 table_id | 说明各数据集计算口径差异后让用户选 |
| 综合 vs 细分数据集 | 需求同时匹配两者 | 问用户要全貌还是细分详情 |
| 库存多子类 | 含"库存"且 ≥3 个变体字段 | 列出可售/在途/平台仓/海外仓等候选让用户选，**不得默认选"总库存"** |
| 分类体系 | 存在内部品类与平台类目两套 | 确认用哪套体系 |

### 澄清方式

1. 用中文名称、中文说明、业务粒度和口径差异列出授权候选。
2. 一次只问会改变数据集、字段、时间、币种或筛选的关键问题。
3. 等待用户选择，不在问题中暗示默认答案。
4. 把确认结果写回请求原文（路线 A）或直接用于构造（路线 B），再执行查询。

---

## 十一、库存等快照类指标

指定具体产品（ASIN、渠道 SKU、公司 SKU 等）查库存时，查询目的是**当前最新库存状况**而非历史汇总：

- **默认不加时间聚合**，直接取最新快照日的值；禁止跨日/跨期累加。
- 用户明确要求历史趋势时（"近 30 天可售库存变化""库龄分布"）例外，按日展示快照序列，仍不求和。
- 用户未指定库存类型且存在多个变体字段时，列出候选让用户选择。

---

## 十二、其他工具

### query_chart —— 图表查询

```python
query_chart(chart_uuid="4NQ5f66sU9")            # 仅取图表结构，不执行
query_chart(chart_uuid="4NQ5f66sU9", run=True)  # 执行所有子查询并合并
```

`run=True` 返回 `{chart_uuid, queries: [{index, table_id, payload, result, error}], merged: {rows, meta: {rowCount, queryCount, successCount}}}`。多个 query 各自独立执行，单个失败不中断其他；用 `_query_index` 区分行来源，保留服务端小计/总计。

`query_chart_doc(chart_uuid=..., output_path=...)` 生成该图表的 API 调用 Markdown 文档（查询结构、字段映射、过滤规则与样例）。

### query_build_and_run / query_build / query_run

CLI 风格字符串参数路线，`query_simple` 无法满足时才使用：

```python
query_build_and_run(
    table_id=1,
    dimensions=["date_id", "country_code"],
    metrics=["price:SUM:f_price"],
    where_conditions=["date_id|>=|\"2026-01-01\"", "platform_name|=|\"Amazon\""],
    order_by=["f_price:desc"],
    limit=50,
)
```

- `where_conditions` 格式 `field|operator|value_json`：字符串值需 JSON 转义引号，数组写 `[...]`；操作符 `= != > >= < <= in not in`。
- `data_comparison` 为字符串格式 `field,start_date,end_date`。
- `query_build` 只构造不执行（不需要认证），`query_run` 执行本地 payload 文件。
- **手写 payload 时禁止手填** `userEmail`、`query.from.table`、`query.from.permission`、`query.from.database`——这些由构造层根据数据集 metadata 自动生成，手写必错。

---

## 十三、错误处理速查

| 现象 / 错误码 | 原因 | 处理 |
|--------------|------|------|
| `QS-EXE-005 missing ')' at '{'` | 用了 `data_comparison` 但缺主周期 `filters` | 补主周期日期 filters 后重试 |
| `Unexpected keyword argument` | 参数用了 camelCase | 改 snake_case：`table_id` 而非 `tableId` |
| "字段不存在" | 用 `global_alias` 当字段标识，或字段名靠猜/拼错 | 改用 `field_name`；**回到 `query_metadata` 重新核对，禁止换一个自己想的名字直接重试**；不确定字段归属时用 `include_all_fields=True` 定位。连续两次找不到即停止并如实说明 |
| 指标数值异常放大 | 公式字段被套 `SUM` 二次聚合 | 改传 `expr`，不传 `aggregation` |
| 库存数值膨胀数倍 | 快照指标跨日累加 | 取最新快照日，不做时间聚合 |
| 结果只有 20 行 | 未传 `limit` 且服务端先返回默认页 | `query_flow` 会自动补查；检查 `result_disclosures`，若仍 `truncated=true` 则继续正式分页取全 |
| 结果恒 0 行 | 客户端重复注入了服务端默认条件 | 移除手工写入的 `filter_configs` 同名条件 |
| 环比列缺失或差值恒 0 | 对比期与主周期重合，或数据集不支持 | 核对两个窗口是否真的不同；仍缺列时说明无法比较，必要时降级两次查询 |
| 「无 session_id：请完成授权登录，或传入有效的 session_id」 | 只传了 `jwt` 没传 `session_id`，且本地也无凭证 | 补传 `session_id`（该类工具有硬校验） |
| 「无法确认当前登录账号」 | 对 `query_plan` / `query_flow` 只传了显式凭证 | 这两个工具身份只认传输层已验证账号：改走 `auth_mcp_login()`，或改用 `query_metadata` + `query_simple` 路线 |
| 401 Unauthorized | Token 过期 | `auth_token_refresh()` 刷新 |
| 407 | 显式凭证发往了非签发环境 | 按认证失败处理，核对后端环境 |
| 404（chart） | `chart_uuid` 不存在或无权限 | 确认 UUID 与访问权限 |
| `status=blocked` + `refresh_in_progress` | 元数据后台刷新中 | 等约 25 秒原样重调，最多 3 次 |
| `data_state` 非 `ready` | 元数据未就绪 | 同上；仍失败则说明元数据异常并停止 |

---

## 十四、查询前自检清单

```
□ 凭证：显式传 session_id/jwt，或隐式登录态已就绪（二者任一即可，不必两条都走）
□ 若要用 query_plan / query_flow：是否存在传输层已验证账号？（显式凭证不满足该要求）
□ 路线：自然语言请求是否优先走了 query_flow，而不是凭记忆手拼 query_simple
□ 数据集：是否唯一确认？业务领域词是否搜索了数据集列表本身而非只靠字段命中
□ 手工查询门禁：要发 query_simple 系列前，是否已读完本规范 + 已调用过 query_metadata（缺一不可）
□ 字段：是否来自本次 query_metadata(dataset=...) 响应？是否用的 field_name（不是 global_alias）
□ 字段：每个 field 是否逐字来自元数据（无一个是猜的）？上一次"字段不存在"是否回查了元数据而非换名重试
□ 公式字段：summary_expression / formula_config 非空 → 传 expr，不传 aggregation
□ 默认条件：filter_configs 是否已交由服务端应用（客户端未重复注入），并已准备披露
□ 筛选权限：filters 字段是否在 select_columns？→ 已查组件枚举并完整等值命中
□ 时间：绝对起止日期是否已确定并将披露？近 N 天是否用 N-1 起算？"最近一个月/一周"是否已澄清
□ 对比：用 data_comparison 时是否同时传了主周期 filters？对比期是否与主周期不同
□ 快照：库存类指标是否取最新快照日，未做跨日累加
□ 多表：是否逐表独立锁定快照/当天口径，并在每表 `truncated=false` 后才 LEFT JOIN
□ 行数与排序：limit 是否足够？order_by 是否用了 desc 布尔值
□ 多币种：是否逐币种分别查询（每次一个 globalCurrency），并核对各次 meta.currency、共同维度键和非金额指标；是否完全未使用外部汇率或本地换算
□ 歧义：字段/人员/组织/币种/库存口径是否存在 ≥2 个合理候选未澄清
□ 参数命名：是否全部 snake_case
□ 输出：列名是否使用 verbose_name 原文，未意译
□ 截断：是否核对 `result_disclosures`；`truncated=true` 时已正式分页取全或明确披露
```

---

## 十五、结果与证据合同

MCP-only 场景没有本地 shell，按以下内联证据合同组织结论，**输出顺序固定**：范围与口径 → 主要结论 → 关键贡献/异常 → 可执行观察 → 限制。没有足够证据的节写"未发现"或"无法判断"，但不得省略。

**范围与口径**

- 说明数据集中文名、时间范围、维度、指标、筛选、币种、聚合、排序和返回行数；结果不完整时注明总行数、已展示行数和取全方式。
- 区分主周期与对比周期；说明公式字段使用的是汇总还是明细表达式。
- 披露本次生效的服务端默认条件（`default_filters_zh`）。
- 原币金额按币种分开汇总；不同原币不得混加，也不得与 CNY 列混加。
- **本次生效币种取自返回的 `meta.currency`**（ISO 4217，如 `"currency": "CNY"` 即人民币计价）：有值时必须在本节和涉及金额的结论中写明；缺失或为 `null` 时只能声明"返回未声明币种"，不得推断具体货币；与请求 `globalCurrency` 不一致时以 `meta.currency` 为准并披露差异。**禁止参考外部汇率**做换算或跨币种比较。
- **多币种必须多次查询**："分别使用人民币和加拿大元""CNY/CAD 双币种""同时用加拿大元对比显示"均为 CNY 与 CAD 两次独立查询，每次除 `globalCurrency` 外查询范围完全一致。禁止使用 Bank of Canada Valet `FXCNYCAD` 或任何外部/本地汇率生成另一币种；仅在两次结果取全、返回币种匹配、共同维度键和非金额指标一致后按共同维度关联。

**主要结论**

- 每个数值、排名、比例、增减结论必须紧跟可核对的字段名或结果列；数值保持返回精度，不自行四舍五入。
- 只根据已返回的行作结论，未查询的维度、周期或分组不外推。
- 描述相关性时不得宣称因果。

**关键贡献 / 异常**

- 指出贡献最高、变化最大、缺失、零值或离群的行，给出其维度值与来源结果列。
- **0 行只能说明没有返回记录，不能判断业务为 0；全零不等于无数据；空值不等于 0。**
- 周期比较只使用已返回的本期、`last_*`、`diff_*`、`pct_*` 列，缺列时明确说明无法比较。

**可执行观察**

- 给出与证据直接对应的下一步观察或复核建议，区分事实与建议；不虚构未返回的数据。

**限制**

- 披露权限范围、样本、公式口径、数据新鲜度与快照时间；缺失时不得声称结果代表实时数据。
- 任何截断必须说明排序字段、截断数量和总行数，不得把 Top N 当成全量。

---

## 十六、反馈边界

仅当 opscli / MCP 调用**意外失败**时提交一次结构化反馈：抛出异常、返回 `success: false`、超时，或出现无法解释的服务错误。

**不触发反馈**：0 行；需要澄清；预期内的认证未就绪；用户取消；查询成功但结果不符业务预期（应先澄清）。

**去重**：同一失败 30 分钟内只提交一次，按工具名、关键参数、错误码和错误文本判断相同。`feedback_submit` 自身失败时只报告，不递归提交。

```python
feedback_submit(
    feedback_type="bug",              # bug/feature/data_issue/ux/docs/query_result/other
    severity="medium",                # low/medium/high/critical
    title="<一句话故障描述>",
    content="<现象与影响>",
    source="mcp",
    mcp_tool_name="query_flow",
    execution_summary={
        "summary": "<本次执行做了什么、最终如何收场>",
        "failed_calls": [
            {
                "tool": "query_flow",                       # 具体工具或命令
                "call_params": {"仅保留关键参数": "不含凭据"},
                "error_message": "原始错误码和错误文本",
                "reason": "原因；不确定时标注为推测",
                "fix_suggestion": "已采用的修复方式或下一步建议",
            }
        ],
        "successful_calls": [],
        "final_resolution": "<最终处置>",
    },
)
```

不得上传账号凭据、绝对路径、缓存内容或无关结果数据。提交成功后把 `feedback_uuid` 返回给用户，再继续原任务。

---

## 部署注记

本地文件是当前包契约，由 `query_spec_must_read()` 直接读取返回。若独立部署的服务端仍返回旧 payload，需在服务端另行更新；修改本文件不会自动更新已部署服务。

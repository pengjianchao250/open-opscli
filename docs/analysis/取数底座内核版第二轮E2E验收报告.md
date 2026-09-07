# 取数底座内核版第二轮 E2E 验收报告

> 日期：2026-09-07 ｜ 被测：`ops-dataset-query` Skill v1.4.0（内核规划器版）→ 修复后 v1.4.1 ｜ 分支：release

## 一、验收范围与方式

第一轮验收（见《取数底座e2e多维矩阵验收报告》）暴露的内核/后端缺陷全部修复并合入 release 后，本轮重新做一次多轮、多维度的端到端验收：

| 维度 | 测试员 | 场景数 | 环境 |
| --- | --- | --- | --- |
| E1 基础取数 / 时间口径 / 趋势按日 | 子代理 | 14（含 2 次幂等复测） | QA 后端（隔离 HOME + 隔离 worktree CLI） |
| E2 筛选 / 组件枚举 / 币种 / 澄清 | 子代理 | 16 | 同上 |
| E3 图表 UUID / 降级路径 / MCP / 随包脚本 / 工具预算 | 子代理 | 7 组 22 项 | 同上 + 进程内 MCP 调用 |
| E4 文档与内核一致性复审 | 子代理 | 上一轮 11 项复核 + 本轮 10 键实证 + 197 个标识全仓扫描 | 只读 |
| 后端联动（快照指标 / 缓存币种 / 图表 404） | 主会话 | 8 条 | 本地后端 http://ops.cm（QA 库） |

- 主仓库当时处于 master 合并中，验收全部在 release 的 git worktree 及其独立 venv 上进行，QA 登录态与本地后端登录态分别隔离在两个 HOME 下。
- 所有场景均记录完整 stdout 与落盘结果，路径见文末。

## 二、结果总览

| 维度 | 结果 |
| --- | --- |
| E1 | 12 PASS / 2 预期澄清 / 0 FAIL；时间口径（近 7 天、本月、上周、环比、同比、显式区间）全部用独立 datetime 复算一致；证据合同 12/12 非空且 `missing_paths=[]`；三条独立路径（各平台 / 不拆分 / 筛 Temu）金额逐位一致；幂等复测两条完全一致 |
| E2 | 15 PASS / 1 FAIL（P0，见三.1） |
| E3 | 21 PASS / 1 FAIL（P1，见三.2）；图表 404 修复在 QA 已生效（优于任务书预期）；工具调用预算三请求各 2 次 |
| E4 | 上一轮 11 项文档问题全部修正且无回退；命令与参数 0 处虚构；文档提到而内核不写出的键 0 个；剩余问题集中在 QUERY_SPEC.md 滞后（见三.3） |
| 后端联动 | 缓存回放保留币种且 `meta.cached=true`；不存在图表 UUID 返回 404；QA 库 `snapshot_metric` 已迁移并标记 197 个指标；快照指标多日窗口仍被 SUM（见三.1 第 6 条） |

## 三、发现的缺陷与修复

### 3.1 内核（规划器 / 执行器）——本轮全部修复并有先红后绿测试

| # | 级别 | 现象 | 修复 |
| --- | --- | --- | --- |
| 1 | P0 | 「近7天销售额 只看德国」：德国不在授权枚举，且原文无字段标签，反查零命中后被静默放行成全部国家 | 国家字段接入常见国家词表 `_KNOWN_COUNTRY_VALUES`：反查零命中时用词表识别未授权国家，转 `component_filter_unauthorized` 澄清并下发当前账号可见国家候选 |
| 2 | P2 | 趋势/按日查询 `orderBy=null`，服务端返回日期完全乱序，与「按日期序列表述」的强制披露冲突 | 含时间粒度维度且用户未点名排序时默认写入 `orderBy=[{date_field, desc:false}]`；执行器既有本地重排兜底承接服务端未排序的情况 |
| 3 | P2 | 「各仓库库存量」：数据集没有仓库维度，分组诉求静默消失在数据集确认澄清里 | 新增 `dimension_not_in_dataset` 澄清码：「各X/每个X」点名的维度对不上任何授权维度标签时澄清，并回填 `unknown_requested_fields` → `field_suggestions_zh` |
| 4 | P2 | 「各渠道订单量前3」：无行数单位的 TopN 既不解析也不披露 | `_LIMIT_RE` 接受无单位写法，数字后紧跟时间单位（前7天/前3个月）仍排除 |
| 5 | P3 | 「订单量」静默映射为「销量」无披露 | 新增 `model_view.field_alias_mappings_zh` 与强制披露「字段称呼已按数据集口径对应」 |
| 6 | P1 | 快照指标（总库存等）多日窗口被服务端 SUM 成 7 天之和（本地后端实测 147590 = 各日之和） | 规划器把「全部为快照指标 + 未按时间粒度分组 + 多日窗口」收敛为最新完整快照日，写 `execution_ref.snapshot_policy` 并强制披露；快照与流量指标混查转 `snapshot_metric_window_conflict` 澄清；对比周期各取周期末快照日 |
| 7 | P3 | `freshness_status` 恒为空，「没有刷新完成度就不把末日异常当业务事实」不可执行 | 执行器新增 `result_disclosures.freshness_disclosure_zh`：窗口含今天且返回未声明新鲜度时出现 |
| 8 | P3 | `order_disclosure_zh` 回显技术字段名（price） | 改用执行引用的中文标签（「按「销售额」降序」） |
| 9 | P3 | `platform_semantic_members` 回显内部键（temu） | `PLATFORM_MEMBER_LABELS` 补全 TikTok/Walmart/Wayfair/Temu/Shopify/SHEIN/山姆 |
| 10 | 清理 | `refresh_in_progress` 恢复分支为死代码 | 删除 |

### 3.2 随包脚本与图表路径

| # | 级别 | 现象 | 修复 |
| --- | --- | --- | --- |
| 1 | P1 | 随包 `scripts/evidence_contract.py` 是内核修复前的旧实现：对真实返回形状输出空证据 + 恒定误导披露；图表路径因此没有任何可用证据合同 | `opscli query chart --run` 与 MCP `query_chart(run=True)` 的返回自带 `evidence_contract`（只取 `merged` 段生成）；随包脚本改为内核薄壳，仅供手工复算，测试守卫其输出与内核逐字一致 |

### 3.3 文档

E4 审计的 P1（QUERY_SPEC.md 多币种结构、新增澄清码与 model_view 键、趋势加日期维度）、P2（`--result-dir` 强度、降级白名单、QUERY_SPEC 读取边界、`component_filter_field_ambiguous` 候选口径、`query_component` 例外、`--global-currency` 适用范围）、P3（`--all-fields`、TopN 提示、白名单外币种路径），E3 的 D1–D6（chart 落盘参数、降级构造路径统一、图表路径预算、cli.md 按需读取判据、mcp.md 工具清单、L2b 卡片键名），E1 的 D2–D4（`{success,data}` 包裹体、平台收敛判据、耗时措辞）以及本轮内核新增行为，全部同步进 Skill 文档，版本升至 1.4.1。

## 四、验证证据

- 规划器套件：`tests/query/planner` 417 passed（新增 `test_round2_defects.py` 11 条、`test_snapshot_policy.py` 5 条、`test_entry.py` 3 条，全部先红后绿）；`tests/query` 594 passed。
- `tests/skills`（跳过 test_packaging.py）13 failed / 255 passed、`tests/mcp`（跳过 test_shopify_tools.py）1 failed / 456 passed，失败清单与已记录的预存基线完全一致。
- 本地后端实跑（http://ops.cm，QA 库）：
  - 「近7天各渠道总库存」→ 日期过滤收敛为 2026-09-06 单日，`snapshot_policy` 与披露齐全，6 个渠道行为切面值而非 7 日之和；
  - 「近7天销售额 只看德国」→ `clarify_required` + `component_filter_unauthorized` + 候选「加拿大、美国」；
  - 「近7天销售额趋势」→ `orderBy` 日期升序，返回 7 行按日期递增，`freshness_disclosure_zh` 出现；
  - 「近7天各部门订单量前3」→ `limit=3`、按销量降序、别名映射披露「订单量→销量」；
  - 「各仓库库存量 昨天」→ `dimension_not_in_dataset`，近似字段建议「海外仓库存」；
  - 「近7天Temu销售额」→ `platform_semantic_members=["Temu"]`，平台筛选注入。

## 五、遗留与后续

1. QA 后端仍运行旧代码：缓存回放保留币种、图表 404 等后端修复已在本地验证，需随 auto-scheduler / data-metrics release 部署到 QA 后再复验一次（图表 404 在 QA 已表现为生效）。
2. 后端目前不返回数据新鲜度，`freshness_disclosure_zh` 只能按「窗口含今天」保守提示；如需精确口径需后端在 `meta` 里下发刷新完成度。
3. 单条 `query flow` 冷启动 30~60 秒属环境波动（复测 7~15 秒），文档已改为「常态数秒到 30 秒内，冷启动可能到 60 秒」。
4. 主仓库当前在 master，本轮改动提交在 release；master 需由维护者合并/cherry-pick。

## 六、原始产物

- 第二轮各维度输出：`scratchpad/results/round2_E1|E2|E3|E4/`
- 本地后端复验：`scratchpad/wt_release/results_local/{snap2,round2_fix}/`
- 隔离环境：`scratchpad/wt_release/opscli_qa.sh`（QA）、`opscli_local.sh`（本地后端）

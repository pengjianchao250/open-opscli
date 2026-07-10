# ops-feedback 与 ops-query-wizard 优化改动分析报告

> 分析日期：2026-07-10
> 分析对象：工作区未提交改动（对比 HEAD `21418ad`）
> 涉及范围：`opscli/skills/templates/ops-feedback/`（v1.0.2 → v1.0.16）、`opscli/skills/templates/ops-query-wizard/`（v0.1.1，未 bump）
> 结论摘要：**ops-feedback 分级反馈改造方向正确、脚本实测可用，属于合理优化（附带问题已于当日修复，版本升至 v1.0.17）；ops-query-wizard 的反馈部分合理，但 Step 2–5 新体系依赖的文件在仓库/zip/本机安装目录中全部不存在，按当前状态不可合入。**

---

## 一、ops-feedback（v1.0.2 → v1.0.16）

### 1.1 改动内容

原版规则为"任何查询无论成功失败都必须提交反馈、失败 5 分钟去重"。新版改为四级分级策略：

| 层级 | 场景 | 处理 |
|------|------|------|
| L0 | dry-run / 本地只读 | 不提交 |
| L1 | 成功查询/引导 | 只写本地摘要，远端默认关闭 |
| L2 | 0 行/全空/降级/纠错 | 合并后每任务最多 1 条 |
| L3 | CLI/MCP 失败 | 即时提交 bug（保留原铁律） |

配套新增约 640 行的 `scripts/feedback_guard.py` 守门脚本（decide/record 两个子命令、本地状态去重、30 分钟滑动窗口、`feedback_group_key` 批量聚合、敏感字段脱敏、fail-open、认证轮询抑制），并同步改写 SKILL.md、FEEDBACK_RULE.md、references/cli.md、references/mcp.md 四份文档。

### 1.2 合理性评估（正面）

1. **解决真实痛点**：原版"每次成功查询都提交 query_result"造成成功路径反馈刷屏、token 浪费、后端低信噪比。分级后失败铁律不变（L3 即时提交），砍掉的只是低价值成功反馈。
2. **脚本实测行为正确**：L1 成功事件返回 `write_local_execution_summary`；L3 首次失败 `submit_remote=true`；`record` 后重复失败正确复用 `feedback_uuid` 且 occurrence_count 累加；`call_params` 中的 `token` 字段被正确脱敏。
3. **边界考虑周全**：fail-open 不递归反馈、认证轮询预期状态抑制、状态文件损坏按空状态继续、24 小时状态自动清理、`non_blocking` 防止反馈流程变成终止态。
4. **"先 guard 后 payload"低 token 快速路径**设计合理：仅 guard 放行才构造完整 execution_summary、才读长参考文档。

### 1.3 发现的问题与处置

| # | 级别 | 问题 | 处置（2026-07-10） |
|---|------|------|------|
| 1 | 高 | 全局 `~/.claude/CLAUDE.md` 铁律段仍写"5 分钟去重"，与 FEEDBACK_RULE.md/SKILL.md 的 30 分钟冲突 | ✔ 已修复：同步为 30 分钟并补充 `feedback_group_key` 聚合说明 |
| 2 | 高 | SKILL.md / FEEDBACK_RULE.md 声称 `evaluate_agent_traces.py` / `evaluate_wizard_traces.py` 是"当前参考实现"，全仓库不存在这两个文件 | ✔ 已修复：改为标注"待建设项"，并指向真实存在的 `tests/skills/test_feedback_guard.py` |
| 3 | 高 | 640 行新脚本零测试，违反铁律22 | ✔ 已修复：新增 `tests/skills/test_feedback_guard.py`（26 个用例，覆盖分类/去重/聚合/预算/脱敏/瘦身/兜底/清理），全部通过 |
| 4 | 中 | 脚本全英文 docstring、无中文注释，违反铁律17 | ✔ 已修复：全部改为中文 docstring 与段落注释，逻辑不变 |
| 5 | 中 | 状态文件默认 `~/.opscli/`，与项目统一配置目录 `~/.config/opscli/`（CONFIG_DIR）不一致 | ✘ 暂不处理（改路径涉及已部署用户状态迁移，需单独评估） |
| 6 | 低 | `fingerprint()` / `fingerprint_source()` 为死代码，且 `fingerprint()` 存在变量覆盖隐患（group_key 场景 identity 会错误回退为工具名）；`is_feedback_tool` marker 列表重复 | ✔ 已修复：删除两个死函数、去重 marker |
| 7 | 权衡 | 去重为滑动窗口：窗口内重复失败只刷新 `last_seen` 与本地计数，持续复发的失败不会自动再次远端提交，远端无法感知失败仍在持续 | ✔ 已明示：四份文档均补充滑动窗口语义说明；"累计 N 次强制再报"机制作为候选优化未实现 |
| 8 | 低 | 版本号从 v1.0.2 直接跳到 v1.0.16，中间 13 个版本无记录 | ✘ 无法追溯，仅记录在案 |

修复验证：`uv run pytest tests/skills/test_feedback_guard.py tests/skills/test_ops_feedback_template.py` → 32 passed；重写后脚本 CLI 冒烟（decide L3 失败事件）输出 `submit_immediate_failure_feedback / submit_remote=true`，行为与修复前一致。修复后版本 bump 至 v1.0.17。

---

## 二、ops-query-wizard（v0.1.1，未 bump）

### 2.1 改动内容

1. **反馈闭环分级化**：规则10、Step 10 流程图、纠错规则、analysis-guide 阶段五共四处，从"每次查询强制提交 query_result"改为跟随 ops-feedback 分级策略。
2. **Step 2–5 大改**：接入 ops-dataset-query 的一整套新体系——`validate_metadata.py` 自检、`agent_query_planner.py` 规划（compact 模式）、`get_dataset_guidance.py` contract/full 双模式、`decision_contract` 硬边界、冲突索引、知识包字段推荐、min_safe_query 默认策略、权限枚举前置。

### 2.2 合理性评估（正面）

- 反馈分级改造与 ops-feedback 完全联动，四处文档改得一致、无漏改。
- 设计意图质量高：字段推荐必须可追溯（否则不标 ✦）、min_safe_query 禁止无过滤裸跑大表、"用户主动筛选 vs 账号默认权限范围"区分、禁止编造默认 filters、公式指标禁止二次聚合——每条都针对真实取数事故模式，与铁律12 精神一致。

### 2.3 致命问题：引用悬空（截至分析日未解决）

新流程强依赖的文件在以下三处均不存在：仓库模板目录、`ops-dataset-query.zip`、本机已安装 `~/.claude/skills/ops-dataset-query`：

- 脚本：`agent_query_planner.py`、`get_dataset_guidance.py`、`validate_metadata.py`、`search_business_glossary.py`、`detect_field_ambiguity.py`（现存仅 `route_intent.py`、`search.py`）
- 数据：`ops_query_agent_contract.json`、`agent_dataset_decision_guide.json`、`dataset_selection_conflict_index.jsonl`、`agent_dataset_usage_catalog.jsonl`、`agent_dataset_knowledge_pack.jsonl`、`query_metadata_field_fallback.jsonl`、`global_filter_semantics.json`、`agent_business_glossary.jsonl`

后果：step-guide 将 Step 2 第 2、3 步写为**强制**执行 `validate_metadata.py` 与 `agent_query_planner.py`，Agent 一进 Step 2 即脚本报错；要么整段指引失效退化为旧行为，要么按反馈铁律为"脚本不存在"这类自造失败提交无效 bug 反馈。

该改动疑似面向一个尚未落库的新版 ops-dataset-query（该 Skill 支持远端升级，配套改动可能在别处）。方向本身没有问题，但**必须与 ops-dataset-query 的配套脚本和数据文件同批落地并联调通过后才可合入**。

### 2.4 其他问题

1. **【中】VERSION.json 未 bump**：行为大改但版本仍为 v0.1.1，`opscli skills status/upgrade` 依赖版本号，已安装用户无法感知升级。
2. **【低】"低 token"目标与文档自身膨胀矛盾**：SKILL.md"数据集匹配"一条膨胀为 500+ 字单段落，step-guide Step 2 从 5 行增至 40+ 行，并硬编码大量外部 schema 字段名和枚举值（`planner_decision_guide_snapshot_v1`、`planner_status` 四态等），与未落库 schema 强耦合，维护成本高。

---

## 三、处置建议汇总

| 项 | 建议 |
|---|---|
| ops-feedback 分级策略 | 保留；随附问题已修复（v1.0.17），guard 状态目录迁移（`~/.opscli` → `~/.config/opscli`）单独评估 |
| ops-query-wizard 反馈部分 | 保留，与 ops-feedback 一致 |
| ops-query-wizard Step 2–5 改造 | 暂缓合入，等待 ops-dataset-query 配套脚本与数据文件同批落地并联调；同时 bump VERSION.json；建议 ops-dataset-query 先行发布 |

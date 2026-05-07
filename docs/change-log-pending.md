# 待归档变更记录

## 2026-05-07 docs/guide — 更新 CLI 和 MCP 两份使用手册至 v0.0.35

**变更原因**：两份手册（`opscli命令用例手册.md` 和 `MCP工具使用手册.md`）停留在 v0.0.10，项目已迭代至 v0.0.35，缺少 seller-sprite 模块、mcp user 命令组、query catalog/simple 子命令、search/fetch MCP 工具等大量新增内容，需要全量更新以保持文档与代码一致。

**改动点**：

### opscli命令用例手册.md
1. 版本号从 `0.0.10` 更新为 `0.0.35`
2. 命令总览树新增 `seller-sprite`（含 account 子命令组）、`mcp user` 子命令组、`query catalog`/`query simple` 子命令
3. 新增第 6.2 节 `query catalog` 命令（读取业务语义索引）
4. 新增第 6.5 节 `query simple` 命令（基于 JSON 文件/字符串的简化查询）
5. 新增第 8 节 `seller-sprite` 模块完整文档（collect、frequency、keyword-mining、keyword-reverse、archive、login、login-status、schema、account save/list/delete，共 11 个子命令）
6. 新增第 9 节 `mcp` 管理模块（user list/add/remove/rotate，共 4 个子命令）
7. Skills 模板表从 4 个更新为 9 个
8. 新增组合用例：卖家精灵完整采集流程（10.5）、MCP 用户管理（10.6）
9. 快速索引表同步更新

### MCP工具使用手册.md
1. 版本号从 `0.0.10` 更新为 `0.0.35`
2. Tool 总览树新增 `query_catalog`、knowledge 分支（search/fetch）
3. 新增第 5.2 节 `query_catalog` 工具（读取业务语义索引）
4. 新增第 8 节 Knowledge 模块（ChatGPT/OpenAI 兼容的 `search` 和 `fetch` 工具，遵循 Company Knowledge 标准格式）
5. 新增组合用例：使用业务语义索引定位数据集（7.6）、使用 search/fetch 搜索数据集（7.7）
6. 认证状态速查表新增 `query_catalog`、`search`、`fetch` 三个工具
7. 快速索引表新增 `query_catalog`、`search`、`fetch` 映射

**验证结果**：文档变更，无代码修改，无需测试
**影响范围**：两份使用指南文档，不影响代码功能
**回滚方式**：git checkout -- `docs/guide/MCP工具使用手册.md` `docs/guide/opscli命令用例手册.md`
---

## 2026-05-07 ops-dataset-query 文档 — 补充 payload 互斥与 select 结构说明

**变更原因**：AI 在实际调用中频繁出现两类错误：(1) `opscli query simple` 同时传 `--payload` 和 `--json` 导致 CLI 报错；(2) 手写 `query run` payload 使用 `global_alias` 作为 key 而非 `expr`/`alias`，导致服务端 422 校验失败
**改动点**：
1. `references/cli.md` — `opscli query simple` 章节增加 `--payload`/`--json` 互斥警告框和错误示例
2. `references/cli.md` — `opscli query run` 章节增加 `query.select` 必填字段说明（`expr` + `alias`），含正确和错误对比示例
3. `references/mcp.md` — `query_run` 章节增加同样的 `select` 结构要求说明
**验证结果**：文档变更，无代码修改，无需测试
**影响范围**：ops-dataset-query Skill 的 CLI 和 MCP 参考文档
**回滚方式**：git revert 对应 commit
---

## 2026-05-07 MCP query/search — 4 项调用异常修复

**变更原因**：基于实际调用记录分析，发现 4 个影响数据查询体验的问题：query_simple 因透传 skills_dir 导致 TypeError；search 工具多词搜索命中率极低；where_conditions 格式文档缺失导致 AI 连续试错；CLI 优先级提示不够强
**改动点**：
1. `opscli/mcp/tools/query.py` — query_simple 调用 build_simple_and_run 时剔除 skills_dir 参数（build_simple 不接受此参数）
2. `opscli/mcp/tools/chatgpt.py` — search 工具新增 _tokenize_query 分词函数，_score_dataset_match / _score_field_match 支持多 token 逐词匹配累加分数
3. `opscli/mcp/tools/query.py` — query_build 和 query_build_and_run 的 docstring 补充 where_conditions 格式说明（field|operator|value_json）和示例
4. `opscli/skills/templates/ops-dataset-query/SKILL.md` — 运行模式判断增加"opscli 项目目录下必须用 CLI"的强制规则
**验证结果**：146 个测试通过（1 个已有的认证依赖测试失败，与本次无关）；多词搜索验证 "Amazon 销售额 广告花费" 可匹配到 verbose_name 含"广告花费"的字段（分数 50，原来为 0）
**影响范围**：MCP query_simple / search / query_build_and_run 工具；ops-dataset-query SKILL.md
**回滚方式**：git revert 对应 commit
---

## 2026-04-30 ops-dataset-query - P0/P1 修复 + 搜索空结果强制升级

**变更原因**：ops-dataset-query Skill 存在 10 项问题（P0-P3），包括 __pycache__ 泄漏、版本号不统一、where 字段名错误、函数重复定义、文档重复、搜索空结果无升级兜底等。用户反馈搜索"广告"返回空 `[]` 后 AI 直接放弃，未触发 upgrade。

**改动点**：
1. P0-1: 新增 `.gitignore`（__pycache__/*.pyc/*.pyo/.DS_Store）
2. P0-2: SKILL.md 版本号改为 `see data/VERSION.json`，cli.md/mcp.md 移除硬编码版本
3. P0-3: `query_mcp.py` 修复 `"logic": "AND"` → `"operator": "AND"`
4. P1-1: 8 个脚本的重复函数（discover_data_dir/load_local_index/resolve_dataset_alias/resolve_field_alias/try_upgrade/check_mapping_hit）统一提取到 `core.py`
5. P1-2: 新建 `references/query-patterns.md`（225行），cli.md 和 mcp.md 的重复高级计算章节改为引用（净减 ~290 行）
6. P2: SKILL.md/cli.md/mcp.md 增加"搜索结果为空时必须先 upgrade 再重试"的强制规则和示例

**验证结果**：8 个脚本 `import` 全部通过，无循环依赖
**影响范围**：ops-dataset-query Skill 的所有脚本和参考文档
**回滚方式**：`git checkout -- opscli/skills/templates/ops-dataset-query/`

---

## 2026-04-29 opscli - 实现 Skill 委托模式，防止 AI 猜测字段名

**变更原因**：测试调用记录显示，AI 在执行数据集查询时经常直接猜测字段名（如 `ds_pdTYjvLRCadv.asin`），导致 `INVALID_PAYLOAD` 错误。需要显式声明业务逻辑层 Skill 应将数据查询工作委托给 `ops-dataset-query` Skill，由其负责字段发现、metadata 验证和 payload 构造。

**改动点**：
- 为 9 个数据查询类 Skill 的 `SKILL.md` 添加"## 技能委托声明"部分
  - ops-asin-health-diagnoser（之前已完成）
  - ops-competitive-intelligence-analyst
  - ops-cross-border-product-selector
  - ops-advertising-efficiency-optimizer
  - ops-inventory-health-monitor
  - ops-product-attribute-analyzer
  - ops-perspective-builder
  - ops-profit-structure-analyzer
  - ops-refund-priority-matrix
- 每个委托声明包含：
  - 责任边界表（数据查询层 → ops-dataset-query，业务逻辑层 → 当前 Skill）
  - 委托触发规则表（5 场景，标注 ✅ 必须委托 / ❌ 可直接执行）
  - 委托调用方式示例（→ 调用 / ← 返回）
  - 反例警告（禁止直接猜测字段名）
- 插入位置统一为"阅读入口"和"使用原则"之间

**验证结果**：
- `grep -l "## 技能委托声明" opscli/skills/templates/ops-*/SKILL.md | wc -l` 返回 9
- 所有 9 个数据查询类 Skill 已包含完整委托声明

**影响范围**：
- AI Agent 在调用这些 Skill 时，会优先切换到 ops-dataset-query 进行字段发现
- 减少 INVALID_PAYLOAD 错误，避免额外的往返修复
- 不影响 CLI 模式用户直接使用 opscli query 命令

**回滚方式**：
- 删除各 SKILL.md 中"## 技能委托声明"部分（从 `---` 到下一个 `---`）

---

## 2026-04-27 opscli - 新增 chart_analyze_mcp.py

**变更原因**：为 ops-dataset-query Skill 新增 MCP 无状态模式的图表异常检测脚本，原 `chart_analyze.py` 依赖 `opscli` CLI（subprocess），无法在纯 MCP 环境中使用。

**改动点**：
- 新增 `opscli/skills/templates/ops-dataset-query/scripts/chart_analyze_mcp.py`
- 移除所有 `subprocess` 调用 `opscli` 的逻辑
- 数据获取改为纯文件输入（`--input` / `--dc-input`），由 MCP Agent 预先通过 `query_chart` / `query_build_and_run` Tool 获取后传入
- 移除自动 `upgrade` 兜底，改为返回错误并提示调用 MCP `skills_upgrade`
- 文件头部添加详细 MCP 调用指南注释（含前置 session 检查、Tool 调用示例、dataComparison 用法）
- 核心异常检测逻辑（5 类规则）与 `chart_analyze.py` 完全一致

**验证结果**：`python -m py_compile` 语法检查通过

**影响范围**：不影响现有 `chart_analyze.py`，为 MCP 环境提供独立入口

**回滚方式**：删除 `chart_analyze_mcp.py` 即可

---

## 2026-04-27 opscli - 新增 chart_map_mcp.py / excel_export_mcp.py / query_mcp.py / updater_mcp.py

**变更原因**：为 ops-dataset-query Skill 的 4 个核心脚本创建 MCP 无状态模式版本，原脚本均依赖 opscli CLI（subprocess 或直接导入内部模块），无法在纯 MCP 环境中使用。

### chart_map_mcp.py
- 新增 `opscli/skills/templates/ops-dataset-query/scripts/chart_map_mcp.py`
- 移除 `subprocess` 调用 `opscli query chart`（原 `--uuid`/`--run` 参数）
- 移除 `_try_upgrade()` 自动升级逻辑，映射失败时提示调用 MCP `skills_upgrade`
- 数据入口改为纯 `--input` 文件（由 MCP `query_chart` 获取后保存）
- 保留核心映射函数：`discover_data_dir`、`load_local_index`、`map_chart_queries`、`map_query_results`

### excel_export_mcp.py
- 新增 `opscli/skills/templates/ops-dataset-query/scripts/excel_export_mcp.py`
- 不再从 `chart_analyze.py` 导入 CLI 函数（`_check_mapping_hit`、`_try_upgrade`、`load_chart_data`）
- 自行实现文件版 `load_chart_data()` 和 `_check_mapping_hit()`
- 移除 `--uuid` 和 `--no-auto-upgrade` 参数
- 保留 Excel 导出核心逻辑：样式、行列类型判断、百分比列识别、列宽自适应

### query_mcp.py
- 新增 `opscli/skills/templates/ops-dataset-query/scripts/query_mcp.py`
- 原 `query.py` 为纯 opscli 转发脚本（`subprocess` 调用 CLI），MCP 模式下无直接价值
- 改造为**本地 Payload 构造器**：使用本地 CSV 索引实现字段别名解析（`global_alias > field_name > verbose_name`），构造标准 query payload JSON
- 支持 `build` 子命令（dimensions/metrics/where/order_by/limit/offset/data_comparison）和 `metadata` 子命令
- 输出 payload JSON 文件，供 MCP `query_run` Tool 使用
- 实现字段歧义自动消歧（`_pick_primary_field`，优先选取原始字段）

### updater_mcp.py
- 新增 `opscli/skills/templates/ops-dataset-query/scripts/updater_mcp.py`
- 移除对 `opscli.skills.models.SkillRecord` 和 `opscli.skills.updater.SkillsUpdater` 的依赖
- 改为仅检查本地 `VERSION.json` 和数据文件（`datasets.csv`、`dataset_fields.csv`、`query_metadata.json`）完整性的轻量脚本
- 更新操作提示通过 MCP `skills_upgrade` Tool 执行

**验证结果**：`python -m py_compile` 语法检查全部通过（4/4）

**影响范围**：不影响现有 CLI 版本脚本，为 MCP 环境提供独立入口

**回滚方式**：删除 4 个 `*_mcp.py` 文件即可

---

## 2026-04-27 opscli - 更新 SKILL_MCP.md 文档

**变更原因**：将新增的 5 个 MCP 版本脚本（`query_mcp.py`、`chart_map_mcp.py`、`chart_analyze_mcp.py`、`excel_export_mcp.py`、`updater_mcp.py`）的调用方式及用法补充到 SKILL_MCP.md 中，方便 MCP Agent 查阅。

**改动点**：
- 在 `opscli/skills/templates/ops-dataset-query/SKILL_MCP.md` 的"辅助脚本"章节中新增"MCP 环境辅助脚本"小节
- 每个脚本包含：功能说明、用法示例、输入来源（对应哪个 MCP Tool）、输出格式
- `query_mcp.py` 单独说明与 `query_run` Tool 的配合使用流程
- `chart_analyze_mcp.py` 包含 5 类异常检测规则速查表
- `excel_export_mcp.py` 包含格式规范说明

**影响范围**：仅文档更新，不影响代码

**回滚方式**：回退 SKILL_MCP.md 修改即可

---

## 2026-04-27 opscli - 新增 ops-skills/SKILL_MCP.md

**变更原因**：`ops-skills` 虽然不需要 `*_mcp.py` 脚本（核心功能本身就是 MCP Tool），但缺少 MCP 模式下的使用文档，导致 MCP Agent 无法了解 `skills_list`、`skills_install`、`skills_status`、`skills_upgrade` 四个 Tool 的参数格式和返回结构。

**改动点**：
- 新增 `opscli/skills/templates/ops-skills/SKILL_MCP.md`
- 包含完整的 4 个 MCP Tool 参数表：
  - `skills_list`：本地扫描，无需认证
  - `skills_status`：含远端版本对比
  - `skills_install`：纯本地模板安装
  - `skills_upgrade`：仅支持 `ops-dataset-query` 远端升级
- 提供典型工作流（全新环境初始化、日常版本维护、指定路径安装、强制重置）
- 明确认证说明：`skills_list`/`skills_install` 纯本地操作无需认证；`skills_status`/`skills_upgrade` 远端调用由服务器端内部处理

**影响范围**：仅文档新增，不影响代码

**回滚方式**：删除 SKILL_MCP.md 即可

---

## 2026-04-27 opscli - 新增 MCP 工具使用手册

**变更原因**：CLI 命令用例手册 (`opscli命令用例手册.md`) 无法直接指导 MCP 环境下的 Tool 调用，需要一份对应的 MCP Tool 使用手册，覆盖全部 4 个模块（auth / amazon / query / skills）共 24+ 个 Tool 的参数、返回结构和示例。

**改动点**：
- 新增 `docs/guide/MCP工具使用手册.md`
- 结构与 CLI 手册一一对应，但使用 Python 函数调用风格展示参数
- 每个 Tool 包含：参数表、返回示例、调用示例
- 包含认证状态速查表（哪些 Tool 需要认证、认证方式）
- 包含 CLI → MCP Tool 的映射对照表（快速索引）
- 覆盖 CLI 手册中所有 8 个常见组合用例的 MCP 版本

**影响范围**：仅文档新增，不影响代码

**回滚方式**：删除 `docs/guide/MCP工具使用手册.md` 即可

---

## 2026-04-29 opscli/skills - Skills 深度审查修复（16 项）

**变更原因**：对已开发完成的 9 个 Skills 进行全面深度审查，发现 7 项必须修复问题 + 6 项建议修复 + 3 项可选优化，逐一修复确保代码质量和安全性。

**改动点**：

### 🔴 必须修复（7 项）
1. **permission 格式错误**：5 个 reference 文件中 `"permission": ["{permission}"]` 改为 `"permission": "{permission}"`（字符串而非数组）
   - `ops-competitive-intelligence-analyst/reference/dataset_fields_mapping.md`
   - `ops-refund-priority-matrix/reference/dataset_fields_mapping.md`
   - `ops-perspective-builder/reference/dataset_fields_mapping.md`
   - `ops-profit-structure-analyzer/reference/dataset_fields_mapping.md`
   - `ops-cross-border-product-selector/reference/dataset_fields_mapping.md`
2. **透视模板缺失**：`build_perspective_config.py` 补充 4 个缺失模板（`ad_type_comparison`、`device_traffic`、`promotion_effectiveness`、`inventory_structure`）及对应触发词
3. **四行动策略硬编码**：`competitive_analysis.py` 的 `analyze_four_actions()` 将硬编码的保温杯建议改为基于品类数据和定位分析动态生成
4. **毛利润可能为负**：`analyze_cost_structure.py` 的 `gross_profit = 1.0 - total_cost` 改为 `max(0.0, min(1.0, 1.0 - total_cost))`
5. **重复 import**：`calculate_roas_acos.py` 删除 `if __name__` 块中重复的 `from typing import Optional`
6. **预估成本硬编码**：`product_selector.py` 的 `price * 0.35` 改为可配置参数 `DEFAULT_COST_RATIO` + 支持 `item.estimated_cost` 和 `internal_capability.cost_ratio`

### 🟡 建议修复（6 项）
7. **字段映射声明**：`ops-asin-health-diagnoser/SKILL.md` 阈值表添加 `sell_qty_days → inventory_days` 字段映射说明
8. **参数类型标注错误**：`product_selector.py` 的 `classify_quadrant` 参数 `sentiment_score` 从 `Optional[str]` 改为 `Optional[float]`
9. **硬编码日期**：`generate_replenishment_plan.py` 新增 `reference_date` 参数，默认 `datetime.now()`，支持测试和回测
10. **description 混合语言**：`ops-profit-structure-analyzer` 和 `ops-refund-priority-matrix` 的 frontmatter description 改为纯英文
11. **错误输出方向**：`calculate_health_score.py` 错误信息同时输出到 stdout 和 stderr
12. **SKILL.md 标题风格**：统一 3 个标题为 `# 英文标题` + 中文副标题格式

### 新增铁律
13. **CLAUDE.md 新增【铁律18】**：代码修改后必须更新变更记录文件 `docs/change-log-pending.md`

**验证结果**：所有 14 个脚本通过 `echo '{}' | python script.py` 基础测试，关键脚本（health_score、cost_structure、roas_acos、perspective_builder、competitive_analysis、product_selector）通过正常数据测试

**影响范围**：仅影响 Skills 模板的脚本和文档，不影响 opscli 核心功能（auth/query/mcp）

**回滚方式**：`git checkout -- opscli/skills/templates/ CLAUDE.md docs/change-log-pending.md`

---

## 2026-04-29 CLAUDE.md - 整合 Andrej Karpathy 编码行为准则为铁律19-22

**变更原因**：将 https://github.com/forrestchang/andrej-karpathy-skills/blob/main/CLAUDE.md 中 4 条编码行为准则翻译为中文，以【铁律19~22】形式追加到项目 CLAUDE.md 的铁律章节，与项目现有铁律风格保持一致。

**改动点**：
- CLAUDE.md 新增 4 条铁律：
  - 【铁律19】编码前先思考，不假设、不掩盖困惑（原文：Think Before Coding）
  - 【铁律20】极简优先，只写解决问题所需的最少代码（原文：Simplicity First）
  - 【铁律21】精确变更，只改必须改的（原文：Surgical Changes）
  - 【铁律22】目标导向执行，定义成功标准并验证闭环（原文：Goal-Driven Execution）
- 原则：忠于原文核心精神，中文表达贴合项目铁律风格（禁止行为列表 + 判断标准）

**验证结果**：4 条铁律内容对照原文无遗漏，中文表达通顺

**影响范围**：仅影响 CLAUDE.md 文档，不影响代码

**回滚方式**：删除 CLAUDE.md 中【铁律19】至【铁律22】段落

---

## 2026-04-29 auto-scheduler + opscli - 图表查询接口增加过滤字段及新增 chart-doc 指令

**变更原因**：
1. 服务端 `latest-request-data` 接口需要返回当前图表数据集支持的过滤条件字段，供 opscli 侧了解可用 WHERE 条件
2. opscli 侧需要在图表查询结果中透传过滤字段信息
3. 新增 `opscli query chart-doc` 指令，支持通过 chart_uuid 自动生成完整 API 调用 Markdown 文档

**改动点**：

### 服务端（auto-scheduler）
- 修改 `vendor/aukey/data-metrics/src/Http/Controllers/CliQueryApiController.php`
  - 引入 `Aukey\DataMetrics\Models\SelectColumnRelation`
  - `latestRequestData` 方法新增逻辑：通过 `query.from.alias` → `dm_tables.dataset_alias` → `dm_select_column_relations.dataset_alias` 查询启用的过滤字段
  - 返回结构扩展：每个 query item 新增 `filterable_fields` 字段（含 `column_name`、`verbose_name`、`source_column_name`）
  - 按 `dataset_alias` 缓存避免重复查询

### opscli 侧
- 修改 `opscli/query/services/manager.py`
  - `run_chart_queries` 方法透传 `filterable_fields` 和 `query_structure` 到每个 query 结果中
  - 新增 `generate_chart_doc(chart_uuid)` 方法：生成完整 Markdown 文档，含数据集概览、过滤字段表、查询结构说明、API 调用顺序、Payload 示例、WHERE 条件构建指南
  - 示例中敏感字段（`table`/`permission`）使用占位符，不返回 `userEmail`
- 修改 `opscli/query/commands/cli.py`
  - 新增 `chart-doc` 子命令：`opscli query chart-doc --uuid <chart_uuid> [--output <file>] [--pretty]`
  - 支持将 Markdown 文档直接写入文件

**验证结果**：
- `python -m py_compile opscli/query/services/manager.py opscli/query/commands/cli.py` 语法检查通过
- 服务端 PHP 文件未引入语法错误（新增 import + 扩展已有循环逻辑）

**影响范围**：
- 服务端 `latest-request-data` 接口返回结构向后兼容扩展（新增字段）
- opscli `query chart` 和 `query chart-run` 返回的每个 query 中新增 `filterable_fields` 和 `query_structure`
- 新增 `query chart-doc` 命令，不影响现有命令

**回滚方式**：
- 服务端：回退 `CliQueryApiController.php` 的 `latestRequestData` 方法修改
- opscli：回退 `manager.py` 中 `run_chart_queries` 和 `generate_chart_doc`，回退 `cli.py` 中 `chart_doc` 命令

---

## 2026-04-29 query - 优化 chart-doc 生成文档结构

**变更原因**：生成的文档存在三个缺陷：可过滤字段在多 Query 时重复渲染浪费 token；7.1 字段映射表列数达 8 列宽表 AI 不友好；缺少字段命名约定说明导致 AI 无法处理边界场景
**改动点**：
1. `opscli/query/services/manager.py - generate_chart_doc`：
   - §2 新增"字段命名约定"小节（§2.2），说明 query_alias / global_alias / origin_name / expr 的格式规律、生成方式和使用场景，及公式字段边界说明
   - §7.1 输出字段映射由 1 张 8 列宽表拆分为 2 张 4 列表（表A字段语义 + 表B字段引用），以 field_name 作连接键，expr 列去掉并在表B注释中说明
   - §7.3 可过滤字段新增去重逻辑：对比当前 Query 与所属数据集（§5.2）的 filterable_fields 集合，完全相同时只输出一行引用语句，不同才完整渲染
2. `tests/query/test_manager.py`：更新两个受影响的测试断言匹配新双表格式和去重引用格式
**验证结果**：pytest tests/query/ 39 passed
**影响范围**：opscli query chart-doc 命令输出的 Markdown 文档结构；不影响 API 调用逻辑
**回滚方式**：git revert 此次改动，恢复 manager.py 和 test_manager.py 对应段落
---

## 2026-04-29 skills/templates - 精简所有 Skill 的 references 文档

**变更原因**：`data-query-service-dev-guide.md`（1173行）在 9 个业务 Skill 中存在完全相同的 10 份副本，占每个 Skill 文档总量的 60-75%；其中大量章节（多次查询、MOY/ACC/PPT、缓存、PHP 伪代码）对 Skill 执行无用，造成 AI 上下文浪费和维护困难

**改动点**：
1. 新建 `query-essential-guide.md`（149行）：从完整 dev-guide 中提取 Skill 真正需要的内容（WHERE 操作符、SELECT 格式、日期规范、dataComparison、错误码），复制到 9 个业务 Skill 的 references/
2. 删除 9 个业务 Skill 中的 `data-query-service-dev-guide.md`，保留 `ops-dataset-query/references/` 中的唯一完整版
3. 精简 `ops-asin-health-diagnoser/references/dataset_fields_mapping.md`（134行→65行）：去掉静态 payload 模板，保留数据集索引 + 核心字段业务语义 + chart-doc 使用指引
4. 更新 9 个 Skill 的 `SKILL.md`、`references/cli.md`、`references/mcp.md` 中的文件名引用（data-query-service-dev-guide → query-essential-guide）

**验证结果**：
- dev-guide 残留检查通过（9 个业务 Skill 均已删除）
- query-essential-guide 分布：9 个 Skill 均已到位
- 各 Skill 文档总行数：平均从 ~1800 行降至 ~737 行，减少约 59%

**影响范围**：所有业务类 Skill 的 references 目录结构；ops-dataset-query 不受影响
**回滚方式**：从 ops-dataset-query/references/data-query-service-dev-guide.md 重新 cp 到各 Skill，删除 query-essential-guide.md，恢复文件名引用
---

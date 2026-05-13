---
name: ops-dataset-query
description: 使用 MCP Tool 查询本地缓存的数据集与字段索引，执行数据查询（无状态模式）
---

# ops-dataset-query (MCP 无状态模式)

使用 MCP Tool 查询本地缓存的数据集与字段索引，通过 `query_simple`、`query_build_and_run`、`query_run` 等 Tool 执行数据查询。**无状态模式**：服务器不保存用户 OAuth 凭证，所有认证信息由调用方传入。

---

## 文档阅读入口

> **【强制】文档阅读顺序**
>
> 1. **必须优先阅读 `references/simple-query-guide.md`** — 简化接口参数、使用场景、示例
> 2. **MCP 简易版 Tool 详解**：`references/mcp-simple-guide.md` — `query_simple`、`query_build_and_run`
> 3. **MCP 完整版 Tool 详解**：`references/mcp-advanced-guide.md` — `query_build`、`query_run`、`query_chart`、降级方案、MCP 辅助脚本
> 4. **只有多次查询失败时**，才尝试阅读 `references/data-query-service-dev-guide.md`
> 5. **涉及 `innerWhere` 的数据集（子查询数据集，inner_where_enabled=true）不允许使用 `query_run` 手写完整 payload**，只能用 `query_simple`

---

## ChatGPT / OpenAI 兼容工具

本 Skill 同时提供 OpenAI [Company Knowledge](https://openai.com/index/introducing-company-knowledge/) 标准工具，无需认证即可搜索本地数据知识库：

| 工具 | 用途 | 参数 | 返回 |
|------|------|------|------|
| `search` | 搜索数据集和字段 | `query: str` | `{"results": [{"id", "title", "url"}]}` |
| `fetch` | 获取详细信息 | `id: str` | `{"id", "title", "text", "url", "metadata"}` |

---

## 调用前置要求

> **认证按动作触发**：本地知识检索不要求登录；涉及远端 catalog、查询执行、图表运行或升级时，必须确认有效 `session_id`。

- 本地只读动作可直接执行：`search`、`fetch`、`query_catalog(source="local")`
- `query_metadata` 远端优先，远端失败自动回退本地（无需额外检查）
- 远端动作前先调用 `auth_is_authenticated(session_id)` 检测 session 有效性：`query_catalog()`、`query_simple`、`query_build_and_run`、`query_run`、`query_chart(run=True)`、`skills_upgrade`
- 若返回 `false` 或报错，说明 `session_id` 缺失或已过期
- **若 `session_id` 缺失/过期**：
  1. `auth_login_start()` → 获取 `verification_url` + `user_code`
  2. 提示用户在浏览器中打开 URL 并输入验证码
  3. 按 `interval` 轮询 `auth_login_poll(device_code)` 直到 `status=authorized`
  4. 获取返回的 `session_id`，保存到当前对话上下文
- 只有认证状态确认正常后，才允许继续执行远端动作

**标准前置流程**：
```python
auth_is_authenticated(session_id="xxx")
# 如无效 → auth_login_start() → auth_login_poll(device_code="xxx") → 再次 auth_is_authenticated
```

---

## 使用原则

- 本 Skill 只负责本地字段搜索、缓存读取和辅助构造查询参数
- 所有远端查询动作必须通过 MCP Tool 执行，**禁止直接调用后端 HTTP 接口**
- 本地数据过期或字段不存在时，先执行 `skills_upgrade(name="ops-dataset-query")` 再重试查询
- 字段搜索结果已按相关性排序（精确匹配 > 子串匹配 > 关键词匹配）
- **`query_simple` 优先**：普通聚合、数据对比、MOY 趋势、子查询等场景，优先使用简化接口（详见 `references/simple-query-guide.md` 和 `references/mcp-simple-guide.md`）
- `query_build_and_run` 适合基于简化参数构造标准 query payload 并立即执行（详见 `references/mcp-simple-guide.md`）
- `query_build` 适合基于简化参数构造标准完整 query payload（输出完整版结构，不执行，详见 `references/mcp-advanced-guide.md`）
- `query_run` 适合透传完整手写高级 payload（仅当简化接口和 `query_build` 均不满足需求时使用，详见 `references/mcp-advanced-guide.md`）
- **`query_run` 禁用场景**：涉及 `innerWhere` 的数据集（子查询类型，`inner_where_enabled=true`）**禁止使用** `query_run`，只能用 `query_simple`
- `query_chart` 适合通过图表 UUID 直接获取图表结构或执行图表查询，无需手动构造 payload（详见 `references/mcp-advanced-guide.md`）
- 所有查询工作流都必须以前置的 `session_id` 有效性检测作为起点
- **文档引用顺序**：优先参考 `references/simple-query-guide.md` 和 `references/mcp-simple-guide.md`；多次查询失败时才参考 `references/data-query-service-dev-guide.md`

---

## 【强制】字段存在性检查

> 在 MCP 模式下，构造任何 query 参数前，必须先确认目标数据集和字段真实存在；**搜索结果为空时，先判断本地数据是否已初始化，再决定是否升级**。

**标准顺序**：
1. 用 `search(query="...")` 或 `fetch(id="...")` 确认目标 `dataset_alias` 和字段
2. 用 `query_metadata()`（无参数）查看可用数据集列表
3. 如需获取**最新**字段信息（含公式字段、聚合方式），调用 `query_metadata(dataset="<alias>")`（远端优先，自动回退本地）
4. 如果数据集或字段不存在，先检查本地数据是否为空/placeholder
5. 为空时执行 `skills_upgrade(name="ops-dataset-query")`
6. 升级后重新执行字段检查
7. 若升级后仍不存在，明确告知用户当前本地索引和 metadata 中没有该字段，不要猜字段名继续查

**【强制】搜索结果为空时的处理流程**：
> 当 `search()` 返回空列表时，不要直接告知用户"找不到"。先确认本地数据是否为空/placeholder；为空时升级本地数据再重试。

**判断原则**：
- `search` / `fetch` / 本地脚本结果里都找不到目标字段时，不要直接构造 payload
- 优先接受这几类命中：`field_name`、`global_alias`、`verbose_name`
- 公式字段必须额外看 `query_metadata`，不能只看索引名称就推断表达式
- `query_metadata` 与本地索引同时都缺失时，才可判定当前 Skill 数据未覆盖或字段确实不可用

### 【强制】比较类查询优先级规则

> 涉及环比、同比、趋势对比等场景时，**必须按以下优先级选择方案，禁止跳过高优先级直接多次调用 Tool 后在客户端合并结果**。

| 优先级 | 场景 | 方案 |
|--------|------|------|
| ① 最优 | 当期 vs 对比期汇总对比（环比/同比） | `dataComparison`（服务端条件聚合，一次 SQL） |
| ② 次优 | 按时间粒度分组的趋势环比/同比 | `MOY` 高级计算（服务端窗口函数，一次 SQL） |
| ③ 兜底 | ①② 均因工具限制无法使用时 | 多次 `query_run` + 客户端合并 |

> `comparison`（MOY/ACC/PPT）写在 `select` 字段内部可正常透传。

---

## 本地数据文件

| 文件 | 内容 | 说明 |
|------|------|------|
| `data/VERSION.json` | 版本号 | `{"name": "ops-dataset-query", "version": "v1.x.x"}` |
| `data/dataset_catalog.json` | **预定义业务意图集合**（非数据集列表） | version、intent_count、intents、query_strategy |
| `data/dataset_fields.csv` | 字段明细 | dataset_alias、field_name、verbose_name、global_alias、field_type、formula_config 等 |
| `data/datasets.csv` | 数据集列表 | table_id、dataset_alias、dataset_name、dataset_type、inner_where_enabled 等 |
| `data/query_metadata.json` | 查询元数据 | 字段类型映射、可用聚合方式等 |

CSV 各列详细说明见 `references/data-query-service-dev-guide.md` 附录。

---

## 辅助脚本索引

以下脚本位于 `scripts/` 目录，**不依赖 opscli，可直接运行**。

| 脚本 | 用途 | 详细文档 |
|------|------|---------|
| `search.py` | 本地字段搜索 | `references/mcp-advanced-guide.md` |
| `core.py` | CSV 加载、搜索打分、数值转换等底层工具函数 | `references/mcp-advanced-guide.md` |
| `query_mcp.py` | 本地 Payload 构造器（简化参数 → 完整 payload JSON） | `references/mcp-advanced-guide.md` |
| `chart_map_mcp.py` | chart 字段别名映射 | `references/mcp-advanced-guide.md` |
| `chart_analyze_mcp.py` | 图表异常检测 | `references/mcp-advanced-guide.md` |
| `excel_export_mcp.py` | 图表数据 Excel 导出 | `references/mcp-advanced-guide.md` |
| `updater_mcp.py` | 本地数据状态检查 | `references/mcp-advanced-guide.md` |

---

## 辅助 Tool 索引

以下 Tool 用于数据集/字段检索和意图分析，**不直接执行数据查询**。

| Tool | 用途 | 认证要求 | 详细文档 |
|------|------|---------|---------|
| `query_metadata` | 读取数据集 metadata。**无参数返回数据集列表**；指定参数时远端优先获取最新字段 | 远端时需要 | `references/mcp-advanced-guide.md` |
| `query_catalog` | 将 NL 需求与**预定义业务意图（intents）匹配**，识别目标数据集（**非数据集列表**，查数据集列表请用 `query_metadata`） | 远端时需要 | `references/mcp-advanced-guide.md` |

---

## 查询 Tool 索引

| Tool | 类型 | 说明 | 详细文档 |
|------|------|------|---------|
| `query_simple` | 简易版 | 基于简化参数直接执行查询（推荐优先使用） | `references/mcp-simple-guide.md` |
| `query_build_and_run` | 简易版 | 基于简化参数构造标准 payload 并立即执行 | `references/mcp-simple-guide.md` |
| `query_build` | 完整版 | 基于简化参数构造标准完整 payload（不执行，不需要认证） | `references/mcp-advanced-guide.md` |
| `query_run` | 完整版 | 透传完整手写 payload（仅当简化接口和 `build` 均不满足时使用） | `references/mcp-advanced-guide.md` |
| `query_chart` | 完整版 | 通过图表 UUID 获取结构或执行，含多 query | `references/mcp-advanced-guide.md` |

---

## 高级查询说明

**使用优先级**：
1. **`query_simple`**（推荐）：普通聚合、数据对比、MOY 趋势、子查询等场景
2. **`query_build_and_run`**：基于 `dimensions`/`metrics` 等简化参数构造标准 query payload 并立即执行
3. **`query_build`**：基于简化参数构造标准完整 query payload（不执行，输出完整版结构供 `query_run` 使用）
4. **`query_run`**：仅当上述均无法满足需求时，手写完整 payload 透传

**文档引用顺序（强制）**：
1. **优先阅读 `references/simple-query-guide.md`** — 所有普通场景先按简化接口处理
2. **MCP Tool 细节阅读 `references/mcp-simple-guide.md`**
3. **只有多次查询失败时**，才阅读 `references/data-query-service-dev-guide.md` 排查深层问题
4. **涉及 `innerWhere` 的数据集（子查询类型）禁止使用 `query_run`**，无论简化接口是否满足需求，都必须使用 `query_simple`

> 简化接口完整说明见 **`references/simple-query-guide.md`**。
> MCP 简易版 Tool 详解见 **`references/mcp-simple-guide.md`**。
> MCP 完整版 Tool 详解见 **`references/mcp-advanced-guide.md`**。
> 完整 query payload 规范（innerWhere / translate / 权限占位符等）见 **`references/data-query-service-dev-guide.md`**（多次失败时参考）。

---

## MCP 认证工具速查

| 动作 | Tool |
|------|------|
| 检查 session 有效性 | `auth_is_authenticated(session_id="xxx")` |
| 获取 JWT | `auth_get_token(system="ops", session_id="xxx")` |
| 检查 JWT 有效期 | `auth_check_token(jwt="xxx")` |
| 刷新 JWT | `auth_token_refresh(system="ops", session_id="xxx")` |

---

## 错误处理

| 场景 | 解决方法 |
|------|---------|
| 本地数据为空 | `skills_upgrade(name="ops-dataset-query")` |
| dataset_alias 不存在 | 先 `query_metadata()` 查看可用数据集列表；确认拼写或 `skills_upgrade` 同步最新数据集 |
| 字段映射全部失败 | 先 `query_metadata(dataset="<alias>")` 远端获取最新字段；仍失败则 `skills_upgrade(name="ops-dataset-query", force=True)` |
| 仅需确认单个数据集字段 | `query_metadata(dataset="<alias>")` 按需远端查询，无需全量升级 |
| 未登录 / session 无效 | `auth_login_start()` → 浏览器授权 → `auth_login_poll()` |
| Token 过期 | `auth_token_refresh(session_id)`；如 session 也过期则重新 Device Flow 授权 |
| payload 文件不存在 | 先 `query_build` 生成 |
| chart_uuid 不存在或已删除 | 确认图表 ID 正确，或检查该图表是否有访问权限 |
| 图表查询执行失败 | 查看返回的 `error` 字段获取具体错误信息，常见原因：数据集权限不足、字段已变更 |

---

## 典型工作流

### 意图分析 → 数据集选择 → 构造 → 执行（推荐）

> **【强制】用户未指定 dataset 时，必须从远程 catalog 意图匹配开始，禁止跳过直接用本地搜索猜测。**

```
1. 检查 session 有效性（auth_is_authenticated）
   → 无效则重新 Device Flow 授权

2. 远程 catalog 意图分析（query_catalog）
   → 从 intents 中匹配 use_cases / keywords / scenario_description
   → 按 priority 选择最佳候选
   → 提取 table_id、dataset_alias、default_filters、comparison_strategy

3. 用本地索引校验目标字段
   → search(query="<field_name>") 或 query_metadata(dataset="<dataset_alias>")

4. 构造并执行查询
   → 简易版：query_simple / query_build_and_run（详见 mcp-simple-guide.md）
   → 完整版：query_build → query_run / query_chart（详见 mcp-advanced-guide.md）
```

### 数据更新 → 重新查询

```
1. 检查 session（auth_is_authenticated）
2. 检查版本状态（skills_status）
3. 升级到最新（skills_upgrade）
4. 重新查询
```

---

## 安装与管理

```python
# 0. 先检查 session（skills_install / skills_upgrade 需要认证）
auth_is_authenticated(session_id="xxx")

# 安装（skills_dir 可选，未指定时自动发现 ~/.claude/skills 等标准路径）
skills_install(name="ops-dataset-query")

# 强制重装
skills_install(name="ops-dataset-query", force=True)

# 查看版本
skills_status()

# 升级
skills_upgrade(name="ops-dataset-query")
```

---

## 字段搜索（本地索引）

本 Skill 内置本地字段索引，可用于辅助确认 `dataset_alias`、`field_name`、`verbose_name`。

**推荐流程**：本地索引确认字段名 → `query_metadata` 查看完整 metadata → **`query_simple`**（优先）或 `query_build_and_run` / 手写 payload + `query_run`

### `search.py` — 本地字段搜索

命令行关键词搜索本地字段索引，支持按数据集过滤和限制返回数量。

**用法**：`python scripts/search.py <keyword> [--dataset <dataset_alias>] [-n <limit>]`

**输出**：JSON 数组，每项包含字段完整信息（dataset_alias、field_name、verbose_name、global_alias、field_type 等）。

### `core.py` — 底层工具函数库

提供 CSV 加载、行过滤、搜索打分、数值转换与格式化等基础能力，仅依赖 Python 标准库。

**核心函数**：

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `load_csv_rows(path)` | `Path` | `list[dict]` | 加载 CSV 为字典列表（utf-8-sig 编码，兼容 BOM） |
| `filter_rows_by_dataset(rows, dataset)` | `list[dict]`, `str \| None` | `list[dict]` | 按 dataset_alias 过滤行 |
| `search_rows(rows, keyword, limit=10)` | `list[dict]`, `str`, `int` | `list[dict]` | 按关键词搜索并返回相关性排序结果 |
| `to_float(v)` | `Any` | `float` | 安全转换查询结果为 float，失败返回 0.0 |
| `safe_pct(cur, prev)` | `float`, `float` | `float \| None` | 计算环比变化率（小数形式），除零保护 |
| `format_pct(value)` | `float \| None` | `str` | 格式化变化率为可读字符串，如 "+12.34%" / "N/A" |

**搜索排序策略（相关性从高到低）**：

| 匹配类型 | 分值 |
|---------|------|
| `field_name` 精确匹配 | 120 |
| `verbose_name` 精确匹配 | 100 |
| `field_name` 子串匹配 | 60 |
| `verbose_name` 子串匹配 | 45 |
| `dataset_alias` 精确匹配 | 40 |
| `description` 子串匹配 | 10 |

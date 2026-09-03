---
name: ops-dataset-query
description: 使用本地缓存的数据集与字段索引辅助检索和查询（CLI 模式）
---

# ops-dataset-query（CLI 模式）

使用本地缓存的数据集与字段索引辅助检索可用数据集、维度和指标，通过 `opscli query` 执行数据查询，通过 `opscli skills upgrade` 拉取远端最新数据。

---

## 文档阅读入口

> **【强制】文档阅读顺序**
>
> 1. **必须优先阅读 `references/rules.md`** — 查询前意图澄清规则
> 2. **必须优先阅读 `references/ask-user-question-guide.md`** — 结构化提问与确认规范
> 3. **必须优先阅读 `references/simple-query-guide.md`** — 简化接口参数、使用场景、示例
> 4. **CLI 查询命令详解**：`references/cli-simple-guide.md` — `opscli query simple`、`opscli query chart`、辅助脚本

---

## 调用前置要求

> **认证按动作触发**：本地只读检索不要求登录；涉及远端执行或升级时，必须先检测是否已授权登录。

- 本地只读动作可直接执行：`python scripts/search.py`、`python scripts/route_intent.py`、`opscli query metadata`、`opscli query intent`、`opscli query catalog`
- 远端动作前先执行 `opscli auth token status`：`opscli query simple --run`、`opscli query chart --run`、`opscli skills upgrade ops-dataset-query`
- 若状态中出现“未登录 / 未授权 / Token 过期 / expired / 401”，必须立即调用 `ops-auth` Skill
- 若是“未登录 / 未授权 / 401”，在 `ops-auth` 中执行 `opscli auth login`
- 若是 JWT Token 过期，优先执行 `opscli auth token refresh --all` 或 `opscli auth token refresh -s ops`；刷新失败再执行 `opscli auth login`
- 登录或刷新后重新执行 `opscli auth token status`，确认正常后再继续远端动作

**标准前置流程：**

```bash
# 仅在远端执行或升级前检查是否已登录
opscli auth token status

# 2. 如 JWT Token 已过期，先刷新
opscli auth token refresh --all

# 3. 如未登录、未授权、刷新失败或状态仍异常，立即调用 ops-auth Skill 处理
opscli auth login

# 4. 登录后再次确认
opscli auth token status
```

---

## 使用原则

- 本 Skill 只负责本地字段搜索、缓存读取和辅助构造查询参数
- 所有远端查询动作必须通过 `opscli query` 执行，**禁止直接调用后端 HTTP 接口**
- 本地数据过期或字段不存在时，先执行 `opscli skills upgrade ops-dataset-query` 再重试查询
- 字段搜索结果已按相关性排序（精确匹配 > 子串匹配 > 关键词匹配）
- **`opscli query simple` 优先**：普通聚合、数据对比、MOY 趋势、子查询等场景，优先使用简化接口（详见 `references/simple-query-guide.md` 和 `references/cli-simple-guide.md`）
- `opscli query chart` 适合通过图表 ID 直接获取查询结构并执行，支持多 query 自动合并、小计/总计处理、Excel 导出（详见 `references/cli-simple-guide.md`）
- 所有查询工作流都必须以前置的 `ops-auth` 登录检测作为起点
- **文档引用顺序**：参考 `references/simple-query-guide.md` 和 `references/cli-simple-guide.md`

---

## 【强制】字段存在性检查

> 在 CLI 模式下，构造任何 query 参数前，必须先确认目标数据集和字段真实存在；**搜索结果为空时，先判断本地数据是否已初始化，再决定是否升级**。

标准顺序：

0. 若用户未显式指定 `dataset_alias/table_id`，必须先执行 `opscli query intent -q "<用户自然语言需求>"` 走远端实时意图目录；不可用/报错/未命中再执行 `python scripts/route_intent.py` 本地意图路由，仍未命中再用 `python scripts/search.py` 关键词搜索
1. 已确认目标数据集后，确认目标 `dataset_alias` 是否存在于 `data/datasets.csv`，或用 `opscli query metadata`（无参数）查看数据集列表
2. 再确认目标字段是否存在于 `data/dataset_fields.csv`
3. 如需获取**最新**字段信息（含公式字段、聚合方式、表达式结构），执行 `opscli query metadata --dataset <dataset_alias> --pretty`（远端优先，自动回退本地）
4. 如果数据集或字段不存在，先检查本地数据是否为空/placeholder；为空时执行 `opscli skills upgrade ops-dataset-query`
5. 升级后重新执行字段检查
6. 若升级后仍不存在，明确告知用户当前本地索引和 metadata 中没有该字段，不要猜字段名继续查

**【强制】搜索结果为空时的处理流程**：

> 当 `python scripts/search.py` 返回空列表 `[]` 时，不要直接告知用户"找不到"。先确认本地数据是否为空/placeholder；为空时升级本地数据再重试。

```bash
# 搜索返回空结果时
python scripts/search.py "广告" -n 20
# 输出: []

# 如果本地数据为空/placeholder，升级本地数据
opscli skills upgrade ops-dataset-query

# 升级后重新搜索
python scripts/search.py "广告" -n 20
# 如果仍然为空，再告知用户
```

推荐检查方式：

```bash
# 0. 用户未指定数据集时，先走远端意图目录，不可用/未命中再做本地意图路由
opscli query intent -q "查看库存周转趋势" --pretty
python scripts/route_intent.py "查看库存周转趋势"

# 1. 意图路由确认数据集后，再确认数据集
python scripts/search.py sales_order_d -n 20

# 2. 在指定数据集内确认字段
python scripts/search.py order_cost --dataset sales_order_d -n 20

# 3. 再看完整 metadata
opscli query metadata --dataset sales_order_d --pretty

# 4. 字段不存在且本地数据为空/placeholder 时先升级
opscli skills upgrade ops-dataset-query
```

判断原则：

- `dataset_fields.csv` 里找不到目标字段时，不要直接写 payload
- 优先接受这几类命中：`field_name`、`global_alias`、`verbose_name`
- 公式字段必须额外看 metadata，不能只看 CSV 名称就推断表达式
- `query_metadata` 与本地 CSV 同时都缺失时，才可判定当前 Skill 数据未覆盖或字段确实不可用

### 【强制】比较类查询优先级规则

> 涉及环比、同比、趋势对比等场景时，**必须按以下优先级选择方案，禁止跳过高优先级直接多次调用 CLI 后在客户端合并结果**。

| 优先级 | 场景 | 方案 |
|--------|------|------|
| ① 最优 | 当期 vs 对比期汇总对比（环比/同比） | `dataComparison`（服务端条件聚合，一次 SQL） |
| ② 次优 | 按时间粒度分组的趋势环比/同比 | `MOY` 高级计算（服务端窗口函数，一次 SQL） |
| ③ 兜底 | ①② 均因工具限制无法使用时 | 多次 `opscli query simple` + 客户端合并 |

`dataComparison` 不是独立日期过滤器。使用 `--data-comparison` 时，必须同时用 `--where` 传入当前主查询周期的日期条件；`--data-comparison` 只表示对比周期。不要只传 `--data-comparison`，否则可能触发 `QS-EXE-005 missing ')' at '{'` 等 SQL 解析错误。若已报错，先补上主周期日期 `--where` 后重试，仍失败再降级为纯日期 `--where` 查询。

> `comparison`（MOY/ACC/PPT）写在 `select` 字段内部可正常透传。

---

## 本地数据文件

| 文件 | 内容 | 说明 |
|------|------|------|
| `data/VERSION.json` | 版本号 | `{"name": "ops-dataset-query", "version": "v1.x.x"}` |
| `data/intent_taxonomy.yml` | 本地业务意图分类 | intents（意图 ID/触发关键词/主数据集/路由规则/澄清条件），供 route_intent.py 使用 |
| `data/dataset_fields.csv` | 字段明细 | dataset_alias、field_name、verbose_name、global_alias、field_type、formula_config、detail_expression、summary_expression 等 |
| `data/datasets.csv` | 数据集列表 | table_id、dataset_alias、dataset_name、dataset_category、inner_where_enabled、description、remarks、select_column_count、select_column_names |
| `data/dataset_select_columns.csv` | **查询组件关联** | current_dataset_alias、column_name、verbose_name、component_dataset_alias |
| `data/query_metadata.json` | 查询元数据 | 字段类型映射、可用聚合方式等 |

CSV 各列详细说明见 `references/simple-query-guide.md` 底部附录。

### `data/dataset_select_columns.csv` 使用说明

查询组件关联表描述了每个数据集预配置的**可枚举筛选维度**（select column），以及该维度的枚举值来自哪个数据集。

| 列名 | 含义 |
|------|------|
| `current_dataset_alias` | 当前要查询的数据集 alias |
| `column_name` | 查询组件的字段名（筛选维度） |
| `verbose_name` | 查询组件的中文显示名 |
| `component_dataset_alias` | 枚举值来源数据集的 alias（可用此别名查询合法枚举值） |

**典型使用场景**：

```bash
# 用 Python 读取某数据集的可用查询组件
# 注意：文件带有 UTF-8 BOM，必须使用 encoding='utf-8-sig'，否则第一列名会多出 \ufeff 导致 KeyError
python3 -c "
import csv
with open('data/dataset_select_columns.csv', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))
ds = 'sales_summary'
cols = [r for r in rows if r['current_dataset_alias'] == ds]
print(cols)
"
# 示例输出：
# [
#   {'current_dataset_alias': 'sales_summary', 'column_name': 'platform',
#    'verbose_name': '平台', 'component_dataset_alias': 'platform_options'},
#   {'current_dataset_alias': 'sales_summary', 'column_name': 'date_range',
#    'verbose_name': '日期范围', 'component_dataset_alias': 'date_config'}
# ]
```

**构造 filters 时的应用规则**：

1. 构造某数据集的 `filters` 前，先读取 `dataset_select_columns.csv` 确认哪些字段有预配置的枚举值来源
2. 对于 `column_name` 对应的字段，其合法枚举值来自 `component_dataset_alias` 数据集
3. 若用户指定的筛选值不在枚举范围，优先用 `component_dataset_alias` 查询合法值集合后再构造 filter
4. 没有在本文件中出现的字段，按普通字段处理，不做枚举约束

---

## 辅助命令参考

以下命令用于数据集/字段检索和意图分析，**不直接执行数据查询**。

### `opscli query metadata`

读取数据集的 query metadata（字段定义、可用聚合方式等）。

**两种用法**：

| 用法 | 行为 | 认证 |
|------|------|------|
| 无参数 `opscli query metadata` | **远端优先**返回数据集列表（不含字段），远端失败回退本地缓存 | 远端时需要 |
| 指定数据集 `--dataset <alias>` 或 `--table-id <id>` | **远端优先**拉取最新字段信息，远端失败自动回退本地缓存 | 远端时需要 |

```
选项：
  --dataset TEXT      dataset_alias（与 --table-id 二选一）
  --table-id INTEGER  table_id（与 --dataset 二选一）
  --skills-dir TEXT   指定 Skill 目录
  --pretty            格式化 JSON 输出
```

```bash
# 查看所有可用数据集列表（远端优先，自动回退本地）
opscli query metadata --pretty

# 获取指定数据集的最新字段信息（远端优先）
opscli query metadata --dataset sales_order_d --pretty
opscli query metadata --table-id 123 --pretty
```

---

### `opscli query intent` / `opscli query catalog`（远端实时意图目录）

> **推荐入口**：用户未指定 dataset/table_id 时，**先**用远端实时意图目录路由选表（不依赖本地快照）；不可用、报错或 `fallback_required=true` 时再降到本地 `route_intent.py`。

`opscli query catalog` 读取数据集业务语义索引（dataset catalog），返回完整 catalog JSON（`version`、`intent_count`、`intents` 数组、`query_strategy`）：

```bash
opscli query catalog [--source remote|local] [--fallback-local/--no-fallback-local] [--skills-dir <目录>] [--pretty]
```

- `--source`：`remote`（默认，远端优先）或 `local`（仅本地缓存）。
- `--fallback-local` / `--no-fallback-local`：`--source remote` 时远端失败是否回退本地缓存，默认回退。
- `--skills-dir`：自定义 Skills 目录，用于读取本地缓存 catalog。

`opscli query intent` 将自然语言需求匹配到 catalog 中的 intents，返回选表候选与业务约束，并向服务端上报一次匹配事件（fire-and-forget，上报失败不影响匹配结果）：

```bash
opscli query intent -q "<用户原文>" [--source remote|local] [--fallback-local/--no-fallback-local] [--skills-dir <目录>] [--pretty]
```

返回重点字段：

| 字段 | 说明 |
|------|------|
| `matched` | 是否命中任一 intent；`false` 时无 `selected`，转本地 `route_intent.py` |
| `candidates[]` | 候选列表，每项含 `intent_code`、`table_id`、`dataset_alias`、`score`、`intent_constraints`（`hard_constraints`/`avoid_when`/`clarify_when`/`recommended_dimensions`/`recommended_metrics`/`default_filters`/`comparison_strategy`）、`routing_status`（`direct_intent` / `embedded_intent`）、`embedded_from_table_id`（`embedded_intent` 时指向原始意图行，实际查询仍落在 `table_id` 指向的父表） |
| `ask_user_question_required` | `true` 时候选不唯一（多个候选分数接近），必须用 `AskUserQuestion` 让用户从 `candidates` 里选，不得默认取第一个 |
| `fallback_required` / `fallback_reason` | `true` 表示 catalog 为空或无匹配意图，转本地 `route_intent.py` |
| `selected` | `matched=true` 且 `ask_user_question_required=false` 时的唯一候选，可直接采用 |
| `match_record_id` | 本次匹配的服务端归因记录 ID（上报失败为 `null`）；命中并执行查询时须透传 |

**意图归因参数**：`opscli query simple --run` 与 `opscli query run` 均支持三个可选参数，向服务端透传本次选表来源：`--intent-code <编码>`（取自候选的 `intent_code`）、`--selection-source <来源>`（`planner`/`intent_route`/`local_fallback`/`user_specified` 四选一）、`--match-record-id <ID>`（取自 `query intent` 返回的 `match_record_id`）。三者均可选，不传不影响执行；经 `query intent` 命中候选后应一并透传，便于闭环统计。

**约束提示处置**：候选里的 `intent_constraints`（`hard_constraints` / `avoid_when` / `clarify_when`）是尚未经人工复核的业务约束提示，**必须先向用户复述并确认，再决定是否套用**，不得静默应用，也不得忽略。

### `python scripts/route_intent.py`（本地意图路由）

> **兜底入口**：`opscli query intent` 不可用、报错或未命中时，用该脚本做本地意图匹配（不依赖网络）。

```bash
python scripts/route_intent.py "<用户自然语言问题>" [--top-n 3] [--data-dir data/]
```

返回重点字段：

| 字段 | 说明 |
|------|------|
| `top_results` | 候选意图列表，含 `intent_id`、`primary_dataset`、`execution_alias`、`table_id`、`confidence`、`matched_keywords` |
| `routing_status` | `direct_intent`（直接路由）/ `embedded_intent`（口径映射执行） |
| `requires_clarification` | 为 `true` 时必须先用 AskUserQuestion 澄清，禁止直接执行查询 |
| `fallback_needed` | 为 `true` 时回退本地关键词搜索（search.py） |

命中后执行查询时透传 `--selection-source local_fallback`。

---

## 查询命令索引

| 命令 | 类型 | 说明 | 详细文档 |
|------|------|------|---------|
| `opscli query simple` | 简易版 | 基于简化参数构造并执行查询（推荐优先使用）；支持 `--global-currency` 与意图归因参数 | `references/cli-simple-guide.md` |
| `opscli query intent` | 意图路由 | 自然语言 → 远端实时意图目录选表候选（用户未指定数据集时的第一步） | 本文「辅助命令参考」 |
| `opscli query catalog` | 意图目录 | 读取完整数据集业务语义索引 | 本文「辅助命令参考」 |
| `opscli query chart` | 图表 | 通过图表 ID 获取查询结构并执行，含多 query/小计总计 | `references/cli-simple-guide.md` |

---

## 高级查询说明

**使用优先级**：
1. **`opscli query simple`**（推荐）：普通聚合、数据对比、MOY 趋势、子查询等场景，服务端自动处理技术细节
2. **`opscli query chart`**：通过图表 ID 获取查询结构并执行，支持多 query 自动合并

**文档引用顺序（强制）**：
1. **优先阅读 `references/simple-query-guide.md`** — 所有普通场景先按简化接口处理
2. **CLI 命令细节阅读 `references/cli-simple-guide.md`**


> 简化接口完整说明见 **`references/simple-query-guide.md`**。
> CLI 简易版命令详解见 **`references/cli-simple-guide.md`**。
> 查询命令详解见 **`references/cli-simple-guide.md`**。

---

## 字段搜索（本地索引）

本 Skill 内置本地字段索引，可用于辅助确认 `dataset_alias`、`field_name`、`verbose_name`。

**推荐流程**：本地索引确认字段名 → `opscli query metadata` 查看完整 metadata → `opscli query simple` / `opscli query chart`

**搜索排序策略（相关性从高到低）：**

| 匹配类型 | 分值 |
|---------|------|
| `field_name` 精确匹配 | 120 |
| `verbose_name` 精确匹配 | 100 |
| `field_name` 子串匹配 | 60 |
| `verbose_name` 子串匹配 | 45 |
| `dataset_alias` 精确匹配 | 40 |
| `description` 子串匹配 | 10 |

---

## 错误处理

| 场景 | 解决方法 |
|------|---------|
| 本地数据为空 | `opscli skills upgrade ops-dataset-query` |
| dataset_alias 不存在 | 先 `opscli query metadata` 查看可用数据集列表；确认拼写或 `opscli skills upgrade` 同步最新数据集 |
| 字段映射全部失败（`mapped_name` 等于 `global_alias`） | 先 `opscli query metadata --dataset <alias>` 远端获取最新字段；仍失败则 `opscli skills upgrade ops-dataset-query --force` |
| 仅需确认单个数据集字段 | `opscli query metadata --dataset <alias>` 按需远端查询，无需全量升级 |
| 未登录 | 调用 `ops-auth` Skill，并执行 `opscli auth login` |
| Token 过期 | 调用 `ops-auth` Skill，优先执行 `opscli auth token refresh --all`；刷新失败或仍异常时再执行 `opscli auth login` |
| opscli 未找到 | 激活虚拟环境或设置 `OPSCLI_BIN` |
| 远端 manifest 不存在 | 检查网络和 ops 服务地址配置 |

---

## AI Agent 使用规范

### 【禁止】用管道截断 opscli 输出后再解析 JSON

> ⚠️ **典型错误**：将 `opscli query ... --run --pretty` 通过 `| head -N` 截断后，尝试解析输出为 JSON，必然报 `JSONDecodeError`。

**错误原因**：`| head -N` 在读取 N 行后关闭管道，opscli 进程输出被强制截断，JSON 结构不完整。Claude Code 的 persisted-output 临时文件同样只是截断预览，**不可作为 JSON 解析源**。

**禁止写法**：
```bash
# 错误：head 截断了 JSON，无法解析
opscli query simple ... --run --pretty 2>&1 | head -80

# 错误：读取 persisted-output 临时文件（内容截断，JSON 不完整）
with open('/path/to/tool-results/xxxxx.txt') as f:
    data = json.load(f)
```

**正确写法**：始终将完整输出重定向到临时文件，再读取解析：
```bash
# 正确：完整输出到文件
opscli query simple ... --run --pretty > /tmp/result.json

# 或使用 --output 参数
opscli query simple ... --output /tmp/result.json --run

# Python 解析时从临时文件读取
python3 -c "import json; print(json.load(open('/tmp/result.json'))['data']['result']['meta'])"
```

---

## 典型工作流

### 意图分析 → 数据集选择 → 构造 → 执行（推荐）

> **【强制】用户未指定 dataset 时，先走远端意图目录 `opscli query intent`，不可用/未命中再做本地意图路由，最后本地关键词搜索，禁止跳过直接猜测数据集。**

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 1a. 远端实时意图目录（优先）
opscli query intent -q "<用户自然语言问题>" --pretty
# matched=true 且 ask_user_question_required=false → 取 selected.table_id / selected.dataset_alias
# ask_user_question_required=true → AskUserQuestion 让用户在 candidates 里选
# intent_constraints 先向用户复述确认再套用
# 命令不可用 / 报错 / matched=false / fallback_required=true → 转 1b

# 1b. 本地意图路由（不依赖网络，兜底）
python scripts/route_intent.py "<用户自然语言问题>"
# 命中 direct_intent     → 使用返回的 table_id / dataset_alias
# 命中 embedded_intent   → 使用 execution_alias 执行，向用户说明口径映射
# requires_clarification=true → 先用 AskUserQuestion 澄清

# 2. 用本地索引校验目标字段是否存在
python scripts/search.py <field_name> --dataset <dataset_alias> -n 20
# 或查看完整 metadata
opscli query metadata --dataset <dataset_alias> --pretty

# 3. 基于确认的 table_id 构造查询，经 query intent 命中时透传归因参数；含币种意图时传 --global-currency
opscli query simple --table-id <table_id> --payload /tmp/simple.json \
  --intent-code <selected.intent_code> --selection-source intent_route --match-record-id <match_record_id> \
  --run --pretty
#    详见 references/cli-simple-guide.md 中的简化接口示例
```

### 意图路由未命中时的回退工作流

> 本地意图覆盖有限，未命中属正常现象。**静默回退，不提示用户。**

```bash
# route_intent.py 返回 fallback_needed=true 时：

# 1. 静默进入本地关键词搜索
python scripts/search.py "<用户关键词>" -n 20

# 示例：用户查询"物控库存周转 Temu 近30天趋势"
python scripts/search.py "库存周转" -n 20
# 返回2个数据集：ds_97zj6R0KDKpB（物控库存周转）、ds_dI5gNc0YRLrD（物控库存周转期初期末）

# 2. 搜索返回多个候选 → AskUserQuestion 让用户选择
#    注意：同类业务场景的多数据集通常口径不同，必须澄清后再执行

# 3. 用户选定数据集后 → 检查查询组件（dataset_select_columns.csv）→ 校验 filter 权限 → 执行查询
```

**何时用意图路由 vs 何时用关键词搜索**：

| 场景 | 方式 |
|------|------|
| 用户给出自然语言需求且未指定数据集 | 先 opscli query intent，不可用/未命中再 route_intent.py，再 search.py |
| 用户已明确指定数据集别名 | 跳过意图路由，直接进入字段检查 |
| 只需确认字段是否存在 | 直接 python scripts/search.py |

### 数据更新 → 重新查询

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

opscli skills status --pretty
opscli skills upgrade ops-dataset-query
opscli query metadata --dataset sales_order_d --pretty
```

---

## 安装与管理

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

opscli skills install ops-dataset-query            # 安装
opscli skills install ops-dataset-query --force     # 强制重装
opscli skills status --pretty                       # 查看版本
opscli skills upgrade ops-dataset-query             # 升级
```

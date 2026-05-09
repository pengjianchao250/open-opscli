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
> 1. **必须优先阅读 `references/simple-query-guide.md`** — 简化接口参数、使用场景、示例
> 2. **CLI 简易版命令详解**：`references/cli-simple-guide.md` — `opscli query simple`
> 3. **CLI 完整版命令详解**：`references/cli-advanced-guide.md` — `opscli query run`、`opscli query chart`、降级方案
> 4. **只有多次查询失败时**，才尝试阅读 `references/data-query-service-dev-guide.md`
> 5. **涉及 `innerWhere` 的数据集（子查询数据集，inner_where_enabled=true）不允许使用 `opscli query run` 手写完整 payload**，只能用 `opscli query simple`

---

## 调用前置要求

> **认证按动作触发**：本地只读检索不要求登录；涉及远端 catalog、远端执行或升级时，必须先检测是否已授权登录。

- 本地只读动作可直接执行：`python scripts/search.py`、`opscli query catalog --source local`、`opscli query metadata`
- 远端动作前先执行 `opscli auth token status`：`opscli query catalog`、`opscli query simple --run`、`opscli query build --run`、`opscli query run`、`opscli query chart --run`、`opscli skills upgrade ops-dataset-query`
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
- `opscli query build` 适合基于 `--dimension`/`--metric` 参数构造标准完整 query payload（输出完整版结构，详见 `references/cli-advanced-guide.md`）
- `opscli query run` 适合透传完整手写高级 payload（仅当简化接口和 `query build` 均不满足需求时使用）
- **`opscli query run` 禁用场景**：涉及 `innerWhere` 的数据集（子查询类型，`inner_where_enabled=true`）**禁止使用** `opscli query run`，只能用 `opscli query simple`
- `opscli query chart` 适合通过图表 ID 直接获取查询结构并执行，支持多 query 自动合并
- 所有查询工作流都必须以前置的 `ops-auth` 登录检测作为起点
- **文档引用顺序**：优先参考 `references/simple-query-guide.md` 和 `references/cli-simple-guide.md`；多次查询失败时才参考 `references/data-query-service-dev-guide.md`

---

## 【强制】字段存在性检查

> 在 CLI 模式下，构造任何 query 参数前，必须先确认目标数据集和字段真实存在；**搜索结果为空时，先判断本地数据是否已初始化，再决定是否升级**。

标准顺序：

1. 先确认目标 `dataset_alias` 是否存在于 `data/datasets.csv`
2. 再确认目标字段是否存在于 `data/dataset_fields.csv`
3. 如需进一步确认公式字段、聚合方式、表达式结构，再执行 `opscli query metadata --dataset <dataset_alias> --pretty`
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
# 1. 先确认数据集
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
| ③ 兜底 | ①② 均因工具限制无法使用时 | 多次 `opscli query run` + 客户端合并 |

`dataComparison` 不是独立日期过滤器。使用 `--data-comparison` 时，必须同时用 `--where` 传入当前主查询周期的日期条件；`--data-comparison` 只表示对比周期。不要只传 `--data-comparison`，否则可能触发 `QS-EXE-005 missing ')' at '{'` 等 SQL 解析错误。若已报错，先补上主周期日期 `--where` 后重试，仍失败再降级为纯日期 `--where` 查询。

> `comparison`（MOY/ACC/PPT）写在 `select` 字段内部可正常透传。

---

## 本地数据文件

| 文件 | 内容 | 说明 |
|------|------|------|
| `data/VERSION.json` | 版本号 | `{"name": "ops-dataset-query", "version": "v1.x.x"}` |
| `data/dataset_catalog.json` | 业务语义索引 | version、intent_count、intents（使用案例/关键词/场景/优先级/数据集映射）、query_strategy |
| `data/dataset_fields.csv` | 字段明细 | dataset_alias、field_name、verbose_name、global_alias、field_type、formula_config、detail_expression、summary_expression 等 |
| `data/datasets.csv` | 数据集列表 | table_id、dataset_alias、dataset_name、dataset_type、dataset_category、data_source、main_dttm_col、inner_where_enabled、cache_timeout、description |
| `data/query_metadata.json` | 查询元数据 | 字段类型映射、可用聚合方式等 |

CSV 各列详细说明见 `references/data-query-service-dev-guide.md` 附录。

---

## 辅助命令参考

以下命令用于数据集/字段检索和意图分析，**不直接执行数据查询**。

### `opscli query metadata`

读取指定数据集的 query metadata（字段定义、可用聚合方式等）。

```
选项：
  --dataset TEXT      dataset_alias（与 --table-id 二选一）
  --table-id INTEGER  table_id（与 --dataset 二选一）
  --skills-dir TEXT   指定 Skill 目录
  --pretty            格式化 JSON 输出
```

```bash
opscli query metadata --dataset sales_order_d --pretty
opscli query metadata --table-id 123 --pretty
```

---

### `opscli query catalog`

读取数据集业务语义索引（dataset catalog）。默认远端优先，远端失败时回退本地缓存；用于自然语言需求匹配 intents 后选出候选数据集。

```
选项：
  --source TEXT       数据来源：remote（默认）或 local
  --fallback-local / --no-fallback-local
                      远端失败时是否回退本地缓存
  --skills-dir TEXT   指定 Skill 目录
  --pretty            格式化 JSON 输出
```

```bash
# 读取完整 catalog
opscli query catalog --pretty

# 只读取本地缓存
opscli query catalog --source local --pretty

# 只允许远端，失败直接报错
opscli query catalog --source remote --no-fallback-local --pretty

# 指定 Skill 目录
opscli query catalog --skills-dir ~/.claude/skills --pretty
```

**返回结构**：

```json
{
  "success": true,
  "command": "query catalog",
  "data": {
    "version": "v1.0.0",
    "intent_count": 15,
    "intents": [
      {
        "use_case": "销售订单分析",
        "keywords": ["订单", "销售额", "出库"],
        "scenario": "查看某时段内的销售订单汇总数据",
        "priority": 1,
        "dataset_alias": "sales_order_d"
      }
    ],
    "query_strategy": {}
  },
  "error": null
}
```

---

## 查询命令索引

| 命令 | 类型 | 说明 | 详细文档 |
|------|------|------|---------|
| `opscli query simple` | 简易版 | 基于简化参数构造并执行查询（推荐优先使用） | `references/cli-simple-guide.md` |
| `opscli query build` | 完整版 | 基于简化参数构造标准完整 query payload，可选执行 | `references/cli-advanced-guide.md` |
| `opscli query run` | 完整版 | 透传完整手写 payload（仅当简化接口和 `build` 均不满足时使用） | `references/cli-advanced-guide.md` |
| `opscli query chart` | 完整版 | 通过图表 ID 获取查询结构并执行，含多 query/小计总计 | `references/cli-advanced-guide.md` |

---

## 高级查询说明

**使用优先级**：
1. **`opscli query simple`**（推荐）：普通聚合、数据对比、MOY 趋势、子查询等场景，服务端自动处理技术细节
2. **`opscli query build`**：基于 `--dimension`/`--metric` 参数快速构造标准 query payload
3. **`opscli query run`**：仅当简化接口无法满足需求时，手写完整 payload 透传

**文档引用顺序（强制）**：
1. **优先阅读 `references/simple-query-guide.md`** — 所有普通场景先按简化接口处理
2. **CLI 命令细节阅读 `references/cli-simple-guide.md`**
3. **只有多次查询失败时**，才阅读 `references/data-query-service-dev-guide.md` 排查深层问题
4. **涉及 `innerWhere` 的数据集（子查询类型）禁止使用 `opscli query run`**，无论简化接口是否满足需求，都必须使用 `opscli query simple`

> 简化接口完整说明见 **`references/simple-query-guide.md`**。
> CLI 简易版命令详解见 **`references/cli-simple-guide.md`**。
> CLI 完整版命令详解见 **`references/cli-advanced-guide.md`**。
> 完整 query payload 规范（innerWhere / translate / 权限占位符等）见 **`references/data-query-service-dev-guide.md`**（多次失败时参考）。

---

## 字段搜索（本地索引）

本 Skill 内置本地字段索引，可用于辅助确认 `dataset_alias`、`field_name`、`verbose_name`。

**推荐流程**：本地索引确认字段名 → `opscli query metadata` 查看完整 metadata → `opscli query build` 或手写 payload + `opscli query run`

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
| dataset_alias 不存在 | 检查拼写或 `opscli skills upgrade` 同步最新数据集 |
| 字段映射全部失败（`mapped_name` 等于 `global_alias`） | 脚本会自动 upgrade 重试；手动执行 `opscli skills upgrade ops-dataset-query --force` |
| 未登录 | 调用 `ops-auth` Skill，并执行 `opscli auth login` |
| Token 过期 | 调用 `ops-auth` Skill，优先执行 `opscli auth token refresh --all`；刷新失败或仍异常时再执行 `opscli auth login` |
| opscli 未找到 | 激活虚拟环境或设置 `OPSCLI_BIN` |
| 远端 manifest 不存在 | 检查网络和 ops 服务地址配置 |
| payload 文件不存在 | 先 `opscli query build --output` 生成 |

---

## AI Agent 使用规范

### 【禁止】用管道截断 opscli 输出后再解析 JSON

> ⚠️ **典型错误**：将 `opscli query ... --run --pretty` 通过 `| head -N` 截断后，尝试解析输出为 JSON，必然报 `JSONDecodeError`。

**错误原因**：`| head -N` 在读取 N 行后关闭管道，opscli 进程输出被强制截断，JSON 结构不完整。Claude Code 的 persisted-output 临时文件同样只是截断预览，**不可作为 JSON 解析源**。

**禁止写法**：
```bash
# 错误：head 截断了 JSON，无法解析
opscli query build ... --run --pretty 2>&1 | head -80

# 错误：读取 persisted-output 临时文件（内容截断，JSON 不完整）
with open('/path/to/tool-results/xxxxx.txt') as f:
    data = json.load(f)
```

**正确写法**：始终将完整输出重定向到临时文件，再读取解析：
```bash
# 正确：完整输出到文件
opscli query build ... --run --pretty > /tmp/result.json

# 或使用 --output 参数
opscli query build ... --output /tmp/result.json --run

# Python 解析时从临时文件读取
python3 -c "import json; print(json.load(open('/tmp/result.json'))['data']['result']['meta'])"
```

---

## 典型工作流

### 意图分析 → 数据集选择 → 构造 → 执行（推荐）

> **【强制】用户未指定 dataset 时，必须从远程 catalog 意图匹配开始，禁止跳过直接用本地搜索猜测。**

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 1.【强制】远程 catalog 意图分析（默认远端优先，失败自动回退本地缓存）
opscli query catalog --pretty
# 从返回的 intents 中匹配用户需求：
#   - 比对 use_cases / keywords / scenario_description
#   - 按 priority 选择最佳候选
#   - 提取 table_id、dataset_alias、default_filters、comparison_strategy

# 2. 用本地索引校验目标字段是否存在
python scripts/search.py <field_name> --dataset <dataset_alias> -n 20
# 或查看完整 metadata
opscli query metadata --dataset <dataset_alias> --pretty

# 3. 基于 catalog 提供的 table_id + default_filters + comparison_strategy 构造查询
#    详见 references/cli-simple-guide.md 中的简化接口示例
```

**意图匹配示例**：

用户说"查广告数据" → catalog 返回 `intent_code: instant_advertising_analysis`：
- `table_id: 15`，`dataset_alias: ds_0759e20F0DrG`
- `default_filters: [{"field": "amazon_cat", "value": "Amazon", "operator": "="}]`
- `comparison_strategy: {"trend_compare": "MOM", "summary_compare": "dataComparison"}`

→ 直接用 `table_id=15` + `platform_name in ["Amazon"]` 构造查询，无需猜测数据集。

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

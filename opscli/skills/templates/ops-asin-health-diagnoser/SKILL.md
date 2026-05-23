---
name: ops-asin-health-diagnoser
description: 诊断 Amazon ASIN 健康度。通过 6 大指标（毛利率、转化率、ACOS、退款率、库存周转、星级）计算综合评分 0-100，识别问题 ASIN 并给出优先行动建议。当用户说"诊断ASIN"、"分析产品表现"、"健康度评分"、"ASIN体检"、"周会报告"时触发。支持 CLI 和 MCP 双模式。
version: v0.2.2
---

# ASIN 健康诊断器

计算 Amazon ASIN 综合健康评分（0-100），识别表现不佳的 ASIN，给出优先行动建议。

---

## 目标

- 对单一或批量 ASIN 进行 6 指标健康诊断
- 输出综合评分 + 分项指标 + 问题识别 + 优先行动建议
- 支持自定义权重和阈值（利润优先 / 增长优先 / 自定义）

---

## 快速开始

### 必要参数

| 参数 | 说明 | 示例 |
|------|------|------|
| ASIN | 至少一个 Amazon ASIN | `B08XXXXXX` 或 `B08XXXXXX, B09YYYYYY` |
| 日期范围 | 分析周期 | `2025-01-01 ~ 2025-01-31` 或 `最近30天` |

### 可选参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| 权重方案 | `default` / `profit_first` / `growth_first` / 自定义 JSON | `default` |
| 团队/部门过滤 | 按团队名、部门名筛选 | 无（按 ASIN 查询） |

### 典型调用

用户说：**"帮我诊断一下 B08XXXXXX 最近30天的健康度"**

执行步骤：
1. 认证检查（见下方强制门禁）
2. 查询主数据集运营指标
3. 查询辅助数据集星级
4. 合并数据，运行 `scripts/calculate_health_score.py` 计算评分
5. 输出诊断报告

---

## 默认执行策略

- 用户要求"执行、诊断、分析、检查"时，按已固化流程直接处理，只追问缺失的必要参数（ASIN、日期范围）
- 已验证的数据路径和查询命令直接复用，不重新做 catalog 搜索或字段预检
- **只有以下情况才加载额外 reference 并展开分析**：
  - 缺少必要参数
  - 查询字段/权限变化、空结果
  - 用户要求自定义权重/阈值、测试、优化、发布或跨工具迁移
  - 新场景超出固化范围

---

## 运行模式判断

不要为模式判断额外运行检测脚本，直接按规则判断：

1. 用户明确指定 CLI 或 MCP → 遵循
2. 当前在 `opscli` 项目本地终端 → 默认 CLI，读 `references/cli.md`
3. 当前基于 MCP Tool 协作 → 读 `references/mcp.md`
4. CLI 首次正式命令失败 → 直接切 MCP，不额外询问
5. CLI 和 MCP 都不可用 → 建议安装 `aukeys-opscli`

一旦确定模式，保持单一路径，不要来回切换。

---

## 强制认证门禁

**进入本 Skill 后必须先完成认证检查，检查通过前禁止查询、运行脚本或读取数据。**

### CLI 模式

```bash
opscli auth token status              # 检查登录状态
opscli auth token refresh --all       # Token 过期时刷新
opscli auth login                     # 未登录时授权
```

### MCP 模式

```python
auth_is_authenticated(session_id="xxx")   # 检查 session
auth_login_start()                         # session 无效时启动 Device Flow
auth_login_poll(device_code="xxx")         # 轮询授权
```

禁止：跳过认证、手写/复用过期 Token、未登录时运行脚本。

---

## 日常工作流

### 单一 ASIN 诊断

**CLI 模式：**

```bash
# 1. 查询主数据集（运营指标）
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension asin --dimension product_name \
  --metric gross_profit_percent --metric convert_percent \
  --metric ads_acos --metric refund_percent --metric sell_qty_days \
  --where "asin|eq|\"B08XXXXXX\"" \
  --where "date_id|between|[\"2025-01-01\",\"2025-01-31\"]" \
  --output /tmp/asin_main.json --run --pretty

# 2. 查询辅助数据集（星级）
opscli query build \
  --dataset ds_pdTYjvLRCadv \
  --dimension asin \
  --metric "star:avg:f_star" \
  --where "asin|eq|\"B08XXXXXX\"" \
  --output /tmp/asin_star.json --run --pretty

# 3. 合并数据并计算评分
python scripts/calculate_health_score.py --input /tmp/asin_merged.json --pretty
```

**MCP 模式：**

```python
# 1. 查询主数据集
result = query_build_and_run(
    dataset="ds_d35ac6f3910c",
    dimensions=["asin", "product_name"],
    metrics=["gross_profit_percent:avg", "convert_percent:avg",
             "ads_acos:avg", "refund_percent:avg", "sell_qty_days:avg"],
    where_conditions=['asin|eq|"B08XXXXXX"',
                      'date_id|between|["2025-01-01","2025-01-31"]'],
    limit=100, session_id="xxx", skills_dir="/path/to/skills"
)

# 2. 查询辅助数据集（星级）
star_result = query_build_and_run(
    dataset="ds_pdTYjvLRCadv",
    dimensions=["asin"],
    metrics=["star:avg:f_star"],
    where_conditions=['asin|eq|"B08XXXXXX"'],
    limit=100, session_id="xxx", skills_dir="/path/to/skills"
)

# 3. 合并数据并调用脚本计算评分
```

### 批量 ASIN 诊断

将 `asin|eq|` 改为 `asin|in|["B08X","B09Y","B07Z"]`，使用 `--batch` 参数：

```bash
python scripts/calculate_health_score.py --input /tmp/batch_merged.json --batch --pretty
```

### 自定义权重

```bash
python scripts/calculate_health_score.py --input /tmp/asin_metrics.json \
  --weights '{"gross_profit_percent": 0.40, "ads_acos": 0.25}' --pretty
```

预置权重方案见 `references/threshold_reference.md`。

---

## 数据集

| 数据集 | dataset_alias | 用途 |
|--------|--------------|------|
| 主数据集 | `ds_d35ac6f3910c` | 毛利率、转化率、ACOS、退款率、周转天数 |
| 辅助数据集 | `ds_pdTYjvLRCadv` | 星级、评论数、排名 |

详细字段映射和查询 payload 模板见 `references/dataset_fields_mapping.md`。
固化查询命令见 `references/data-recipes.md`。

---

## 健康评分公式

```
评分 = SUM(weight_i * normalize(metric_i))
```

各指标通过线性插值标准化到 0-100，再按权重加权求和。默认权重：

| 指标 | 权重 | 方向 |
|------|------|------|
| 毛利率 | 0.30 | 越高越好 |
| 转化率 | 0.20 | 越高越好 |
| ACOS | 0.20 | 越低越好 |
| 退款率 | 0.15 | 越低越好 |
| 库存周转天数 | 0.10 | 越低越好 |
| 星级 | 0.05 | 越高越好 |

星级缺失时自动重分配权重到其他指标。

---

## 核心判断规则

| 指标 | 健康 | 预警 | 严重 |
|------|------|------|------|
| 毛利率 | >= 20% | 10%-20% | < 10% |
| 转化率 | >= 10% | 5%-10% | < 5% |
| ACOS | <= 20% | 20%-30% | > 30% |
| 退款率 | <= 5% | 5%-10% | > 10% |
| 库存周转 | <= 45 天 | 45-90 天 | > 90 天 |
| 星级 | >= 4.3 | 4.0-4.3 | < 4.0 |

完整判断规则、行动建议、新品例外和品类差异见 `references/operating-rules.md`。

---

## 输出规范

### 文本诊断报告

```
【ASIN】B08XXXXXX（产品名称）
【健康度评分】72/100（Good）
【分项指标】
  + 毛利率：18.5% [!] 预警（目标>=20%）
  + 转化率：12.3% [OK] 健康
  + ACOS：22.1% [!] 预警（目标<=20%）
  + 退款率：4.2% [OK] 健康
  + 库存周转：38天 [OK] 健康
  + 星级：4.5 [OK] 健康
【主要问题】ACOS 偏高、毛利率低于目标
【建议行动】
  1. [P1] 优化广告投放，将 ACOS 从 22% 降至 18%
  2. [P1] 评估采购成本，谈判降低 2-3%
【数据时间】2025-01-01 ~ 2025-01-31
```

### JSON 结构化输出

脚本输出 `{"success": true, "data": {...}}` 格式，包含 `health_score`、`health_level`、`metrics_detail`、`issues`、`prioritized_actions`。

### 评分等级

| 分数 | 等级 | 含义 |
|------|------|------|
| >= 80 | Excellent | 健康度优秀 |
| 60-79 | Good | 健康度良好 |
| 40-59 | Fair | 需要关注 |
| < 40 | Poor | 需要立即干预 |

---

## 脚本

| 脚本 | 说明 |
|------|------|
| `scripts/core.py` | 核心计算逻辑（标准化、评分、格式化、数据提取） |
| `scripts/calculate_health_score.py` | 统一入口，支持 `--input` / `--batch` / `--weights` / `--benchmarks` / `--pretty` |
| `scripts/record_run.py` | 执行日志记录 |

### 脚本调用

```bash
# 单个 ASIN
echo '{"asin":"B08X","metrics":{...}}' | python scripts/calculate_health_score.py --pretty

# 批量
python scripts/calculate_health_score.py --input /tmp/batch.json --batch --pretty

# 自定义权重
python scripts/calculate_health_score.py --input /tmp/data.json \
  --weights '{"gross_profit_percent":0.40,"ads_acos":0.25}' --pretty

# 记录执行日志
python scripts/record_run.py --intent "诊断ASIN健康度" --status success --output /tmp/result.json
```

---

## 错误处理

| 场景 | 处理 |
|------|------|
| 未登录 | 执行认证门禁流程 |
| Token 过期 | `opscli auth token refresh --all`（CLI）或 `auth_token_refresh`（MCP） |
| 本地数据为空 | `opscli skills upgrade ops-dataset-query` |
| dataset_alias 不存在 | 检查拼写或升级同步最新数据集 |
| 健康评分为 NaN | 检查输入指标完整性，补全缺失指标后重算 |
| 查询返回空结果 | 确认 ASIN 和日期范围是否正确，检查权限 |
| opscli 命令不可用 | 切换 MCP 模式或安装 aukeys-opscli |

---

## 按需加载资料

| 场景 | 读取 |
|------|------|
| CLI 模式具体命令参考 | `references/cli.md` |
| MCP 模式具体 Tool 调用参考 | `references/mcp.md` |
| 完整判断规则、行动建议、新品例外 | `references/operating-rules.md` |
| 阈值和权重详细配置 | `references/threshold_reference.md` |
| 字段映射和 payload 模板 | `references/dataset_fields_mapping.md` |
| 固化查询命令和 recipe | `references/data-recipes.md` |
| 跨工具复用或降级方案 | `references/cross-tool-portability.md` |
| 测试、回归、评分和发布前验收 | `references/testing-benchmark.md` |
| 记录运行或提交候选 | `references/execution-log-schema.md`、`references/skill-submission-governance.md` |

---

## 执行日志与候选提交

- 每次真实运行后，按 `references/execution-log-schema.md` 记录一条执行摘要到 `runs/YYYY-MM.jsonl`
- 默认状态：`personal_draft`
- 多次执行有效后，按 `references/skill-submission-governance.md` 判断是否成为 `candidate`
- 使用 `scripts/record_run.py` 记录执行日志
- 未经用户确认，不自动提交

---

## 使用原则

- 所有远端查询必须走选定模式的正式查询入口，**禁止直接调用后端 HTTP 接口**
- 使用 `opscli query build`（CLI）或 `query_build_and_run`（MCP）构造 payload，**禁止手写 `userEmail`、`from.table`、`from.permission`**
- 涉及环比/同比时，优先使用服务端 `dataComparison` 能力，不要降级为多次查询
- 星级缺失时排除星级并重分配权重，在输出中标注"星级数据不可用"

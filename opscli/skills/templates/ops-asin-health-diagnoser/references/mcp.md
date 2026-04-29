---
name: ops-asin-health-diagnoser
mcp-version: v0.1.0
description: 使用 MCP Tool 查询 ASIN 健康诊断数据并计算评分（无状态模式）
---

# ops-asin-health-diagnoser (MCP 无状态模式)

使用 MCP Tool 查询 ASIN 运营数据，通过本地缓存索引辅助字段检索，使用 `scripts/calculate_health_score_mcp.py` 计算健康评分。**无状态模式**：服务器不保存用户 OAuth 凭证，所有认证信息由调用方传入。

---

## 调用前置要求

> **【强制】每次调用 `query_*` 前，必须先确认已提供有效 `session_id`；禁止默认假设用户已经登录。**

- 进入本 Skill 后，第一步先调用 `auth_is_authenticated(session_id)` 检测 session 有效性
- 若返回 `false` 或报错，说明 `session_id` 缺失或已过期
- **若 `session_id` 缺失**：
  1. 调用 `auth_login_start()` 获取 `verification_url` + `user_code`
  2. 提示用户在浏览器中打开 URL 并输入验证码
  3. 按 `interval` 轮询 `auth_login_poll(device_code)` 直到 `status=authorized`
  4. 获取返回的 `session_id`，保存到当前对话上下文
- 只有认证状态确认正常后，才允许继续执行 `query_metadata`、`query_build`、`query_run`、`query_build_and_run`

**标准前置流程（MCP Tool 调用）：**

```python
# 1. 先检查 session 是否有效
auth_is_authenticated(session_id="xxx")

# 2. 如 session_id 缺失或过期，重新授权
auth_login_start()                     # 获取 device_code / user_code
auth_login_poll(device_code="xxx")     # 轮询直到 authorized，获取新 session_id

# 3. 登录后再次确认
auth_is_authenticated(session_id="新session_id")
```

> **【强制】使用本 Skill 前，必须先阅读 `references/data-query-service-dev-guide.md`**

---

## 使用原则

- 本 Skill 负责字段搜索、缓存读取和辅助构造查询参数
- 所有远端查询动作必须通过 MCP Tool 执行，**禁止直接调用后端 HTTP 接口**
- 本地数据过期时，先执行 `skills_upgrade(name="ops-dataset-query")` 再重试查询
- 健康评分计算通过 `scripts/calculate_health_score_mcp.py` 完成（无 opscli 依赖）

---

## MCP Tool 调用参考

### 数据查询

查询 ASIN 运营数据使用 `ops-dataset-query` Skill 中定义的 MCP Tool：

#### 查询主数据集指标

```python
# 1. 构造并执行主数据集查询
result = query_build_and_run(
    dataset="ds_d35ac6f3910c",
    dimensions=["asin", "product_name"],
    metrics=[
        "gross_profit_percent:avg",
        "convert_percent:avg",
        "ads_acos:avg",
        "refund_percent:avg",
        "sell_qty_days:avg"
    ],
    where_conditions=[
        'asin|eq|"B08XXXXXX"',
        'date_id|between|["2025-01-01","2025-01-31"]'
    ],
    limit=100,
    session_id="xxx",
    skills_dir="/path/to/skills"
)
```

#### 查询辅助数据集（星级）

```python
# 2. 构造并执行辅助数据集查询
star_result = query_build_and_run(
    dataset="ds_pdTYjvLRCadv",
    dimensions=["asin"],
    metrics=["star:avg:f_star"],
    where_conditions=['asin|eq|"B08XXXXXX"'],
    limit=100,
    session_id="xxx",
    skills_dir="/path/to/skills"
)
```

#### 合并数据并计算健康评分

```python
# 3. 使用本地脚本计算健康评分
# 先将合并后的指标数据写入 JSON 文件，再调用脚本
import json, subprocess

metrics = {
    "gross_profit_percent": 0.185,
    "convert_percent": 0.123,
    "ads_acos": 0.221,
    "refund_percent": 0.042,
    "inventory_days": 38,
    "star": 4.5
}

input_data = {
    "asin": "B08XXXXXX",
    "product_name": "产品名称",
    "date_range": "2025-01-01 ~ 2025-01-31",
    "metrics": metrics
}

# 写入临时文件
with open("/tmp/asin_metrics.json", "w") as f:
    json.dump(input_data, f, ensure_ascii=False)

# 调用 MCP 版本脚本
result = subprocess.run(
    ["python", "scripts/calculate_health_score_mcp.py"],
    input=json.dumps(input_data),
    capture_output=True,
    text=True
)
health_result = json.loads(result.stdout)
```

---

## 辅助脚本（无 opscli 依赖）

### `calculate_health_score_mcp.py` — 健康评分计算

从 stdin 读取 JSON 输入或通过 `--input` 指定文件，计算 ASIN 健康评分并输出 JSON。**不依赖 opscli 命令行工具**。

**用法**：

```bash
# 从 stdin 读取
echo '{"asin": "B08XXXXXX", "metrics": {...}}' | python scripts/calculate_health_score_mcp.py

# 从文件读取
python scripts/calculate_health_score_mcp.py --input /tmp/asin_metrics.json --pretty

# 自定义权重
python scripts/calculate_health_score_mcp.py --input /tmp/asin_metrics.json \
  --weights '{"gross_profit_percent": 0.40, "ads_acos": 0.25, ...}' \
  --pretty

# 自定义阈值
python scripts/calculate_health_score_mcp.py --input /tmp/asin_metrics.json \
  --benchmarks '{"gross_profit_percent": {"healthy": 0.25, "warning": 0.15, "direction": "higher_is_better"}}' \
  --pretty

# 批量诊断（输入 JSON 数组）
python scripts/calculate_health_score_mcp.py --input /tmp/batch_metrics.json --batch --pretty
```

**输入格式（单个 ASIN）**：

```json
{
  "asin": "B08XXXXXX",
  "product_name": "产品名称",
  "date_range": "2025-01-01 ~ 2025-01-31",
  "metrics": {
    "gross_profit_percent": 0.185,
    "convert_percent": 0.123,
    "ads_acos": 0.221,
    "refund_percent": 0.042,
    "inventory_days": 38,
    "star": 4.5
  }
}
```

**输入格式（批量 ASIN）**：

```json
[
  {
    "asin": "B08XXXXXX",
    "product_name": "产品名称",
    "date_range": "2025-01-01 ~ 2025-01-31",
    "metrics": { ... }
  },
  {
    "asin": "B09YYYYYY",
    "product_name": "另一个产品",
    "date_range": "2025-01-01 ~ 2025-01-31",
    "metrics": { ... }
  }
]
```

**输出格式**：

```json
{
  "success": true,
  "data": {
    "asin": "B08XXXXXX",
    "product_name": "产品名称",
    "health_score": 72,
    "health_level": "Good",
    "metrics_detail": [
      {
        "metric": "gross_profit_percent",
        "value": 0.185,
        "normalized_score": 85.0,
        "status": "good",
        "weight": 0.30,
        "weighted_score": 25.5,
        "benchmark": {"healthy": 0.20, "warning": 0.10, "direction": "higher_is_better"}
      },
      ...
    ],
    "issues": [...],
    "prioritized_actions": [...],
    "formatted_diagnosis": "..."
  }
}
```

---

## 典型工作流

### 单一 ASIN 诊断

```python
# 0. 先检查 session；如无效则重新 Device Flow 授权
auth_is_authenticated(session_id="xxx")

# 1. 查询主数据集获取运营指标
result = query_build_and_run(
    dataset="ds_d35ac6f3910c",
    dimensions=["asin", "product_name"],
    metrics=[
        "gross_profit_percent:avg",
        "convert_percent:avg",
        "ads_acos:avg",
        "refund_percent:avg",
        "sell_qty_days:avg"
    ],
    where_conditions=[
        'asin|eq|"B08XXXXXX"',
        'date_id|between|["2025-01-01","2025-01-31"]'
    ],
    limit=100,
    session_id="860b0636485b5188a2b9b4ed5210e736",
    skills_dir="/Users/mask/.config/opencode/skills"
)

# 2. 查询辅助数据集获取星级
star_result = query_build_and_run(
    dataset="ds_pdTYjvLRCadv",
    dimensions=["asin"],
    metrics=["star:avg:f_star"],
    where_conditions=['asin|eq|"B08XXXXXX"'],
    limit=100,
    session_id="860b0636485b5188a2b9b4ed5210e736",
    skills_dir="/Users/mask/.config/opencode/skills"
)

# 3. 合并数据并计算健康评分
# 在 AI Agent 中直接使用核心函数计算
```

### 批量 ASIN 诊断

```python
# 0. 先检查 session
auth_is_authenticated(session_id="xxx")

# 1. 批量查询主数据集
result = query_build_and_run(
    dataset="ds_d35ac6f3910c",
    dimensions=["asin", "product_name"],
    metrics=[
        "gross_profit_percent:avg",
        "convert_percent:avg",
        "ads_acos:avg",
        "refund_percent:avg",
        "sell_qty_days:avg"
    ],
    where_conditions=[
        'asin|in|["B08XXXXXX","B09YYYYYY","B07ZZZZZZ"]',
        'date_id|between|["2025-01-01","2025-01-31"]'
    ],
    limit=1000,
    session_id="860b0636485b5188a2b9b4ed5210e736",
    skills_dir="/Users/mask/.config/opencode/skills"
)

# 2. 使用脚本批量计算健康评分
python scripts/calculate_health_score_mcp.py --input /tmp/batch_metrics.json --batch --pretty
```

---

## 【强制】比较类查询优先级规则

> 涉及环比、同比、趋势对比等场景时，**必须按以下优先级选择方案：**

| 优先级 | 场景 | 方案 |
|--------|------|------|
| ① 最优 | 当期 vs 对比期汇总对比（环比/同比） | `dataComparison`（服务端条件聚合，一次 SQL） |
| ② 次优 | 按时间粒度分组的趋势环比/同比 | `MOY` 高级计算（服务端窗口函数，一次 SQL） |
| ③ 兜底 | ①② 均因工具限制无法使用时 | 多次 `query_build_and_run` + 客户端合并 |

---

## MCP 认证工具速查

### 检查 session 有效性
```python
auth_is_authenticated(session_id="860b0636485b5188a2b9b4ed5210e736")
# → {success: true, data: true}
```

### 获取 JWT
```python
auth_get_token(system="ops", session_id="860b0636485b5188a2b9b4ed5210e736")
# → {success: true, data: "eyJhbG..."}
```

---

## 错误处理

| 场景 | 解决方法 |
|------|---------|
| 本地数据为空 | `skills_upgrade(name="ops-dataset-query")` |
| dataset_alias 不存在 | 检查拼写或 `skills_upgrade` 同步最新数据集 |
| 未登录 / session 无效 | 调用 `auth_login_start()` → 浏览器授权 → `auth_login_poll()` |
| Token 过期 | `auth_token_refresh(session_id)`；如 session 也过期则重新 Device Flow |
| 健康评分为 NaN 或异常 | 检查输入指标数据是否完整，补全缺失指标后重算 |

---

## 安装与管理

```python
# 安装
skills_install(name="ops-asin-health-diagnoser", skills_dir="/Users/mask/.config/opencode/skills")

# 强制重装
skills_install(name="ops-asin-health-diagnoser", force=True, skills_dir="/Users/mask/.config/opencode/skills")

# 查看版本
skills_status(skills_dir="/Users/mask/.config/opencode/skills")

# 升级
skills_upgrade(name="ops-asin-health-diagnoser", skills_dir="/Users/mask/.config/opencode/skills")
```
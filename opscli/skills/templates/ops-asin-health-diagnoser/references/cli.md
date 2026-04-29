---
name: ops-asin-health-diagnoser
description: 使用 CLI 模式查询本地数据集索引并执行 ASIN 健康诊断数据查询
version: v0.1.0
---

# ops-asin-health-diagnoser (CLI 模式)

使用 `opscli` 命令行工具查询 ASIN 运营数据，通过本地缓存索引辅助字段检索，使用 `scripts/calculate_health_score.py` 计算健康评分。

---

## 调用前置要求

> **【强制】每次使用本 Skill 前，必须先检测是否已授权登录；禁止默认假设用户已经登录。**

- 进入本 Skill 后，第一步先执行 `opscli auth token status`
- 若命令失败，或输出中出现"未登录 / 未授权 / Token 过期 / expired / 401"等状态，必须立即调用 `ops-auth` Skill
- 只有认证状态确认正常后，才允许继续读取本地索引、执行查询或运行诊断脚本

**标准前置流程：**

```bash
# 1. 先检查是否已登录
opscli auth token status

# 2. 如 JWT Token 已过期，先刷新
opscli auth token refresh --all

# 3. 如未登录、未授权、刷新失败或状态仍异常，立即调用 ops-auth Skill 处理
opscli auth login

# 4. 登录后再次确认
opscli auth token status
```

> **【强制】使用本 Skill 前，必须先阅读 `references/data-query-service-dev-guide.md`**

---

## 使用原则

- 本 Skill 负责字段搜索、缓存读取和辅助构造查询参数
- 所有远端查询动作必须通过 `opscli query` 执行，**禁止直接调用后端 HTTP 接口**
- 本地数据过期时，先执行 `opscli skills upgrade ops-dataset-query` 再重试查询
- 健康评分计算通过 `scripts/calculate_health_score.py` 完成

---

## 典型工作流

### 单一 ASIN 诊断

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

# 1. 查询主数据集获取运营指标
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension asin --dimension product_name \
  --metric gross_profit_percent --metric convert_percent \
  --metric ads_acos --metric refund_percent --metric sell_qty_days \
  --where "asin|eq|\"B08XXXXXX\"" \
  --where "date_id|between|[\"2025-01-01\",\"2025-01-31\"]" \
  --output /tmp/asin_main.json \
  --run --pretty

# 2. 查询辅助数据集获取星级
opscli query build \
  --dataset ds_pdTYjvLRCadv \
  --dimension asin \
  --metric "star:avg:f_star" \
  --where "asin|eq|\"B08XXXXXX\"" \
  --output /tmp/asin_star.json \
  --run --pretty

# 3. 合并数据并计算健康评分
python -c "
import json, sys
sys.path.insert(0, '$SKILL_DIR/scripts')
from calculate_health_score import calculate_health_score

main_data = json.load(open('/tmp/asin_main.json'))
star_data = json.load(open('/tmp/asin_star.json'))
# 提取指标并计算评分
metrics = {...}  # 从查询结果提取并合并指标
result = calculate_health_score(metrics)
print(json.dumps(result, indent=2, ensure_ascii=False))
"
```

### 批量 ASIN 诊断

```bash
# 0. 先检查认证状态
opscli auth token status

# 1. 批量查询主数据集
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension asin --dimension product_name \
  --metric gross_profit_percent --metric convert_percent \
  --metric ads_acos --metric refund_percent --metric sell_qty_days \
  --where "asin|in|[\"B08XXXXXX\",\"B09YYYYYY\",\"B07ZZZZZZ\"]" \
  --where "date_id|between|[\"2025-01-01\",\"2025-01-31\"]" \
  --output /tmp/batch_main.json \
  --run --pretty

# 2. 逐行计算健康评分并排名
python scripts/calculate_health_score.py < /tmp/batch_merged.json
```

### 使用健康评分脚本（CLI 模式）

```bash
# 从 stdin 读取 JSON 数据并计算评分
echo '{
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
}' | python scripts/calculate_health_score.py
```

### 自定义权重和阈值

```bash
echo '{
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
  },
  "weights": {
    "gross_profit_percent": 0.40,
    "convert_percent": 0.10,
    "ads_acos": 0.25,
    "refund_percent": 0.15,
    "inventory_days": 0.05,
    "star": 0.05
  },
  "benchmarks": {
    "gross_profit_percent": {"healthy": 0.25, "warning": 0.15, "direction": "higher_is_better"},
    "convert_percent": {"healthy": 0.10, "warning": 0.05, "direction": "higher_is_better"},
    "ads_acos": {"healthy": 0.18, "warning": 0.25, "direction": "lower_is_better"},
    "refund_percent": {"healthy": 0.05, "warning": 0.10, "direction": "lower_is_better"},
    "inventory_days": {"healthy": 30, "warning": 60, "direction": "lower_is_better"},
    "star": {"healthy": 4.3, "warning": 4.0, "direction": "higher_is_better"}
  }
}' | python scripts/calculate_health_score.py
```

---

## 数据查询 Payload 模板

> ⚠️ **构造查询时使用 `opscli query build` 命令自动生成完整 payload**，不要手写 `userEmail`、`from.table`、`from.permission` 等字段，这些由 opscli 自动填充。

详细字段映射和 payload 模板见 `references/dataset_fields_mapping.md`。

---

## 【强制】比较类查询优先级规则

> 涉及环比、同比、趋势对比等场景时，**必须按以下优先级选择方案：**

| 优先级 | 场景 | 方案 |
|--------|------|------|
| ① 最优 | 当期 vs 对比期汇总对比（环比/同比） | `dataComparison`（服务端条件聚合，一次 SQL） |
| ② 次优 | 按时间粒度分组的趋势环比/同比 | `MOY` 高级计算（服务端窗口函数，一次 SQL） |
| ③ 兜底 | ①② 均因工具限制无法使用时 | 多次 `opscli query run` + 客户端合并 |

---

## 错误处理

| 场景 | 解决方法 |
|------|---------|
| 本地数据为空 | `opscli skills upgrade ops-dataset-query` |
| dataset_alias 不存在 | 检查拼写或 `opscli skills upgrade` 同步最新数据集 |
| 未登录 | 调用 `ops-auth` Skill，执行 `opscli auth login` |
| Token 过期 | 优先 `opscli auth token refresh --all`；刷新失败再 `opscli auth login` |
| opscli 未找到 | 激活虚拟环境或设置 `OPSCLI_BIN` |
| 健康评分为 NaN 或异常 | 检查输入指标数据是否完整，补全缺失指标后重算 |

---

## 安装与管理

```bash
opscli skills install ops-asin-health-diagnoser            # 安装
opscli skills install ops-asin-health-diagnoser --force     # 强制重装
opscli skills status --pretty                                # 查看版本
opscli skills upgrade ops-asin-health-diagnoser             # 升级
```
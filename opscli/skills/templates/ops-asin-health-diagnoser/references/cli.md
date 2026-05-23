---
name: ops-asin-health-diagnoser
description: ASIN 健康诊断 CLI 模式操作手册
version: v0.2.0
---

# ASIN 健康诊断（CLI 模式）

使用 `opscli` 命令行工具查询 ASIN 运营数据，通过 `scripts/calculate_health_score.py` 计算健康评分。

> 认证门禁和运行模式判断见主 `SKILL.md`，本文件只补充 CLI 特有命令和操作。

---

## 使用原则

- 所有远端查询必须通过 `opscli query` 执行，**禁止直接调用后端 HTTP**
- 使用 `opscli query build` 构造 payload，**禁止手写 `userEmail`、`from.table`、`from.permission`**
- 本地数据过期时执行 `opscli skills upgrade ops-dataset-query`

---

## 完整工作流

### 1. 单一 ASIN 诊断

```bash
# 查询主数据集
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension asin --dimension product_name \
  --metric gross_profit_percent --metric convert_percent \
  --metric ads_acos --metric refund_percent --metric sell_qty_days \
  --where "asin|eq|\"B08XXXXXX\"" \
  --where "date_id|between|[\"2025-01-01\",\"2025-01-31\"]" \
  --output /tmp/asin_main.json --run --pretty

# 查询星级
opscli query build \
  --dataset ds_pdTYjvLRCadv \
  --dimension asin \
  --metric "star:avg:f_star" \
  --where "asin|eq|\"B08XXXXXX\"" \
  --output /tmp/asin_star.json --run --pretty

# 合并数据并计算评分
python scripts/calculate_health_score.py --input /tmp/asin_merged.json --pretty
```

### 2. 批量 ASIN 诊断

```bash
# 批量查询主数据集
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension asin --dimension product_name \
  --metric gross_profit_percent --metric convert_percent \
  --metric ads_acos --metric refund_percent --metric sell_qty_days \
  --where "asin|in|[\"B08XXXXXX\",\"B09YYYYYY\",\"B07ZZZZZZ\"]" \
  --where "date_id|between|[\"2025-01-01\",\"2025-01-31\"]" \
  --output /tmp/batch_main.json --run --pretty

# 批量计算评分（按评分降序排列）
python scripts/calculate_health_score.py --input /tmp/batch_merged.json --batch --pretty
```

### 3. 自定义权重

```bash
python scripts/calculate_health_score.py --input /tmp/asin_metrics.json \
  --weights '{"gross_profit_percent": 0.40, "ads_acos": 0.25}' --pretty
```

### 4. 自定义阈值

```bash
python scripts/calculate_health_score.py --input /tmp/asin_metrics.json \
  --benchmarks '{"gross_profit_percent": {"healthy": 0.25, "warning": 0.15, "direction": "higher_is_better"}}' \
  --pretty
```

---

## 比较类查询

涉及环比、同比时，按优先级选择：

| 优先级 | 方案 | 说明 |
|--------|------|------|
| 1 | `dataComparison`（服务端条件聚合） | 一次 SQL 完成当期 vs 对比期 |
| 2 | `MOY` 高级计算（服务端窗口函数） | 按时间粒度分组的趋势环比/同比 |
| 3 | 多次 `opscli query run` + 客户端合并 | 兜底方案 |

---

## 错误处理

| 场景 | 解决方法 |
|------|---------|
| 本地数据为空 | `opscli skills upgrade ops-dataset-query` |
| dataset_alias 不存在 | 检查拼写或 `opscli skills upgrade` |
| opscli 未找到 | 激活虚拟环境或确认安装路径 |

---

## 安装与管理

```bash
opscli skills install ops-asin-health-diagnoser            # 安装
opscli skills install ops-asin-health-diagnoser --force     # 强制重装
opscli skills status --pretty                                # 查看版本
opscli skills upgrade ops-asin-health-diagnoser             # 升级
```

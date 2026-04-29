---
name: ops-asin-health-diagnoser
description: Diagnoses Amazon ASIN health by calculating composite scores from gross_profit_percent, convert_percent, ads_acos, refund_percent, inventory_turnaround_days, and star rating using internal operational data. Use when evaluating product performance, identifying underperforming ASINs, prioritizing operational interventions, or preparing weekly review reports.
---

# ASIN Health Diagnoser

Calculates a composite health score (0-100) for Amazon ASINs using internal operational data from opscli datasets.

## Capabilities

- Single ASIN deep diagnosis with 6 core metrics
- Batch ASIN health ranking and filtering
- Department/team-level health overview
- Prioritized action recommendations with expected impact
- Support for custom weights and thresholds

## Health Score Formula

```
Score = w1 * normalize(gross_profit_percent) +
        w2 * normalize(convert_percent) +
        w3 * normalize(1 - ads_acos) +
        w4 * normalize(1 - refund_percent) +
        w5 * normalize(1 / inventory_days) +
        w6 * normalize(star / 5)
```

Default weights: `[0.30, 0.20, 0.20, 0.15, 0.10, 0.05]`

## Threshold Reference

> **字段映射说明**：数据集 `ds_d35ac6f3910c` 中的 `sell_qty_days` 字段对应本 Skill 中的 `inventory_days` 指标，`ads_acos` 对应 `ads_acos`，`convert_percent` 对应转化率字段。

| Metric | Dataset Field | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| gross_profit_percent | > 20% | 10-20% | < 10% |
| convert_percent | > 10% | 5-10% | < 5% |
| ads_acos | < 20% | 20-30% | > 30% |
| refund_percent | < 5% | 5-10% | > 10% |
| inventory_days | < 45 | 45-90 | > 90 |
| star | > 4.3 | 4.0-4.3 | < 4.0 |

## Input Format

- Single ASIN: `"B08XXXXXX"`
- Multiple ASINs: `"B08XXXXXX, B09YYYYYY"`
- Team filter: `"team_name = 'Kitchen-Team-A'"`
- Date range: `"last 30 days"`, `"2025-01-01 to 2025-01-31"`

## Output Format

For each ASIN:

```
【ASIN】B08XXXXXX（Product Name）
【健康度评分】72/100（良好）
【分项指标】
  ├─ 毛利率：18.5% ⚠️（预警，目标>20%）
  ├─ 转化率：12.3% ✅（健康）
  ├─ ACOS：22.1% ⚠️（预警，目标<20%）
  ├─ 退款率：4.2% ✅（健康）
  ├─ 库存周转：38天 ✅（健康）
  └─ 星级：4.5⭐ ✅（健康）
【主要问题】ACOS 偏高、毛利率低于目标
【建议行动】
  1. [P1] 优化广告投放，将 ACOS 从 22% 降至 18%
  2. [P1] 评估采购成本，谈判降低 2-3%
【数据时间】2025-01-01 ~ 2025-01-31
```

## Scripts

- `scripts/calculate_health_score.py`: Calculates composite health score from JSON input

## How to Use

### Step 1: Query Data

Use opscli query commands to fetch ASIN metrics:

```bash
# Build query payload
opscli query build \
  --dataset ds_d35ac6f3910c \
  --dimension asin --dimension product_name \
  --metric gross_profit_percent --metric convert_percent \
  --metric ads_acos --metric refund_percent --metric sell_qty_days \
  --output payload.json

# Run query
opscli query run --payload payload.json
```

### Step 2: Run Diagnosis

```bash
echo '{"asin": "B08XXXXXX", "metrics": {...}}' | python scripts/calculate_health_score.py
```

## Best Practices

1. Always compare against team/category averages, not just absolute thresholds
2. When star rating is missing, exclude it from calculation and note the gap
3. For new products (< 30 days), use relaxed thresholds
4. Flag any ASIN with multiple Critical metrics for immediate attention
5. Use `opscli query build` to construct payloads instead of writing SQL manually

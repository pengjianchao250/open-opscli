# 市场画像输出模板

## 模板结构

```markdown
# 市场概况：{类别}

## 执行摘要
- ASIN 总数：{count}
- 总销售额：{金额}
- 分析周期：{period}

## 市场最优属性组合
{top_combo}
- 市场份额：{share}%
- ASIN 数量：{count}（占总数的 {count_pct}%）
- 每个 ASIN 的销售额：${spa}
- 状态：{供不应求/供给充足/供给过剩}

## 三大机会
1. {combo_1} — 机会得分：{score}
2. {combo_2} — 机会得分：{score}
3. {combo_3} — 机会得分：{score}

## 供应过剩的细分市场
1. {combo_1}——效率低，考虑缩减

## 建议
- {recommendation_1}
- {recommendation_2}
```

## 判定规则

- **供应不足**：sales_per_asin > 1.5x 平均值且市场份额 < 20%
- **供应过剩**：sales_per_asin < 0.5x 平均值且市场份额 > 30%
- **供需平衡**：sales_per_asin 在均值的 0.8-1.2 倍之间

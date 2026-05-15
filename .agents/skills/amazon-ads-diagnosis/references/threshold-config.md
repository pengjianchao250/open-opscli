# 阈值配置说明

判断标准不应永远写死。推荐采用“默认阈值 + 场景化覆盖”的方式：

1. 默认使用 `thresholds.default.json`，适合成熟品、常规月度复盘。
2. 用户明确给出目标时，复制默认配置到工作区并修改，例如：
   - 控亏目标：降低 `highAcos`、`warnAcos`、`highAdShare`。
   - 新品冷启动：提高 ACOS 容忍度，降低立即收缩的敏感度。
   - 大促期：提高样本阈值，避免短期波动导致误判。
   - 高毛利品类：可适当提高可接受 ACOS。
   - 低毛利品类：必须更严格控制广告费占比。
3. 用户未给目标但数据出现明显亏损、毛利异常或口径差异时，先在分析说明中声明采用“利润优先”或“控费优先”的判断侧重点。
4. 只有当阈值会显著影响结论时才询问用户；普通月度复盘可直接用默认阈值，并在 `09_规则说明` 中展示。

## 配置结构

脚本支持通过 `--threshold-config <json路径>` 传入配置。JSON 可以只覆盖部分字段，未提供的字段会沿用默认值。

示例：

```json
{
  "thresholds": {
    "highAcos": 0.25,
    "warnAcos": 0.18,
    "goodAcos": 0.10,
    "highAdShare": 0.10,
    "weakMargin": 0.08,
    "rowSpend": {
      "asin": 8000,
      "campaign": 8000
    }
  }
}
```

## 字段含义

- `highAcos`：高风险 ACOS，超过后倾向立即控量。
- `warnAcos`：预警 ACOS，提示投产偏弱。
- `goodAcos`：优秀 ACOS，结合 CVR 和毛利判断是否可放量。
- `lowCtr`：低点击率，用于判断高曝光低点击。
- `lowCvr`：低转化率，用于判断点击后不转化。
- `goodCvr`：较好转化率，用于识别可放量对象。
- `highAdShare`：广告费占总销售偏高阈值。
- `weakMargin`：弱毛利率阈值。
- `rowSpend`：各维度最小花费样本阈值。
- `minClicks`：各维度判断 CVR 的最小点击样本。
- `minImpressions`：各维度判断 CTR 的最小曝光样本。

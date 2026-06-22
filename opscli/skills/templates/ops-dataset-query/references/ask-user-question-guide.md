---
name: ops-dataset-query-ask-user-question
description: ops-dataset-query 中 AskUserQuestion 结构化澄清规范
---

# AskUserQuestion 结构化澄清规范

> **适用范围**：本 Skill 在执行查询前需要用户确认数据集、字段、时间、筛选、币种、查询参数或纠错方向时，必须优先使用 `AskUserQuestion`，不能只用纯文本提问代替结构化确认。

---

## 一、核心原则

1. **有歧义就问**：凡 `references/rules.md` 或 `QUERY_SPEC.md` 标记为"必须澄清/让用户选择/确认后执行"的场景，都必须使用 `AskUserQuestion`。
2. **确认前不构造查询**：用户未明确确认前，不得把推荐的数据集、字段、时间范围、过滤条件写入 `query_simple` 参数。
3. **推荐不等于默认**：即使命中 1 个推荐项，也只能作为推荐展示，仍需让用户确认或改选。
4. **长列表先展示全文**：候选项 >4 个时，先用文本列出完整候选（或前 300 项并提示可输入"更多"），再用 `AskUserQuestion` 展示最相关的 2~3 个快捷选项。
5. **保留自由输入**：每次 `AskUserQuestion` 必须提供"其他（自定义）"或等价选项，允许用户输入序号、字段名、数据集别名或自然语言补充。

---

## 二、使用策略

| 场景 | 处理方式 |
|------|---------|
| 候选项 ≤4 个 | 直接用 `AskUserQuestion` 展示全部候选 |
| 候选项 >4 个 | 文本展示全量候选 + `AskUserQuestion` 展示推荐项和"其他" |
| 只有 1 个推荐项但来自自然语言匹配 | 用 `AskUserQuestion` 确认"使用推荐项 / 查看其他候选 / 自定义" |
| 用户明确指定且唯一命中 | 可不打断查询，但必须在查询前参数摘要中明示 |
| 用户明确指定但模糊命中多个 | 必须用 `AskUserQuestion` 让用户选唯一项 |
| 规则允许默认值 | 可采用默认值，但必须在查询前参数摘要中展示，并允许用户修改 |

---

## 三、必须结构化提问的场景

### 3.1 数据集选择

触发条件：
- 用户只给出业务领域或自然语言需求（如"广告数据"、"销售数据"、"库存数据"），未指定 dataset/table_id。
- `datasets.csv`、`query_metadata()` 或本地搜索返回多个候选数据集。
- 仅字段搜索命中一个表，但业务领域词可能存在其他粒度数据集。
- 用户指定的数据集名称模糊匹配到多个相似数据集。

要求：
- 先基于 `query_metadata()` 或 `datasets.csv` 获取数据集候选。
- 对"广告/销售/库存/物流/财务"等大领域词，必须搜索数据集列表本身，不能只依赖字段搜索结果。
- 列出候选时说明：数据集名称、table_id、dataset_alias、数据粒度、适用场景、主要约束。

示例：

```text
AskUserQuestion:
  questions:
    - question: "您的需求匹配到多个广告相关数据集，请选择本次查询的数据粒度："
      header: "数据集"
      options:
        - label: "综合广告费数据集"
          description: "适合查看整体广告费、广告销售额、ACOS、点击等汇总指标"
        - label: "Campaign 明细数据集"
          description: "适合按 campaign / 广告组下钻诊断"
        - label: "广告类型细分数据集"
          description: "适合对比 SP/SB/SD/SBV 等广告类型"
        - label: "其他（输入数据集名或序号）"
          description: "在输入框中输入候选列表里的序号、dataset_alias 或 table_id"
```

### 3.2 字段与指标选择

触发条件：
- 用户术语精确匹配到 ≥2 个字段。
- 用户术语模糊匹配到 ≥2 个字段。
- 同一 `field_name` 出现在多个 table_id，且口径/粒度可能不同。
- 公式指标（如 ACOS/ROAS）跨多个数据集存在。
- 库存、SKU、ASIN、品类、人员/组织等存在多个变体或层级。

要求：
- 文本列出所有候选字段，包含 field_name、verbose_name、dataset/table_id、口径说明。
- 用 `AskUserQuestion` 让用户选择唯一字段或多选字段。
- 公式字段必须说明汇总表达式或口径差异。

### 3.3 时间范围与对比口径

触发条件：
- 用户说"最近一个月"、"最近一周"、"本月前 N 天 vs 上月完整月"等存在滚动/自然周期歧义。
- 跨月/跨年对比天数不对等。
- 用户要求环比/同比/上期对比，但主周期或对比周期不完整。

要求：
- 用日期算法先计算候选范围，再用 `AskUserQuestion` 展示选项。
- "近 N 天"默认包含今天，但必须在查询前参数摘要中展示起止日期。

示例：

```text
AskUserQuestion:
  questions:
    - question: "您说的最近一个月想按哪种时间口径查询？"
      header: "时间范围"
      options:
        - label: "近30天（含今天）"
          description: "滚动30天，起始日期 = 今天 - 29天"
        - label: "本自然月"
          description: "从本月1日到今天"
        - label: "最近30个完整自然日"
          description: "不含今天，适合日报已完结口径"
        - label: "其他（自定义日期）"
          description: "输入日期范围，例如 2026-04-01 ~ 2026-04-30"
```

### 3.4 币种

触发条件：
- 用户明确提到"美金/USD/原币/站点币种"。
- 用户做财务核算、导出报表或要求对账。
- 同一金额指标存在原币与 CNY，且用户要求精准口径。

要求：
- 普通查询默认 CNY，可不单独提问，但必须在查询前参数摘要和输出中明示。
- 触发以上条件时，用 `AskUserQuestion` 确认 CNY / 原币 / 自定义。

### 3.5 查询前参数摘要

若本次查询中发生过任一自动推荐或默认选择，执行前必须展示参数摘要并用 `AskUserQuestion` 确认。

摘要至少包含：
- 数据集：名称、table_id、dataset_alias
- 时间范围：起止日期、是否包含今天
- 维度：verbose_name / field_name
- 指标：verbose_name、聚合方式、公式字段说明
- 筛选：字段、操作符、值
- 币种：CNY / 原币
- 排序与条数
- dataComparison：主周期与对比周期

示例：

```text
AskUserQuestion:
  questions:
    - question: "以上查询参数是否正确？"
      header: "确认执行"
      options:
        - label: "确认执行"
          description: "参数无误，立即执行查询"
        - label: "修改数据集"
          description: "重新选择数据集，字段和指标需重新确认"
        - label: "修改字段/筛选"
          description: "调整维度、指标、时间或过滤条件"
        - label: "其他（自定义调整）"
          description: "输入修改指令，例如 '改成按部门汇总' 或 '时间改上月'"
```

### 3.6 查询异常与纠错

触发条件：
- 查询返回 0 行且 filters 非空。
- 主要指标全为空或全为 0。
- 用户反馈结果不对、字段不对、条件不对、排序/条数不对。

要求：
- 用户明确反馈错误时，直接切换 `ops-query-wizard` 纠错模式。
- AI 自检异常时，先用 `AskUserQuestion` 提供纠错入口。

示例：

```text
AskUserQuestion:
  questions:
    - question: "查询结果可能异常，您希望我怎么修正？"
      header: "纠错"
      options:
        - label: "进入引导纠错"
          description: "切换到 ops-query-wizard，逐步检查数据集、字段和筛选"
        - label: "放宽筛选重试"
          description: "先去掉部分过滤条件，验证是否有数据"
        - label: "修改字段口径"
          description: "重新选择指标、维度或公式口径"
        - label: "其他（说明问题）"
          description: "输入您认为不对的地方，例如 '数据集用错了'"
```

---

## 四、禁止行为

- 禁止因为字段搜索结果集中在一个表，就认定数据集唯一。
- 禁止把"告知用户将使用某数据集"当作用户确认。
- 禁止只展示推荐项而隐藏其他候选。
- 禁止没有自由输入选项。
- 禁止在用户未确认前执行查询。
- 禁止查询结果异常后在当前 Skill 内反复重试而不进入纠错流程。

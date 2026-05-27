---
name: ops-amazon-listing-analysis
description: 基于 ASIN 和卖家精灵采集材料，输出 Amazon Listing 表达与一致性优化建议
version: 0.1.0
---

# ops-amazon-listing-analysis

围绕 Amazon ASIN 做 Listing 表达与一致性优化分析。该 Skill 不负责直接采集网页数据，采集动作必须调用 `ops-seller-sprite` 或 `opscli seller-sprite`。

---

## 输入要求

用户必须提供：

- Amazon ASIN
- 显式关键词

标准采集命令：

```bash
opscli seller-sprite collect --asin <ASIN> --keyword <KEYWORD> --site us --period 30d --limit 50 --output-dir ./seller_sprite_runs --pretty
```

---

## 分析材料

优先读取采集结果中的：

- 高频词
- 关键词列表
- 关键词趋势
- PPC 与 ABA 相关字段
- 竞品 ASIN
- 页面 Markdown
- 截图路径

---

## 输出范围

只能输出：

- 问题定位
- 优化方向
- 修改示例

---

## 禁止输出

- 完整可直接上线文案
- 自动替换现有 Listing
- 多语言重写
- 自动刊登操作
- 没有证据支撑的确定性结论

---

## 输出格式

```markdown
## 问题定位

- 问题：...
- 依据：...

## 优化方向

- 方向：...
- 依据：...

## 修改示例

- 原表达：...
- 示例：...
- 说明：该示例仅用于方向参考，不是完整上线文案。
```

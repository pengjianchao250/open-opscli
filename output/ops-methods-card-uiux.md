# ops-methods-card UIUX

日期：2026-05-12

## 范围

本次没有新增前端页面。UIUX 只约束最终生成的本地 HTML 报告。

## HTML 报告原则

- 完整 HTML 文件，可直接浏览器打开。
- 样式内联，不依赖构建工具。
- 参考 `references/卡片输出示例.html` 的信息层级。
- 不保留示例中的虚构数据。
- 所有结论必须来自用户输入、方法卡详情和 Excel 数据。

## 页面结构

建议结构：

1. 标题区：方法卡名称、用户问题、数据文件、生成时间。
2. 关键指标区：根据 Excel 数值字段生成。
3. 方法卡匹配说明：说明为什么选中该卡。
4. 数据摘要：字段、样本量、极值、均值。
5. 分析过程：按 `analysisSteps` 展开。
6. 报告正文：按 `outputContract.content` 展开。
7. 质量校验：按 `qualityRules` 说明结论边界。

## 输出路径

```text
output/methods-card/<方法卡ID或名称>-YYYYMMDD-HHMMSS.html
```


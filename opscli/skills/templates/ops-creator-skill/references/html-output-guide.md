# HTML 展示输出

当 Skill 的结果需要给运营、主管、跨团队或用户审阅时，可以生成静态 HTML。HTML 不是替代 Markdown/Excel，而是让结果更容易浏览、对比和反馈。

## 适合生成 HTML 的场景

- Amazon 广告诊断、Listing 健康检查、库存预警、利润复盘。
- Skill 测试结果审阅：with-skill、baseline、通用替代方案并排比较。
- 培训交接：流程、案例、错误示范、检查清单。
- 需要图表、指标卡、可折叠明细或高亮异常的报告。

## 默认设计

- 生成单个静态 `.html` 文件。
- CSS 内联或放在同目录，不依赖某个 AI 工具的内置浏览器。
- 数据量大时只展示摘要和前 N 条明细，完整数据另存 CSV/XLSX。
- 不使用复杂前端工程；优先 Python 模板字符串、Jinja2 或标准库生成。
- 页面顶部写清数据周期、口径、生成时间、输入文件和待确认假设。

## 推荐结构

```html
<section id="summary">核心结论和指标卡</section>
<section id="actions">行动建议</section>
<section id="exceptions">例外与人工确认</section>
<section id="benchmark">测试/基准对比</section>
<section id="details">明细表</section>
<section id="notes">数据口径与限制</section>
```

## Skill 中的输出约定

```markdown
## 输出规范

默认输出：
- Markdown 摘要：适合聊天和归档。
- CSV/XLSX 明细：适合继续处理。
- HTML 报告：适合审阅和展示。

HTML 文件命名：
`outputs/YYYY-MM-DD_<对象>_<任务名>.html`
```

## 测试 HTML

至少检查：

- 文件存在且非空。
- 标题、周期、对象、口径存在。
- 关键指标和异常数量与 CSV/JSON 一致。
- 高风险项有明显样式。
- 不依赖远程资源也能打开。

## Python 实现建议

优先使用 Python 生成 HTML：

- 简单场景：标准库 + 字符串模板。
- 表格场景：`pandas.to_html()` 或手写转义。
- Excel 同步输出：`openpyxl`。
- 需要图表：先用 SVG/纯 HTML 表格，或生成本地图片后嵌入。

不要把大量原始数据直接塞进 HTML；大表放 CSV/XLSX，HTML 只放摘要和可审阅明细。

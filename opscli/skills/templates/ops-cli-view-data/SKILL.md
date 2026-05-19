---
name: ops-cli-view-data
description: Use when a chart UUID and Analysis View filterRule are already available and the chart data needs to be queried and exported as Excel.
version: see data/VERSION.json
---

# ops-cli-view-data

本 Skill 只负责数据获取与 Excel 导出。它依赖 `ops-dataset-query`，通过图表 UUID 获取查询结构，将运行时过滤条件注入到查询 payload，再执行查询并导出 Excel。

---

## 何时使用

- 已经拿到 Analysis View 的 `source.chartInfo.chartId`
- 已经完成运行时参数校验
- 需要把图表数据导出为 `.xlsx`

---

## CLI 用法

```bash
python scripts/export_view_data.py \
  --chart-uuid a6104122-3616-46b5-aaac-938861bf3052 \
  --filter-rule /tmp/filter_rule.json \
  --output /tmp/analysis-view.xlsx \
  --pretty
```

参数：

| 参数 | 必填 | 说明 |
|---|---:|---|
| `--chart-uuid` | 是 | 图表 UUID |
| `--filter-rule` | 否 | Analysis View 保存的 `source.chartInfo.filterRule` JSON 文件 |
| `--output` | 否 | Excel 输出路径；不传时自动生成 `chart-data-{chart_uuid}-{YYYYMMDD-HHMMSS}.xlsx` |
| `--sheet-name` | 否 | Sheet 名称，默认 `视图数据` |
| `--skills-dir` | 否 | Skill 安装根目录 |
| `--pretty` | 否 | 格式化输出 JSON |

---

## 过滤规则约定

- `--filter-rule` 输入为运营系统同构的 `filterRule` JSON 对象，通常由 `ops-cli-view-runner` 生成。
- 字段匹配优先使用规则中的 `fieldId`、`field`、`globalAlias`、`originName`、`key`、`title` 等信息，对应 `ops-dataset-query` 返回的 `field_mappings` / `datasets[].fields` / `datasets[].filterable_fields`。
- 本 Skill 会把 `filterRule` 注入到底层 `cli-query` payload 的 `where`，Excel 导出仍复用 `ops-dataset-query`。

---

## 输出

```json
{
  "success": true,
  "chart_uuid": "a6104122-3616-46b5-aaac-938861bf3052",
  "chart_result": "/tmp/ops-cli-view-data/chart_result.json",
  "excel": {
    "success": true,
    "output": "/tmp/analysis-view.xlsx",
    "rows": 12,
    "columns": ["日期", "总库存"]
  }
}
```

---

## 依赖关系

- 必须已安装 `ops-dataset-query`
- 远端查询动作由 `ops-dataset-query/scripts/query.py` 转发到正式 `opscli query` 入口
- Excel 导出由 `ops-dataset-query/scripts/excel_export.py` 完成

---

## 本地开发闭环

- 回归契约：`opscli/skills/evals/cases/ops-cli-view-data.json`
- 本地执行：`python scripts/skill_dev_loop/run_eval.py --skill ops-cli-view-data --pretty`
- 改 `SKILL.md` 或 `scripts/export_view_data.py` 后先跑本地 eval；低于 `min_score` 时先修契约失败项，再继续迭代。

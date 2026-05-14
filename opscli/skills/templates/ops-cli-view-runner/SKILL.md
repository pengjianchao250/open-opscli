---
name: ops-cli-view-runner
description: Use when the user provides an Analysis View ID and needs to run the view, resolve missing runtime parameters, and export the result as Excel.
version: see data/VERSION.json
---

# ops-cli-view-runner

本 Skill 是 Analysis View 运行入口。调用方通常只提供视图 ID 和运行时参数，本 Skill 会读取视图详情、校验必填参数、把参数写回运营系统同构的 `filterRule.rules[]`，再调用 `ops-cli-view-data` 导出 Excel。

---

## 何时使用

- 用户提供 Analysis View ID，例如 `10`
- 需要先判断运行参数是否齐全
- 需要最终拿到视图数据 Excel

---

## CLI 用法

```bash
python scripts/run_view.py \
  --view-id 10 \
  --params '{"473f5ca149fcdc4a65c8574f6280c78f28e8e4f3":"A"}' \
  --output /tmp/view-10.xlsx \
  --pretty
```

也可以从文件读取参数：

```bash
python scripts/run_view.py \
  --view-id 10 \
  --params-file /tmp/view_params.json \
  --output /tmp/view-10.xlsx \
  --pretty
```

---

## 参数

| 参数 | 必填 | 说明 |
|---|---:|---|
| `--view-id` | 是 | Analysis View 自增 ID |
| `--params` | 否 | 运行时参数 JSON 字符串 |
| `--params-file` | 否 | 运行时参数 JSON 文件 |
| `--output` | 否 | Excel 输出路径；不传时自动生成 `analysis-view-{id}-{YYYYMMDD-HHMMSS}.xlsx` |
| `--sheet-name` | 否 | Sheet 名称，默认使用视图名称 |
| `--skills-dir` | 否 | Skill 安装根目录 |
| `--allow-empty-params` | 否 | 调试时允许必填参数为空 |
| `--pretty` | 否 | 格式化输出 JSON |

---

## 过滤规则约定

- 运行时参数 key 使用 `missing[].field` 或 `input_schema.required` 中的字段 ID。
- 若未显式传 `--params`，会优先复用视图中已保存的 `source.chart_info.filter_rule.rules[].value`。
- 写回参数时保留原始 `filterRule.rules[]` 结构，并补齐运营系统过滤器字段：`fieldId`、`field`、`title`、`originalTitle`、`type`、`fieldType`、`operator`、`dateOperator`、`filterType`、`enumValue`、`value`。
- `filterRule` 结构应与运营系统图表查询参数里的 `filterRule` 保持一致，不在 runner 中改写为底层 SQL/where 结构。
- 若视图保存的是精简 `filter_rule`，runner 会使用 `input_schema.required[field].description` 补 `title`，保证下游可按运营系统字段名匹配过滤条件。

---

## 缺参数输出

```json
{
  "success": false,
  "needs_input": true,
  "missing": [
    {
      "field": "473f5ca149fcdc4a65c8574f6280c78f28e8e4f3",
      "type": "string",
      "description": "SKU等级"
    }
  ]
}
```

---

## 成功输出

```json
{
  "success": true,
  "view_id": 10,
  "view_name": "库存分析视图",
  "chart_uuid": "a6104122-3616-46b5-aaac-938861bf3052",
  "excel": {
    "success": true,
    "output": "/tmp/view-10.xlsx"
  }
}
```

---

## 依赖关系

- 需要本机已登录 `opscli auth`
- 通过 `/api/v1/ai/cli-view/{id}` 获取视图详情
- 数据查询与 Excel 导出交给 `ops-cli-view-data`

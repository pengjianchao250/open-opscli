---
description: 图表查询与 Excel 导出 — 复杂图表入口（CLI query chart / MCP query_chart / 映射、异常检测、导出脚本）
---

# 图表查询与 Excel 导出

仅当用户明确提供图表 UUID 或要求复杂图表（多 query、小计/总计、Excel 透视导出）时使用本入口；普通查询走 `opscli query flow` / MCP `query_flow`。

## 入口

**CLI 模式**：

```bash
opscli query chart --uuid <chart_uuid> --pretty           # 仅查看图表查询结构
opscli query chart --uuid <chart_uuid> --run --pretty     # 获取并执行所有查询（结果自动合并）
opscli query chart --uuid <chart_uuid> --run --dry-run --pretty  # 仅生成 SQL 不执行
opscli query chart-doc --uuid <chart_uuid> --output <文件.md>    # 生成图表 API 调用 Markdown 文档
```

**MCP 模式**：`query_chart(chart_uuid=..., run=True|False, dry_run=False)`（需要认证）。

| 参数 | 说明 |
| --- | --- |
| `--uuid <chart_uuid>` | 图表唯一标识，必填 |
| `--run` | 获取并执行图表的全部子查询；不传则只返回查询结构 |
| `--dry-run` | 只生成 SQL 不执行：返回体里没有结果行，也**不会**附带证据合同 |
| `--result-file <文件.json>` | 把完整结果写入指定 JSON 文件，stdout 只保留预览行；**仅与 `--run` 同用生效**，优先级高于 `--save-result` |
| `--save-result` | 把完整结果写入默认临时路径，stdout 只保留预览行；**仅与 `--run` 同用生效** |
| `--pretty` | 格式化输出 JSON |

结果行数较大时必须传 `--result-file` 或 `--save-result`，否则全量行会原样进入返回体、撑爆上下文；落盘后返回体给出 `result_file` 路径，并说明 stdout 里的 `preview_rows` 只是前若干行预览。

返回中 `datasets` 是公共字段语义层（含 `fields`、`filterable_fields`），`queries` 是执行层；优先消费服务端字段语义，不重复做本地推断。多 query 各自独立执行，单条失败不阻断其余，合并行带 `_query_index` 标识来源。

## 多 query 小计/总计规则（强制）

一个图表可能返回多个 query（看 `merged.meta.queryCount`），按 `query.groupBy` 长度识别：与 Query 0 相同为明细行；更少为小计行；为空为总计行。

1. 必须遍历所有 queries，不能只读 `queries[0]`。
2. 小计/总计必须直接取服务端返回值，禁止本地累加明细行计算（服务端聚合口径可能与简单累加不同）。
3. 明细、小计、总计合并为同一张表展示：小计行仅填充其 groupBy 包含的维度列（其余留空），并在可辨识维度列标注 **小计**；总计行维度列全部留空并标注 **总计**。
4. 默认展示全部维度和指标列，不省略字段。

## 字段映射与格式

- 先用映射脚本自动映射：CLI 用 `python3 scripts/chart_map.py --input <结果json> --map-results --pretty`；MCP 用 `python3 scripts/chart_map_mcp.py`（零 opscli 依赖，仅文件输入输出）。
- 映射不完整（`mapped_name` 仍为 `global_alias`）时手动补充：从 `payload.query.select[].expr` 提取 `field_name`，再按当前账号字段元数据查 `verbose_name`。
- 百分比类公式指标服务端返回小数（如 `-0.2039` 即 -20.39%），展示时 ×100 保留两位小数，无数据显示 `-`。

## 异常检测（可选）

`python3 scripts/chart_analyze.py --input <结果json> --pretty`（MCP 用 `chart_analyze_mcp.py`）。内置 5 类规则：负毛利、毛利环比降超 30%、原价金额环比降超 20%、广告费升且毛利降、订单量归零。输出 `summary`/`anomalies`/`findings`。

## Excel 导出

前置依赖 `pip install openpyxl`：

```bash
python3 scripts/excel_export.py --input <结果json> --output <输出.xlsx> [--sheet-name 名称]
python3 scripts/excel_export.py --uuid <chart_uuid> --output <输出.xlsx>   # 自动调用 opscli 执行后导出
```

MCP 模式用 `python3 scripts/excel_export_mcp.py --input ... --output ...`。

格式要求：表头蓝底白字加粗并冻结首行；数值列千分位、百分比列百分比格式；小计行灰底加粗、总计行深蓝底白字加粗；负毛利红字；列宽按内容自适应（最大约 50 字符）；小计/总计数据直接来自 `queries[1+].result.data`。

## 证据合同（已内嵌，无需补跑）

`opscli query chart --uuid <chart_uuid> --run` 与 MCP `query_chart(run=True)` 的返回 `data` 里**已经自带** `evidence_contract`：它只由 `merged` 段生成（`queries[i]` 下的查询结构与可筛选字段是元数据噪声，混进去会挤掉真正的结果行），构建失败时改为 `evidence_contract_error`。直接按其 `required_evidence` / `required_disclosures_zh` / `forbidden_inferences_zh` 组织结论，**不需要**再补跑任何证据脚本。`--dry-run` 没有结果行，因此不附证据合同。

随包的 `scripts/evidence_contract.py` 已改为内核薄壳（只调用内核实现，不再自带第二份算法），仅用于对**已落盘的结果文件**做手工复算，例如复核 `--result-file` 的产物；它需要用装有 opscli 的 Python 运行：

```bash
python3 scripts/evidence_contract.py --input <结果json>   # 也可从 stdin 读取
```

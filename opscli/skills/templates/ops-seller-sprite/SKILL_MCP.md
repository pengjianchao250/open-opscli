---
name: ops-seller-sprite
mcp-version: v1.0.0
description: SellerSprite/卖家精灵 MCP usage guide for querying scenarios and exporting JSON or XLSX files through seller_sprite_* tools.
---

# ops-seller-sprite MCP

Use these MCP tools:

- `seller_sprite_scenarios`: list available scenarios.
- `seller_sprite_run`: run a scenario and create an export file.
- `seller_sprite_job_status`: read a saved task result by `job_id`.
- `seller_sprite_export`: read export path, `file://` URL, filename, format, and MIME type.

## Workflow

1. Call `seller_sprite_scenarios` when scenario names or required params are uncertain.
2. Call `seller_sprite_run` with `scenario`, `site`, `period`, `params`, and optionally `export_format`.
3. Use the returned `data.job_id` for follow-up status/export calls.
4. Call `seller_sprite_export` when the user needs the file link.

## Export Format

- MCP default: `json`.
- Use `export_format: "xlsx"` when the user asks for XLS, XLSX, Excel, 表格, or 导出文件.
- `xls` is accepted by the backend as an alias for `xlsx`.

## Scenario Mapping

| Natural language | scenario |
| --- | --- |
| 选竞品 / competitor lookup | `competitor-lookup` |
| 选产品 / product research | `product-research` |
| 关键词挖掘 / keyword mining | `keyword-miner` |
| 关键词反查 / reverse ASIN | `keyword-reverse` |
| 查流量来源 / traffic source | `traffic-source` |
| 选市场 / market research | `market-research` |

## Call Examples

```json
{
  "scenario": "keyword-reverse",
  "site": "JP",
  "period": "nearly",
  "params": {
    "asin": "B07YRMT36L"
  },
  "export_format": "xlsx"
}
```

```json
{
  "scenario": "keyword-miner",
  "site": "JP",
  "period": "nearly",
  "params": {
    "keyword": "flashlight",
    "filterRootWord": 1,
    "amazonChoice": true
  }
}
```

```json
{
  "scenario": "traffic-source",
  "site": "US",
  "period": "nearly",
  "params": {
    "keyword": "solar outdoor lights"
  }
}
```

```json
{
  "scenario": "market-research",
  "site": "CA",
  "period": "nearly",
  "params": {
    "departmentKeyword": "Baby Diapers",
    "newReleaseNum": 3
  },
  "export_format": "xlsx"
}
```

## Result Handling

For `seller_sprite_run`, read:

- `data.job_id`
- `data.row_count`
- `data.export.filename`
- `data.export.path`
- `data.export.url`
- `data.export.format`

If `success=false`, report `error.message` and do not reuse stale files.

---
name: ops-asin-data-collector
description: Use this skill when Codex users need ASIN inspection data through the current opscli asin-data live-data and fetch-file commands, including real-time basic/listing/BI data, historical SellerSprite keyword files, competitor files, and Rufus files.
version: 0.1.6
---

# ops-asin-data-collector

Codex-facing wrapper for the current ASIN inspection data commands. For AI 巡检取数, only use `opscli asin-data live-data` and `opscli asin-data fetch-file`.

## Hard Command Boundary

Allowed ASIN inspection data commands:

| Need | CLI command | MCP equivalent |
| --- | --- | --- |
| Complete real-time basic data | `opscli asin-data live-data --data-scope basic --upload-xlsx --return-mode ai_ready --pretty` | `asin_data_live_data(data_scope="basic", upload_xlsx=true, return_mode="ai_ready")` |
| Listing interface only | `opscli asin-data live-data --data-scope listing_basic --upload-xlsx --return-mode ai_ready --pretty` | `asin_data_live_data(data_scope="listing_basic", upload_xlsx=true, return_mode="ai_ready")` |
| Real-time BI data | `opscli asin-data live-data --data-scope bi --sales-start <YYYY-MM-DD> --sales-end <YYYY-MM-DD> --upload-xlsx --return-mode ai_ready --pretty` | `asin_data_live_data(data_scope="bi", sales_start=..., sales_end=..., upload_xlsx=true, return_mode="ai_ready")` |
| Real-time basic + BI | `opscli asin-data live-data --data-scope all --sales-start <YYYY-MM-DD> --sales-end <YYYY-MM-DD> --upload-xlsx --return-mode ai_ready --pretty` | `asin_data_live_data(data_scope="all", sales_start=..., sales_end=..., upload_xlsx=true, return_mode="ai_ready")` |
| Historical SellerSprite keyword reverse | `opscli asin-data fetch-file --file keyword_reverse --pretty` | `asin_data_fetch_file(file_key="keyword_reverse")` |
| Historical SellerSprite keyword miner | `opscli asin-data fetch-file --file keyword_miner --pretty` | `asin_data_fetch_file(file_key="keyword_miner")` |
| Historical competitor file | `opscli asin-data fetch-file --file competitor --pretty` | `asin_data_fetch_file(file_key="competitor")` |
| Historical Rufus file | `opscli asin-data fetch-file --file rufus --pretty` | `asin_data_fetch_file(file_key="rufus")` |

Do not use any other `opscli asin-data` data command for ASIN inspection workflows.

## Trigger Scope

Use this Skill when the user asks for any of these:

- ASIN 巡检取数、ASIN 实时基础数据、ASIN 实时 BI 数据
- 单个或批量 ASIN 的刊登基础、爬虫详情、销售流量、SP 搜索词、活动、库存周转数据
- 卖家精灵关键词反查、关键词挖掘、竞品文件、Rufus 文件
- 需要给 AI/Skill 返回 xlsx OSS 地址、数据集索引、字段预览和诊断

Do not use this Skill for final report writing, Listing 文案改写、价格/库存/广告修改，or any operation that changes remote business data.

## Codex Workflow

1. Read `references/codex-usage.md` and `docs/guide/ASIN巡检AI取数命令操作手册.md` before constructing commands.
2. Confirm exactly one input source:
   - file mode: `--input <csv|xlsx|json|jsonl>`
   - single mode: `--asin <ASIN>`
3. For real-time basic/listing/BI data, use `live-data` with `--upload-xlsx --return-mode ai_ready --pretty`.
4. For BI data, always pass `--sales-start <YYYY-MM-DD> --sales-end <YYYY-MM-DD>`.
5. For SellerSprite/Rufus historical files, use `fetch-file`.
6. Prefer batch file mode over looping single ASIN commands.
7. If any `opscli` command or MCP tool fails, immediately submit `ops-feedback` according to project rules, then continue where possible.

## Quick Start

Complete real-time basic data:

```bash
opscli asin-data live-data \
  --asin B0GJDPXFC9 \
  --site US \
  --data-scope basic \
  --upload-xlsx \
  --return-mode ai_ready \
  --pretty
```

Listing interface only:

```bash
opscli asin-data live-data \
  --asin B0GJDPXFC9 \
  --site US \
  --data-scope listing_basic \
  --upload-xlsx \
  --return-mode ai_ready \
  --pretty
```

Real-time BI data:

```bash
opscli asin-data live-data \
  --asin B0GJDPXFC9 \
  --site US \
  --data-scope bi \
  --sales-start 2026-07-01 \
  --sales-end 2026-07-08 \
  --upload-xlsx \
  --return-mode ai_ready \
  --pretty
```

Historical Rufus file:

```bash
opscli asin-data fetch-file \
  --asin B0GJDPXFC9 \
  --site US \
  --file rufus \
  --pretty
```

## Output Contract

For `live-data --return-mode ai_ready`, read output in this order:

1. `success == true`.
2. `data.metadata.protocol == "asin_data_ai_response"`.
3. `data.items[].artifacts[].uri` for xlsx URLs.
4. `data.items[].datasets[]` for `source_key`, row counts, columns, preview rows, and quality flags.
5. `data.items[].diagnostics[]` and `data.diagnostics[]` before making conclusions.

For `fetch-file`, read output in this order:

1. `success == true`.
2. `data.file_url` for historical file URL.
3. `data.content`; xlsx files are `{sheet_name: rows}`, Rufus is Markdown text.

## Data Quality Checks

- For `basic`, verify crawler-derived ASIN fields before using `product_detail`, `image_links`, or `reviews`.
- Prefer `listing_basic` for listing facts such as title, brand, category, price, and image fields.
- For `bi`, treat `EMPTY_DATASET` as no-data rather than command failure.
- For `sp_search_term`, if diagnostics include `ASIN_FILTER_UNVERIFIED`, do not make strong single-ASIN conclusions.
- If `items[].status != "success"` or any diagnostic has `level="error"`, treat the result as failed or partial.

## Installation Note

For a Codex runtime that has not installed this Skill, install or upgrade from the current package/template:

```bash
opscli skills install --yes --runtime all
opscli skills upgrade
```

If local `opscli asin-data live-data` is unavailable, install the latest test package first:

```bash
python -m pip install -i https://test.pypi.org/simple/ --upgrade aukeys-opscli
```

## References

- Command protocol guide: `docs/guide/ASIN巡检AI取数命令操作手册.md`
- Codex usage guide: `references/codex-usage.md`

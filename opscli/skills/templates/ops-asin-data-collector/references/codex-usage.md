# Codex Usage Guide

This guide tells Codex how to use the current ASIN inspection data commands. The command protocol is documented in `docs/guide/ASIN巡检AI取数命令操作手册.md`.

## Command Boundary

Only two ASIN data commands are allowed for AI inspection workflows:

```bash
opscli asin-data live-data
opscli asin-data fetch-file
```

Do not use other `opscli asin-data` data commands for this workflow.

## Current Command Matrix

| Need | CLI command | MCP equivalent |
| --- | --- | --- |
| Complete real-time basic data | `opscli asin-data live-data --data-scope basic --upload-xlsx --return-mode ai_ready --pretty` | `asin_data_live_data(data_scope="basic", upload_xlsx=true, return_mode="ai_ready")` |
| Listing interface only | `opscli asin-data live-data --data-scope listing_basic --upload-xlsx --return-mode ai_ready --pretty` | `asin_data_live_data(data_scope="listing_basic", upload_xlsx=true, return_mode="ai_ready")` |
| Real-time BI data | `opscli asin-data live-data --data-scope bi --sales-start <YYYY-MM-DD> --sales-end <YYYY-MM-DD> --upload-xlsx --return-mode ai_ready --pretty` | `asin_data_live_data(data_scope="bi", sales_start=..., sales_end=..., upload_xlsx=true, return_mode="ai_ready")` |
| Real-time basic + BI | `opscli asin-data live-data --data-scope all --sales-start <YYYY-MM-DD> --sales-end <YYYY-MM-DD> --upload-xlsx --return-mode ai_ready --pretty` | `asin_data_live_data(data_scope="all", sales_start=..., sales_end=..., upload_xlsx=true, return_mode="ai_ready")` |
| SellerSprite keyword reverse | `opscli asin-data fetch-file --file keyword_reverse --pretty` | `asin_data_fetch_file(file_key="keyword_reverse")` |
| SellerSprite keyword miner | `opscli asin-data fetch-file --file keyword_miner --pretty` | `asin_data_fetch_file(file_key="keyword_miner")` |
| Competitor file | `opscli asin-data fetch-file --file competitor --pretty` | `asin_data_fetch_file(file_key="competitor")` |
| Rufus file | `opscli asin-data fetch-file --file rufus --pretty` | `asin_data_fetch_file(file_key="rufus")` |

For AI usage, always set `--return-mode ai_ready --upload-xlsx` on CLI `live-data`. MCP `asin_data_live_data` defaults to `ai_ready`, but passing it explicitly is still preferred.

## Input Modes

Use exactly one input mode.

### File Mode

Use this for batch ASINs:

```bash
opscli asin-data live-data \
  --input ./asins.csv \
  --asin-column asin \
  --site-column site \
  --data-scope bi \
  --sales-start 2026-07-01 \
  --sales-end 2026-07-08 \
  --upload-xlsx \
  --return-mode ai_ready \
  --pretty
```

Recommended columns:

| Column | Required | Notes |
| --- | --- | --- |
| `asin` | yes | 10-character Amazon ASIN |
| `site` | no | Marketplace, defaults to `US` |

### Single-ASIN Mode

Use this when the user provides one ASIN:

```bash
opscli asin-data live-data \
  --asin B0GJDPXFC9 \
  --site US \
  --data-scope basic \
  --upload-xlsx \
  --return-mode ai_ready \
  --pretty
```

## Data Scope

| Scope | Behavior |
| --- | --- |
| `basic` | Fetches `listing_basic` + `crawler_details`; returns/uploads only `basic` xlsx. |
| `listing_basic` | Fetches only `listing_basic`; returns/uploads only `basic` xlsx. |
| `bi` | Fetches `sales_traffic`, `sp_search_term`, `deals`, `turnover_inventory`; returns/uploads only `bi` xlsx. |
| `all` | Fetches complete basic and BI data; returns/uploads both `basic` and `bi` xlsx. |

## Historical Files

SellerSprite and Rufus use `fetch-file`:

```bash
opscli asin-data fetch-file --asin B0GJDPXFC9 --site US --file keyword_reverse --pretty
opscli asin-data fetch-file --asin B0GJDPXFC9 --site US --file keyword_miner --pretty
opscli asin-data fetch-file --asin B0GJDPXFC9 --site US --file competitor --pretty
opscli asin-data fetch-file --asin B0GJDPXFC9 --site US --file rufus --pretty
```

## Output Contract

`live-data --return-mode ai_ready` returns:

| Field | Meaning |
| --- | --- |
| `success` | CLI wrapper success flag |
| `data.metadata.protocol` | Must be `asin_data_ai_response` |
| `data.items[].artifacts[]` | xlsx artifact index with `file_key`, `uri`, `local_path`, `complete` |
| `data.items[].datasets[]` | dataset manifest with `source_key`, sheet name, row/column counts, columns, preview rows, quality flags |
| `data.items[].diagnostics[]` | ASIN-level warnings/errors |
| `data.diagnostics[]` | global warnings/errors |
| `data.split_file_urls` | legacy URL map; read only as compatibility fallback |

`fetch-file` returns:

| Field | Meaning |
| --- | --- |
| `success` | CLI wrapper success flag |
| `data.asin` | ASIN |
| `data.site` | marketplace |
| `data.file_key` | requested file type |
| `data.file_url` | historical file URL, string or array |
| `data.content` | xlsx as `{sheet_name: rows}`; Rufus as Markdown text |

## Data Quality Checks

Before using real-time `basic` crawler-derived fields:

1. Compare requested ASIN with crawler ASIN fields.
2. If product links contain a different ASIN, treat `product_detail`, `image_links`, and `reviews` as suspect.
3. Prefer `listing_basic` fields for listing facts.

BI row counts should be checked by `source_key`. `sp_search_term` may contain ASIN-group-level data; if diagnostics include `ASIN_FILTER_UNVERIFIED`, do not make single-ASIN conclusions without explicit verification.

## Failure Handling

If any `opscli` command fails, immediately submit structured feedback through `ops-feedback` in the same session. Include command, call params, original error code/message, inferred reason, and next fix suggestion.

MCP failures may include a `feedback` draft. The AI Agent must still submit the feedback according to project rules.

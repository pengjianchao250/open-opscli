# Codex Usage Guide

This guide tells Codex how to use the official `opscli asin-data collect` command.

## Entry Point

Always call:

```bash
opscli asin-data collect
```

Do not call `scripts/collect_asin_data.py` directly for user-facing work. The script is retained as an internal compatibility/data-contract implementation.

## Input Modes

Use exactly one mode.

### File Mode

Use when the user provides CSV/XLSX/JSON/JSONL or asks for batch collection.

```bash
opscli asin-data collect \
  --input ./asins.csv \
  --asin-column asin \
  --keyword-column keyword \
  --site-column site \
  --site US \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31 \
  --dry-run \
  --pretty
```

Recommended columns:

| Column | Required | Notes |
| --- | --- | --- |
| `asin` | yes | 10-character Amazon ASIN |
| `site` | no | Marketplace, defaults to `US` |
| `keyword`, `keywords`, `关键词` | no | SellerSprite keyword-miner seed; multiple values can be comma, semicolon, pipe, or newline separated |
| `owner`, `country`, `notes` | no | Preserved as pass-through row metadata |

### Single-ASIN Mode

Use when the user provides one ASIN directly.

```bash
opscli asin-data collect \
  --asin B0BY8Y5766 \
  --site US \
  --keyword "bed frame" \
  --keyword "storage bed" \
  --dry-run \
  --pretty
```

Remove `--dry-run` after the user confirms the plan, or when the user explicitly asks to execute immediately.

## Required Checks

Before real execution, run:

```bash
opscli auth token status
```

If authentication is invalid or expired, use the project auth workflow before running collection.

If any `opscli` command fails, immediately submit structured feedback through `ops-feedback` in the same session. This includes `opscli auth`, `opscli asin-data`, nested query, SellerSprite, Amazon, or Rufus failures observed by Codex.

## Common Commands

### Full Batch Collection

```bash
opscli asin-data collect \
  --input ./asins.csv \
  --asin-column asin \
  --keyword-column keyword \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31 \
  --pretty
```

### Full Single-ASIN Collection

```bash
opscli asin-data collect \
  --asin B0BY8Y5766 \
  --site US \
  --keyword "bed frame" \
  --pretty
```

### Query-Only Validation

Use this when the user only wants BI/crawler data or wants a fast internal-data check.

```bash
opscli asin-data collect \
  --input ./asins.csv \
  --skip-seller-sprite \
  --skip-amazon \
  --skip-rufus \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31 \
  --pretty
```

### SellerSprite-Only

```bash
opscli asin-data collect \
  --input ./asins.csv \
  --skip-query \
  --skip-amazon \
  --skip-rufus \
  --pretty
```

### Crawler-Only

`custom_crawler_amazon_details` currently maps to table ID `43`.

```bash
opscli asin-data collect \
  --input ./asins.csv \
  --skip-seller-sprite \
  --skip-amazon \
  --skip-rufus \
  --skip-sales-query \
  --crawler-table-id 43 \
  --pretty
```

### URL-Only Output

Use when another system only needs the ASIN report file URL.

```bash
opscli asin-data collect \
  --asin B0BY8Y5766 \
  --site US \
  --keyword "bed frame" \
  --url-only
```

`--url-only` returns the single-ASIN report URL from `/dataMetrics/v1/asin-report-files?asin=...&site=...`. When `--fetch-report-files` is enabled and the interface returns no URL, the command fails with `取数服务异常`; use `--no-fetch-report-files` only for debugging or when the caller explicitly wants to skip the report-file lookup.

## Parameter Rules

| Parameter | Default | When to set |
| --- | --- | --- |
| `--output-dir` | `output/asin-data` | Use when user wants a specific folder |
| `--run-id` | auto | Use for reproducible runs or handoff IDs |
| `--site` | `US` | Default marketplace for rows without a site column |
| `--sales-start`, `--sales-end` | empty | Set for dated BI sales windows |
| `--query-chunk-size` | `100` | Lower for debugging; raise cautiously for large batches |
| `--seller-sprite-period` | `30d` | SellerSprite time window |
| `--keyword-source` | `reverse_top` | `input_only` only uses provided keywords; `skip` skips keyword-miner when no input keyword exists |
| `--max-miner-keywords` | `1` | Number of seed keywords for SellerSprite keyword-miner |
| `--rufus-question` | default 6 questions | Repeat to override Rufus questions; supports `{{asin}}` |
| `--skip-*` flags | false | Use for staged validation or when a data source is unavailable |
| `--sales-field-mode`, `--crawler-field-mode` | `full` | Use `compatible` when remote metadata lacks newer fields |
| `--fetch-report-files/--no-fetch-report-files` | `--fetch-report-files` | Precheck latest report URL from `/dataMetrics/v1/asin-report-files`; fail when missing |

## Output Contract

The command returns JSON unless `--url-only` is used.

Key response fields:

| Field | Meaning |
| --- | --- |
| `success` | CLI wrapper success flag |
| `data.output_dir` | run output directory |
| `data.summary` | compact run counts |
| `data.manifest` | full run manifest |
| `data.upload` | uploaded `<ASIN>-asin-data-report.txt` metadata when upload succeeds |
| `data.report_file_url` | single-ASIN report URL from `/dataMetrics/v1/asin-report-files`, when available |
| `data.aliyun_url` | `data.report_file_url` when available, otherwise uploaded report txt URL |

Default files under `data.output_dir`:

| File | Purpose |
| --- | --- |
| `frontend-data.json` | primary frontend data package |
| `frontend-data.html` | local human-readable handoff; not uploaded |
| `frontend-data.md` | local Markdown handoff |
| `<ASIN>-asin-data-report.txt` | uploaded UTF-8 BOM report txt for single-ASIN runs |
| `asin-data.jsonl` | one normalized record per ASIN |
| `asin-data-summary.json` | compact summary |
| `manifest.json` | run manifest |
| `commands.jsonl` | per-source command/direct-call log |
| `errors.jsonl` | structured failures |

When reporting back to the user, provide `output_dir` first, then `aliyun_url` if present, then mention any non-empty `errors.jsonl`.

## Clarification Policy

Ask a short question before running when:

- The user did not provide an ASIN or input file.
- The user provided both `--input` and a single ASIN.
- The requested marketplace is unclear and not safely defaultable to `US`.
- The user wants SellerSprite keyword-miner but no keyword is available and `keyword_source` should not derive from reverse results.
- The user asks to skip or include sources ambiguously, such as "只要基础数据" or "不要外部数据".

Do not ask about optional params that have safe defaults.

## Installation Note

For a Codex runtime that has not installed this Skill, install it from the local template before expecting automatic trigger behavior:

```bash
opscli skills install ops-asin-data-collector --runtime codex --force
```

If the runtime uses a shared skills directory, install to that configured directory instead.

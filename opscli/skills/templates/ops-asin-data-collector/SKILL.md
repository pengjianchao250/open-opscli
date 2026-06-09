---
name: ops-asin-data-collector
description: Collects batch ASIN data from SellerSprite, Amazon scrape, crawler datasets, and BI sales datasets through official opscli commands. Use when operations users need to fetch SellerSprite keyword reverse/miner/listing-analysis data, Amazon listing snapshots, BI sales data, crawler listing data, or frontend-facing ASIN data packages for one or more ASINs from CSV/XLSX/JSON/JSONL inputs.
version: 0.1.2
---

# ops-asin-data-collector

Batch data collection wrapper for operations Codex users. It reads an ASIN input file, plans or executes existing `opscli` commands, and writes a unified per-ASIN data package.

## Quick Start

Dry-run first:

```bash
python opscli/skills/templates/ops-asin-data-collector/scripts/collect_asin_data.py \
  --input ./asins.csv \
  --asin-column asin \
  --keyword-column keyword \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31 \
  --dry-run
```

Execute after reviewing the plan:

```bash
python opscli/skills/templates/ops-asin-data-collector/scripts/collect_asin_data.py \
  --input ./asins.csv \
  --asin-column asin \
  --keyword-column keyword \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31
```

## Workflow

1. Read the input file with `scripts/parse_asin_input.py`.
2. Normalize ASINs, site, one-or-more keywords, and source row metadata.
3. Run BI sales and crawler dataset queries in ASIN chunks through `opscli query simple`.
4. For each ASIN, run SellerSprite `keyword-reverse`; run `keyword-miner` only when a keyword is available or derived.
5. For each ASIN, run SellerSprite `listing-analysis` and attach the complete AI task `content`.
6. For each ASIN, run `opscli amazon scrape` unless skipped.
7. Run Amazon Rufus questions for each ASIN through `opscli amazon-rufus get-backend`, unless skipped.
8. Build frontend-facing Chinese sections: `基础数据`, `卖家精灵关键词数据`, `卖家精灵AI全景分析数据`, `Rufus优化建议数据`.
8. Write `manifest.json`, `asin-data.jsonl`, `frontend-data.json`, `frontend-data.md`, `asin-data-summary.json`, `commands.jsonl`, and `errors.jsonl`.

## Boundaries

- Do not call SellerSprite, Amazon, BI, crawler, or ops backend HTTP APIs directly.
- Use only official `opscli` entry points.
- Use `--payload` files for `opscli query simple`; avoid inline `--json` on Windows PowerShell.
- If any `opscli` command fails during an agent-run task, immediately submit `ops-feedback` according to project rules.
- This Skill collects data only. It does not generate final reports, edit listing content, change prices, modify images, or operate ads/campaigns.
- Use `--skip-sales-query`, `--skip-crawler-query`, `--skip-seller-sprite`, `--skip-listing-analysis`, and `--skip-amazon` for staged verification.
- Use `--skip-rufus` to skip Amazon Rufus. Rufus collection uses official `opscli amazon-rufus` commands only and reads only the report path returned by the current command.

## Inputs

Supported file formats: CSV, XLSX, JSON, JSONL.

Recommended columns:

| Column | Required | Purpose |
| --- | --- | --- |
| `asin` | yes | Amazon ASIN |
| `site` | no | Marketplace, default `US` |
| `keyword` / `keywords` / `关键词` | no | SellerSprite keyword-miner seed. Multiple keywords in one cell may be separated by comma, semicolon, pipe, or newline. |
| `country` | no | Pass-through metadata |
| `owner` | no | Pass-through metadata |
| `notes` | no | Pass-through metadata |

## Outputs

Default output directory:

```text
output/asin-data/<run_id>/
```

Main files:

- `manifest.json`: run parameters and summary.
- `asin-data.jsonl`: one normalized record per ASIN, including `frontend_data`.
- `frontend-data.json`: aggregate frontend-friendly JSON with Chinese section names.
- `frontend-data.md`: Markdown handoff for frontend consumers.
- `asin-data-summary.json`: compact success/error counts.
- `commands.jsonl`: command plan and execution status.
- `errors.jsonl`: structured per-source errors.
- Query payload/result files are chunked when `--query-chunk-size` is smaller than the input ASIN count.
- Input keywords are preserved in `input.keywords`, `frontend_data.基础数据.输入关键词列表`, and `frontend_data.卖家精灵关键词数据.关键词输入`.
- Rufus answers are preserved in `rufus.answers` and `frontend_data.Rufus优化建议数据.数据`.

## References

- Data contract: `references/data-contract.md`
- Source mapping: `references/source-mapping.md`
- Execution policy: `references/execution-policy.md`
- Usage guide: `docs/guide/ASIN批量取数服务使用说明.md`

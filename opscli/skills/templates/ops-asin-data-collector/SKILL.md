---
name: ops-asin-data-collector
description: Collects batch ASIN data from SellerSprite, Amazon scrape, crawler datasets, BI sales datasets, and Rufus through the official opscli asin-data command. Use when operations users need to fetch SellerSprite keyword reverse/miner/listing-analysis data, Amazon listing snapshots, BI sales data, crawler listing data, Rufus optimization suggestions, or frontend-facing ASIN data packages for one or more ASINs from CSV/XLSX/JSON/JSONL inputs.
version: 0.1.2
---

# ops-asin-data-collector

Batch data collection wrapper for operations Codex users. It reads an ASIN input file, executes the first-class `opscli asin-data collect` command, and writes a unified per-ASIN data package. The command calls SellerSprite, Query, Amazon, and Rufus Python service managers directly instead of shelling out to nested `opscli` commands.

## Quick Start

Dry-run first:

```bash
opscli asin-data collect \
  --input ./asins.csv \
  --asin-column asin \
  --keyword-column keyword \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31 \
  --dry-run
```

Single ASIN:

```bash
opscli asin-data collect \
  --asin B0BY8Y5766 \
  --site US \
  --keyword "bed frame"
```

Execute after reviewing the plan:

```bash
opscli asin-data collect \
  --input ./asins.csv \
  --asin-column asin \
  --keyword-column keyword \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31
```

## Workflow

1. Read the input file with `scripts/parse_asin_input.py`.
2. Normalize ASINs, site, one-or-more keywords, and source row metadata.
3. Run BI sales and crawler dataset queries in ASIN chunks through `QueryManager`.
4. For each ASIN, call SellerSprite `keyword-reverse`; call `keyword-miner` only when a keyword is available or derived.
5. For each ASIN, call SellerSprite `listing-analysis` and attach the complete AI task `content`.
6. For each ASIN, call `AmazonManager.scrape_product` unless skipped.
7. Run Amazon Rufus questions for each ASIN through `RufusManager.get_backend`, unless skipped.
8. Build frontend-facing Chinese sections: `基础数据`, `卖家精灵关键词数据`, `卖家精灵AI全景分析数据`, `Rufus优化建议数据`.
8. Write `manifest.json`, `asin-data.jsonl`, `frontend-data.json`, `frontend-data.md`, `asin-data-summary.json`, `commands.jsonl`, and `errors.jsonl`.

## Boundaries

- Use `opscli asin-data collect` as the stable entry point.
- Do not wrap SellerSprite, Query, Amazon, or Rufus by invoking nested CLI subprocesses from the collector; use the corresponding Python managers directly.
- The legacy `scripts/collect_asin_data.py` remains only as the data-contract implementation source reused by the command.
- If any `opscli` command fails during an agent-run task, immediately submit `ops-feedback` according to project rules.
- This Skill collects data only. It does not generate final reports, edit listing content, change prices, modify images, or operate ads/campaigns.
- Use `--skip-sales-query`, `--skip-crawler-query`, `--skip-seller-sprite`, `--skip-listing-analysis`, and `--skip-amazon` for staged verification.
- Use `--skip-rufus` to skip Amazon Rufus. Rufus collection uses the official Rufus service package and writes the same Markdown report path expected by the frontend data contract.

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
- `frontend-data.txt`: upload copy with the same Markdown content. The shared file upload endpoint rejects `.md`, so `--upload` / `--url-only` returns the `.txt` OSS URL.
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

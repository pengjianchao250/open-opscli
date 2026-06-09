---
name: ops-asin-data-collector
description: Use this skill when Codex users need to run opscli asin-data collect for ASIN batch data collection, single-ASIN collection, SellerSprite keyword reverse/miner/listing-analysis data, Amazon listing snapshots, BI sales data, crawler listing data, Rufus optimization suggestions, or frontend-facing ASIN data packages from CSV/XLSX/JSON/JSONL inputs.
version: 0.1.3
---

# ops-asin-data-collector

Codex-facing wrapper for the official `opscli asin-data collect` command. Use it to collect one or more ASINs into a unified data package containing SellerSprite, Amazon scrape, BI sales, crawler Listing, Rufus, and frontend-facing outputs.

## Trigger Scope

Use this Skill when the user asks for any of these:

- ASIN 批量取数、ASIN 数据包、ASIN 采集、Listing 数据采集
- 单个 ASIN 的卖家精灵、Amazon 页面、BI 销售、爬虫 Listing 或 Rufus 数据
- 生成前端可读的 `frontend-data.json`，并保留本地预览用 `frontend-data.html`
- 通过 Codex 调用 `opscli asin-data collect`

Do not use this Skill for final report writing, Listing 文案改写、价格/库存/广告修改，or any operation that changes remote business data.

## Codex Workflow

1. Read `references/codex-usage.md` before constructing the command.
2. Confirm exactly one input source:
   - file mode: `--input <csv|xlsx|json|jsonl>`
   - single mode: `--asin <ASIN>` with optional repeated `--keyword`
3. For real collection, first check auth with `opscli auth token status`.
4. Run `opscli asin-data collect ... --dry-run --pretty` unless the user explicitly asks to execute immediately.
5. After dry-run review, run the same command without `--dry-run`.
6. Return the `output_dir`, `frontend-data.json`, `frontend-data.html`, `frontend-data.md`, and JSON `aliyun_url` when present.
7. If any `opscli` command fails, immediately submit `ops-feedback` according to project rules, then continue with the user task where possible.

## Quick Start

Dry-run first:

```bash
opscli asin-data collect \
  --input ./asins.csv \
  --asin-column asin \
  --keyword-column keyword \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31 \
  --dry-run \
  --pretty
```

Single ASIN:

```bash
opscli asin-data collect \
  --asin B0BY8Y5766 \
  --site US \
  --keyword "bed frame" \
  --pretty
```

Execute after reviewing the plan:

```bash
opscli asin-data collect \
  --input ./asins.csv \
  --asin-column asin \
  --keyword-column keyword \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31 \
  --pretty
```

## Workflow

1. Read the input file or single ASIN arguments.
2. Normalize ASINs, site, one-or-more keywords, and source row metadata.
3. Run BI sales and crawler dataset queries in ASIN chunks through `QueryManager`.
4. For each ASIN, call SellerSprite `keyword-reverse`; call `keyword-miner` only when a keyword is available or derived.
5. For each ASIN, call SellerSprite `listing-analysis` and attach the complete AI task `content`.
6. For each ASIN, call `AmazonManager.scrape_product` unless skipped.
7. Run Amazon Rufus questions for each ASIN through `RufusManager.get_backend`, unless skipped.
8. Build frontend-facing Chinese sections: `基础数据`, `卖家精灵关键词数据`, `卖家精灵AI全景分析数据`, `Rufus优化建议数据`.
9. Write `manifest.json`, `asin-data.jsonl`, `frontend-data.json`, `frontend-data.html`, `frontend-data.md`, `asin-data-summary.json`, `commands.jsonl`, and `errors.jsonl`.

## Boundaries

- Use `opscli asin-data collect` as the stable entry point.
- Do not wrap SellerSprite, Query, Amazon, or Rufus by invoking nested CLI subprocesses from the collector; use the corresponding Python managers directly.
- The legacy `scripts/collect_asin_data.py` remains only as the data-contract implementation source reused by the command; Codex users should call the CLI command.
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
- `frontend-data.html`: local human-readable HTML handoff; upload is not used because the file service rejects html.
- `--upload` / `--url-only`: uploads `frontend-data.json` and returns this OSS URL.
- `frontend-data.md`: local Markdown handoff for operators.
- `asin-data-summary.json`: compact success/error counts.
- `commands.jsonl`: command plan and execution status.
- `errors.jsonl`: structured per-source errors.
- Query payload/result files are chunked when `--query-chunk-size` is smaller than the input ASIN count.
- Input keywords are preserved in `input.keywords`, `frontend_data.基础数据.输入关键词列表`, and `frontend_data.卖家精灵关键词数据.关键词输入`.
- Rufus answers are preserved in `rufus.answers` and `frontend_data.Rufus优化建议数据.数据`.

## References

- Codex usage guide: `references/codex-usage.md`
- Data contract: `references/data-contract.md`
- Source mapping: `references/source-mapping.md`
- Execution policy: `references/execution-policy.md`
- Usage guide: `docs/guide/ASIN批量取数服务使用说明.md`

# Execution Policy

## Recommended Order

1. Parse and validate input.
2. Build command plan.
3. Run `--dry-run` for operator review.
4. Execute query sources in ASIN batches.
5. Execute SellerSprite per ASIN with low concurrency.
6. Execute Amazon scrape per ASIN.
7. Merge and write output files.

## Concurrency

This MVP script executes sequentially for predictable logs. Increase parallelism only after stable production runs.

Recommended future limits:

| Source | Suggested limit |
| --- | --- |
| Query datasets | batch size 50-200 ASINs |
| SellerSprite | 1-2 concurrent jobs |
| Amazon scrape | 2-3 concurrent jobs |

## Query Rules

- Use `opscli query simple --payload <file> --run`.
- Do not use inline `--json` on Windows PowerShell.
- Validate metadata before relying on dataset fields.
- Use `--query-chunk-size` to split BI and crawler queries by ASIN count.
- Formula fields must not receive extra normal aggregation.
- For every query execution, submit `ops-feedback` according to the query feedback rule.

## Failure Handling

- Per-source failures do not stop the entire run unless input parsing fails.
- Every failed source writes an item to `errors.jsonl`.
- Every command attempt writes an item to `commands.jsonl`.
- If a Codex agent observes an `opscli` command failure, it must submit `ops-feedback` immediately in the same session.

## Safe Defaults

- Use `--dry-run` first.
- Use fake or small ASIN samples before large batches.
- Skip expensive or unstable sources with `--skip-seller-sprite`, `--skip-amazon`, `--skip-sales-query`, `--skip-crawler-query`, or `--skip-query`.

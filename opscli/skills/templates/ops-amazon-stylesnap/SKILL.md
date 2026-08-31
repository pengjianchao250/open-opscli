---
name: ops-amazon-stylesnap
description: "Use Chrome control to process one or more Amazon ASINs serially: read each product title, ASIN, and first product image, upload each image to Amazon StyleSnap for visual search, extract all visible results, and save structured JSON. Use for low-frequency, human-supervised competitor image searches; stop the batch for login, CAPTCHA, robot checks, region verification, or other anti-bot states."
---

# Amazon StyleSnap Reverse Image Search

## Scope

Run a supervised ASIN workflow by reusing the operator's local Chrome session. The input may contain one or more ASINs. Process multiple ASINs serially, one at a time, read each Amazon product page, upload its primary image to StyleSnap, collect visible result cards, and write traceable JSON files. Do not parallelize, use standalone Playwright, read browser credentials, or bypass Amazon controls.

Use for one-off or low-frequency US Amazon product-image searches. Do not use for bulk crawling, background HTTP requests, private API reverse engineering, CAPTCHA bypass, proxy rotation, or load testing.

## Preconditions

1. Prefer the Chrome control capability and connect to the operator's existing Chrome. Do not create a new browser profile.
2. Confirm that Chrome can open `https://www.amazon.com/` and `https://www.amazon.com/stylesnap`.
3. Ask the operator to complete Amazon/StyleSnap login, region selection, and CAPTCHA handling. Never read, export, print, or persist cookies, passwords, tokens, Local Storage, or Session Storage.
4. Accept one ASIN or a user-provided list of ASINs/product URLs. Normalize each value by removing whitespace and uppercasing; require `^[A-Z0-9]{10}$`. When given a product URL, extract the ASIN from `/dp/` or `/gp/product/`. Remove duplicate ASINs while preserving input order.
5. The user's explicit request to run this Skill authorizes uploading the first successfully identified image for every valid input ASIN. Do not ask for a separate confirmation before each upload. If the user has not clearly authorized the run, ask once before starting the batch.

If Chrome control is unavailable, use the Codex App in-app browser as a fallback. If neither browser surface is available, stop and explain that the required browser capability must be enabled; do not substitute standalone Playwright.

## Workflow

### 1. Read each Amazon source product

1. Process ASINs in input order. Open `https://www.amazon.com/dp/<ASIN>` for the current item.
2. Wait for the page to settle. Check for login, CAPTCHA, robot check, region verification, or an error page. Pause for the operator if any appears.
3. Read the title from the visible product title; use structured page data `name` only as a fallback.
4. Read the first primary gallery image. Prefer `data-old-hires`, then the largest URL from `data-a-dynamic-image`, then `src`. Do not choose ads, recommendations, or thumbnail-only images.
5. Record `source.url`, `source.asin`, `source.title`, and `source.image_url`. If the primary image cannot be identified reliably, mark this ASIN as failed and continue to the next ASIN only if no batch-level stop condition has appeared.

### 2. Upload each image to StyleSnap

1. For a user-authorized run, proceed without an additional per-ASIN confirmation once a reliable primary image is found.
2. Open `https://www.amazon.com/stylesnap` and check for login or anti-bot states.
3. Click the visible `Upload a Photo` button first and verify that the browser file chooser opens. Only then set the source image on the chooser. Do not set `input[type=file]` directly without the preceding visible click: StyleSnap may leave the page unchanged. If the page only supports drop, use the browser's visible interaction. Do not inject scripts to bypass the chooser or call hidden upload APIs.
4. Wait for results. Use only a small, observable amount of scrolling to trigger lazy loading. Do not rapidly refresh or open parallel StyleSnap searches.
5. If CAPTCHA, login, an error, rate-limit notice, or abnormal page state appears, stop the entire batch and report the state while leaving the page available for operator takeover. An explicit normal empty result is recorded for the current ASIN and does not by itself stop the batch.

### 3. Extract result cards

Use the visible DOM/HTML as the primary source. Target `.similar-styles article.cellContainer` cards and extract:

- `rank`, `asin`, `title` (the visible brand/display name), `image_url`, and `product_url`.
- `colors_or_patterns`: visible text such as `+5 colors/patterns`.
- `rating`: numeric star rating, when present.
- `review_count`: numeric review count, when present.
- `currency`: currency symbol or code from the price markup.
- `current_price`: current price as a decimal number, combining the whole and fraction spans.
- `original_price`: crossed-out/list price when present; otherwise `null`.
- `raw_card_text`: normalized visible card text for audit and future parser improvements.

Extract ASIN from `/dp/<ASIN>`, `/gp/product/<ASIN>`, or `data-csa-c-item-id` when possible; otherwise use `null`. Normalize known product URLs to `https://www.amazon.com/dp/<ASIN>`.

Deduplicate by ASIN first. For results without ASIN, deduplicate by `product_url + title + image_url`. Keep the first occurrence and never guess a missing ASIN.

## Output

Create one run directory for every invocation, including a single-ASIN invocation:

```text
output/ops-amazon-stylesnap/runs/<YYYYMMDD-HHmmss>/
  summary.json
  items/<ASIN>/
    results.json
    source-image.<ext>
```

Use the local start time as the run ID in exact `YYYYMMDD-HHmmss` format. Write no runtime artifact outside this canonical root. Always write `summary.json` with the input order, per-ASIN status, result count, result and source-image paths, and any batch stop reason. For every valid ASIN, write `items/<ASIN>/results.json`; when a local copy is needed for upload, keep the original image format when possible and write it as `items/<ASIN>/source-image.<ext>`.

Store file paths in JSON relative to the run directory, for example `items/B0XXXXXXXX/results.json` and `items/B0XXXXXXXX/source-image.jpg`. Never store absolute paths. Files created in browser-managed temporary asset directories are staging files only: copy the selected image into the run directory before writing JSON, and do not reference the temporary path in final output.

```json
{
  "source": {
    "asin": "B0XXXXXXXX",
    "url": "https://www.amazon.com/dp/B0XXXXXXXX",
    "title": "Product title",
    "image_url": "https://...",
    "local_image": "items/B0XXXXXXXX/source-image.jpg"
  },
  "results": [],
  "meta": {
    "query_time": "2026-08-12T10:00:00+08:00",
    "result_count": 0,
    "browser": "chrome",
    "source_page": "https://www.amazon.com/stylesnap"
  }
}
```

The result page may expose only a brand/display name instead of the full product title. Preserve that value as `title` and set `title_is_display_name: true` in `meta`; do not open every result page just to expand titles during a low-frequency run.

Extraction priority is: visible DOM/HTML, structured page data already rendered in the page, then screenshot for visual verification only. The Chrome control surface does not provide a supported network-response listener for this workflow, so do not depend on intercepting private API responses. Screenshots are not the primary data source because they cannot reliably provide ASINs, links, exact prices, or review counts.

Use UTF-8 valid JSON. Represent unknown fields as `null`; never invent values. A zero-result search is a successful empty array with `result_count: 0`.

## Safety and Stop Conditions

- Multiple ASINs are allowed only when explicitly supplied by the user. Process them serially with a deliberate pause between items; never use concurrency, scheduled runs, or automatic retries on anti-bot pages.
- If a batch-level anti-bot or rate-limit condition appears, stop immediately and leave unprocessed ASINs listed as `not_started` in `summary.json`.
- Stop immediately on CAPTCHA, `robot check`, login, region verification, abnormal redirect, rate-limit notice, or page error. Wait for operator action.
- Do not refresh CAPTCHA pages, switch accounts, rotate proxies, spoof fingerprints, or call undocumented endpoints.
- For ordinary loading/network failure, wait once and retry once. Stop after the second failure while preserving source data already collected.
- Never write account information, order data, addresses, cookies, tokens, or authentication material to JSON, logs, or the response.

## Completion Report

Report the ASIN, source title, whether the primary image was found, StyleSnap result count, relative JSON path, and whether manual takeover occurred. Do not output image binaries, cookies, tokens, or browser-sensitive data.

For a failure, report the last completed step and a recoverable action, such as: `Source image found; waiting for the operator to handle the StyleSnap verification page.`

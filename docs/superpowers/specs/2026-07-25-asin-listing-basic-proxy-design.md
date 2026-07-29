# ASIN Listing Basic Proxy Design

Date: 2026-07-25
Status: Confirmed for specification review
Base branch: `master`
Feature branch: `codex/asin-data-listing-basic-proxy`

## Goal

Replace the direct BI listing requests used by `opscli asin-data basic` with the OPS Amazon listing basic proxy while preserving the existing `listing_basic` response contract.

## Upstream Contract

Endpoint:

```text
POST {ops_system_url}/api/v1/data-metrics/amazon-listing/basic
```

Request headers:

```text
Authorization: Bearer <OPS JWT>
Content-Type: application/json
Accept: application/json
```

Request body:

```json
{
  "asin": "B0GN8LBPW9",
  "site": "US"
}
```

Successful response shape:

```json
{
  "code": 200,
  "msg": "操作成功",
  "data": {
    "asin": "B0GN8LBPW9",
    "site": "US",
    "total": 1,
    "list": [
      {
        "asin": "B0GN8LBPW9",
        "ASIN": "B0GN8LBPW9"
      }
    ]
  }
}
```

The base URL must come from `get_ops_system_url()`. It must not be built from `OPS_URL`, because `OPS_URL` already includes `/api` and would produce a duplicated path segment.

## Client Integration

`AsinBiReportDataClient` remains the shared source orchestrator used by simplified CLI, legacy live-data, category enrichment, and MCP callers. Its `listing_basic` branch changes to the new proxy so every existing caller receives the same source consistently.

The proxy path uses `AuthClient.build_request_auth("ops")`. Direct Polaris/BI listing authentication is not used for this source, and the proxy path has no fallback to `getAmazonListing` or `amazonlisdet`.

`crawler_details` and all BI domains remain unchanged.

## Batch Behavior

The proxy accepts one ASIN per request while the CLI accepts repeated ASINs. The client therefore:

1. Normalizes ASIN and site values using existing helpers.
2. Sends one POST body per ASIN.
3. Uses `ThreadPoolExecutor` with at most eight workers.
4. Preserves the input ASIN order when combining rows.
5. Keeps each upstream payload in `raw` keyed by ASIN.

Source status rules:

- `success`: every request succeeded, including valid zero-row responses.
- `partial`: at least one request succeeded and at least one failed.
- `failed`: every request failed.

Per-ASIN failures are returned in `errors_by_asin`. One failed ASIN must not discard successful rows for other ASINs.

## Row Adaptation

Rows come from `response.data.list`. They are already the final listing field structure, so the adapter must not remap Chinese field aliases through the old BI template logic.

For each row:

1. Copy the upstream row without mutating the raw payload.
2. Resolve ASIN from lowercase `asin`, uppercase `ASIN`, or the request ASIN.
3. Store exactly one lowercase `asin` field.
4. Remove uppercase `ASIN`.
5. Preserve all other upstream fields unchanged.
6. Add `site` only when both `site` and the localized site field are absent.

The adapter does not deduplicate separate business rows beyond removing the duplicate ASIN key inside each row.

## Public Response Compatibility

The CLI continues to return:

```text
success
command
data.status
data.asins
data.site
data.sources.listing_basic.key
data.sources.listing_basic.label
data.sources.listing_basic.endpoint
data.sources.listing_basic.status
data.sources.listing_basic.row_count
data.sources.listing_basic.rows
data.sources.listing_basic.raw
data.sources.listing_basic.errors_by_asin
error
```

Existing source names, top-level fields, and `crawler_details` structure do not change.

## Error Handling

- HTTP, invalid JSON, and business errors use the existing ASIN BI report error classes.
- A successful response with missing `data.list` is treated as an empty list.
- A non-object item inside `data.list` is ignored.
- Credentials and upstream authorization headers must never appear in errors or telemetry.
- Existing CLI failure handling and automatic `ops-feedback` behavior remain unchanged.

## Configuration

No new user configuration key is added. Environment selection continues through:

```ini
[systems]
ops_system_url = http://ops.api.xenkee.com
```

The fixed path `/api/v1/data-metrics/amazon-listing/basic` is owned by the client.

## Testing

Tests must verify:

1. The exact POST URL, JSON body, OPS Bearer header, and cookies.
2. Extraction from `data.list`.
3. Removal of uppercase `ASIN` while retaining lowercase `asin`.
4. Preservation of Chinese and extended listing fields.
5. Site fallback behavior.
6. Batch concurrency and stable input ordering.
7. `success`, `partial`, and `failed` source aggregation.
8. The absence of calls to old BI listing endpoints.
9. The unchanged simplified CLI response shape.
10. Existing crawler, BI, category Top, MCP, telemetry, and Skill regressions.

## Non-Goals

- No change to crawler data collection.
- No change to BI domain endpoints or date parameters.
- No new CLI or MCP parameters.
- No fallback to direct BI/Polaris listing endpoints.
- No Excel or OSS behavior change.
- No backend API implementation.

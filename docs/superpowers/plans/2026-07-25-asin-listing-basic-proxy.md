# ASIN Listing Basic Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every runtime `listing_basic` request through the OPS Amazon listing basic POST endpoint while preserving the existing source and CLI response structure.

**Architecture:** Keep `AsinBiReportDataClient` as the shared source orchestrator. Add a dedicated proxy fetch path for `listing_basic`, reuse common OPS authentication, adapt `data.list` rows, and leave crawler and BI paths unchanged.

**Tech Stack:** Python 3.10+, httpx, ThreadPoolExecutor, pytest, Typer CLI.

## Global Constraints

- Endpoint is `{ops_system_url}/api/v1/data-metrics/amazon-listing/basic`.
- Request body is one ASIN per POST: `{"asin": "...", "site": "US"}`.
- Authentication is OPS Bearer authentication from `AuthClient.build_request_auth("ops")`.
- No runtime fallback to `getAmazonListing` or `amazonlisdet`.
- Public `listing_basic` source keys and simplified CLI response shape remain unchanged.
- Crawler and BI domain behavior must not change.

---

### Task 1: Proxy Request and Row Adapter

**Files:**
- Modify: `tests/asin_data/test_bi_report_data.py`
- Modify: `opscli/asin_data/services/bi_report_data.py`

**Interfaces:**
- Consumes: `AuthClient.build_request_auth("ops")`, normalized ASINs, site mapping.
- Produces: `listing_basic` source dictionary with `status`, `row_count`, `rows`, `raw`, and `errors_by_asin`.

- [ ] Add a failing test that calls `client.fetch(source_keys=["listing_basic"])` and asserts an exact POST to `http://ops.example.com/api/v1/data-metrics/amazon-listing/basic` with OPS headers and `{"asin": ..., "site": ...}`.
- [ ] Assert the response reads `data.list`, preserves extended fields, removes uppercase `ASIN`, and keeps one lowercase `asin`.
- [ ] Run the focused test and verify it fails because runtime still calls the old GET endpoints.
- [ ] Add `DEFAULT_AMAZON_LISTING_BASIC_ENDPOINT` and inject/configure `ops_system_url` using `get_ops_system_url()`.
- [ ] Route the `listing_basic` branch to a new proxy source method using common OPS headers and cookies.
- [ ] Add a row adapter that copies each object row, resolves ASIN, removes uppercase `ASIN`, and fills site only when missing.
- [ ] Run the focused test and verify it passes.

### Task 2: Batch Ordering and Partial Failures

**Files:**
- Modify: `tests/asin_data/test_bi_report_data.py`
- Modify: `opscli/asin_data/services/bi_report_data.py`

**Interfaces:**
- Consumes: Single-ASIN proxy request helper from Task 1.
- Produces: Stable batch aggregation with at most eight workers.

- [ ] Add failing tests for multiple ASINs returned in input order despite different request completion order.
- [ ] Add failing tests for one successful ASIN plus one failed ASIN producing `partial`, retained rows, and `errors_by_asin`.
- [ ] Add a failing test for all requests failing and producing `failed` with zero rows.
- [ ] Implement concurrent one-ASIN POST requests and deterministic ordered aggregation.
- [ ] Store successful raw payloads by ASIN without mutation.
- [ ] Run all new proxy tests and verify they pass.

### Task 3: Runtime Isolation from Legacy Listing Endpoints

**Files:**
- Modify: `tests/asin_data/test_bi_report_data.py`
- Modify: `tests/asin_data/test_query_service.py` only if response assertions need expansion.
- Modify: `opscli/asin_data/services/bi_report_data.py`

**Interfaces:**
- Consumes: Existing simplified `AsinDataQueryService.fetch_basic` flow.
- Produces: Existing `data.sources.listing_basic` response using only the proxy at runtime.

- [ ] Add an assertion that runtime listing fetches never call `getAmazonListing`, `amazonlisdet`, or Polaris auth builders.
- [ ] Verify a valid empty `data.list` produces source `success` and `row_count: 0`.
- [ ] Verify crawler-only requests do not call the listing proxy.
- [ ] Remove listing-specific OPS-auth exemptions from runtime dispatch so auth errors fail the source consistently.
- [ ] Keep legacy private helpers unreachable unless removal is proven safe by the existing suite.
- [ ] Run BI report and query-service tests.

### Task 4: Regression and Real Smoke Test

**Files:**
- Modify only files required by failures attributable to this change.

**Interfaces:**
- Consumes: Final proxy implementation.
- Produces: Verified CLI behavior against the configured OPS environment.

- [ ] Run `tests/asin_data/test_bi_report_data.py` and `tests/asin_data/test_query_service.py`.
- [ ] Run the complete `tests/asin_data` suite and ASIN MCP tests.
- [ ] Run `git diff --check` and inspect changed files.
- [ ] Execute `opscli asin-data basic --asin B0GN8LBPW9 --site US --source listing` with branch code.
- [ ] Confirm source success, one lowercase `asin`, no uppercase `ASIN`, and no credentials in output.
- [ ] Commit implementation and tests.
- [ ] Push `codex/asin-data-listing-basic-proxy`.

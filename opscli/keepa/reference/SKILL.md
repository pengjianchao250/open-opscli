---
name: keepa-basic-internal
description: Internal basic Keepa usage notes for Python code, CLI commands, and MCP tools.
visibility: internal
---

# Keepa Basic Usage

This internal note explains the basic ways to call the Keepa integration from
opscli. It is not an installable user Skill.

## Authentication

Preferred source is OPS integration account `platform=keepa`; store the Keepa
API key in the account password field. Local fallback:

```powershell
$env:OPSCLI_KEEPA_API_KEY="YOUR_KEEPA_API_KEY"
```

## CLI Commands

Check quota for developer/operator debugging only:

```powershell
opscli keepa-debug token-status
```

List scenarios:

```powershell
opscli keepa scenarios
```

Run a product request:

```powershell
opscli keepa run product --site US --params '{"asin":"B0088PUEPK","stats":30}'
```

Default export is XLSX with Chinese headers. `--export-format` currently accepts
`xls`, `xlsx`, and formatted `json`; backend comparison should use the task `raw.json`.

Run with low-quota override:

```powershell
opscli keepa run product --site US --params '{"asins":["B0088PUEPK"]}' --force
```

Run with explicit output directory in local debug mode:

```powershell
opscli keepa-debug run seller --site US --params '{"seller":"A2L77EE7U53NWQ"}' --output-dir D:\tmp\keepa
```

## Python Calls

Use the manager in async code:

```python
from opscli.keepa.domain.models import KeepaScenarioRequest
from opscli.keepa.services import KeepaApiManager

manager = KeepaApiManager()
result = await manager.run(
    KeepaScenarioRequest(
        scenario="product",
        site="US",
        params={"asin": "B0088PUEPK", "stats": 30},
        force=True,
    )
)
print(result.to_dict())
```

Use it from sync scripts:

```python
import asyncio

from opscli.keepa.domain.models import KeepaScenarioRequest
from opscli.keepa.services import KeepaApiManager

result = asyncio.run(
    KeepaApiManager().run(
        KeepaScenarioRequest(
            scenario="product-search",
            site="US",
            params={"keyword": "flashlight", "page": 0},
        )
    )
)
print(result.export.path if result.export else result.result_path)
```

Read token status:

```python
import asyncio

from opscli.keepa.services import KeepaApiManager

status = asyncio.run(KeepaApiManager().token_status())
print(status["quota"])
```

Convert Keepa time minutes:

```python
from opscli.keepa.time import (
    keepa_minutes_to_unix_milliseconds,
    keepa_minutes_to_unix_seconds,
)

keepa_time = 7588958
seconds = keepa_minutes_to_unix_seconds(keepa_time)
milliseconds = keepa_minutes_to_unix_milliseconds(keepa_time)

assert seconds == 1749177480
assert milliseconds == 1749177480000
```

Keepa time is minutes. UTC Unix conversion:

- seconds: `(keepa_time + 21564000) * 60`
- milliseconds: `(keepa_time + 21564000) * 60000`

`keepa_run` keeps `raw_response` unchanged and adds derived time fields only in
normalized `rows`, such as `lastUpdateUnixSeconds`, `lastUpdateUnixMilliseconds`,
and `lastUpdateUtc`. For `keepa_time=7588958`, the UTC ISO time is
`2025-06-06T02:38:00Z`.

## MCP Tools

Basic MCP workflow:

1. `keepa_spec_must_read`
2. `keepa_scenarios`
3. `keepa_run`
4. `keepa_export`

Do not expose account source, API key, or standalone token status in MCP
conversations. If quota is insufficient or a request is stuck waiting for quota,
tell the user to retry later or contact operations.

Example `keepa_run` arguments:

```json
{
  "scenario": "product",
  "site": "US",
  "params": {
    "asin": "B0088PUEPK",
    "stats": 30,
    "history": true
  },
  "force": true
}
```

The run saves `params.json`, `raw.json`, `result.json`, and an XLSX export under
the task directory. JSON user export is not supported for now; backend
comparison should use `raw.json`. When OPS file upload is available, the export
metadata includes a cloud URL; otherwise use the local `export.path`.

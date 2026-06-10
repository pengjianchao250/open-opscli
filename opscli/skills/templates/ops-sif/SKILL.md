---
name: ops-sif
description: Use when the user asks for Sif关键词, Sif 查销量, 查流量, 多产品对比, 查排名, 每日排名, 运营时光机, 产品时光机, or their section exports through opscli CLI.
---

# ops-sif

Use this Skill to turn natural-language Sif platform requests into `opscli sif` CLI commands.

## Default Path

Use the Sif platform CLI:

```bash
opscli sif run 查销量 --asin B01NBNDC1T --site US
opscli sif run 查流量 --asin B01NBNDC1T --site US
opscli sif run 多产品对比 --asin B075WPKK5P,B07KVV8RFF,B07QQ21GL2 --site US
opscli sif run 查排名 --asin B0BMW2985V --site US
opscli sif run 运营时光机 --asin B01NBNDC1T --last-months 6 --granularity day
opscli sif run 产品时光机 --keyword "balloon pump" --site US
```

If the user names a specific Sif submodule, pass `--sections` so only that XLSX is downloaded.

```bash
opscli sif run 查流量 --asin B01NBNDC1T --sections 流量结构
opscli sif run 多产品对比 --asin B075WPKK5P,B07KVV8RFF --sections 重点广告词
```

## Missing Params Policy

- Ask only for missing required params.
- Required for `查销量` and `查流量`: one ASIN.
- Required for `多产品对比`: at least two ASINs, comma-separated.
- Required for `查排名` and `运营时光机`: one ASIN.
- Required for `产品时光机`: one keyword via `--keyword`.
- Do not ask for optional params. Use defaults unless the user explicitly provides them.
- Do not ask the user for Sif password, cookie, token, or account credentials in chat.

## Intent Map

| User intent keywords | CLI feature | `--sections` |
| --- | --- | --- |
| 查销量, 销量趋势 | `查销量` | omit for all sales exports |
| 不同变体销量, 下载图表 | `查销量` | `不同变体销量` |
| 同组变体销量, 下载搜索结果 | `查销量` | `同组变体销量` |
| 查流量, 查流量词 | `查流量` | omit for all traffic exports |
| 流量结构, 查流量结构 | `查流量` | `流量结构` |
| 反查流量词, 流量词 | `查流量` | `反查流量词` |
| 多变体自然位, 查多变体自然位 | `查流量` | `多变体自然位` |
| 多产品对比 | `多产品对比` | omit for all compare exports |
| 对比销量 | `多产品对比` | `对比销量` |
| 对比流量结构, 对比流量词, 流量词 | `多产品对比` | `对比流量词` |
| 对比流量分, 流量分 | `多产品对比` | `对比流量分` |
| 重点流量词 | `多产品对比` | `重点流量词` |
| 重点广告词, 广告词 | `多产品对比` | `重点广告词` |
| 查排名, 每日排名, 推排名, 查坑位 | `查排名` | omit |
| 运营时光机, 运营流量趋势, 流量变化 | `运营时光机` | `流量变化` |
| 流量词数量变化 | `运营时光机` | `流量词数量变化` |
| 产品时光机, 关键词产品时光机, 按关键词查产品销量 | `产品时光机` | omit |

ASCII aliases are supported for non-Chinese terminals: `sales`, `traffic`, `traffic-keywords`, `compare`, `ranking`, `operation-time-machine`, and `keyword-product-time-machine`.

## CLI Params

| Parameter | Required | Notes |
| --- | --- | --- |
| `feature` | yes | `查销量`, `查流量`, `多产品对比`, `查排名`, `运营时光机`, or `产品时光机` |
| `--asin` | conditional | Single ASIN for sales/traffic/ranking/operation time machine; comma-separated ASINs for compare |
| `--keyword` | conditional | Required for `产品时光机` |
| `--site` | no | Marketplace code or Chinese marketplace name. Default `US` |
| `--sections` | no | Comma-separated section names; omit for all sections |
| `--time-piece-type` | no | `latelyDay`, `week`, or `month` where supported |
| `--time-piece-value` | no | Depends on time type |
| `--granularity` | no | Ranking supports `week/month`; operation time machine supports `day/week/month` |
| `--last-months` | no | Operation time machine supports `3/6/12/24`; default `6` |
| `--change-type` | no | Operation time machine: `all` means 流量词数量变化 |
| `--page-num` | no | Default `1` |
| `--page-size` | no | User asks “查20条” -> `--page-size 20` |
| `--output-dir` | no | Export root directory; default uses user-level opscli config directory |
| `--job-id` | no | Stable job id for repeatable runs |

## Site Mapping

Always pass a Sif `country` code through `--site`. The actual supported values come from `opscli.sif.sites.SITE_ALIASES`, shared by all Sif features. Common aliases include:

| User text | `--site` |
| --- | --- |
| 美国, 美国站, US, USA | `US` |
| 英国, 英国站, UK, GB | `UK` |
| 加拿大, 加拿大站, CA | `CA` |
| 法国, 法国站, FR | `FR` |
| 西班牙, 西班牙站, ES | `ES` |
| 意大利, 意大利站, IT | `IT` |
| 澳大利亚, 澳大利亚站, AU | `AU` |
| 墨西哥, 墨西哥站, MX | `MX` |
| 阿联酋, 阿联酋站, AE | `AE` |
| 巴西, 巴西站, BR | `BR` |
| 沙特, 沙特站, SA | `SA` |
| 日本, 日本站, JP | `JP` |
| 德国, 德国站, DE | `DE` |

## Time Mapping

Use explicit time params only when the user provides time. Otherwise use feature defaults.

### Sales and Compare Sales

Default:

```bash
--time-piece-type latelyDay --time-piece-value 30
```

Rules:

- “最近30天” -> `--time-piece-type latelyDay --time-piece-value 30`
- “2026-02月” / “2026年2月” -> `--time-piece-type month --time-piece-value 2026-02`
- Month selection must be a past month. If the requested month is not in the past, fall back to `latelyDay/30`.

### Traffic and Compare Traffic

Default:

```bash
--time-piece-type latelyDay --time-piece-value 7
```

Rules:

- “最近7天” -> `--time-piece-type latelyDay --time-piece-value 7`
- “最近30天” -> `--time-piece-type latelyDay --time-piece-value 30`
- “某周” -> `--time-piece-type week --time-piece-value YYYY-MM-DD`, where the value is the first day of that selected past week.
- “2026-02月” / “2026年2月” -> `--time-piece-type month --time-piece-value 2026-02`
- Week must be in the past. If it is later than today, fall back to `latelyDay/7`.
- Month can be current month or past month for traffic. If invalid, fall back to `latelyDay/30`.

### Ranking

Default:

```bash
--granularity week
```

Rules:

- “按周” / “周” -> `--granularity week`
- “按月” / “月” -> `--granularity month`

### Operation Time Machine

Default:

```bash
--granularity day --last-months 6
```

Rules:

- “日趋势” -> `--granularity day`
- “周趋势” -> `--granularity week`
- “月趋势” -> `--granularity month`
- “近三个月/近六个月/近一年/近两年” -> `--last-months 3/6/12/24`
- “流量词数量变化” -> `--sections 流量词数量变化` or `--change-type all`

### Product Time Machine

Default:

```bash
--time-piece-type latelyDay --time-piece-value 7
```

Rules:

- “最近30天” -> `--time-piece-type latelyDay --time-piece-value 30`
- “某周” -> `--time-piece-type week --time-piece-value YYYY-MM-DD`
- “2026-02月” -> `--time-piece-type month --time-piece-value 2026-02`

## Endpoint Contracts

The CLI builds Sif query params internally:

```text
country=<site>&_t=<timestamp>&_m=<marker>
```

Never ask the user to provide `_t`, `_m`, Cookie, or authorization.

### 查销量

`不同变体销量`:

- POST `/api/updown/boughtListingHistory/download`
- Payload: `{"asins":["<ASIN>"]}`
- Natural language keywords such as “不同变体销量” or “下载图表” -> pass `--sections 不同变体销量`.

`同组变体销量`:

- POST `/api/updown/boughtByAsin/download`
- Payload fields:
  - `pageNum`: default `1`
  - `pageSize`: default `100`; user says “20条” -> `20`
  - `sortBy`: `""`
  - `desc`: `true`
  - `asins`: single ASIN list
  - `timePieceType`: default `latelyDay`; supports `month`
  - `timePieceValue`: default `30`; month example `2026-02`
- Natural language keywords such as “同组变体销量” or “下载搜索结果” -> pass `--sections 同组变体销量`.

### 查流量

`流量结构`:

- GET `/api/struct/listingscore/chart/download`
- Query fields: `country`, `timePieceType`, `timePieceValue`, `asin`, `dimension=asin`, `desc=true`

`反查流量词`:

- POST `/api/updown/asinKeywordList/download`
- Payload defaults:
  - `pageSize=50`, `pageNum=1`
  - `sort=scoreInfo.scoreRatio`, `desc=true`
  - `conditions=["totalPeriod.total"]`
  - `keyword=""`, `keywordSearch=""`, `listingSearch=false`

`多变体自然位`:

- POST `/api/updown/asinMultiNf/keywordList/download`
- Payload defaults:
  - `pageSize=100`, `pageNum=1`
  - `searchKeyword=""`, `searchAsin=""`
  - `sortBy=nfScore`, `desc=true`

For `反查流量词` and `多变体自然位`, user says “查20条” -> pass `--page-size 20`.

### 多产品对比

`对比销量`:

- POST `/api/updown/boughtByAsin/download`
- Payload defaults:
  - `pageNum=1`, `pageSize=100`, `sortBy=""`, `desc=true`
  - `asins=[...]`
  - `timePieceType=latelyDay`, `timePieceValue=30`

`对比流量结构`:

- POST `/api/compare/summary/multiAsin/download`
- Payload fields:
  - `timePieceType`, `timePieceValue`
  - `type=1`, `sortBy=""`, `desc=true`
  - `searchValue="<ASIN1>,<ASIN2>..."`
  - `showType=1` for `对比流量词`
  - `showType=2` for `对比流量分`

`对比流量词`:

- POST `/api/compare/compareMyKeywords/download`
- Payload fields:
  - `isMine=false`, `vipModule=false`, `asins=[...]`
  - `sortBy=""`, `desc=true`
  - `strategy=legacyForSales_exact`, `granularity=week`
  - `myPageNum=1`, `myPageSize=10`
  - `listType=1` for `重点流量词`
  - `listType=2` for `重点广告词`
  - `myCompareField=""`

User says “查20条重点广告词” -> pass:

```bash
--sections 重点广告词 --page-size 20
```

### 查排名

`每日排名`:

- List: POST `/api/search/subscribe/v2`
- Download: POST `/api/updown/userSubs/download`
- Payload fields:
  - `asin`: one ASIN
  - `granularity`: default `week`; supports `week/month`
  - list payload also includes `pageNum=1`, `pageSize=200`, `interval=7`, `sortBy=estSearchesNum`, `desc=true`, `isListingSearch=true`, `isExample=true`

### 运营时光机

- List: POST `/api/search/timeMachine/asinOpTrafficTrend/list`
- Download: POST `/api/updown/timeMachine/asinOpTrafficTrend/download`
- Payload fields:
  - `asin`: one ASIN
  - `granularity`: default `day`; supports `day/week/month`
  - `lastMonths`: default `6`; supports `3/6/12/24`
  - `listingSearch=false`, `endDay=null`, `interval=null`
  - `type=all` only when the user asks for 流量词数量变化

### 产品时光机

- List: POST `/api/search/bought/keyword`
- Download: POST `/api/updown/boughtByKeyword/download`
- Payload fields:
  - `keyword`: required
  - `timePieceType`: default `latelyDay`
  - `timePieceValue`: default `7`
  - list payload also includes `pageNum=1`, `pageSize=100`, `sortBy=""`, `desc=true`

## Output

Every command writes:

- `params.json`
- `raw.json`
- `result.json`
- one or more Sif XLSX downloads

For successful runs, report the concise feature result and generated XLSX filenames/links. Do not print raw Cookie/token/auth values.

## Guardrails

- Prefer CLI when running locally; use Sif MCP tools when the client has opscli-mcp enabled.
- Do not ask the user for Sif credentials in chat.
- Do not place Sif account, password, cookie, or token in examples, logs, tests, or reports.
- If an `opscli` command fails unexpectedly, follow the repository rule and submit `ops-feedback` immediately.
- Do not call Sif HTTP APIs directly from the agent; use `opscli sif`.

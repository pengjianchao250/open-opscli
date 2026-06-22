---
name: ops-sif-mcp
description: Use Sif MCP tools for Sif 查销量、查流量、多产品对比、查排名、运营时光机、产品时光机 exports. Prefer MCP when running inside a client connected to opscli-mcp.
---

# ops-sif MCP

Use these MCP tools when the user asks for Sif platform exports from a client:

1. `sif_spec_must_read` must be called before the first Sif operation in a session.
2. `sif_scenarios` lists supported features and sections.
3. `sif_run` executes the feature and returns generated XLSX exports.
4. `sif_job_status` reads a previous result by `job_id`.
5. `sif_export` returns one or all export links for a `job_id`.

Do not ask the user for Sif account, password, cookie, token, `_t`, or `_m`.
The service reads Sif credentials from OPS integration account platform `sif`, then falls back to `OPSCLI_SIF_USERNAME` and `OPSCLI_SIF_PASSWORD`.

## Required Params

- `查销量`: one ASIN.
- `查流量`: one ASIN.
- `多产品对比`: at least two ASINs. Pass them as comma-separated `asin` or as `asins`.
- `查排名`: one ASIN.
- `运营时光机`: one ASIN.
- `产品时光机`: one keyword.

## Optional Params

- `site`: default `US`. Accepts site code or marketplace name, such as `美国`, `美国站`, `US`.
- `sections`: optional list or comma-separated text. Omit to download all sections.
- `time_piece_type`: `latelyDay`, `week`, or `month`, where supported.
- `time_piece_value`: value for the selected time type.
- `keyword`: required for `产品时光机`.
- `granularity`: `week/month` for ranking; `day/week/month` for operation time machine.
- `last_months`: operation time machine supports `3/6/12/24`, default `6`.
- `change_type`: operation time machine, use `all` for 流量词数量变化.
- `page_num`: default `1`.
- `page_size`: use when the user asks for a specific row count.
- `output_dir`: optional; normally omit so the service writes to the user-level opscli config directory.
- `job_id`: optional stable job id.

## Intent Map

| User words | `feature` | `sections` |
| --- | --- | --- |
| 查销量, 销量趋势 | `查销量` | omit |
| 不同变体销量, 下载图表 | `查销量` | `不同变体销量` |
| 同组变体销量, 下载搜索结果 | `查销量` | `同组变体销量` |
| 查流量, 查流量词 | `查流量` | omit |
| 流量结构 | `查流量` | `流量结构` |
| 反查流量词, 流量词 | `查流量` | `反查流量词` |
| 多变体自然位 | `查流量` | `多变体自然位` |
| 多产品对比 | `多产品对比` | omit |
| 对比销量 | `多产品对比` | `对比销量` |
| 对比流量词 | `多产品对比` | `对比流量词` |
| 对比流量分 | `多产品对比` | `对比流量分` |
| 重点流量词 | `多产品对比` | `重点流量词` |
| 重点广告词 | `多产品对比` | `重点广告词` |
| 查排名, 每日排名, 推排名, 查坑位 | `查排名` | omit |
| 运营时光机, 运营流量趋势, 流量变化 | `运营时光机` | `流量变化` |
| 流量词数量变化 | `运营时光机` | `流量词数量变化` |
| 产品时光机, 关键词产品时光机 | `产品时光机` | omit |

ASCII aliases are also supported: `sales`, `traffic`, `traffic-keywords`, `compare`, `ranking`, `operation-time-machine`, `keyword-product-time-machine`.

## Site Mapping

Pass a Sif country code through `site`. Supported values are resolved by `opscli.sif.sites.SITE_ALIASES`, the same mapping used by all Sif CLI features.

| User text | site |
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

For `查销量`, default to:

```json
{"time_piece_type":"latelyDay","time_piece_value":"30"}
```

For `查流量` and traffic-related compare sections, default to:

```json
{"time_piece_type":"latelyDay","time_piece_value":"7"}
```

If the user asks for the last 7 or 30 days, use `latelyDay` with `7` or `30`.
If the user asks for a month, use `month` with `YYYY-MM`.
If the user asks for a week, use `week` with the first day of that week as `YYYY-MM-DD`.

For `查排名`, default to:

```json
{"granularity":"week"}
```

For `运营时光机`, default to:

```json
{"granularity":"day","last_months":6}
```

Use `change_type:"all"` only when the user asks for 流量词数量变化.

For `产品时光机`, default to:

```json
{"time_piece_type":"latelyDay","time_piece_value":"7"}
```

## Examples

Run sales for one ASIN:

```json
{"feature":"查销量","asin":"B01NBNDC1T","site":"US"}
```

Only download traffic structure:

```json
{"feature":"查流量","asin":"B01NBNDC1T","site":"美国","sections":["流量结构"]}
```

Only download key ad keywords for multiple products:

```json
{
  "feature":"多产品对比",
  "asin":"B075WPKK5P,B07KVV8RFF,B07QQ21GL2",
  "sections":["重点广告词"],
  "page_size":20
}
```

Run ranking:

```json
{"feature":"查排名","asin":"B0BMW2985V","site":"US","granularity":"week"}
```

Run operation time machine keyword count change:

```json
{"feature":"运营时光机","asin":"B01NBNDC1T","sections":["流量词数量变化"],"last_months":6,"granularity":"day","change_type":"all"}
```

Run product time machine:

```json
{"feature":"产品时光机","keyword":"balloon pump","site":"US"}
```

## Output

`sif_run` returns `exports`, where every item includes:

- `filename`
- `display_filename`
- `path`
- `url`
- `download_markdown`
- `format`
- `mime_type`

It also returns top-level `download_links`. Use `download_links[].markdown` when showing links to the user, so the clickable text is the XLSX filename instead of a generic label such as `打开XLSX`.

When OPS file upload is available, `url` is the remote downloadable link. If upload is unavailable, `url` is a `file://` link to the local service file.

Do not expose Sif credentials in the answer. Report concise result info: feature, ASIN, ASIN count, keyword, site, and XLSX filenames/links. Prefer this format:

```markdown
- 流量结构: [流量结构_B01NBNDC1T_1780000000001.xlsx](download-url)
```

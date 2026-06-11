# Sif 平台查流量与多产品对比架构方案

## 结论

继续采用平台模块方式，不恢复已删除的 `opscli/sales/`：

```text
opscli sif run 查销量 ...
opscli sif run 查流量 ...
opscli sif run 多产品对比 ...
```

Sif 登录、请求参数、下载、落盘、错误处理应抽到平台公共层，三个业务模块只负责各自 payload、endpoint、normalizer 和 export key。

## 推荐目录

```text
opscli/sif/
  cli.py
  client.py
  config.py
  domain/
    exceptions.py
    models.py
  shared/
    downloads.py
    runner.py
    requests.py
  sales/
    provider.py
    models.py
    normalizer.py
    export.py
  traffic/
    provider.py
    models.py
    normalizer.py
    scenarios.py
  compare/
    provider.py
    models.py
    normalizer.py
    scenarios.py
```

Skill 目录：

```text
opscli/skills/templates/ops-sif/
  SKILL.md
  data/VERSION.json
```

迁移策略：

1. 新增 `ops-sif`。
2. 将 `ops-sif-sales` 内容合并进 `ops-sif`。
3. 旧 `ops-sif-sales` 模板已删除，后续统一只保留 `ops-sif`。

## CLI 分发

`opscli/sif/cli.py` 中维护功能路由：

```python
FEATURE_HANDLERS = {
    "查销量": SifSalesProvider,
    "查流量": SifTrafficProvider,
    "查流量词": SifTrafficProvider,
    "查流量(词)": SifTrafficProvider,
    "多产品对比": SifCompareProvider,
}
```

CLI 参数需要扩展：

```text
--asin
--site
--time-piece-type
--time-piece-value
--sections
--my-asin
--output-dir
--job-id
--timeout
--json
--pretty
```

`--asin` 在查销量/查流量中校验为单个 ASIN，在多产品对比中解析为列表。

## SifApiClient 扩展

当前 `SifApiClient` 已有：

- 登录与登录诊断。
- `_request_params()` 生成 `country/_t/_m`。
- `_post_json()`。
- `_download()`。
- XLSX 校验。

建议扩展为通用下载方法：

```python
def download_get(self, path: str, *, query: dict[str, Any], country: str) -> bytes
def download_post(self, path: str, *, payload: dict[str, Any], country: str) -> bytes
```

同时保留现有查销量方法，或把查销量也改为 scenario 调用，减少重复。

## 查流量 scenarios

```python
TRAFFIC_DOWNLOADS = {
    "structure": {
        "method": "GET",
        "path": "/api/struct/listingscore/chart/download",
        "filename": "listingScoreChart_{asin}_{timestamp}.xlsx",
        "query": build_listing_score_chart_query,
    },
    "keywords": {
        "method": "POST",
        "path": "/api/updown/asinKeywordList/download",
        "filename": "asinKeywordList_{asin}_{timestamp}.xlsx",
        "payload": build_asin_keyword_list_payload,
    },
    "multi_nf": {
        "method": "POST",
        "path": "/api/updown/asinMultiNf/keywordList/download",
        "filename": "asinMultiNfKeywordList_{asin}_{timestamp}.xlsx",
        "payload": build_asin_multi_nf_payload,
    },
}
```

Provider 执行流程：

```text
normalize request
build job dir
write params.json
for each selected section:
  build sanitized query/payload
  call SifApiClient download
  save xlsx
  append raw request meta and export meta
write raw.json
write result.json
return Sif run result
```

## 多产品对比 scenarios

```python
COMPARE_DOWNLOADS = {
    "sales": {
        "method": "POST",
        "path": "/api/updown/boughtByAsin/download",
        "filename": "compareBoughtByAsin_{asin_count}_{timestamp}.xlsx",
        "payload": build_compare_sales_payload,
        "status": "confirmed",
    },
    "traffic_words": {
        "method": "POST",
        "path": "/api/compare/summary/multiAsin/download",
        "filename": "compareSummaryTrafficWords_{asin_count}_{timestamp}.xlsx",
        "payload": build_compare_summary_payload_show_type_words,
        "showType": 1,
        "status": "confirmed",
    },
    "traffic_score": {
        "method": "POST",
        "path": "/api/compare/summary/multiAsin/download",
        "filename": "compareSummaryTrafficScore_{asin_count}_{timestamp}.xlsx",
        "payload": build_compare_summary_payload_show_type_score,
        "showType": 2,
        "status": "confirmed",
    },
    "my_traffic_keywords": {
        "method": "POST",
        "path": "/api/compare/compareMyKeywords/download",
        "filename": "compareMyTrafficKeywords_{asin_count}_{timestamp}.xlsx",
        "payload": build_compare_my_keywords_payload_list_type_traffic,
        "listType": 1,
        "status": "confirmed",
    },
    "my_ad_keywords": {
        "method": "POST",
        "path": "/api/compare/compareMyKeywords/download",
        "filename": "compareMyAdKeywords_{asin_count}_{timestamp}.xlsx",
        "payload": build_compare_my_keywords_payload_list_type_ad,
        "listType": 2,
        "status": "confirmed",
    },
}
```

多产品对比关键 payload 已确认：

```json
{
  "pageNum": 1,
  "pageSize": 100,
  "sortBy": "",
  "desc": true,
  "asins": [
    "B075WPKK5P",
    "B07KVV8RFF",
    "B07QQ21GL2",
    "B07YJPFJ43",
    "B08PNQCKF7"
  ],
  "timePieceType": "latelyDay",
  "timePieceValue": "30"
}
```

枚举已确认：

- `showType=1`：流量词。
- `showType=2`：流量分。
- `listType=1`：重点流量词。
- `listType=2`：重点广告词。

## 输出模型

建议新增平台通用结果模型，替代过于 sales 命名的模型：

```python
SifRunRequest
SifExportResult
SifRunResult
```

字段：

```text
feature
provider
site
asin
asins
time_piece_type
time_piece_value
sections
output_dir
job_id
params
```

查销量可逐步迁移到通用模型，避免 `SifSalesRunRequest` 扩展到所有功能后命名不准确。

## 输出目录

当前查销量默认目录：

```text
CONFIG_DIR / "sif" / "sales" / "runs"
```

建议扩展为：

```text
CONFIG_DIR / "sif" / "<feature-key>" / "runs"
```

示例：

```text
~/.config/opscli/sif/sales/runs/
~/.config/opscli/sif/traffic/runs/
~/.config/opscli/sif/compare/runs/
```

如果用户传 `--output-dir`，仍以用户指定目录为根目录。

## 站点规范化

新增站点解析层，将用户输入的国家名称、站点名称、编码统一为 Sif `country` 编码：

```python
SITE_ALIASES = {
    "US": "US",
    "美国": "US",
    "美国站": "US",
    "UK": "UK",
    "GB": "UK",
    "英国": "UK",
    "英国站": "UK",
    "CA": "CA",
    "加拿大": "CA",
    "加拿大站": "CA",
    "FR": "FR",
    "法国": "FR",
    "法国站": "FR",
    "ES": "ES",
    "西班牙": "ES",
    "西班牙站": "ES",
    "IT": "IT",
    "意大利": "IT",
    "意大利站": "IT",
    "AU": "AU",
    "澳大利亚": "AU",
    "澳大利亚站": "AU",
    "MX": "MX",
    "墨西哥": "MX",
    "墨西哥站": "MX",
    "AE": "AE",
    "阿联酋": "AE",
    "阿联酋站": "AE",
    "BR": "BR",
    "巴西": "BR",
    "巴西站": "BR",
    "SA": "SA",
    "沙特": "SA",
    "沙特站": "SA",
    "JP": "JP",
    "日本": "JP",
    "日本站": "JP",
    "DE": "DE",
    "德国": "DE",
    "德国站": "DE",
}
```

未知站点返回可读错误，不直接把原始中文传给 Sif API。

## Referer 与页面上下文

查流量结构下载接口为 GET：

```text
/api/struct/listingscore/chart/download
```

该接口需要带页面上下文请求头，至少包含 `Referer`。实现要求：

- `Referer` 按 Sif 查流量页面构造，包含当前 `country`、`asin`、时间范围等上下文。
- `Origin` 保持 `https://www.sif.com`。
- `Accept` 使用 XLSX 或通用下载可接受类型。
- 这些 header 由 Sif 客户端内部生成，不要求用户传参。

## 错误处理

新增错误不需要单独建异常体系，复用 Sif 现有异常：

- `SIF_LOGIN_REQUIRED`
- `SIF_LOGIN_FAILED`
- `SIF_API_REQUEST_FAILED`
- `SIF_DOWNLOAD_FAILED`
- `SIF_OUTPUT_PERMISSION_DENIED`

错误 payload 必须包含 sanitized 信息：

```json
{
  "request_payload": {},
  "request_query": {},
  "path": "/api/..."
}
```

不能包含 Cookie、authorization、token、password。

## 测试策略

新增测试目录：

```text
tests/sif/test_traffic_provider.py
tests/sif/test_compare_provider.py
tests/sif/test_traffic_payloads.py
tests/sif/test_compare_payloads.py
tests/sif/test_sif_cli.py
```

覆盖：

- 查流量 3 个 payload/query 构造。
- 多产品对比 payload 构造和 ASIN 列表解析。
- 下载字节保存为 XLSX。
- `params.json` 不含敏感信息。
- `result.json` schema 稳定。
- CLI feature 分发。
- 未确认枚举值 warning。

## MCP 判断

第一版不做 MCP。

理由：

- 用户明确 CLI 是确定方式。
- 新接口枚举仍需确认。
- Sif 登录和下载本身已有复杂度，先稳定 CLI 和文件契约。

后续满足以下条件再做 MCP：

- 查流量/多产品对比真实运行稳定。
- result schema 已用于至少一轮分析。
- 用户需要 AI Agent 不经 shell 直接调用。
- Sif Skill 已统一为 `ops-sif`。

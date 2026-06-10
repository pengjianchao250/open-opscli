# SIF 查排名与时光机能力扩展 Architecture

## 总体方案

采用现有 SIF 平台结构扩展，不新增顶级模块：

```text
opscli/sif/
  ranking/
    __init__.py
    scenarios.py
    provider.py
  operation_time_machine/
    __init__.py
    scenarios.py
    provider.py
  product_time_machine/
    __init__.py
    scenarios.py
    provider.py
```

继续通过：

- `opscli sif run <feature>` 提供 CLI。
- `SifServiceManager` 提供 MCP 编排。
- `SifApiClient` 提供认证、列表接口、下载接口。
- `opscli.sif.sites.normalize_site` 提供站点标准化。
- `ops-sif` Skill 提供自然语言映射。

## 数据模型调整

扩展 `SifRunRequest`：

```python
keyword: str | None = None
granularity: str | None = None
last_months: int | None = None
change_type: str | None = None
```

说明：

- `keyword` 仅用于产品时光机。
- `granularity` 用于查排名和运营时光机。
- `last_months` 用于运营时光机。
- `change_type` 用于运营时光机，映射 SIF payload 中的 `type` 字段，避免直接使用 Python 内置名 `type`。

## SifApiClient 调整

新增公开方法：

```python
def post_json(self, path: str, *, payload: dict[str, Any], country: str | None = None) -> dict[str, Any]:
    ...
```

内部复用当前 `_post_json`、`_headers`、`_ensure_authenticated` 和 `_request_params`。Provider 不再直接调用私有 `_post_json`。

## 配置与输出目录

扩展 `DEFAULT_FEATURE_OUTPUT_DIRS`：

```python
"ranking": CONFIG_DIR / "sif" / "ranking" / "runs"
"operation_time_machine": CONFIG_DIR / "sif" / "operation_time_machine" / "runs"
"product_time_machine": CONFIG_DIR / "sif" / "product_time_machine" / "runs"
```

`OPSCLI_SIF_OUTPUT_DIR` 仍可覆盖全部 feature 默认目录。

## Feature 分发

扩展 CLI `FEATURE_DEFINITIONS`：

- `查排名` -> `SifRankingProvider`
- `运营时光机` -> `SifOperationTimeMachineProvider`
- `产品时光机` -> `SifProductTimeMachineProvider`

扩展 Service Manager `FEATURE_SCENARIOS`：

- `查排名`
  - key: `ranking`
  - aliases: `查排名`、`每日排名`、`推排名`、`查坑位`、`ranking`
  - sections: `每日排名`
  - default granularity: `week`
- `运营时光机`
  - key: `operation_time_machine`
  - aliases: `运营时光机`、`运营流量趋势`、`流量变化`、`流量词数量变化`、`operation-time-machine`
  - sections: `流量变化`、`流量词数量变化`
  - default granularity: `day`
  - default lastMonths: `6`
- `产品时光机`
  - key: `product_time_machine`
  - aliases: `产品时光机`、`关键词产品时光机`、`keyword-product-time-machine`
  - sections: `产品时光机`
  - default timePieceType: `latelyDay`
  - default timePieceValue: `7`

## CLI 参数校验

`--asin` 从全局必填改为可选，按 feature 校验：

- `查排名`、`运营时光机` 必须有 `--asin`。
- `产品时光机` 必须有 `--keyword`。
- `多产品对比` 仍要求至少两个 ASIN。

站点处理保持现状：

- CLI 接收到 `--site` 后继续通过 `normalize_site(site)` 标准化。
- Provider 内部也保留 `normalize_site(request.site)`，保证 MCP 和测试直接调用 Provider 时同样使用 SIF 已有站点字段。
- 本次不新增独立国家表，不复制 SellerSprite 或 Amazon Rufus 的国家映射。

新增参数：

```python
keyword: str | None = typer.Option(None, "--keyword", help="产品时光机关键词")
granularity: str | None = typer.Option(None, "--granularity", help="day/week/month 或 week/month")
last_months: int | None = typer.Option(None, "--last-months", help="运营时光机最近月份数")
change_type: str | None = typer.Option(None, "--change-type", help="运营时光机变化类型；all=流量词数量变化")
```

## Provider 设计

每个新增 Provider 均遵循同一落盘流程：

1. 标准化 site、ASIN 或 keyword。
2. 解析 sections 和默认参数。
3. 写 `params.json`。
4. 调用列表接口并写入 `raw.json`。
5. 调用下载接口并保存 XLSX。
6. 写 `result.json`。
7. 返回 `SifRunResult`。

### 查排名 payload

列表：

```json
{
  "filterAsin": "",
  "granularity": "week",
  "asin": "B0BMW2985V",
  "endDay": null,
  "pageNum": 1,
  "pageSize": 200,
  "interval": 7,
  "sortBy": "estSearchesNum",
  "desc": true,
  "isListingSearch": true,
  "isExample": true
}
```

下载：

```json
{
  "isListingSearch": true,
  "asin": "B0BMW2985V",
  "granularity": "week",
  "isExample": true
}
```

### 运营时光机 payload

列表和下载共用基础 payload：

```json
{
  "granularity": "day",
  "asin": "B01NBNDC1T",
  "endDay": null,
  "interval": null,
  "listingSearch": false,
  "lastMonths": 6
}
```

当 `change_type="all"` 时追加：

```json
{"type": "all"}
```

默认不传 `type`。

### 产品时光机 payload

列表：

```json
{
  "pageNum": 1,
  "pageSize": 100,
  "sortBy": "",
  "desc": true,
  "keyword": "balloon pump",
  "timePieceType": "latelyDay",
  "timePieceValue": "7"
}
```

下载：

```json
{
  "keyword": "balloon pump",
  "sortBy": "",
  "desc": true,
  "timePieceValue": "7",
  "timePieceType": "latelyDay"
}
```

## 输出 JSON 结构

所有新增 feature 使用稳定结构：

```json
{
  "schema_version": "sif_<feature>.v1",
  "feature": "查排名",
  "provider": "sif",
  "asin": "B0BMW2985V",
  "site": "US",
  "query": {},
  "summary": {
    "export_count": 1,
    "list_item_count": 0,
    "warning_count": 0
  },
  "exports": {},
  "requests": [],
  "list_response": {},
  "warnings": []
}
```

产品时光机用 `keyword` 替代 `asin`。

## MCP 调整

扩展 `sif_run` 入参：

```python
keyword: str = ""
granularity: str | None = None
last_months: int | None = None
change_type: str | None = None
```

构造 `SifRunRequest` 时传入这些字段。`decorate_download_payload` 保持不变。

## Skill 调整

更新：

- `opscli/skills/templates/ops-sif/SKILL.md`
- `opscli/skills/templates/ops-sif/SKILL_MCP.md`

新增：

- intent mapping
- required/optional params
- examples
- sections mapping
- 默认时间范围和粒度
- 站点名称解释为 SIF 现有 `SITE_ALIASES` 支持的值，不在 Skill 中维护第二份国家映射

## 测试计划

新增测试：

- `tests/sif/test_ranking_payloads.py`
- `tests/sif/test_operation_time_machine_payloads.py`
- `tests/sif/test_product_time_machine_payloads.py`
- `tests/sif/test_ranking_provider.py`
- `tests/sif/test_operation_time_machine_provider.py`
- `tests/sif/test_product_time_machine_provider.py`

扩展测试：

- `tests/sif/test_sif_cli.py`
- `tests/sif/test_service_manager.py`
- `tests/mcp/test_sif_tools.py`

建议验证命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\sif tests\mcp\test_sif_tools.py -q -p no:cacheprovider
```

## 安全边界

- 不落盘 SIF 密码、Cookie、Token、authorization。
- MCP 返回只暴露文件名、文件 URL、feature、site、query 摘要。
- 错误中的 request payload/query 继续走 sanitized 逻辑。

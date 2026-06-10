# SIF 查排名与时光机能力扩展 PRD

## 目标

在现有 SIF 平台能力中新增：

- `查排名`
- `运营时光机`
- `产品时光机`

新增能力需要与已实现的 `查销量`、`查流量`、`多产品对比` 保持一致的使用方式、登录方式、输出结构、MCP 下载链接和 Skill 自然语言触发体验。

## 用户价值

运营人员可以通过自然语言、CLI 或 MCP 客户端直接获取 SIF 页面同款导出文件，同时保留列表接口 JSON，后续可接入后端数据库和分析流程。

## 范围

### CLI

继续使用平台级入口：

```powershell
opscli sif run 查排名 --asin B0BMW2985V --site US
opscli sif run 运营时光机 --asin B01NBNDC1T --site 美国 --last-months 6 --granularity day
opscli sif run 产品时光机 --keyword "balloon pump" --site US
```

新增参数：

- `--keyword`：产品时光机必填。
- `--granularity`：查排名、运营时光机使用。
- `--last-months`：运营时光机使用，默认 `6`。
- `--change-type`：运营时光机使用，空值表示流量变化，`all` 表示流量词数量变化。

继续支持：

- `--site`
- `--time-piece-type`
- `--time-piece-value`
- `--sections`
- `--page-num`
- `--page-size`
- `--output-dir`
- `--json`
- `--pretty`

`--site` 的站点名称和编码解析必须复用 SIF 模块已有定义，即 `opscli.sif.sites.normalize_site` 与 `SITE_ALIASES`，与当前 `查销量`、`查流量`、`多产品对比` 保持一致。

### MCP

扩展现有 `sif_run`，不新增独立工具。MCP 需要支持：

- `feature="查排名"`，传 `asin`。
- `feature="运营时光机"`，传 `asin`。
- `feature="产品时光机"`，传 `keyword`。
- 返回结果中继续包含 `download_links`，链接展示名为 XLSX 文件名。

### Skill

更新 `ops-sif` 与 `ops-sif-mcp` 文档：

- 新增三类 feature 的自然语言识别。
- 新增必填参数和可选过滤项说明。
- 新增时间范围、站点、粒度、关键词映射规则。
- 明确不向用户索要 SIF Cookie、Token、`_t`、`_m`、账号密码。

## 功能需求

### 查排名

必填：

- ASIN

可选：

- 站点，默认 `US`
- `granularity`，默认 `week`，支持 `week/month`

输出：

- `每日排名_<ASIN>_<timestamp>.xlsx`
- `raw.json` 包含列表接口 `/api/search/subscribe/v2` 响应
- `result.json` 使用 `schema_version=sif_ranking.v1`

### 运营时光机

必填：

- ASIN

可选：

- 站点，默认 `US`
- `lastMonths`，默认 `6`，支持 `3/6/12/24`
- `granularity`，默认 `day`，支持 `day/week/month`
- `change_type`，默认空值；`all` 表示流量词数量变化

输出：

- `运营时光机_<ASIN>_<timestamp>.xlsx`
- `raw.json` 包含列表接口 `/api/search/timeMachine/asinOpTrafficTrend/list` 响应
- `result.json` 使用 `schema_version=sif_operation_time_machine.v1`

### 产品时光机

必填：

- keyword

可选：

- 站点，默认 `US`
- `timePieceType`，默认 `latelyDay`
- `timePieceValue`，默认 `7`
- `pageNum`，默认 `1`
- `pageSize`，默认 `100`

输出：

- `产品时光机_<keyword>_<timestamp>.xlsx`
- `raw.json` 包含列表接口 `/api/search/bought/keyword` 响应
- `result.json` 使用 `schema_version=sif_product_time_machine.v1`

## 非功能需求

- 不写入账号、密码、Cookie、Token 到 `params.json/raw.json/result.json`。
- SIF 登录继续优先使用 OPS 集成账号 platform=`sif`，再 fallback 到环境变量。
- 站点支持范围不在本需求内另行扩展，新增模块只消费 SIF 现有站点字段。
- 失败时沿用现有友好错误输出，并保留 sanitized request payload/query。
- 测试不得请求真实 SIF 网络。
- 默认输出目录按 feature 分区，避免多人或多功能混用文件。

## 验收标准

- `opscli sif features --pretty` 能看到新增三个 feature。
- `opscli sif run 查排名 --asin B0BMW2985V --json` 能生成 XLSX、raw、result。
- `opscli sif run 运营时光机 --asin B01NBNDC1T --last-months 6 --granularity day --json` 能生成 XLSX、raw、result。
- `opscli sif run 产品时光机 --keyword "balloon pump" --json` 能生成 XLSX、raw、result。
- `sif_scenarios` 能列出新增 feature、sections、默认参数。
- `sif_run(feature="产品时光机", keyword="balloon pump")` 能返回 `download_links`。
- 单元测试覆盖 payload、Provider 输出、CLI 分发、MCP 入参。

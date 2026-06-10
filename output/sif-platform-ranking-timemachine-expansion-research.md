# SIF 查排名与时光机能力扩展 Research

## 背景

当前 `opscli sif` 已实现同一 SIF 平台下的 `查销量`、`查流量`、`多产品对比` 三类能力，公共能力包括：

- `opscli sif run <feature>` 作为平台级入口。
- `SifApiClient` 统一处理登录、`_t`、`_m`、Cookie、authorization、POST/GET 下载。
- `SifServiceManager` 统一支撑 MCP 侧账号注入、Provider 分发、结果读取、导出文件上传和下载链接装饰。
- 输出目录默认按 feature 写入用户级配置目录 `~/.config/opscli/sif/<feature>/runs`。
- Provider 负责写入 `params.json`、`raw.json`、`result.json` 和 XLSX 导出文件。
- 国家/站点字段已由 SIF 模块内 `opscli/sif/sites.py` 统一定义，新增能力应复用 `normalize_site` 和 `SITE_ALIASES`，不要另建站点枚举。
- Skill 与 MCP 文档通过自然语言映射 feature、sections 和关键参数。

本次扩展的三个模块均属于同一 SIF 平台，应复用上述体系，不新增顶级命令，不复制登录逻辑。

## 现有实现观察

`查销量` 使用专用 `SifSalesRunRequest` 和 `SifSalesProvider`，会先调用列表接口保留原始 JSON，再调用下载接口生成 SIF 风格 XLSX 文件名。

`查流量` 与 `多产品对比` 使用通用 `SifRunRequest`，按 `scenarios.py` 组装 payload，并通过 `SifApiClient.download_post/download_get` 下载 XLSX。当前它们主要记录下载请求与导出结果，新增模块需要进一步把列表接口响应写入 `raw.json/result.json`，满足后续入库预留。

MCP 已具备 `sif_scenarios`、`sif_run`、`sif_job_status`、`sif_export`。因此新增模块只需要扩展 `SifServiceManager` 的 feature 表、Provider 分发和 MCP 入参，不需要新增独立 MCP server。

## 新增模块调研结论

### 查排名

业务入口：SIF -> 查坑位/推排名 -> 每日排名。

核心输入：

- ASIN：必填。
- 站点：默认美国，沿用 SIF 现有 `normalize_site`。
- `granularity`：`week` 或 `month`，建议 CLI/MCP 默认 `week`。

列表接口：

- POST `/api/search/subscribe/v2`
- 用于写入 `raw.json` 和 `result.json`。
- 默认 payload 保留 `pageNum=1`、`pageSize=200`、`interval=7`、`sortBy=estSearchesNum`、`desc=true`、`isListingSearch=true`、`isExample=true`。

下载接口：

- POST `/api/updown/userSubs/download`
- 生成每日排名 XLSX。

### 运营时光机

业务入口：SIF -> 运营时光机 -> ASIN -> 详情列表。

核心输入：

- ASIN：必填。
- 站点：默认美国，沿用 SIF 现有 `normalize_site`。
- `lastMonths`：`3`、`6`、`12`、`24`，默认 `6`。
- `granularity`：`day`、`week`、`month`，默认 `day`。
- `type`：默认不传或 `null` 表示流量变化；`all` 表示流量词数量变化。

列表接口：

- POST `/api/search/timeMachine/asinOpTrafficTrend/list`
- 用于写入 `raw.json` 和 `result.json`。

下载接口：

- POST `/api/updown/timeMachine/asinOpTrafficTrend/download`
- 生成运营时光机 XLSX。

接口材料中下载接口示例包含 `granularity=day`，参数说明又提到周/月趋势。实现应允许 `day/week/month`，如 SIF 实测拒绝某个枚举，由统一错误提示暴露 request payload，便于后续修正。

### 产品时光机

业务入口：SIF -> 产品时光机 -> 关键词。

核心输入：

- `keyword`：必填，不使用 ASIN。
- 站点：默认美国，沿用 SIF 现有 `normalize_site`。
- `timePieceType`：默认 `latelyDay`，支持 `latelyDay`、`week`、`month`。
- `timePieceValue`：默认 `7`，支持 `7`、`30`、周首日 `YYYY-MM-DD`、月份 `YYYY-MM`。

列表接口：

- POST `/api/search/bought/keyword`
- 用于写入 `raw.json` 和 `result.json`。

下载接口：

- POST `/api/updown/boughtByKeyword/download`
- 生成产品时光机 XLSX。

## 自然语言触发要点

新增 Skill 需要能识别：

- “查排名 / 每日排名 / 推排名 / 查坑位” -> `查排名`
- “运营时光机 / 运营流量趋势 / 流量变化 / 流量词数量变化” -> `运营时光机`
- “产品时光机 / 关键词产品时光机 / 按关键词查产品销量” -> `产品时光机`

如果用户说“只要流量词数量变化”，应映射为 `运营时光机` 且 `type=all`。如果用户说“只要流量变化”，应不传 `type` 或传空值。

## 主要风险

- SIF 部分接口返回业务成功码可能不是固定 `0`，必须复用当前 `SifApiClient._raise_for_business_error` 的宽松成功码策略。
- 产品时光机以关键词为主，CLI 当前 `--asin` 为必填，需要调整为按 feature 校验。
- 现有 `SifApiClient` 没有公开 JSON POST 方法，新增模块需要公共 `post_json` 方法调用列表接口。
- `运营时光机` 的 `type` 字段默认是否完全不传或传 `null` 需要以 SIF Network 为准。基于用户说明，建议默认不传，选择流量词数量变化时传 `type=all`。
- 文件名应延续 SIF 下载命名风格；如果接口没有返回原始文件名，目前实现仍需用中文业务名 + 关键参数 + 时间戳生成稳定文件名。

## 研究结论

本次扩展适合采用“平台模块 + 场景 Provider”的方式实现：

- 新增 `opscli/sif/ranking/`、`opscli/sif/operation_time_machine/`、`opscli/sif/product_time_machine/`。
- 每个模块包含 `scenarios.py` 与 `provider.py`。
- 复用 `SifRunRequest`，补充 `keyword`、`granularity`、`last_months`、`change_type` 等字段。
- 复用 SIF 模块已有国家字段，不调整 `opscli/sif/sites.py` 之外的新映射表。
- CLI、MCP、Skill 都只扩展现有 SIF 入口。
- 输出保持 `params.json`、`raw.json`、`result.json`、XLSX 文件四件套，MCP 保持下载链接能力。

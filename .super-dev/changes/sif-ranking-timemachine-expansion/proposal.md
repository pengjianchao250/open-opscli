# SIF 查排名与时光机能力扩展 Proposal

## 背景

现有 SIF 平台已支持 `查销量`、`查流量`、`多产品对比`，并通过同一套 CLI、Provider、SIF 登录、MCP Tool、Skill 和输出目录机制交付。本次新增 `查排名`、`运营时光机`、`产品时光机`，需要保持相同的接入模型。

## 目标

- 新增 `opscli sif run 查排名 --asin ...`
- 新增 `opscli sif run 运营时光机 --asin ...`
- 新增 `opscli sif run 产品时光机 --keyword ...`
- MCP `sif_run` 支持上述 feature，并返回下载链接。
- Skill 支持自然语言触发新增 feature。
- 列表接口 JSON 写入 `raw.json/result.json`，下载接口保存 XLSX。
- 站点字段复用 `opscli.sif.sites.normalize_site` 和现有 `SITE_ALIASES`。

## 非目标

- 不新增顶级命令。
- 不引入新的 SIF 登录方式。
- 不引入新的国家/站点字段定义。
- 不请求真实 SIF 网络作为单元测试依赖。

## 设计摘要

- 新增三个 SIF feature 子模块：`ranking`、`operation_time_machine`、`product_time_machine`。
- 扩展 `SifRunRequest`，支持 `keyword`、`granularity`、`last_months`、`change_type`。
- 给 `SifApiClient` 增加公开 `post_json` 方法，用于列表接口。
- 扩展 CLI、`SifServiceManager`、MCP `sif_run` 和 `ops-sif` Skill。
- 默认输出目录按 feature 写入用户级配置目录。

## 验收

- `opscli sif features --pretty` 列出新增三个 feature。
- 新增三类 feature 的 Provider 单测能验证 payload、raw/result 和 XLSX 落盘。
- MCP `sif_run` 能接收 `keyword/granularity/last_months/change_type`。
- SIF 测试集与 MCP SIF 测试通过。

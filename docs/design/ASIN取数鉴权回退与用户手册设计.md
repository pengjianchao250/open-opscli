# ASIN 取数鉴权回退与用户手册设计

## 背景

ASIN 实时刊登取数默认使用当前用户的 Polaris JWT，以保证返回结果受个人刊登权限约束。本地 `polaris_enabled=false`、Polaris 系统未注册、JWT 获取接口异常或 Token 失效时，当前 `user` 模式会在个人 JWT 和直接 exchange 均失败后终止，无法自动使用 OPS 托管的 BJX Token。

同时，现有 ASIN 取数说明分散在 Skill、旧批量手册和代码帮助中，缺少 `live-data`、`fetch-file`、Yicopy、类目 Top10 的统一参数说明，以及 CLI/MCP 成功和失败返回协议。

## 目标

- `user` 模式优先使用当前用户 Polaris JWT。
- 个人 JWT 和直接 Token exchange 均失败时，自动回退 OPS 托管 BJX Token。
- `managed` 和 `bi_login` 显式模式保持原有语义。
- 新增一份 CLI 用户命令手册和一份 MCP ASIN 工具手册。
- 每个公开取数命令均给出成功、失败返回示例和字段含义。
- 手册只包含 `live-data`、`fetch-file`、`yicopy-keyword-engine`、`category-top` 及对应 MCP 工具，不包含 `collect`。

## 非目标

- 不改变 OPS Device Flow 登录流程。
- 不改变 `polaris_enabled` 的配置优先级。
- 不改变 BI 登录账号模式或托管 BJX Token 接口。
- 不新增 CLI/MCP 公开参数。
- 不在手册中暴露真实 Token、Cookie、Session ID、账号或密码。

## 鉴权流程

### user 模式

默认模式由 `OPSCLI_ASIN_DATA_LISTING_AUTH_MODE` 未设置、为空、`user`、`current_user` 或 `personal` 触发。

```text
1. AuthClient.build_request_auth("polaris")
2. 失败后使用本地 session_id 请求 /api/auth/cli-token
3. 仍失败后使用 OPS JWT 请求
   /dataMetrics/v1/asin-report-files/polaris-bjx-token
4. 三条路径均失败才返回 POLARIS_USER_AUTH_MISSING
```

个人 JWT 成功时不得请求 BJX Token。BJX Token 只作为可用性兜底，不改变默认的个人权限优先策略。

### managed 模式

`OPSCLI_ASIN_DATA_LISTING_AUTH_MODE=managed` 时直接请求 BJX Token，不尝试个人 Polaris JWT。

### bi_login 模式

`OPSCLI_ASIN_DATA_LISTING_AUTH_MODE=bi_login` 时保持现有 BI 登录链路，不自动切换个人 JWT 或 BJX Token。

## Polaris 本地开关

配置文件位置：

```text
Windows: %USERPROFILE%\.config\opscli\config.ini
macOS/Linux: ~/.config/opscli/config.ini
```

启用示例：

```ini
[systems]
polaris_enabled = true
```

也可使用进程环境变量：

```text
OPSCLI_POLARIS_ENABLED=true
```

优先级保持为进程环境变量、项目 `.env`、用户 `config.ini`、代码默认值。用户希望严格按个人权限取数时应启用 Polaris 并执行登录/Token 检查；关闭时 `live-data` 仍可通过直接 exchange 或 BJX Token 兜底，但返回权限可能来自托管账号。

## 错误协议

三条鉴权路径都失败时，错误信息需要保留路径摘要，但不得包含 Token、Cookie、Session ID、密码或响应敏感正文。

```json
{
  "code": "POLARIS_USER_AUTH_MISSING",
  "message": "Polaris user auth is missing or invalid: ...; direct token exchange failed: ...; managed BJX token fallback failed: ..."
}
```

现有 CLI 和 MCP envelope 保持不变：

```json
{
  "success": false,
  "command": "asin-data live-data",
  "data": null,
  "error": {
    "code": "...",
    "message": "..."
  }
}
```

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "...",
    "message": "..."
  },
  "feedback": {}
}
```

## 手册产物

### CLI 手册

路径：`docs/guide/ASIN取数CLI命令手册.md`

内容：

- 安装、升级、登录和 Polaris 开关。
- `live-data` 的 `data_scope`、`return_mode`、日期、站点和 OSS 上传。
- `fetch-file` 支持的 `basic/bi/keyword_reverse/keyword_miner/competitor/rufus`。
- `yicopy-keyword-engine` 的输入、输出格式和文件写入。
- `category-top` 的日期、站点、Top 数量、补充取数和 OSS 上传。
- 四个命令的成功与失败 JSON。
- 常见错误、退出码和恢复动作。
- 明确禁止使用 `collect` 作为本手册的取数入口。

### MCP 手册

路径：`docs/guide/ASIN取数MCP工具手册.md`

内容：

- `asin_data_live_data`。
- `asin_data_fetch_file`。
- `asin_data_yicopy_keyword_engine`。
- `asin_data_category_top`。
- 参数类型、默认值、成功和失败 envelope。
- HTTP/SSE 与本地 stdio 的认证要求。
- Polaris 个人 JWT 和 BJX Token 回退由服务端自动执行，调用方不得传递或读取敏感 Token。

## 返回示例原则

- 示例必须来自当前代码契约或测试 mock，不使用推测字段。
- 大型 `rows`、`raw` 和 Excel 内容只展示最小代表性结构。
- `live-data` 分别展示 `content`、`url_only` 和 `ai_ready` 的关键差异。
- Top10 展示 `category_top`、`listing_basic`、`crawler_details` 三个 dataset。
- 所有 URL 使用 `https://example.oss/...`，所有认证值使用 `<redacted>`。

## 测试范围

- user 模式个人 JWT 成功时不调用 BJX Token。
- Polaris 未注册时，直接 exchange 失败后回退 BJX Token。
- `/api/auth/cli-token` 返回 HTTP 500 时回退 BJX Token。
- BJX Token 成功时刊登请求使用其 Bearer Token。
- 三条路径均失败时错误包含三段原因且不包含敏感值。
- managed 与 bi_login 模式行为不变。
- CLI/MCP 手册中的命令名、参数枚举和工具名与代码一致。
- 手册不存在 `asin-data collect` 取数示例。

## 验收标准

- 默认 user 模式在个人 Polaris JWT 不可用时仍可通过 BJX Token 获取刊登数据。
- 个人 JWT 可用时保持个人权限，不提前使用托管账号。
- CLI、MCP 和 Top10 自动复用同一鉴权回退。
- 两份 Markdown 手册可直接提供给普通用户或 AI Skill 使用。
- 定向鉴权、ASIN CLI、MCP 和文档契约测试全部通过。


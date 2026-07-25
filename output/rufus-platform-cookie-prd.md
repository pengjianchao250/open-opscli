# Rufus 平台 Cookie CLI PRD

日期：2026-06-08

## 目标

为 `opscli amazon-rufus` 增加平台 Cookie 后端同步 CLI，让 Agent 或用户通过 `platform`、`country`、`content` 三字段调用 OPS 后端 `/v1/platform-cookies` 保存或读取当前用户的平台 Cookie content。Rufus 的内部状态统一打包进 `content`。

## 非目标

- 不实现 `cookie_content`、账号、域名、过期时间、备注等独立 CLI 参数。
- 不要求用户在聊天中粘贴 Cookie 原文。
- 不新增 MCP Tool。
- 不在 Skill 目录增加 Python 脚本。

## 用户故事

### 保存平台 Cookie 记录

作为 Agent，我希望通过一个只包含平台、国家和 stdin content 的 CLI 命令触发后端保存或覆盖当前用户的平台 Cookie content。

验收标准：

- 命令格式：`opscli amazon-rufus platform-cookie save <PLATFORM> <COUNTRY> --from-stdin --pretty`。
- CLI 请求体只包含 `{"platform": "<PLATFORM>", "country": "<COUNTRY>", "content": "<CONTENT>"}`。
- `PLATFORM` 不能为空，超过 50 字符应在本地拒绝。
- `COUNTRY` 必须是 2 位字母国家代码。
- `CONTENT` 不能为空，只从 stdin 读取。
- 请求自动携带 ops JWT 和 session cookie。
- CLI 保存成功输出不回显 `content`。

### 读取平台 Cookie content

作为 Agent，我希望读取当前用户在指定平台和国家的 Cookie content，用于内部 Rufus 状态恢复。

验收标准：

- 命令格式：`opscli amazon-rufus platform-cookie get <PLATFORM> <COUNTRY> --pretty`。
- CLI 使用 `GET /v1/platform-cookies?platform=<PLATFORM>`。
- 命中且国家匹配时输出 `status=exists` 和 `content`。
- 未命中业务码 `404` 时输出 `status=missing`，命令本身成功退出。
- 最终回复和报告不得展示 `content`；CLI get 输出仅供内部工具消费。

## CLI 输出草案

保存成功：

```json
{
  "success": true,
  "command": "amazon-rufus platform-cookie save",
  "data": {
    "platform": "amazon",
    "country": "US",
    "status": "saved",
    "message": "保存成功",
    "content_length": 1234
  },
  "error": null
}
```

读取命中：

```json
{
  "success": true,
  "command": "amazon-rufus platform-cookie get",
  "data": {
    "platform": "amazon",
    "country": "US",
    "status": "exists",
    "message": "操作成功",
    "content": "{\"country\":\"US\",\"storage_state\":{\"cookies\":[],\"origins\":[]}}",
    "content_length": 62
  },
  "error": null
}
```

查询未命中：

```json
{
  "success": true,
  "command": "amazon-rufus platform-cookie get",
  "data": {
    "platform": "amazon",
    "country": "US",
    "status": "missing",
    "message": "该平台尚未保存 Cookie",
    "content": "",
    "content_length": 0
  },
  "error": null
}
```

## 成功指标

- CLI 保存只接收平台、国家和 stdin content。
- Transport 测试覆盖 GET/POST 的 URL、鉴权、请求体和 query 参数。
- Browser state store 测试覆盖完整 Rufus record 通过远端 `content` 往返并被 provider 读取。
- 默认 Rufus manager/provider 状态读写不再创建、读取或依赖 `browser-state-<COUNTRY>.json`；显式 local fallback 测试需在用例名中标明。
- CLI/Manager 测试覆盖 save/get 和业务码 404 映射。
- Skill 文档说明使用 `platform-cookie save/get`，且除 `platform/country/content` 外不拆字段。
- 相关定向测试通过。

## 安全边界

输出禁止包含：

- `cookie_content` 独立字段
- Cookie header
- Authorization
- headers
- payload
- `storage_state`
- seed request

`content` 本身可能包含敏感状态，允许 CLI get 输出给内部工具消费，但不得写入最终回复、报告或 feedback。

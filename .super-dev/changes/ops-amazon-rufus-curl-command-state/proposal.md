# ops-amazon-rufus cURL 命令态变更提案

## 背景

Rufus 当前将登录态中的 streaming 请求材料保存为结构化 `curl_data` 对象，并在读取端兼容 `storage_state`、顶层 `headers`、`payload_template`、`streaming_url` 等旧字段。该结构和浏览器 Copy-as-cURL 的用户心智不一致，也带来多套等价字段的维护成本。

## 目标

将 Rufus 后端请求凭证的 canonical 保存结构切换为 `curl` 命令字符串，格式贴近浏览器 Copy-as-cURL：

```text
curl 'https://www.amazon.com/rufus/cl/streaming?...' -H 'accept: */*' -H 'cookie: ...' --data-raw '{"queryContext":{"query":""}}'
```

读取端只解析 `record["curl"]`，不再兼容旧 `curl_data`、顶层请求字段或 `storage_state` fallback。

## 范围

1. 修改 Rufus 状态保存服务，写入 `version=2` 和 `curl` 字符串。
2. 修改后端凭证 provider，只从新 `curl` 字段解析请求材料。
3. 修改登录态状态判断，使 `can_get_backend` 和 `get_backend` 使用同一新结构。
4. 更新测试和 `ops-amazon-rufus` skill 文档。

## 非目标

1. 不迁移历史平台 Cookie content。
2. 不新增 MCP 入参或 CLI 明文输出。
3. 不在 skill 目录新增 Rufus 获取脚本。
4. 不修改默认题库和报告格式。

## 风险与处理

旧 `curl_data` 或仅有 `storage_state` 的用户会被判定为 `invalid`，需要重新执行登录采集或重新保存 Copy-as-cURL。CLI/MCP 输出继续保持脱敏，不能展示 `curl`、cookie、headers、payload 或平台 Cookie content。

## 验收

1. 新保存 content 包含 `curl`，不包含 `curl_data`。
2. `RufusBackendSecretProvider` 只接受新 `curl` 结构。
3. `login_status` 对旧结构返回不可用摘要。
4. Rufus 相关目标测试通过。

# ops-amazon-rufus cURL 命令态调研

## 背景

用户要求将 Rufus skill 保存用户登录态时使用的 cURL 参数改为浏览器 Copy-as-cURL 一致的命令格式，即字段内容应类似 `curl 'https://...' -H '...' --data-raw '...'`，尽量不包含无意义转义符。同时，使用该登录态的地方只保留新结构解析，不再兼容旧结构。

本轮处于 Super Dev `research` 阶段，只产出调研与设计文档，不进入代码实现。

## 本地代码现状

Rufus 获取代码不在 skill 模板目录中。`opscli/skills/templates/ops-amazon-rufus/README.md` 明确说明获取代码归属 `opscli/mcp/tools/amazon_rufus.py` 和 `opscli/amazon_rufus/`，skill 模板只作为 MCP-only 入口索引。

当前相关链路如下：

1. `RufusCurlParser.parse(raw_curl)` 已支持解析浏览器 Copy-as-cURL 文本，识别 URL、`-H/--header`、`-b/--cookie` 和 `--data*` 系列参数。
2. `RufusManager.save_curl()` 接收用户从 stdin 输入的 raw cURL，解析为结构化 `ParsedCurlRufusRequest`，再通过 `RufusBrowserStateStore.save()` 保存。
3. `RufusBrowserStateStore._build_seed_record()` 当前保存结构化 `curl_data` 对象，包含 `url`、`headers`、`cookies`、`payload_template`，同时保留 `streaming_url`、`headers`、`payload_template`、`seed_request` 等旧字段。
4. `RufusBackendSecretProvider.load()` 当前优先解析 `curl_data`，并兼容旧字段和 `storage_state` 派生 Cookie。
5. `RufusManager.get_backend()` 通过 `RufusBackendSecretProvider` 读取登录态，再交给 `HeadlessRufusClient.query()` 请求 `/rufus/cl/streaming`。

现状问题：

1. `curl_data` 是内部对象，不是浏览器 Copy-as-cURL 的原始体验，人工查看或从浏览器粘贴时不直观。
2. `curl_data.payload_template` 作为 JSON 嵌套在平台 Cookie content 内，展示时会产生较多转义。
3. `RufusBackendSecretProvider` 仍有旧字段 fallback，和“只保留新结构解析代码”的要求不一致。

## 联网调研

curl 官方 manpage 说明 `-H/--header` 可添加 HTTP header，`-b/--cookie` 可发送 Cookie，`--data-raw` 属于 `--data` 类请求体参数，URL 可作为命令参数或通过 `--url` 指定。来源：<https://curl.se/docs/manpage.html>

结论：

1. 新保存结构使用普通 cURL 命令字符串是合理的，因为它可以完整表达 Rufus streaming URL、headers、Cookie 和 JSON body。
2. 为贴近浏览器 Copy-as-cURL，命令应使用 `curl '<url>' -H '<header>: <value>' ... --data-raw '<json>'` 形态。
3. 为减少转义，应生成单行命令，不使用 shell 续行反斜杠；参数值优先单引号包裹，只有值中包含单引号时才做必要 shell quoting。

## 新结构建议

平台 Cookie content 最终决策为直接保存 Rufus streaming cURL 命令字符串，而不是继续保持 Rufus 状态 JSON 容器：

```text
curl 'https://www.amazon.com/rufus/cl/streaming?tabId=tab-1&programId=NILE_CLASSIC%3Adesktop-cl' -H 'accept: */*' -H 'anti-csrftoken-a2z: csrf-token' -H 'content-type: application/json' -H 'cookie: session-id=abc; ubid-main=def' --data-raw '{"queryContext":{"query":""},"pageContext":{"targetUrl":"https://www.amazon.com/dp/B0TEST1234","targetPageMetadata":[{"type":"ASIN","value":"B0TEST1234"}]}}'
```

说明：

1. 远端 `content` 必须以 `curl ` 开头。
2. 不再保存 `curl_data`。
3. 不再保存顶层旧字段 `streaming_url`、`headers`、`payload_template` 作为消费 fallback。
4. 本地 fallback 文件可以继续保存 JSON record；远端接口的 `content` 不再引入 JSON 级转义。
5. Cookie、headers、payload 仍属于敏感内容，不进入 MCP 响应、报告、Agent 回复或 feedback。

## 影响面

需要修改的代码边界：

1. `opscli/amazon_rufus/services/browser_state_store.py`
   - 将 seed 保存结构从 `curl_data` 对象改为 `curl` 命令字符串。
   - 远端平台 Cookie content 直接保存 cURL 命令；本地 fallback 继续保存 JSON record。
   - 增加内部 cURL 命令构造函数，负责 header 过滤、payload compact JSON、shell 参数 quoting。
2. `opscli/amazon_rufus/services/backend_secret.py`
   - 删除 `_normalize_curl_data()` 和旧字段 fallback。
   - 新增或复用 `RufusCurlParser`，只从 cURL 命令解析请求材料。
   - 裸 cURL content 读取时，从 payload 的 `pageContext` 合成内部 `SeedRequestRecord`。
3. `opscli/amazon_rufus/services/manager.py`
   - `save_curl()` 可先解析用户 raw cURL，再保存为规范化后的 browser-like `curl` 命令。
   - `login_status()` 的 `can_get_backend` 应以 `curl` 可解析为准，避免旧 `storage_state` 被误判为可用后端凭证。
4. 测试
   - 更新 `curl_data` 断言为 `curl` 命令断言。
   - 增加旧 `curl_data` 不再兼容的失败测试。
   - 保留敏感字段不输出测试。

## 风险

1. 旧平台 Cookie content 中只有 `curl_data` 或 `storage_state` 的用户需要重新执行 `amazon_rufus_watch_login` 或重新保存 Copy-as-cURL。
2. 如果 cURL 命令中参数值包含单引号，生成器必须使用必要 shell quoting；这会出现少量不可避免的转义。
3. 如果只靠 `curl` 解析，`login_status` 和 `get_backend` 的可用性必须保持一致，否则会出现状态显示可用但获取失败。

## 研究结论

推荐实施“远端 content 直接保存 `curl` 命令字符串，cURL 为唯一后端凭证输入”的方案。它符合用户对浏览器 Copy-as-cURL 一致性的要求，也能按 YAGNI 删除旧 `curl_data` / `storage_state` 凭证兼容分支，降低后续状态结构维护成本。

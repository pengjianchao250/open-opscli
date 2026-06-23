# ops-amazon-rufus cURL 命令态架构

## 架构决策

远端平台 Cookie content 采用单一 canonical 文本：

```text
/v1/platform-cookies content -> raw cURL -> RufusCurlParser.parse() -> RufusSecret -> HeadlessRufusClient.query()
```

旧链路：

```text
record["curl_data"] / record["headers"] / record["payload_template"] / storage_state fallback
```

本次移除旧 `curl_data` / `storage_state` 作为后端凭证的消费端兼容。远端历史 JSON record 仅允许作为过渡读取，其中仍必须包含新 `curl` 字段。

## 新数据契约

平台 Cookie content 中直接保存浏览器 streaming cURL 命令态：

```text
curl 'https://www.amazon.com/rufus/cl/streaming?tabId=tab-1&programId=NILE_CLASSIC%3Adesktop-cl' -H 'accept: */*' -H 'anti-csrftoken-a2z: csrf-token' -H 'content-type: application/json' -H 'cookie: session-id=abc; ubid-main=def' --data-raw '{"queryContext":{"query":""},"pageContext":{"targetUrl":"https://www.amazon.com/dp/B0TEST1234","targetPageMetadata":[{"type":"ASIN","value":"B0TEST1234"}]}}'
```

字段规则：

1. 远端 `content` 本身必须为 `curl ` 开头的命令字符串。
2. cURL 是唯一后端请求材料来源。
3. `country` 仍由平台 Cookie API 外层字段承载，并必须和调用国家一致。
4. 本地 fallback 文件可继续保存 `version=2`、`curl` 和脱敏 `seed_request` 元数据，便于本机调试。
5. `curl_data`、顶层 `headers`、顶层 `payload_template`、顶层 `streaming_url` 不再写入远端 content。

## 保存流程

### watch-login 保存

```text
BrowserAttachService.watch_login_and_capture_seed_request
  -> 返回 storage_state 和 SeedRequestRecord
RufusManager.watch_login
  -> RufusBrowserStateStore.save(..., seed_request)
RufusBrowserStateStore.save
  -> 从 seed_request.request_headers 提取 Cookie
  -> 过滤 authorization、proxy-authorization、content-length
  -> request_body 解析为 compact JSON
  -> 构造 browser-like curl 命令
  -> 远端 content 直接保存 curl 命令
  -> 本地 fallback 保存 version=2、curl、seed_request 元数据
```

### curl save 保存

```text
RufusManager.save_curl(raw_curl)
  -> RufusCurlParser.parse(raw_curl)
  -> 使用 ParsedCurlRufusRequest 规范化 URL、headers、cookies、payload_template
  -> RufusBrowserStateStore.save_curl_command(...)
  -> 远端 content 直接保存 curl 命令，本地 fallback 保存 JSON record
```

说明：如果现有 `save()` 方法继续承载两种保存来源，应把 cURL 构造逻辑拆成私有小函数，避免重复。不要新增泛化存储抽象。

## 读取流程

```text
RufusBackendSecretProvider.load(country)
  -> record = browser_state_store.load(country)
     - 远端裸 cURL 会被包装为 {"country": country, "version": 2, "curl": raw_curl}
     - 远端旧 JSON record 仍可读取其中 curl
  -> raw_curl = record["curl"]
  -> parsed = RufusCurlParser.parse(raw_curl)
  -> seed_request = _load_seed_request(record, parsed)
     - JSON record 有 seed_request 时复用脱敏元数据
     - 裸 cURL 时从 payload pageContext 合成内部 SeedRequestRecord
  -> return RufusSecret(
       url=parsed.url,
       headers=parsed.headers,
       cookies=parsed.cookies,
       payload_template=parsed.payload_template,
       storage_state=None,
       seed_request=seed_request
     )
```

删除：

1. `_normalize_curl_data()`
2. 旧 `record["headers"]` fallback
3. 旧 `record["payload_template"]` fallback
4. 旧 `record["streaming_url"]` fallback
5. `storage_state` 派生 Cookie 作为后端凭证 fallback

## cURL 命令构造规则

推荐新增私有函数：

```python
def _build_curl_command(self, *, url: str, headers: dict[str, str], cookies: str, payload_template: dict) -> str:
    """构造浏览器 Copy-as-cURL 风格的单行 cURL 命令。"""
```

规则：

1. 输出单行，以 `curl ` 开头。
2. URL 使用第一个位置参数，不默认使用 `--url`。
3. headers 使用 `-H '<key>: <value>'`。
4. Cookie 使用 `-H 'cookie: <cookie header>'`，保证浏览器 Copy-as-cURL 风格。
5. payload 使用 `--data-raw '<compact json>'`。
6. header 过滤名单保持：`cookie`、`authorization`、`proxy-authorization`、`content-length`。Cookie 由单独 `-H 'cookie: ...'` 输出。
7. JSON 使用 `json.dumps(payload_template, ensure_ascii=False, separators=(",", ":"))`。
8. shell quoting 优先单引号；只有内容包含单引号时使用必要转义。

## 登录状态判断

`RufusManager.login_status()` 不应再只检查 `storage_state`。建议流程：

```text
record = browser_state_store.load(country)
parsed = curl_parser.parse(record["curl"])
can_get_backend = parsed.cookies 非空且 parsed.url 包含 /rufus/cl/streaming
session_cookie_count = Cookie header 按 ; 拆分后的有效键值数量
has_streaming_request = can_get_backend
```

旧结构或解析失败：

```json
{
  "status": "invalid",
  "has_login_state": false,
  "can_get_backend": false,
  "session_cookie_count": 0,
  "has_streaming_request": false
}
```

## 测试计划

1. `test_browser_state_store_saves_curl_command_state`
   - 断言远端保存 content 直接以 `curl ` 开头。
   - 断言不包含 `curl_data`、顶层 `headers`、顶层 `payload_template`。
2. `test_backend_secret_provider_loads_only_curl_command`
   - 使用新结构成功还原 `RufusSecret`。
3. `test_backend_secret_provider_rejects_legacy_curl_data`
   - 只有旧 `curl_data` 时抛出 `RufusSecretNotReadyError`。
4. `test_manager_login_status_uses_curl_command`
   - 新结构 ready，旧结构 invalid。
5. `test_cli_curl_save_from_stdin_outputs_safe_summary`
   - 更新内部断言，继续确认输出不含 cookie、headers、payload、`curl`。
6. MCP schema 和敏感字段测试保持不变，确认没有新增 raw cURL 入参。

## 代码原则

1. KISS：远端保存结构只保留 cURL 命令文本，消费端只走 cURL 解析路径。
2. YAGNI：不做旧 `curl_data` / `storage_state` 迁移；仅兼容历史 JSON record 中的新 `curl` 字段。
3. DRY：保存端和读取端复用 `RufusCurlParser` 的语义，避免再维护一套对象解析逻辑。
4. SOLID：`RufusBrowserStateStore` 负责持久化结构，`RufusCurlParser` 负责解析命令，`RufusBackendSecretProvider` 只做凭证装配。

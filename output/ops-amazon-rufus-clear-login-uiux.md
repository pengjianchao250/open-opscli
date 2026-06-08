# ops-amazon-rufus 登录恢复增强 UIUX

## 体验范围

本轮没有图形界面，不涉及图标库、字体系统、design token system、组件生态或页面骨架。体验设计限定在 CLI 命令顺序、Agent 回复、错误处理和敏感信息隐藏。

若后续新增 Web UI，必须重新冻结：

1. 图标库：Lucide、Heroicons 或 Tabler 中选择。
2. 字体系统。
3. design token system。
4. 组件生态。
5. 页面骨架。

## 用户体验目标

1. MCP 失败后不要让用户手动判断是否需要清理旧状态。
2. 用户只需要完成 Amazon 登录，不需要告诉 Agent “我已登录”。
3. 用户登录后即使 Amazon 跳回首页，也能自动回到商品页继续捕获。
4. 恢复失败时给出明确下一步，不重复弹登录窗口。
5. 回复和报告不泄露任何登录态或请求材料。

## 推荐恢复流程

当 `amazon_rufus_get` 返回可恢复错误时，Agent 内部执行：

```powershell
opscli amazon-rufus logout US --pretty
opscli amazon-rufus watch-login B0TEST1234 US --launch-if-needed
```

用户看到的行为：

1. 旧登录态被清理。
2. Chrome 调试窗口打开 Amazon 国家站点。
3. 用户在窗口中登录 Amazon。
4. 如果 Amazon 登录后跳到首页，CLI 自动识别已登录。
5. CLI 自动打开目标 ASIN 商品页。
6. CLI 捕获 Rufus streaming 请求并保存状态。
7. Agent 重新调用 `amazon_rufus_get` 并返回本次 `report_path`。

## Agent 回复规则

### 恢复开始

可以简短说明：

```text
MCP 获取失败，正在清理 US 站点旧 Rufus 登录态并进入一次登录恢复。
```

不要输出：

1. `logout` 完整 JSON 中的本地路径细节。
2. cookie、headers、payload、storage_state、seed request。
3. CDP 调试内部字段。

### 等待用户登录

可以说明：

```text
请在打开的 Amazon 窗口完成登录；登录后即使跳回首页，命令会自动打开商品页继续捕获 Rufus 请求。
```

用户不需要在聊天中回复“已登录”。

### 恢复成功

最终只展示 MCP 重试成功返回的本次报告路径：

```text
Rufus 报告已生成：output/amazon-rufus/B0TEST1234-YYYYMMDD-HHMMSS.md
```

### 清理失败

如果 `logout` 因 profile 被占用失败，建议回复：

```text
清理 Rufus 调试 Chrome profile 失败。请关闭对应 opscli Rufus 调试 Chrome 窗口后重试；本轮不会继续使用旧 profile 进入登录恢复。
```

不要自动改用 `--no-browser-profile`，除非用户明确要求保留旧 profile 排障。

### 二次失败

如果恢复后 MCP 仍失败：

```text
本次 Skill 调用已触发过一次登录恢复，仍未成功；为避免重复登录循环，不再打开第二次登录窗口。错误：<ERROR_CODE>: <message>
```

## CLI 输出要求

`logout --pretty` 成功输出只作为内部判断：

```json
{
  "success": true,
  "command": "amazon-rufus logout",
  "data": {
    "country": "US",
    "state_deleted": true,
    "browser_profile_deleted": true,
    "mcp_state_cleared": true
  },
  "error": null
}
```

`watch-login --pretty` 成功输出只允许展示脱敏摘要字段：

```json
{
  "country": "US",
  "asin": "B0TEST1234",
  "saved": true,
  "login_detected": true,
  "cookie_count": 2,
  "origin_count": 1,
  "streaming_request_saved": true,
  "has_payload_template": true
}
```

## 敏感信息隐藏

任何最终回复、报告、Skill 文档示例和错误说明都不得包含：

1. cookie 值
2. `session-id`
3. `session-token`
4. headers 明文
5. payload template 明文
6. `storage_state`
7. seed request 明文
8. 本地加密状态文件内容
9. 完整 Rufus streaming URL

## 与现有命令关系

| 命令 | 定位 |
| --- | --- |
| `amazon-rufus logout` | 恢复前清理旧登录态和 opscli-owned Chrome profile |
| `amazon-rufus watch-login` | 等待用户登录，登录后自动打开商品页并捕获 streaming |
| `amazon-rufus get` | 当前宿主没有 MCP 工具时的兼容 CDP 获取入口 |
| `cookie save/status` | 手工保存和检查 Cookie 状态 |
| `curl save` | 手工保存 Copy-as-cURL seed 与 payload template |

## 体验结论

默认恢复路径应让用户只做一件事：在 Amazon 窗口登录。清理旧状态、识别首页登录完成、打开商品页、捕获 streaming、重试 MCP 都由 Skill 和 CLI 自动完成，并且每轮最多恢复一次。

# amazon-rufus-cookie-cli-state Proposal

## 背景

`amazon_rufus_get` MCP 默认链路已经收敛为后端/headless 获取，并通过 `RufusBackendSecretProvider` 从本地加密状态派生 Cookie header。当前 CLI 只有 `init` 和 `save-state`，依赖用户在 CDP Chrome 中登录后捕获完整 Playwright `storage_state`。

本轮需要补齐 CLI cookie mock 状态入口：当用户已经有可用 Amazon Cookie 时，可通过 CLI 保存到同一套加密 Rufus 状态，再让 MCP 按原参数获取 Rufus。Skill 只做流程编排和确认，不解析或保存 cookie。

## 目标

1. 新增 CLI cookie mock 保存入口，支持从 stdin 读取 Cookie header 并加密保存为 Rufus 本地状态。
2. 新增 CLI cookie status 入口，输出脱敏可用性摘要。
3. 让 `RufusBackendSecretProvider` 可读取 cookie mock 保存的状态并继续支撑 `amazon_rufus_get`。
4. 保持 MCP 工具 schema 不变，只暴露 `amazon_rufus_get` 业务参数。
5. 同步 Skill 模板、已安装 Skill、README 和 reference，使 Skill 只编排 CLI/MCP 流程。

## 非目标

1. 不在 MCP 中新增 `cookie`、`headers`、`storage_state`、CDP 参数或 cookie 管理工具。
2. 不把 cookie 保存到仓库、Skill 目录或 `output/`。
3. 不实现远端账号池、后端 cookie API、自动续期或多账号轮转。
4. 不提供 `--cookie "<VALUE>"` 明文参数，避免 shell history 和进程列表泄漏。
5. 不删除现有 `init`、`save-state` 或 CLI `get` 兼容路径。

## 方案

新增服务：

```text
opscli/amazon_rufus/services/cookie_parser.py
```

新增 Manager 方法：

```text
RufusManager.save_cookie(country, cookie_header)
RufusManager.cookie_status(country)
```

新增 CLI：

```powershell
opscli amazon-rufus cookie save US --from-stdin
opscli amazon-rufus cookie status US
```

保存链路：

```text
stdin cookie
  -> RufusCookieParser.parse_cookie_header()
  -> RufusBrowserStateStore.save()
  -> CONFIG_DIR/amazon-rufus/browser-state-US.bin
```

读取链路：

```text
amazon_rufus_get
  -> RufusBackendSecretProvider.load(country)
  -> RufusBrowserStateStore.load(country)
  -> build_cookie_header()
```

## 验收

1. 单元测试覆盖 Cookie header 解析为最小 Playwright `storage_state`。
2. 单元测试证明 cookie mock 状态加密保存，文件中不含明文 cookie。
3. CLI `cookie save --from-stdin` 输出成功摘要且不泄露 cookie。
4. CLI `cookie status` 输出状态摘要且不泄露 cookie。
5. `RufusBackendSecretProvider` 能读取 `cookie save` 写入状态并派生 Cookie header。
6. MCP schema 仍不包含 cookie、headers、storage_state 或 CDP 参数。
7. Skill 模板与 `.agents` 副本同步，且不包含真实 cookie 或明文 cookie 示例。
8. 安装 Skill 后，用子 agent 提示词跑通 Rufus 获取真实流程。

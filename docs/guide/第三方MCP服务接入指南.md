# 第三方 MCP 服务接入指南

## 接入模型

opscli 通过统一上游 Gateway 接入第三方 MCP。生产服务只注册配置中明确审批的 Tool，不会把远端 `tools/list` 动态变化自动暴露给调用方。

每个上游使用独立 HTTP 连接池；每次 Tool 调用创建独立 MCP Session，并在调用完成、异常、取消或总截止时间到达后关闭。会话初始化最长等待 5 秒，关闭清理最长等待 1 秒，远端心跳不会延长配置中的 Tool 总截止时间。

## 准备配置

复制 `configs/mcp-upstreams.example.json`，为每个服务配置唯一 `id`。公开工具名必须使用 `ext_<server_id>_` 前缀，`input_schema` 必须保存经过审批的 JSON Schema 快照。

配置文件禁止保存真实 URL 和凭证，只保存对应环境变量名：

```powershell
$env:OPSCLI_MCP_UPSTREAM_CONFIG_PATH = "C:\opscli\mcp-upstreams.json"
$env:OPSCLI_UPSTREAM_VENDOR_URL = "https://mcp.vendor.example/mcp"
$env:OPSCLI_UPSTREAM_VENDOR_TOKEN_FILE = "C:\opscli\secrets\vendor-token"
```

Linux 部署使用等价环境变量和 Secret 挂载文件。Bearer Token 或自定义 Header 密钥只从 `secret_file_env` 指向的文件读取。

## 配置校验

```bash
opscli mcp upstream validate --config configs/mcp-upstreams.example.json --pretty
```

校验输出只包含服务 ID、URL 环境变量名、域名白名单和公开 Tool 名，不输出真实 URL、Header 或凭证。

## 强制约束

- 只支持 Streamable HTTP 出站调用。
- URL 必须使用 HTTPS，域名和端口必须命中精确白名单。
- URL 禁止用户名、密码、Query 和 Fragment，客户端禁止自动重定向。
- DNS 每次请求重新校验，并把校验后的 IP 直接用于实际连接，同时保留原域名的 Host 和 TLS SNI；默认拒绝回环、私网、链路本地、组播和保留地址。
- 参数在出站前按冻结 JSON Schema 校验。
- `idempotent` 只决定能否重试；`read_only` 和 `destructive` 必须根据真实副作用独立审批，禁止用幂等性推导。
- 非幂等 Tool 的 `max_attempts` 必须为 `1`；幂等 Tool 只重试建连失败、会话初始化超时和 HTTP 429/502/503，读写超时不重试。
- 所有重试共享同一个 Tool 总截止时间。
- 单服务和单用户分别执行并发限制；等待超过队列期限后快速失败。
- 连续基础设施失败达到阈值后熔断，熔断只影响对应上游。
- 参数、Schema 和原始 HTTP 响应流均有硬大小上限，超限会在 MCP 协议解析前中止下载。
- 单个上游的 URL、凭证或安全校验失败只禁用该服务，不阻止核心 MCP 和其他上游启动。

`allow_private_networks` 只应用于明确审批的内部 MCP，不应用于普通第三方服务。即使启用，也仍拒绝回环、链路本地、组播和保留地址。

## 新服务上线

1. 在隔离环境读取远端 `tools/list`。
2. 审核工具描述、参数 Schema、副作用和最长执行时间。
3. 只把需要开放的工具写入版本化配置。
4. 分别审批 `idempotent`、`read_only`、`destructive`；只有可靠幂等工具允许配置两次尝试。
5. 执行配置校验并部署环境变量与 Secret 文件。
6. 重启 opscli MCP，使新配置进入 Tool Catalog 和权限配置流程。
7. 在 OPS 后台为目标用户或角色开放对应 `ext_*` Tool。

当前配置采用启动时快照。修改配置、URL 或凭证文件后需要滚动重启，不支持运行中静默热更新。

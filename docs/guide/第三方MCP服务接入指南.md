# 第三方 MCP 服务接入指南

## 接入模型

opscli 通过统一上游 Gateway 接入第三方 MCP。生产服务只注册配置中明确审批的 Tool，不会把远端 `tools/list` 动态变化自动暴露给调用方。

每个上游使用独立 HTTP 连接池；每次 Tool 调用创建独立 MCP Session，并在调用完成、异常、取消或总截止时间到达后关闭。会话初始化最长等待 5 秒，关闭清理最长等待 1 秒，远端心跳不会延长配置中的 Tool 总截止时间。

## 准备配置

复制 `configs/mcp-upstreams.example.json` 到部署用户的 `~/.config/opscli/mcp-upstreams.json`，为每个服务配置唯一 `id`。公开工具名必须使用 `ext_<server_id>_` 前缀，`input_schema` 必须保存经过审批的 JSON Schema 快照。

固定内部 MCP 可以把 URL 和公共鉴权值直接写入部署配置：

```json
{
  "version": 1,
  "servers": [
    {
      "id": "pnd",
      "enabled": true,
      "url": "http://10.0.0.10:8008/mcp",
      "transport": "streamable_http",
      "allow_private_networks": true,
      "auth": {
        "type": "header",
        "header_name": "Authorization",
        "value": "Basic REPLACE_WITH_REAL_AUTHORIZATION"
      },
      "caller_identity": {
        "source": "email",
        "location": "header",
        "header_name": "X-Opscli-User-Email",
        "required": true
      },
      "tools": [
        {
          "remote_name": "list_available_datasets",
          "exposed_name": "ext_pnd_list_available_datasets",
          "description": "查询当前用户可访问的 PND 数据集目录。",
          "timeout_seconds": 30,
          "idempotent": true,
          "read_only": true,
          "destructive": false,
          "max_attempts": 2,
          "retry_delay_seconds": 0.1,
          "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": false
          }
        }
      ]
    }
  ]
}
```

`auth.value` 是可直接访问上游的明文凭证，因此该文件属于部署密钥文件：只能放在部署用户配置目录，不得提交到 Git、打包进发行物或写入日志。`opscli mcp upstream validate` 不会输出 URL、Header 名或凭证值。

`caller_identity` 不保存具体邮箱。opscli 会从已经通过 OPS API Key 校验的当前请求上下文读取 email，标准化后为该次 MCP Session 的每个 HTTP 请求增加 `X-Opscli-User-Email`。共享连接池不会保存或修改用户 Header；并发调用使用独立请求上下文，避免用户邮箱互相覆盖。缺少可信邮箱时，`required=true` 的上游会在建立远端调用前返回 `UPSTREAM_MCP_IDENTITY_REQUIRED`。

原有环境变量方式继续兼容，适用于不希望在同一配置文件保存 URL 或凭证的部署：

```powershell
$env:OPSCLI_MCP_UPSTREAM_CONFIG_PATH = "C:\opscli\mcp-upstreams.json"
$env:OPSCLI_UPSTREAM_VENDOR_URL = "https://mcp.vendor.example/mcp"
$env:OPSCLI_UPSTREAM_VENDOR_TOKEN_FILE = "C:\opscli\secrets\vendor-token"
```

使用旧格式时，`url_env` 与 `url` 二选一，`secret_file_env` 与 `auth.value` 二选一。Linux 部署可使用等价环境变量和 Secret 挂载文件。

## 配置校验

```bash
opscli mcp upstream validate --config configs/mcp-upstreams.example.json --pretty
```

校验输出只包含服务 ID、URL 环境变量名、域名白名单和公开 Tool 名，不输出真实 URL、Header 或凭证。

## 强制约束

- 只支持 Streamable HTTP 出站调用。
- 公网或域名 URL 必须使用 HTTPS；直接配置的 HTTP 只允许 `allow_private_networks=true` 时使用精确普通私网 IP。
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
- 内联 `auth.value` 不得进入版本库、终端输出、错误或日志；需要更高密钥治理强度时继续使用 `secret_file_env`。

`allow_private_networks` 只应用于明确审批的内部 MCP，不应用于普通第三方服务。即使启用，也仍拒绝回环、链路本地、组播和保留地址。

## 新服务上线

1. 在隔离环境读取远端 `tools/list`。
2. 审核工具描述、参数 Schema、副作用和最长执行时间。
3. 只把需要开放的工具写入版本化配置。
4. 分别审批 `idempotent`、`read_only`、`destructive`；只有可靠幂等工具允许配置两次尝试。
5. 执行配置校验并部署环境变量与 Secret 文件。
6. 重启 opscli MCP，使新配置进入 Tool Catalog 和权限配置流程。
7. 在 OPS 后台为目标用户或角色开放对应 `ext_*` Tool。

当前配置采用启动时快照。修改配置、URL、固定鉴权值或凭证文件后需要滚动重启，不支持运行中静默热更新。

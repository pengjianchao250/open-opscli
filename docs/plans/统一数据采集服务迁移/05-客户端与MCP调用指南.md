# 统一数据采集服务客户端与 MCP 调用指南

## 1. 调用原则

统一数据采集服务只改变部署位置，不统一业务命令和 Tool 名称：

```text
opscli seller-sprite ...      → seller_sprite_* Tool
未来其他业务 CLI              → 对应模块前缀 Tool
```

各模块继续维护自己的参数、状态和结果协议；CLI 和 MCP Host 统一访问 OPS 配置中心中的 `BI运营系统`，由通用 MCP 将数据采集 Tool 静默代理到 Collector。

## 2. 访问拓扑

```text
业务 CLI / MCP Host
  → OPS 配置中心签发当前用户的通用 MCP URL 和 API Key
  → data.http.mcpServers["BI运营系统"]
  → opscli-mcp
  → 同名数据采集 Tool 代理
  → OPSCLI_COLLECTOR_MCP_URL（内部地址）
  → opscli-collector-mcp
  → 已启用 Tool Bundle
```

客户端配置示例：

```json
{
  "success": true,
  "data": {
    "http": {
      "mcpServers": {
        "BI运营系统": {
          "type": "http",
          "url": "https://ops-mcp.example.com/mcp?api_key=mcp_xxx"
        }
      }
    }
  }
}
```

客户端必须精确选择 `BI运营系统`，不需要知道 Collector 域名。Collector 地址仅由通用 MCP 的部署环境配置，且不得包含共享 `api_key`。

## 3. CLI 用户

### 3.1 认证

CLI 使用本机 OPS 登录态获取远端配置：

```bash
opscli auth token status
```

未登录时：

```bash
opscli auth login
```

本机 Session/JWT 不传给业务 Tool。CLI 使用配置接口签发的用户 API Key 访问通用 MCP，通用 MCP 将同一用户 API Key 透传给 Collector，Collector 再次校验后使用隔离 CredentialStore。

### 3.2 SellerSprite 命令保持不变

```bash
opscli seller-sprite scenarios
opscli seller-sprite quota-status
```

普通任务：

```bash
opscli seller-sprite run keyword-reverse \
  --site US \
  --period 30d \
  --params '{"asin":"B0EXAMPLE1"}' \
  --page-size 100 \
  --export-format xls
```

保存 `data.job_id`，随后：

```bash
opscli seller-sprite job-status <job-id> --wait-seconds 30
opscli seller-sprite export <job-id>
```

批量状态：

```bash
opscli seller-sprite jobs-status <job-id-1> <job-id-2> --wait-seconds 30
```

Listing Analysis：

```bash
opscli seller-sprite listing-analysis-submit \
  --asin B0EXAMPLE1 \
  --station GLOBAL \
  --site US \
  --export-format json

opscli seller-sprite listing-analysis-status <job-id>
opscli seller-sprite listing-analysis-result <job-id> --export-format json
```

Listing Analysis 必须走 submit/status/result 三段式，不能传给普通 `run`，也不能使用批量普通状态接口。

### 3.3 管理员命令不远程代理

```text
opscli seller-sprite account-binding ...
opscli seller-sprite queue ...
```

这些命令操作执行主机本地 SQLite，必须在统一数据采集服务服务器、相同服务用户和相同配置目录执行。普通用户在自己电脑执行不能管理远端队列或账号。

### 3.4 `output_dir`

当前 SellerSprite CLI 仍接受 `--output-dir`，但远端会解释为服务器路径。迁移后公开客户端不应依赖该参数；服务端应拒绝绝对路径或强制解析到模块输出根目录。

## 4. MCP Host 配置

### 4.1 Query API Key 模式

```json
{
  "mcpServers": {
    "BI运营系统": {
      "type": "http",
      "url": "https://ops-mcp.example.com/mcp?api_key=mcp_xxx"
    }
  }
}
```

配置是 Secret，不提交 Git、不粘贴聊天、不进入截图和日志。MCP Host 不配置 Collector。

### 4.2 Bearer 模式

客户端支持自定义 Header 时优先：

```text
URL: https://ops-mcp.example.com/mcp
Authorization: Bearer mcp_xxx
```

具体 Header 配置格式以 MCP Host 文档为准。

### 4.3 Tool 可见性

连接到通用 MCP 不表示能调用所有 Collector Bundle：

```text
实际可调用 Tool
= 服务 Profile 注册 Tool
∩ API Key 允许 Tool
∩ 当前模块可用状态
```

客户端应先读取 Tool Catalog 或服务信息，不假定某个后续 Bundle 已部署。

## 5. SellerSprite MCP 调用

首次使用：

```text
seller_sprite_spec_must_read()
seller_sprite_scenarios()
seller_sprite_quota_status()
```

普通任务：

```text
seller_sprite_run(
  scenario="keyword-reverse",
  site="US",
  period="30d",
  params={"asin":"B0EXAMPLE1"},
  page_size=100,
  export_format="xls"
)
```

状态：

```text
seller_sprite_job_status(job_id="<job-id>", wait_seconds=30)
```

多个普通任务：

```text
seller_sprite_jobs_status(
  job_ids=["<job-id-1>", "<job-id-2>"],
  wait_seconds=30
)
```

Listing Analysis：

```text
seller_sprite_listing_analysis_submit(
  asin="B0EXAMPLE1",
  station="GLOBAL",
  site="US",
  export_format="json"
)

seller_sprite_listing_analysis_status(job_id="<job-id>")
seller_sprite_listing_analysis_result(
  job_id="<job-id>",
  export_format="json"
)
```

远端模式不向业务 Tool 传 `session_id/jwt`。如需认证预热，可调用 `auth_mcp_login()`。

## 6. SellerSprite 状态语义

| 字段 | 含义 |
|---|---|
| 顶层 `success` | MCP Tool 调用本身是否成功 |
| `data.state=queued` | 已持久化，等待工作槽 |
| `data.state=running` | Worker 已领取 |
| `data.state=succeeded` | 普通任务成功终态 |
| `data.state=failed` | 业务失败终态 |
| `data.ready=false` | 尚未完成，不是失败 |
| `data.export.url` | 用户应使用的 HTTPS 下载地址 |

`wait_seconds` 最大 30 秒。窗口到期只返回最新状态，不取消、不重排、不重复扣额度。待执行任务不得通过再次调用 `run` 查询状态。

## 7. SellerSprite 额度和账号

- 普通用户的普通任务和 Listing Analysis submit 消耗对应每日额度；
- 状态、结果、导出、场景和额度查询不消耗额度；
- 专属账号用户返回 `unlimited=true`；
- 专属账号任务不计次；
- 专属账号失效、解绑或改绑后失败，不回退公共账号池；
- 用户只能读取自己的任务。

## 8. 后续模块的客户端接入

后续模块保持自己的 CLI：

```python
class FutureCollectorRemoteAdapter(RemoteMcpAdapter):
    def __init__(self, ...):
        super().__init__(
            ...,
            preferred_name="BI运营系统",
            require_preferred=True,
        )
```

要求：

1. CLI 命令面不因部署合并改名；
2. Tool 名必须带模块前缀；
3. Adapter 不硬编码服务器 URL 或 API Key；
4. 通过配置中心获取当前用户的通用 MCP 授权 URL；
5. 严格选择 `BI运营系统`，Collector 地址不暴露给客户端；
6. 不把本机 Session/JWT 透传给远端业务 Tool；
7. 401 最多刷新配置后重试一次；
8. 业务状态协议由模块文档定义，不能套用 SellerSprite 规则。

## 9. 模块停写行为

模块进入 `draining` 时：

- 新提交 Tool 返回稳定“模块维护中”错误；
- 状态、结果和导出继续工作；
- 其他健康 Bundle 继续接受请求；
- 通用 MCP 不得把请求回退到本地业务实现；
- 客户端不得因维护错误重复提交。

## 10. 切流影响

### SellerSprite 首次切流

- CLI 命令和 Tool 名称不变；
- CLI 和 MCP Host 仍访问 `BI运营系统`，无需更新 Collector 地址；
- 通用 MCP 的 SellerSprite 同名 Tool 切换为 Collector 代理；
- 已保存 job ID 随状态数据迁移后继续查询；
- 通用 MCP 重启后加载 Collector 内部路由；
- 通用 MCP 不再注册 SellerSprite 本地实现。

### 后续 Bundle 切流

每个模块独立灰度：

1. 数据采集 Profile 加入 Bundle；
2. API Key Tool 白名单开放灰度用户；
3. 对应 Adapter 改为严格路由；
4. 迁移模块私有状态；
5. 完成验证后全量；
6. 从旧入口移除该 Bundle。

不能因为服务已存在就一次性把所有数据采集客户端切入。

SellerSprite 完整参数仍以[卖家精灵 MCP 接口直连接入说明](../../spec/卖家精灵MCP接口直连接入说明.md)和 `seller_sprite_spec_must_read` 为准。

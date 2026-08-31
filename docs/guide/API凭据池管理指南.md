# API 凭据池管理指南

本模块统一管理 SerpAPI、Canopy、scrape.do 的多个 API 账号。Keepa、卖家精灵继续使用原有集成账号配置，不受本模块影响。

## 数据模型

凭据池采用 `Provider 1:N Account 1:N Credential`：

- Provider：`serpapi`、`canopy`、`scrape_do`。
- Account：平台内的命名账号，包含启停状态、优先级和运行额度。
- Credential：账号的 API Key 版本；轮换后旧版本保留为已撤销记录。
- Runtime：剩余额度、重置时间、最近使用和最后错误。

API Key 按产品要求以明文存入 MySQL 的 `api_account_credentials.secret_value` 字段。交互输入仍然隐藏，管理列表和命令输出只返回掩码，不显示明文。

## 部署配置

后端 MCP 运行环境可以直接复用共享采集 MySQL 配置。凭据池优先读取以下专用变量；某个专用变量未设置时，会回退到对应的 `OPSCLI_COLLECTION_MYSQL_*` 变量，因此同一 MySQL 实例不需要维护两套连接配置：

```text
OPSCLI_API_CREDENTIAL_MYSQL_HOST
OPSCLI_API_CREDENTIAL_MYSQL_PORT
OPSCLI_API_CREDENTIAL_MYSQL_DATABASE
OPSCLI_API_CREDENTIAL_MYSQL_USER
OPSCLI_API_CREDENTIAL_MYSQL_PASSWORD
OPSCLI_API_CREDENTIAL_MYSQL_SSL_CA
```

例如生产服务已经配置了以下共享变量时，无需再重复配置 API 凭据池的 Host、Port、Database、User 和 Password：

```text
OPSCLI_COLLECTION_MYSQL_HOST
OPSCLI_COLLECTION_MYSQL_PORT
OPSCLI_COLLECTION_MYSQL_DATABASE
OPSCLI_COLLECTION_MYSQL_USER
OPSCLI_COLLECTION_MYSQL_PASSWORD
OPSCLI_COLLECTION_MYSQL_SSL_CA
```

若凭据池需要连接不同的数据库，只需为对应字段单独设置 `OPSCLI_API_CREDENTIAL_MYSQL_*`，该字段会覆盖共享配置。

初始化表结构时使用具有 DDL 权限的迁移账号：

```bash
opscli api-credentials init-schema
```

本地通用 MCP 通过 `D:\Gitlab\start-mcp.ps1` 启动时，可继续使用原有初始化参数：

```powershell
D:\Gitlab\start-mcp.ps1 -InitializeSchema
```

该参数只要求输入数据库密码，会先创建 API 凭据池表，再启动 MCP 并创建共享采集表。不需要生成或配置 API 凭据主密钥。

旧 v1 凭据表使用加密列。重新初始化时，空的 v1 表会自动升级为明文 v2 表；如果 v1 表中已有凭据，命令会拒绝自动迁移，避免丢失已有密文，需要先备份并人工迁移。

运行期账号只需要凭据表的必要读写权限，不应具备建表或修改表结构权限。

## 账号管理

新增主账号：

```bash
opscli api-credentials add --provider serpapi --name primary --priority 10 --remark "Google Trends 主账号"
```

新增备用账号：

```bash
opscli api-credentials add --provider serpapi --name backup-1 --priority 20
```

命令通过隐藏输入读取 API Key，不支持把明文 Key 放入命令参数。

查看账号：

```bash
opscli api-credentials list
opscli api-credentials list --provider serpapi
```

轮换、停用、启用和逻辑删除：

```bash
opscli api-credentials rotate --account-id 12
opscli api-credentials disable --account-id 12
opscli api-credentials enable --account-id 12
opscli api-credentials delete --account-id 12 --actor "admin@example.com"
```

同一 Provider 下可配置多个账号。运行时先选择最低优先级数值的可用账号，同优先级选择最久未使用的账号；冷却、禁用、失效、耗尽和已删除账号不参与正常领取。

`add`、`rotate`、`enable`、`disable` 和 `delete` 都直接读写 MySQL，只需要日常 DML 权限。`delete` 是逻辑删除：账号状态变为 `deleted` 并立即退出账号池，但密钥版本和审计记录仍然保留。建议使用 CLI 管理账号，因为 CLI 会同时维护掩码、指纹、版本、运行状态和审计记录；直接修改单个数据库字段可能造成数据不一致。

## SerpAPI SQLite 迁移

执行迁移前先初始化 MySQL 表，再运行：

```bash
opscli api-credentials migrate-serpapi-sqlite
```

也可以指定历史数据库路径：

```bash
opscli api-credentials migrate-serpapi-sqlite --sqlite-path /path/to/serpapi.sqlite3
```

迁移会保留账号名称、API Key、启停状态、额度、套餐、续期日和最近错误。命令不会删除 SQLite 文件；核对 MySQL 账号和业务调用正常后，再由运维人员归档旧文件。

## 安全要求

- 普通业务调用方不能通过接口读取明文 API Key。
- API Key 以明文存储，因此必须严格限制 MySQL 账号、网络和备份文件的访问权限。
- MySQL 密码和 API Key 不得进入日志、异常、遥测或导出文件。
- 修改和轮换账号时应传入 `--actor`，保留审计记录。
- MySQL 生产连接建议启用 TLS，并使用最小权限账号。

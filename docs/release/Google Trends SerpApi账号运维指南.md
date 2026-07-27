# Google Trends SerpApi 账号运维指南

> 本文档用于维护 Google Trends 使用的 SerpApi API Key，包括新增、查看、额度测试、启用和禁用账号。

## 启动方式

安装后的环境可直接使用 `opscli`：

```bash
opscli google-trends api-key --help
```

在项目源码和虚拟环境中，也可以通过 Python 模块启动：

```powershell
.\.venv\Scripts\python.exe -m opscli google-trends api-key --help
```

以下示例统一使用较简洁的 `opscli` 写法，两种启动方式的子命令和参数完全一致。

## 快速开始

```bash
# 1. 新增账号；执行后按提示隐藏输入 API Key
opscli google-trends api-key add --name primary --remark "主账号"

# 2. 查看账号状态和额度
opscli google-trends api-key list

# 3. 调用免费 Account API 验证账号
opscli google-trends api-key test --name primary

# 4. 根据需要禁用或重新启用账号
opscli google-trends api-key disable --name primary
opscli google-trends api-key enable --name primary
```

## 命令说明

### 新增或更新账号

```bash
opscli google-trends api-key add --name primary --remark "主账号"
```

参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--name` | 是 | 本地账号名称，不区分大小写，建议使用稳定且唯一的名称 |
| `--remark` | 否 | 账号用途、负责人或套餐等备注 |

执行后终端会提示：

```text
SerpApi API Key:
```

API Key 使用隐藏输入，不会显示在终端，也不支持通过 `--api-key` 参数传入，避免进入命令历史。

同名账号已存在时会更新其 API Key 和备注，但保留原状态。例如账号原来是 `disabled` 或 `exhausted`，更新 Key 后不会自动恢复为 `active`，需要显式执行 `enable`。

### 查看账号列表

```bash
opscli google-trends api-key list
```

输出包含：

- 账号名称和备注
- 掩码后的 API Key
- 状态
- 剩余搜索次数和当月用量
- 套餐名称和续期日期
- 最近检查、使用、耗尽时间和最后错误

命令不会输出明文 API Key。

### 测试账号和同步额度

```bash
opscli google-trends api-key test --name primary
```

该命令只调用 SerpApi 免费的 Account API：

- 不调用 Search API，不消耗搜索次数。
- 同步剩余次数、当月用量、套餐和续期日期。
- 剩余次数为 `0` 时，将账号标记为 `exhausted`。
- 剩余次数大于 `0` 时，只更新额度，不会自动恢复 `disabled` 或 `exhausted` 状态。

### 禁用账号

```bash
opscli google-trends api-key disable --name primary
```

账号状态变为 `disabled` 后，不再参与 Google Trends 多 Key 自动轮换。

### 启用账号

```bash
opscli google-trends api-key enable --name primary
```

账号状态变为 `active` 后，可以重新参与自动轮换。建议先执行 `test` 确认账号有效且有剩余额度，再执行 `enable`。

## 状态说明

| 状态 | 含义 | 是否参与自动轮换 |
|------|------|------------------|
| `active` | 账号已启用；临时吞吐限流后仍保持此状态 | 是 |
| `exhausted` | Account API 已确认剩余额度为 0，或错误明确表示额度耗尽 | 否 |
| `disabled` | 运维人员主动禁用，或 SerpApi 返回 401/403 | 否 |

### SerpApi 错误处理

业务请求按 [SerpApi API Status and Error Codes](https://serpapi.com/api-status-and-error-codes) 处理：

| 状态 | 本地处理 | 是否切换账号 |
|------|----------|----------------|
| `200` + `search_metadata.status=Success` | 正常返回；即使顶层有 `error`，也可能只是成功但无搜索结果 | 否 |
| `200` + `search_metadata.status=Error` | 记录搜索错误并返回调用方 | 否 |
| `400` | 参数错误，原样换账号无法解决 | 否 |
| `401` | 记录错误并将当前账号标记为 `disabled` | 是 |
| `403` | 账号无权限或已删除，记录错误并标记为 `disabled` | 是 |
| `404` | 请求资源不存在 | 否 |
| `410` | 搜索归档已过期 | 否 |
| `429` + 剩余额度为 0 | 标记为 `exhausted` | 是 |
| `429` + 仍有剩余额度 | 视为每小时吞吐限流，仅记录错误并在本轮跳过，账号保持 `active` | 是 |
| `500` / `503` | SerpApi 服务端错误，返回调用方稍后重试 | 否 |

每次业务调用中，同一个账号最多尝试一次。若账号级错误导致所有可用账号均被尝试，调用会返回“没有可用的 SerpApi API Key”，不会循环重试。

### 月度额度自动恢复

`exhausted` 账号满足以下条件时，会在下一次业务请求中先调用免费的 Account API 复查：

- Account API 已提供 `plan_renewal_date`；
- 当前日期已到续期日；
- 距离上次 Account API 检查已超过 1 小时。

复查结果：

- `total_searches_left > 0`：自动恢复为 `active`，清除耗尽状态，并继续执行当前请求；
- 剩余额度仍为 `0`：保持 `exhausted`，1 小时后才允许再次复查；
- Account API 网络、限流或服务端错误：保持 `exhausted` 并进入 1 小时冷却，不阻断其他 `active` 账号；
- `401/403`：改为 `disabled`，等待人工检查 Key 或账号状态。

没有 `plan_renewal_date` 的账号不会自动恢复，因为这通常表示没有有效月度套餐。此类账号补充额度或更换 Key 后，应手动执行：

```bash
opscli google-trends api-key test --name primary
opscli google-trends api-key enable --name primary
```

人工禁用和因 `401/403` 禁用的账号不会因额度续期自动启用。

## 多账号建议流程

```bash
opscli google-trends api-key add --name primary --remark "主账号"
opscli google-trends api-key add --name backup-1 --remark "第一备用账号"
opscli google-trends api-key add --name backup-2 --remark "第二备用账号"

opscli google-trends api-key test --name primary
opscli google-trends api-key test --name backup-1
opscli google-trends api-key test --name backup-2

opscli google-trends api-key list
```

业务请求会先复查续期日已到且冷却结束的 `exhausted` 账号，再从 `active` 账号中选择最久未使用的账号。某个账号确认耗尽后，会被标记为 `exhausted`，当前请求自动尝试下一个可用账号。

## 本地存储

默认 SQLite 文件：

```text
~/.config/opscli/google_trends/serpapi.sqlite3
```

Windows 通常对应：

```text
%USERPROFILE%\.config\opscli\google_trends\serpapi.sqlite3
```

API Key 按当前运维约定以明文保存在该 SQLite 文件中。请限制配置目录的访问权限，不要把数据库复制到共享目录、日志、工单附件或代码仓库。

## 常见问题

### 提示账号不存在

先查看账号名称：

```bash
opscli google-trends api-key list
```

账号名称查询不区分大小写，但名称内容必须完整一致。

### 更新 Key 后账号仍不可用

同名更新不会自动恢复原状态。先检查额度，再显式启用：

```bash
opscli google-trends api-key test --name primary
opscli google-trends api-key enable --name primary
```

### 所有业务请求提示没有可用 Key

执行：

```bash
opscli google-trends api-key list
```

确认至少一个账号满足：

- 状态为 `active`
- Account API 可访问
- `total_searches_left` 大于 `0`

如账号已续期，使用 `test` 同步额度后，再使用 `enable` 人工恢复。

# AppHub 应用创建、初始化与源码推送指南

## 1. 功能范围

`opscli app` 只提供三个用户命令：

```text
opscli app create
opscli app init
opscli app push
```

| 命令 | 职责 |
| --- | --- |
| `create` | 创建新 AppHub 应用；已绑定目录继续使用原应用 |
| `init` | 初始化 Git 并绑定应用独立仓库 |
| `push` | 提交并推送源码，完成后结束 |

内部前置条件采用幂等补齐：

```text
create = ensure_app
init   = require_binding_or_explicit_id → ensure_git
push   = require_binding → ensure_git → ensure_pushed
```

`opscli app` 不负责拉取建站模板、生成业务代码、规定开发顺序、执行测试或构建，也不负责 AppHub release、版本查询、发布事件、线上部署和健康检查。

## 2. AppHub 配置

AppHub 服务根地址使用 `OPSCLI_APPHUB_URL`。配置值只包含服务根地址，客户端统一追加 `/api/v1`。

源码仓库地址不由 opscli 拼接。`POST /api/v1/apps` 和 `GET /api/v1/apps/{app_id}/git-config` 返回的完整 `repo_url` 是仓库事实源。

AppHub 请求通过 `AuthClient.get_token("ops")` 获取或刷新运营 JWT，发送 `Authorization: Bearer <JWT>` 与 `X-Opscli-Version`。创建请求不发送本地操作 UUID；服务端按同一 owner 和 slug 幂等重入。不发送 `X-Session-Id`、登录 Cookie 或 CSRF 头；无效 Bearer 由 AppHub 返回 401，身份服务不可用返回 503。

## 3. 应用身份文件

### 3.1 `app.yaml`

`app.yaml` 是随源码提交的 AppHub 应用声明。模板中的 `app_id/title` 是示例数据，AppHub 创建成功后由 `opscli app` 回填真实身份：

```yaml
app_id: Ab123
title: 销售日报
```

`opscli app create/init` 只同步 `app_id/title`，并移除旧项目的顶层 `name`；不覆盖 `runtime`、`entrypoint`、`services`、`opscli.datasets`、`llm`、`access` 或其他项目声明。目录中没有 `app.yaml` 时，`create/init` 不生成完整 manifest。`push` 要求 `app.yaml.app_id` 与本地 binding 一致，并且不会静默改写 manifest。

### 3.2 `.opscli/app.json`

`.opscli/app.json` 是本地目录与 AppHub 应用、Git 仓库的 schema v4 binding，保存 `app_id`、`slug`、`repo_url`、固定分支 `master`、控制面环境和非敏感用户信息。

`app_id` 固定五位 Base62，区分大小写且不可变，同时写入 `app.yaml` 和 binding；两处必须完全一致。`slug` 可以重复，只保留在 AppHub 和 binding。binding 必须具有 `apphub_url`（控制面 API 地址），环境不匹配时拒绝操作。v1、v2、v3、旧字段或缺少环境标识的 binding 立即停止，不自动迁移、备份或覆盖。

`.opscli/creation.json` 保存本地操作 UUID、规范化请求摘要和账号/环境摘要；发送前持久化，用于目录并发和创建意图保护，但不作为 HTTP 幂等键。绑定完成后保留完成状态和应用 ID，不保存凭据。

该文件不得进入 Git。项目 `.gitignore` 必须包含：

```gitignore
.opscli/
```

Git Token 只写入本机 credential helper，不进入 binding、日志、命令输出或 remote URL。

### 3.3 `ops-app.config`

当前流程不再生成、读取或校验 `ops-app.config`：

- 应用公开身份和展示名称使用 `app.yaml.app_id/title`。
- slug、仓库和 Owner 信息使用 `.opscli/app.json`；binding 同时保存 `app_id` 用于严格核对。
- 旧公开路径、Compose service 和镜像命名规则由平台负责，不迁移到 `app.yaml`。

## 4. 创建应用

```powershell
opscli app create "销售日报" --path .\sales-dashboard
```

执行步骤：

1. 解析最终目标目录并检查 `.opscli/app.json`。
2. 同目录已绑定相同 slug 时按绑定 ID 核对远端后返回，不重复调用创建 API。
3. 同目录已绑定其他应用时返回 `APP-ALREADY-BOUND`。
4. 无 binding 时先保存本地创建意图，再调用 `POST /api/v1/apps`；重试由服务端按 owner/slug 幂等。
5. 保存 `.opscli/app.json`；创建响应不包含 Git Token。
6. 如果目录中已有 `app.yaml`，回填真实 `app_id/title` 并删除旧顶层 `name`。

未指定 `--path` 时，默认目录为应用 slug，同样会先检查该目录是否已经绑定。`create` 不签发 Git 凭据，也不执行 `git init`、commit 或 push。

网络超时、上游准备失败时，在原目录使用相同名称、账号和环境重试，不能删除本地创建意图；内容或作用域变化会返回 `APP-CREATE-CONFLICT`。已经完成创建但 binding 丢失时，用记录中的 ID 在确认目录完全没有 binding 后显式恢复。

## 5. 初始化 Git

```powershell
opscli app init .\sales-dashboard
```

执行步骤：

1. 读取 schema v4 的 `.opscli/app.json`；只有目录完全没有 binding 时才能指定 `--app-id Ab123` 恢复已有应用。非法或旧 binding 必须人工核对，不能覆盖。`--app` 仅用于核对 slug。
2. 调用 `GET /api/v1/apps/{app_id}` 和 `GET /api/v1/apps/{app_id}/git-config`，校验响应 ID 后刷新应用与仓库信息。禁止 ID 缺失时退回 slug。
3. 首次绑定目标 origin 时调用 `GET /api/v1/apps/{app_id}/git-bind-preflight`，仅接受空仓库成功证据；相同 origin 的后续 init/push 不重复预检。
4. 使用现有 Git 凭据执行 `ls-remote`。明确属于认证失败时自动恢复：平台未绑定凭据则签发第一枚，平台已有凭据则由服务端吊销旧凭据并签发新凭据；网络、仓库状态和历史冲突等非认证错误不会刷新凭据。
5. 新签发凭据先通过仅对子进程生效的临时 Authorization Header 验证，成功后才清理本机旧凭据并保存新凭据到 credential helper。
6. 验证完成后才保存 binding、同步 `app.yaml`，并将 origin 的 fetch URL 和唯一 push URL 收敛到平台仓库。
7. 远端已有 `master` 时获取并建立跟踪；远端分叉或无关历史必须人工处理，不自动执行 `ours` 合并。

## 6. 推送源码

```powershell
opscli app push .\sales-dashboard -m "优化库存风险筛选"
```

`push` 要求有效 binding，会补齐 Git 初始化状态；无绑定时直接停止，不自动创建或选取同名应用。然后：

1. 校验 `origin` 与 binding 仓库一致。
2. 获取 `origin/master` 并拒绝 non-fast-forward、无关历史和 force push。
3. 工作区有修改时执行整体暂存和普通 commit。
4. 将 `HEAD` 推送到远端 `master`。
5. 返回本地及远端 commit SHA，然后结束。

`push --message` 为必填参数，只用于存在修改时创建 Git commit。源码无变化时不创建空 commit。

如果 `.opscli/app.json` 已被跟踪、暂存或未被忽略，push 会返回 `APP-BINDING-TRACKED`，避免本地绑定泄漏。

push 成功只能说明：

```text
源码已推送到远端仓库。
```

不能据此说明应用已发布、已部署、构建成功或健康运行。

## 7. API 边界

`opscli app` 使用：

- `POST /api/v1/apps`
- `GET /api/v1/apps/{app_id}`
- `GET /api/v1/apps/{app_id}/git-config`
- `GET /api/v1/apps/{app_id}/git-bind-preflight`
- `POST /api/v1/git/credentials`

`opscli app` 不调用：

- `POST /api/v1/apps/{slug}/releases`
- `GET /api/v1/apps/{slug}/releases`
- `GET /api/v1/apps/{slug}/releases/{id}/events`

## 8. 常见错误

| 错误码 | 说明 | 处理方式 |
| --- | --- | --- |
| `APP-ALREADY-BOUND` | 目录已绑定其他应用 | 更换目录或核对原 binding |
| `APP-BINDING-INVALID` | binding 损坏、含旧字段或缺少环境标识 | 停止操作并人工核对；不能用 `init --app-id` 覆盖 |
| `APP-BINDING-VERSION` | binding 不是 schema v4 | 停止操作并人工核对原应用信息 |
| `APP-NOT-BOUND` | 未绑定应用 | `create` 新建或 `init --app-id` 恢复 |
| `APP-BINDING-ENVIRONMENT` | binding 控制面环境不一致 | 切回原环境；另一环境使用独立目录 |
| `APP-CREATE-CONFLICT` | 未完成创建的请求、账号或环境发生变化 | 恢复原参数重试，另一创建意图使用独立目录 |
| `APP-MANIFEST-INVALID` | `app.yaml` 无法解析 | 修复 YAML 后重试 |
| `APP-BINDING-TRACKED` | binding 可能进入 Git | 在 `.gitignore` 中加入 `.opscli/` 并从索引移除 |
| `GIT-ORIGIN-MISMATCH` | `origin` 与 binding 不一致 | 重新执行 `opscli app init` |
| `GIT-002` | Git 凭据自动刷新后仍不可用，或本机 credential helper 读写失败 | 检查 AppHub、Git 服务和本机 Git Credential Manager |
| `GIT-003` | 远端 master 领先或历史分叉 | 人工核对并合并远端修改，禁止 force push |

## 9. 安全边界

- AppHub API 携 Bearer JWT 与版本头；本地创建 UUID 不进入 HTTP 请求，不携登录 Cookie 或旧 `X-Session-Id`。
- 不调用 Gitea 管理 API，不持有管理员凭据。
- remote URL 不嵌入用户名或 Token。
- `.opscli/app.json` 不进入 Git。
- 禁止 force push。
- push 完成后 `opscli app` 立即结束，不继续调用 AppHub 发布服务。

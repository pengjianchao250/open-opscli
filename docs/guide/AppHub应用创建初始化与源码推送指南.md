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
| `create` | 创建或复用 AppHub 应用并保存本地 binding |
| `init` | 初始化 Git 并绑定应用独立仓库 |
| `push` | 提交并推送源码，完成后结束 |

内部前置条件采用幂等补齐：

```text
create = ensure_app
init   = ensure_app → ensure_git
push   = ensure_app → ensure_git → ensure_pushed
```

`opscli app` 不负责拉取建站模板、生成业务代码、规定开发顺序、执行测试或构建，也不负责 AppHub release、版本查询、发布事件、线上部署和健康检查。

## 2. AppHub 配置

AppHub 服务根地址使用 `OPSCLI_APPHUB_URL`。配置值只包含服务根地址，客户端统一追加 `/api/v1`。

源码仓库地址不由 opscli 拼接。`POST /api/v1/apps` 和 `GET /api/v1/apps/{slug}/git-config` 返回的完整 `repo_url` 是仓库事实源。

AppHub 请求通过 `AuthClient.get_token("ops")` 获取或刷新运营 JWT，只发送 `Authorization: Bearer <JWT>` 与 `X-Opscli-Version`。不发送 `X-Session-Id`、登录 Cookie 或 CSRF 头；无效 Bearer 由 AppHub 返回 401，身份服务不可用返回 503。

## 3. 应用身份文件

### 3.1 `app.yaml`

`app.yaml` 是随源码提交的 AppHub 应用声明。模板中的 `name/title` 是示例数据，AppHub 创建成功后由 `opscli app` 回填真实身份：

```yaml
name: sales-dashboard
title: 销售日报
```

`opscli app` 只同步 `name/title`，不覆盖 `runtime`、`entrypoint`、`services`、`opscli.datasets`、`llm`、`access` 或其他项目声明。目录中没有 `app.yaml` 时，`opscli app` 不生成完整 manifest。

### 3.2 `.opscli/app.json`

`.opscli/app.json` 是本地目录与 AppHub 应用、Git 仓库的 binding，保存 `app_id`、`slug`、`repo_url`、默认分支和非敏感用户信息。

该文件不得进入 Git。项目 `.gitignore` 必须包含：

```gitignore
.opscli/
```

Git Token 只写入本机 credential helper，不进入 binding、日志、命令输出或 remote URL。

### 3.3 `ops-app.config`

当前流程不再生成、读取或校验 `ops-app.config`：

- 应用名称和展示名称使用 `app.yaml.name/title`。
- `app_id`、仓库和 Owner 信息使用 `.opscli/app.json`。
- 旧公开路径、Compose service 和镜像命名规则由平台负责，不迁移到 `app.yaml`。

## 4. 创建应用

```powershell
opscli app create "销售日报" --path .\sales-dashboard
```

执行步骤：

1. 解析最终目标目录并检查 `.opscli/app.json`。
2. 同目录已绑定相同 slug 时幂等返回，不重复调用创建 API。
3. 同目录已绑定其他应用时返回 `APP-ALREADY-BOUND`。
4. 无 binding 时调用 `POST /api/v1/apps`。
5. 保存 `.opscli/app.json`；创建响应不包含 Git Token。
6. 如果目录中已有 `app.yaml`，只回填真实 `name/title`。

未指定 `--path` 时，默认目录为应用 slug，同样会先检查该目录是否已经绑定。`create` 不签发 Git 凭据，也不执行 `git init`、commit 或 push。

## 5. 初始化 Git

```powershell
opscli app init .\sales-dashboard
```

执行步骤：

1. 读取或恢复 `.opscli/app.json`；缺少 binding 时优先从可访问应用中恢复，仍无匹配时创建应用。
2. 调用 `GET /api/v1/apps/{slug}` 和 `GET /api/v1/apps/{slug}/git-config` 刷新应用与仓库信息。
3. 必要时调用 `POST /api/v1/git/credentials` 签发 Git 凭据。
4. 先探测应用独立仓库，再将其配置为 `origin`；如果目录来自模板 clone，会替换模板仓库的 `origin`。
5. 远端已有 `main` 时获取并建立跟踪；远端为空时保留本地模板源码，等待后续 `push` 创建首个 `main`。
6. 已有 `app.yaml` 时同步身份；没有时不生成模板或业务代码。

## 6. 推送源码

```powershell
opscli app push .\sales-dashboard -m "优化库存风险筛选"
```

`push` 会自动补齐缺失的 create/init 状态，然后：

1. 校验 `origin` 与 binding 仓库一致。
2. 获取 `origin/main` 并拒绝 non-fast-forward 和 force push。
3. 工作区有修改时执行整体暂存和普通 commit。
4. 将 `HEAD` 推送到远端 `main`。
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
- `GET /api/v1/apps/{slug}`
- `GET /api/v1/accessible-apps`
- `GET /api/v1/apps/{slug}/git-config`
- `POST /api/v1/git/credentials`

`opscli app` 不调用：

- `POST /api/v1/apps/{slug}/releases`
- `GET /api/v1/apps/{slug}/releases`
- `GET /api/v1/apps/{slug}/releases/{id}/events`

## 8. 常见错误

| 错误码 | 说明 | 处理方式 |
| --- | --- | --- |
| `APP-ALREADY-BOUND` | 目录已绑定其他应用 | 更换目录或核对原 binding |
| `APP-BINDING-INVALID` | binding 损坏或字段不完整 | 修复或移除错误 binding 后重新恢复 |
| `APP-MANIFEST-INVALID` | `app.yaml` 无法解析 | 修复 YAML 后重试 |
| `APP-BINDING-TRACKED` | binding 可能进入 Git | 在 `.gitignore` 中加入 `.opscli/` 并从索引移除 |
| `GIT-ORIGIN-MISMATCH` | `origin` 与 binding 不一致 | 重新执行 `opscli app init` |
| `GIT-003` | 远端 main 领先 | 合并远端修改后重试，禁止 force push |

## 9. 安全边界

- AppHub API 只携 Bearer JWT 与版本头，不携登录 Cookie 或旧 `X-Session-Id`。
- 不调用 Gitea 管理 API，不持有管理员凭据。
- remote URL 不嵌入用户名或 Token。
- `.opscli/app.json` 不进入 Git。
- 禁止 force push。
- push 完成后 `opscli app` 立即结束，不继续调用 AppHub 发布服务。

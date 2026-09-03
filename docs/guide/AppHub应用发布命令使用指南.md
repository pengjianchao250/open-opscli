# Codex 站点创建、源码推送与发布指南

## 1. 功能范围

第一阶段的 `opscli app` 只提供三个用户命令：

```text
opscli app create
opscli app init
opscli app push
```

平台遵循“一站点一仓库”：每个站点对应 AppHub 管理的独立 Gitea 仓库 `apps/{slug}`。站点仓库地址不在 opscli 中全局配置，也不由 opscli 根据 Gitea 根地址自行拼接；`POST /apps` 和 `GET /apps/{slug}/git-config` 返回的完整 `repo_url` 是仓库事实源。

全新项目遵循“模板先行”：Codex 识别用户的新建站点、新建看板或从零开发运营数据应用意图后，加载 `ops-app-build-spec` 作为统一入口。Skill 阶段 0 确认站点名称和空目标目录并编排 `app create → app init`；模板成功后，同一个 Skill 才进入正式盘点和开发，最后执行 `app push`。`app init` 成功前不得向目录写入 assessment、README、前后端或部署文件。已有源码项目继续跳过模板，禁止覆盖用户代码。

## 2. AppHub 与模板环境配置

AppHub 服务根地址统一使用：

```text
OPSCLI_APPHUB_URL
```

配置值不包含 `/api/apphub/v1`。当前暂定配置为：

```text
预发布：http://10.1.13.143:8080
生产：  http://10.1.13.143:8080
```

生产正式域名确定后只需要替换生产环境的 `OPSCLI_APPHUB_URL`。客户端会自动拼接 API 前缀，例如：

```text
http://10.1.13.143:8080/api/apphub/v1
```

配置优先级与 OPS、Polaris 等现有配置保持一致：项目根目录 `.env`、`~/.config/opscli/config.ini`、代码默认值。

建站模板使用两个独立配置：

```text
OPSCLI_APP_TEMPLATE_REPO
OPSCLI_APP_TEMPLATE_BRANCH
```

当前预发布与生产暂定使用同一组地址，各环境应在自身配置中成组维护：

```env
OPSCLI_APPHUB_URL=http://10.1.13.143:8080
OPSCLI_APP_TEMPLATE_REPO=http://10.1.13.143:3000/aukeys-admin/template.git
OPSCLI_APP_TEMPLATE_BRANCH=main
```

后续生产 AppHub 或 Git 域名确定后，只替换生产部署中的对应完整 URL。opscli 不根据
`OPSCLI_APPHUB_URL` 推导模板仓库域名，也不根据模板仓库域名拼接站点源码仓库地址。

站点源码仓库不再使用 `OPSCLI_APP_REPO_URL`。预发布或生产 AppHub 应根据自身部署配置创建或查找对应环境的仓库，并向 opscli 返回包含协议、主机、端口、组织和仓库名的完整地址，例如：

```text
http://10.1.13.143:3000/apps/sales-dashboard.git
```

## 3. 创建站点

```powershell
opscli app create "销售日报" --path .\sales-daily-dashboard
```

命令执行主体和步骤：

1. `opscli app create` 生成完整 AppYaml。
2. `opscli app create` 调用当前环境 AppHub 的 `POST /api/apphub/v1/apps`。
3. AppHub 创建应用、独立 Gitea 仓库和 `main` 分支，或幂等返回已经存在的应用。
4. AppHub 返回 `app_id/slug/repo_url`，必要时同时返回只出现一次的 Git 凭据。
5. `opscli app create` 将非敏感绑定信息写入站点目录的 `.opscli/app.json`；Git token 只写入本机 Git credential helper。
6. 全新项目此时目录中除 `.opscli` 外仍不应出现 Codex 或 Skill 提前生成的项目文件。

## 4. 初始化 Git

```powershell
opscli app init .\sales-daily-dashboard
```

命令执行主体和步骤：

1. `opscli app init` 读取 `.opscli/app.json`。
2. `opscli app init` 调用 AppHub 的 `GET /api/apphub/v1/apps/{slug}/git-config`，刷新完整 `repo_url`、Git 用户名和凭据绑定状态。
3. 本机缺少 Git 凭据时，`opscli app init` 调用 AppHub Git 凭据签发接口并保存到本机 credential helper。
4. `opscli app init` 将当前站点的独立仓库配置为 Git `origin`，并获取 `origin/main`。
5. 空项目会应用模板内容；已有源码的项目保留现有文件，不用模板覆盖用户代码。
6. 模板仓库和分支仍分别通过 `OPSCLI_APP_TEMPLATE_REPO`、`OPSCLI_APP_TEMPLATE_BRANCH` 配置，它们不是站点源码推送仓库。
7. 模板 fetch 会显式禁用 Git credential helper，以匿名方式拉取公开模板，避免向模板仓库发送站点仓库 token。
8. 空项目成功应用模板后，binding 才更新为当前环境的模板地址和分支；已有源码继续保留原模板元数据。
9. 模板完成后，作为入口的 `ops-app-build-spec` 从阶段 0 进入正式阶段，重新盘点项目并生成 assessment、项目规范和业务代码；不得再运行另一套脚手架覆盖模板。

## 5. 推送并发布

```powershell
opscli app push .\sales-daily-dashboard -m "优化库存风险筛选与明细展示"
```

命令执行主体和步骤：

1. `opscli app push` 调用 AppHub 应用详情和 `git-config`，检查应用状态并刷新站点 `repo_url`。
2. `opscli app push` 校验本地 `origin` 必须等于当前站点绑定的独立仓库，避免推送到错误仓库。
3. `opscli app push` 获取 `origin/main`，拒绝 non-fast-forward 和 force push。
4. 工作区有修改时，`opscli app push` 执行 `git add -A`、创建普通 commit，并推送到 `origin/main`。
5. Git push 成功后，`opscli app push` 获取远端 main commit SHA，并与最近一次健康 release baseline 比较。
6. 有新 commit 时，`opscli app push` 调用 AppHub 的 `POST /api/apphub/v1/apps/{slug}/releases` 发起发布；没有新 commit 时返回 NOOP，不重复发布。
7. `opscli app push` 消费 AppHub 返回的 SSE 发布进度；连接中断时通过 events 接口和 `since_seq` 续订。
8. 最终输出 `commit_sha/release_id/version/status/url` 等非敏感信息。

因此，Git push 本身不会独立触发部署；调用 AppHub release 的主体是 `opscli app push` 命令进程。

## 6. 本地绑定

站点目录中的 `.opscli/app.json` 保存：

```json
{
  "schema_version": 2,
  "app_id": "app-1",
  "site_name": "销售日报",
  "slug": "sales-daily-dashboard",
  "repo_url": "http://10.1.13.143:3000/apps/sales-daily-dashboard.git",
  "default_branch": "main",
  "git_username": "zhangsan",
  "template_repo_url": "http://10.1.13.143:3000/aukeys-admin/template.git",
  "template_branch": "main"
}
```

该文件不保存 token、session、cookie 或 Gitea 管理凭据。`init` 和 `push` 会使用 AppHub `git-config` 返回的最新地址刷新 `repo_url`。

## 7. 常见错误

| 错误码 | 说明 | 处理方式 |
|---|---|---|
| `APP-NOT-BOUND` | 缺少 `.opscli/app.json` | 先执行 `opscli app create` |
| `APP-ALREADY-BOUND` | 目录已绑定其他站点 | 更换目录或确认原绑定 |
| `APPHUB-PROTOCOL` | AppHub 响应缺少必需字段 | 检查 AppHub 契约和当前环境地址 |
| `GIT-NOT-INITIALIZED` | 尚未初始化 Git | 执行 `opscli app init` |
| `GIT-ORIGIN-MISMATCH` | `origin` 与 AppHub 返回的站点仓库不一致 | 重新执行 `opscli app init` |
| `GIT-003` | 远端 main 领先，无法 fast-forward | 先合并远端修改后重试 |
| `GIT-010` | Git 命令失败 | 根据原始错误检查凭据、网络或远端分支 |

## 8. 安全约束

- opscli 不调用 Gitea 管理 API，也不持有 Gitea 管理员凭据。
- Git remote URL 不嵌入用户名或 token。
- Git token 不进入命令输出、日志、binding 或提交历史。
- 模板仓库按公开只读方式匿名 fetch，不复用站点仓库 Git token。
- `opscli app push` 不执行 force push。
- 站点仓库完整地址只能来自当前环境的 AppHub 响应。

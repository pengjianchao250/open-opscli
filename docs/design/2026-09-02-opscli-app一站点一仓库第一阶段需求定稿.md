# opscli app 一站点一仓库第一阶段需求定稿

> 日期：2026-09-02  
> 环境配置修订：2026-09-03  
> 状态：需求定稿，进入代码实现。  
> 范围：只改造 `opscli app create / init / push` 三个现有命令，不扩展其他用户命令。
> 全新项目建站顺序补充见：`docs/design/2026-09-03-opscli-app模板先行建站流程需求定稿.md`。

## 1. 业务目标

用户通过 `opscli app` 创建、初始化并推送站点时，平台遵循“一站点一仓库”：

- AppHub 应用 slug 对应 Gitea 仓库 `apps/{slug}`；
- 每个站点绑定 AppHub 返回的独立 `repo_url`；
- 默认分支固定为 `main`；
- `opscli` 不调用 Gitea 管理 API，不持有 Gitea 管理凭据；
- Git push 成功后，由 `opscli app push` 调 AppHub release 接口触发部署并展示 SSE 进度。

## 2. 命令范围

第一阶段仍然只有三个命令：

```text
opscli app create <site_name> [--path PATH]
opscli app init [PATH]
opscli app push [PATH] --message MESSAGE
```

不新增 `publish`、`versions`、`git`、`members`、`env`、`secret`、`db` 等命令。

## 3. 必须接入的 AppHub API

| API | 用途 |
|---|---|
| `POST /api/apphub/v1/apps` | 创建应用、独立仓库和 main，返回 `repo_url` 及可选的一次性 Git 凭据 |
| `GET /api/apphub/v1/apps/{slug}` | push 前检查应用状态和远端信息 |
| `GET /api/apphub/v1/apps/{slug}/git-config` | 获取仓库地址、Git 用户名和凭据绑定状态 |
| `POST /api/apphub/v1/git/credentials` | 本机凭据缺失时重新签发或 rotate |
| `GET /api/apphub/v1/apps/{slug}/releases` | 获取最近健康发布 baseline，判断 NOOP 和中断恢复 |
| `POST /api/apphub/v1/apps/{slug}/releases` | 以 remote main 的 commit SHA 发起发布 |
| `GET /api/apphub/v1/apps/{slug}/releases/{id}/events` | SSE 中断后从 `since_seq` 续订 |

## 4. create 行为

1. 将站点名称转换为合法 slug，或使用服务端返回的 slug。
2. 发送完整 AppYaml 请求，而不是只发送 `{name}`。
3. 使用响应中的 `app_id/slug/repo_url` 建立本地 binding。
4. 若响应携带一次性 Git token，立即写入受控 Git 凭据文件；token 不得进入输出、日志和 binding。
5. 不使用全局固定仓库地址，不自行创建远端仓库。

## 5. init 行为

1. 读取 binding，并调用 git-config 刷新 `repo_url` 和凭据状态。
2. 本机缺少凭据时调用凭据签发接口；服务端已绑定但本机无凭据时显式 rotate。
3. 设置当前站点独立的 origin。
4. 先 fetch `origin/main`，再以远端 main 为共同祖先初始化本地 main。
5. 空项目应用模板内容；已有源码时不覆盖用户文件。
6. 执行 `git ls-remote` 探活后才报告初始化成功。
7. 空项目初始化时读取当前环境的模板仓库与分支；成功应用后才更新 binding 中的模板元数据。
8. 已有源码的项目不重新套用模板，并保留 binding 中已有的模板元数据。
9. 全新项目在 init 成功拉取模板前，Codex 和 Skill 不得提前写入项目文件；模板完成后才开始业务开发。

## 6. push 行为

1. 调应用详情和 git-config，确认应用、仓库和凭据可用。
2. fetch `origin/main`，本地不包含远端 main 时拒绝并提示先合并，禁止 force push。
3. 工作区有修改时执行 `git add -A` 和普通 commit。
4. 普通推送 `HEAD:main`。
5. 获取 remote main SHA，并与 releases baseline 比较：
   - remote SHA 等于 baseline：提示无新内容，不重复发布；
   - remote SHA 不等于 baseline：调用 releases 发起部署；
   - 上次 push 成功但 release 中断：直接使用 remote SHA 恢复发布。
6. 解析 POST releases 返回的 SSE；断线时使用 events + `since_seq` 续订。
7. 最终输出 `commit_sha/release_id/version/status/url` 等非敏感信息。

## 7. Binding 与配置

- `.opscli/app.json` 升级为 schema v2；
- 保存 `app_id/slug/site_name/repo_url/default_branch/git_username` 等信息；
- 不保存 token、session、cookie 或管理凭据；
- 旧 schema v1 在 init/push 时迁移，固定共享仓库 origin 必须替换为 AppHub 返回的独立仓库；
- AppHub 使用统一 base URL 配置，业务代码不得拼接版本路径。
- AppHub 地址纳入 `opscli/auth/config.py` 的 `[systems].apphub_url` 统一环境配置；
- AppHub 环境变量统一且仅使用 `OPSCLI_APPHUB_URL`；
- 预发布 AppHub 当前配置为 `apphub_url=http://10.1.13.143:8080`；
- 生产 AppHub 正式域名尚未确定，当前暂定同样使用
  `apphub_url=http://10.1.13.143:8080`，正式域名确定后只替换生产环境配置；
- `apphub_url` 配置值不包含 `/api/apphub/v1`；
- `opscli app` 不根据 OPS 域名猜测 AppHub 地址，预发布和生产部署应成组配置
  `ops_url/ops_system_url/apphub_url/app_template_repo/app_template_branch/polaris_system_url`；
- 模板仓库完整地址使用 `[systems].app_template_repo` 或
  `OPSCLI_APP_TEMPLATE_REPO`，默认
  `http://10.1.13.143:3000/aukeys-admin/template.git`；
- 模板分支使用 `[systems].app_template_branch` 或
  `OPSCLI_APP_TEMPLATE_BRANCH`，默认 `main`；
- 模板仓库地址不由 AppHub URL 推导，也不等于 AppHub 返回的站点 `repo_url`。

## 8. 安全与错误处理

- token 在内存中只处理一次，并在错误信息中脱敏；
- Git remote URL 不嵌入用户名或 token；
- 模板 fetch 显式禁用 Git credential helper，以匿名方式拉取公开只读模板；
- `GIT-001`：Git 缺失或版本过低；
- `GIT-002`：凭据缺失或失效；
- `GIT-003`：非 fast-forward；
- `GIT-004`：无新内容可发布，属于提示级结果；
- `GIT-REPO-NOT-READY`：AppHub 已登记但仓库/main 暂不可访问；
- 401 提示重新登录，403 提示权限不足，426 提示升级 opscli，502/503 允许幂等重试。

## 9. 验收标准

1. 两个不同站点创建后 binding 中的 `repo_url` 不同，且均符合 `apps/{slug}`。
2. create/init/push 命令数量保持为三个。
3. init 后 origin 指向当前站点仓库，本地 main 基于 `origin/main`。
4. push 不使用 `--force`，远端领先时返回稳定错误。
5. push 后成功调用 releases，并可消费和续订 SSE。
6. push 成功、release 中断后可直接恢复，不要求制造新 commit。
7. token 不出现在 stdout、stderr、JSON 输出、binding、remote URL 和测试日志中。
8. 测试全部使用 mock、裸 Git 仓库与 `tmp_path`，不访问真实 AppHub/Gitea 或用户凭据。
9. 预发布与生产部署可分别覆盖 AppHub、模板仓库和模板分支，且不新增同义环境变量。

## 10. 本次落地改动清单

本次代码修改只实现第一阶段闭环，用户命令仍固定为 `create / init / push` 三个：

1. 将 AppHub transport 从单个占位创建地址改为统一 base URL 与 `/api/apphub/v1` 前缀，并只封装本阶段所需的 7 个接口。
2. `create` 生成完整 AppYaml，使用 AppHub 返回的 `app_id/slug/repo_url` 写入 binding v2；一次性 Git token 只写入 Git credential helper。
3. `init` 通过 app detail 与 git-config 完成旧 binding 迁移、仓库地址刷新和凭据补发；本地 main 以 `origin/main` 为共同祖先，模板只复制内容、不继承模板历史。
4. `push` 先 fetch 并拒绝 non-fast-forward，再普通 commit/push；随后比较最近健康 release baseline，按需发起 release 并自动续订 SSE。
5. 移除固定共享仓库 `apphub.git` 及 `OPSCLI_APP_REPO_URL` 作为仓库事实源的逻辑；每个站点只信任 AppHub 返回的独立仓库地址。
6. binding、命令输出、日志和 Git remote URL 均不保存或显示 token、session、cookie 和管理凭据。
7. 补充 AppYaml、binding v1→v2、Git 基线、凭据、NOOP、release/SSE 续订和“三命令不扩容”测试。
8. 模板地址与分支接入统一配置加载器；空项目按当前环境应用模板，已有源码保留原模板元数据，模板 fetch 不携带站点凭据。

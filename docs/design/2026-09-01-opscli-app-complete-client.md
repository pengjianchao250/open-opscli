# opscli app 三指令精简方案

> 日期：2026-09-01  
> 状态：已按当前需求落地，AppHub 创建站点接口仍为占位契约。

## 1. 定位

`opscli app` 只负责 Codex 站点源码进入指定 GitLab 仓库前的三个动作：

1. 创建远端站点并绑定本地目录。
2. 初始化 Git，空项目获取模板，已有项目保留源码。
3. 将当前目录全部改动提交并普通 push。

本模块不负责本地运行、站点规范校验、密钥扫描、发布部署、版本回滚、日志、环境变量、成员或数据库管理。

## 2. 命令契约

### 2.1 `opscli app create`

```text
opscli app create <site-name> [--path PATH] [--json]
```

- 调用创建站点服务，当前占位地址为 `https://www.taukeytest.com/test111`。
- 可通过 `OPSCLI_APPHUB_CREATE_SITE_URL` 替换服务地址。
- 请求仅提交 `{"name": "<site-name>"}`；创建人和创建时间由服务端根据登录身份生成。
- 响应当前要求包含 `site_id`、`slug`、`repo_url`，并可包含 `site_name`、`created_by`、`created_at`。
- `--path` 不存在时创建目录；已存在时保留全部文件。
- 写入 `.opscli/app.json`，其中不保存 Git token、Cookie 或其他凭据。

### 2.2 `opscli app init`

```text
opscli app init [PATH] [--json]
```

- 读取 `.opscli/app.json`。
- 未初始化 Git 时执行普通 `git init`。
- 目录除 `.opscli`、`.git` 外没有文件时，从模板仓库的 `template` 分支获取源码。
- 已有任何源码时跳过模板，不 checkout、不覆盖文件。
- 将站点绑定返回的 `repo_url` 配置为 `origin`。
- 模板仓库和分支可通过 `OPSCLI_APP_TEMPLATE_REPO`、`OPSCLI_APP_TEMPLATE_BRANCH` 覆盖。

## 2.3 `opscli app push`

```text
opscli app push [PATH] -m "Codex 对当前修改的一句话总结" [--json]
```

- 校验本地绑定和 Git `origin`，不校验站点源码内容。
- 有工作区改动时执行 `git add -A` 和普通 commit。
- 使用 GitLab 本机凭据执行 `git push -u origin HEAD:main`。
- 禁止 force push，不调用部署、release 或 SSE 接口。
- 工作区无改动时仍会推送已有本地 commit。

## 3. 本地绑定文件

`.opscli/app.json` 当前结构：

```json
{
  "site_id": "site-1",
  "site_name": "销售看板",
  "slug": "sales-dashboard",
  "repo_url": "https://gitlab.example/sites/sales-dashboard.git",
  "created_by": "owner@aukeys.com",
  "created_at": "2026-09-01T00:00:00Z",
  "template_repo_url": "https://gitlab.aukeyit.com/polaris/codex-custom-sites.git",
  "template_branch": "template",
  "schema_version": 1
}
```

该文件是源码仓库的一部分，便于重新 clone 后继续识别站点绑定；敏感凭据只由本机 Git 凭据管理器负责。

## 4. 后续接入正式服务

正式 AppHub 服务落地后只替换 `opscli/app/transport/client.py` 的地址或响应适配，三条 CLI 命令、绑定文件和 Git 流程保持不变。若服务响应字段调整，应同步修改客户端契约测试和本文件。

# Codex 站点创建与源码推送指南

`opscli app` 仅提供 `create`、`init`、`push` 三个命令。`push` 只推送源码，不触发部署。

默认源码目标仓库是 Gitea 仓库 `http://10.1.13.143:3000/aukeys-admin/apphub.git`。浏览器页面地址 `http://10.1.13.143:3000/aukeys-admin/apphub` 仅用于查看仓库，Git 初始化和推送使用带 `.git` 的 clone URL。

## 1. 创建全新站点

```powershell
opscli app create "销售日报" --path .\sales-daily-dashboard
opscli app init .\sales-daily-dashboard
```

第一条命令创建站点并写入 `.opscli/app.json`；第二条命令初始化 Git，并在空项目中获取模板分支源码。

## 2. 绑定已有项目

```powershell
opscli app create "库存健康看板" --path .\inventory-health-dashboard
opscli app init .\inventory-health-dashboard
```

如果目录已有源码，`init` 会保留全部文件、跳过模板，只初始化 Git 并配置目标仓库。

## 3. 推送源码

```powershell
opscli app push .\inventory-health-dashboard -m "优化库存风险筛选与明细展示"
```

Codex 每次调用 `push` 都必须提供一句话修改总结。命令会整体暂存目录改动、创建普通 commit，并通过本机 Git 凭据推送到 Gitea 远端 `main`。

`push` 不执行以下操作：

- 不校验站点技术栈或目录结构。
- 不扫描源码或 Git 历史。
- 不调用部署、release 或日志接口。
- 不执行 force push。

## 4. 配置项

| 环境变量 | 默认值 | 用途 |
|---|---|---|
| `OPSCLI_APPHUB_CREATE_SITE_URL` | `https://www.taukeytest.com/test111` | 创建站点占位服务地址 |
| `OPSCLI_APP_REPO_URL` | `http://10.1.13.143:3000/aukeys-admin/apphub.git` | 站点源码目标 Git 仓库；预发布和生产可分别覆盖 |
| `OPSCLI_APP_TEMPLATE_REPO` | `https://gitlab.aukeyit.com/polaris/codex-custom-sites.git` | 模板 Git 仓库 |
| `OPSCLI_APP_TEMPLATE_BRANCH` | `template` | 模板分支 |

创建站点正式服务尚未上线，联调时通过 `OPSCLI_APPHUB_CREATE_SITE_URL` 指向可用服务即可。该 HTTP 服务地址与源码 Git 仓库是两项独立配置，不能将 Gitea 页面地址配置成创建站点接口。

如果切换了 `OPSCLI_APP_REPO_URL`，应先在项目目录执行一次 `opscli app init`，让 `.opscli/app.json` 和 Git `origin` 同步到新仓库；未同步时 `app push` 会阻止推送，避免把源码发到错误环境。

## 5. 常见错误

| 错误码 | 说明 | 处理方式 |
|---|---|---|
| `APP-NOT-BOUND` | 缺少 `.opscli/app.json` | 先执行 `opscli app create` |
| `APP-ALREADY-BOUND` | 目录已绑定其他站点 | 更换目录或确认原绑定 |
| `GIT-NOT-INITIALIZED` | 尚未初始化 Git | 执行 `opscli app init` |
| `GIT-ORIGIN-MISMATCH` | `origin` 与绑定仓库不一致 | 重新执行 `opscli app init` |
| `GIT-010` | Git 命令失败 | 根据 Git 原始错误检查身份、网络或远端分支 |

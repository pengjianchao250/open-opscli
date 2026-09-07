# 已废弃：opscli app 三指令旧方案

> 日期：2026-09-01  
> 废弃日期：2026-09-02  
> 状态：已废弃，不得作为当前实现、测试或配置依据。

本文原方案基于所有站点共用一个源码仓库、由 `OPSCLI_APP_REPO_URL` 配置目标仓库。其后续记录中的自动 release 方案也已失效；本文不得用于判断当前命令职责。

当前约束如下：

- 每个站点对应 AppHub 管理的独立 Gitea 仓库 `apps/{slug}`；
- 站点完整 `repo_url` 由 AppHub 的创建应用或 `git-config` 接口返回；
- opscli 不配置 Gitea 根地址，不使用 `OPSCLI_APP_REPO_URL`；
- AppHub 服务根地址只使用 `OPSCLI_APPHUB_URL`；
- `opscli app push` 只执行普通 Git commit/push，源码到达远端后立即结束；
- 用户命令只有 `create / init / push` 三个，不提供 release 命令。

现行设计请参考：

- `docs/design/2026-09-05-opscli-app三命令源码交付职责定稿.md`
- `docs/guide/AppHub应用创建初始化与源码推送指南.md`

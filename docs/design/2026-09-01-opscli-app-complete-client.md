# 已废弃：opscli app 三指令旧方案

> 日期：2026-09-01  
> 废弃日期：2026-09-02  
> 状态：已废弃，不得作为当前实现、测试或配置依据。

本文原方案基于所有站点共用一个源码仓库、由 `OPSCLI_APP_REPO_URL` 配置目标仓库，以及 Git push 后不调用 AppHub release 的过渡设计。该设计已经被“一站点一仓库”和正式 AppHub 发布闭环取代。

当前约束如下：

- 每个站点对应 AppHub 管理的独立 Gitea 仓库 `apps/{slug}`；
- 站点完整 `repo_url` 由 AppHub 的创建应用或 `git-config` 接口返回；
- opscli 不配置 Gitea 根地址，不使用 `OPSCLI_APP_REPO_URL`；
- AppHub 服务根地址只使用 `OPSCLI_APPHUB_URL`；
- `opscli app push` 在 Git push 成功后调用 AppHub release，并跟踪 SSE 发布进度；
- 用户命令仍然只有 `create / init / push` 三个。

现行设计请参考：

- `docs/design/2026-09-02-opscli-app一站点一仓库第一阶段需求定稿.md`
- `docs/design/2026-09-02-opscli-app-AppHub-API分析与改造方案.md`
- `docs/guide/AppHub应用发布命令使用指南.md`

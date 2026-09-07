# ops-app 模板克隆后 Git 脱离方案

> 日期：2026-09-07  
> 范围：`opscli app` 新项目模板获取流程、`ops-app-build-spec` Skill 与源码交付前 Git 安全边界。

## 1. 背景

新项目当前直接通过 `git clone` 获取统一模板。clone 完成后，项目根目录会继承模板仓库的 `.git`、提交历史和 `origin`。在执行 `opscli app init` 切换远端之前，用户如果误执行 `git push`，业务代码可能被推回模板仓库。

## 2. 决策

保留直接 clone，不引入临时目录，也不改用 `git archive`。模板 clone 成功后必须立即删除项目根目录的 `.git`，验证清理成功后才能执行 `opscli app create` 和 `opscli app init`。

固定流程：

```text
clone 模板到项目目录
→ 删除并验证项目根目录 .git
→ opscli app create
→ opscli app init
→ 核对业务 origin
→ 开始业务开发
```

## 3. 安全边界

- 只允许删除用户明确指定的项目根目录下名为 `.git` 的直接子项。
- clone 前目标目录必须不存在或为空，禁止覆盖已有项目。
- clone 成功后如果 `.git` 不存在、无法删除或删除后仍存在，流程立即失败。
- `.gitignore`、模板源码和其他点文件必须保留。
- 清理完成前不得执行 `opscli app create/init`，不得开始业务开发。
- `opscli app init` 负责重新执行 `git init`，并将 AppHub 返回的业务仓库设置为新的 `origin`。
- 初始化完成后必须确认 `origin` 不再指向统一模板仓库。

## 4. 落地范围

- 为 `ops-app-build-spec` 增加安全 clone 辅助脚本，封装 clone、`.git` 删除和结果验证。
- 更新 Skill 新项目流程和部署规范，禁止继续依赖“切换模板 origin”的旧流程。
- 增加脚本行为测试和 Skill 契约测试。
- 不修改 `opscli/app/services/gitops.py`；其现有逻辑已经支持“目录中存在源码但没有 `.git`”的初始化场景。
- 不修改模板仓库中的 `bind-apphub-git.py`，该脚本仅保留为参考。

## 5. 非目标

- 不新增 `opscli app` 子命令。
- 不在 `opscli app create` 中删除任何 Git 元数据。
- 不使用临时 clone 目录。
- 不使用 `git archive`。
- 不自动清理 clone 失败后留下的目录，以便保留原始失败证据。

## 6. 验收标准

1. 新项目可以从统一模板仓库获取全部受版本控制的模板文件。
2. 模板准备完成后，项目根目录不存在 `.git`，但 `.gitignore` 保持存在。
3. 非空目标目录会在 clone 前被拒绝。
4. `.git` 清理失败时命令返回非零，后续 `create/init` 不会被执行。
5. `opscli app init` 可以在该目录中创建全新 Git 仓库并绑定 AppHub 业务远端。
6. 安装后的 `ops-app-build-spec` Skill 包含安全 clone 脚本和更新后的部署规范。

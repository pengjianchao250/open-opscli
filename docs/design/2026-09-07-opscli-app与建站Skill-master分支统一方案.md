# opscli app 与建站 Skill master 分支统一方案

> 日期：2026-09-07  
> 状态：已确认并落地  
> 范围：`opscli/app`、统一模板配置、`ops-app-build-spec`、`ops-app-data-builder`、测试与使用文档。

## 1. 背景

AppHub 后端自动部署从应用源码仓库的 `master` 分支取代码。此前 `opscli app`、模板配置和建站 Skill 仍以 `main` 为默认分支，会造成源码已推送但后端部署读取不到对应提交。

## 2. 决策

新应用建站链路统一使用 `master`：

1. 统一模板仓库继续使用 `http://10.1.13.143:3000/aukeys-admin/template.git` 作为 clone URL，模板分支改为 `master`。
2. AppHub 新应用源码仓库默认分支为 `master`。
3. `opscli app init` 将本地分支规范为 binding 中的 `default_branch`；新应用缺省值为 `master`。
4. `opscli app push` 普通推送 `HEAD:master`，并以 `origin/master` 做远端状态和 fast-forward 校验。
5. `.opscli/app.json` 从 AppHub 响应读取 `default_branch`，响应缺失时使用 `master`。
6. `ops-app-data-builder` 在生成数据层前校验本地分支、业务 `origin` 和 `origin/master`。

## 3. 新应用流程

```text
clone template/master
→ 删除模板 .git
→ opscli app create
→ opscli app init（建立本地 master 并绑定业务 origin/master）
→ 开发
→ opscli app push（HEAD:master）
→ AppHub 后端从 master 自动部署
```

模板页面地址中的 `/template/master` 只用于浏览分支；Git clone 仍使用以 `.git` 结尾的仓库 URL，并通过 `--branch master` 选择分支。

## 4. 兼容边界

- 本次只约束新应用，不增加旧应用 `main` 到 `master` 的迁移、检测或自动修复逻辑。
- Git 服务内部按 binding 的 `default_branch` 执行，避免把分支名散落在命令拼接中；新建 binding 的默认值固定为 `master`。
- 初始化结果字段使用 `remote_branch`、`remote_branch_sha`、`remote_branch_exists`，不再把字段名绑定到 `main`。
- 不修改模板仓库中的参考脚本 `bind-apphub-git.py`。

## 5. 验收标准

1. 默认模板配置和安全 clone 脚本都选择 `master`。
2. 新建 binding 默认记录 `default_branch=master`，并能读取 AppHub 返回的同名字段。
3. init、fetch、upstream、merge-base、push 和远端探测全部针对同一 binding 分支。
4. build-spec 明确模板与业务仓库都使用 `master`。
5. data-builder 在分支或业务远端不满足要求时停止生成。
6. 旧应用不在本次改造范围内。

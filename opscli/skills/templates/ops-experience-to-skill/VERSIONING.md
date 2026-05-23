# 本地版本管理规则

这个 Skill 已经作为独立 git 仓库管理。当前稳定点使用 tag 标记，后续修改不要直接覆盖已确认版本。

## 当前稳定版

- 版本：`0.4.2`
- 标签：`v0.4.2`
- 说明：跨境运营经验转 Skill 的中文版本，已包含 ops 数据、跨工具、脚本、HTML、评测、发布治理、本地版本管理、执行日志和内测候选提交；新增运营 Skill 统一框架标准、已有 Skill 归一化流程、阶段 0 访谈的交互式提问与降级规则，以及生成 Skill 的默认执行策略。新建和改造 Skill 默认采用轻量主文件、按需 references、稳定 scripts，并区分“日常直接执行”和“异常/测试/优化时展开分析”。

## 初始版

- 版本：`0.1.0`
- 标签：`v0.1.0`
- 分支：`pre-article-initial`
- 说明：阅读并吸收《重新定义Skill开发》文章之前的版本。该版本保留了业务 6 维访谈、ops 数据、跨工具、脚本、HTML 和评测闭环，但不包含文章启发后新增的发布治理、执行日志、自我迭代兜底和本地版本管理说明。

## 修改前

每次修改前先做三件事：

1. 查看当前状态：`git status --short`
2. 查看最近稳定点：`git log --oneline --decorate -5`
3. 如果当前目录有未提交修改，先确认这些修改是否属于用户已完成版本；不要静默覆盖。

## 修改时

建议使用短分支或直接提交小步变更：

```bash
git switch -c change/YYYYMMDD-topic
```

如果只是一次小修，也可以留在当前分支，但完成后必须提交，并在 `CHANGELOG.md` 写清变更。

## 修改后

完成一次用户确认的版本后：

```bash
git status --short
git add .
git commit -m "Update ops-experience-to-skill ..."
```

如果用户确认它是新的稳定版，再打 tag：

```bash
git tag vX.Y.Z
```

## 查看与恢复

查看历史：

```bash
git log --oneline --decorate --all
```

查看某个版本内容：

```bash
git show v0.1.0:SKILL.md
```

不要用 `git reset --hard` 或强制覆盖来恢复。需要回看旧版时，优先新建分支：

```bash
git switch -c inspect-v0.2.0 v0.2.0
```

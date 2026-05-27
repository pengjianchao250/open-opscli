# 本地版本管理规则

这个 Skill 已经作为独立 git 仓库管理。当前稳定点使用 tag 标记，后续修改不要直接覆盖已确认版本。

## 当前稳定版

- 版本：`0.5.4`
- 标签：`v0.5.4`
- 说明：当前版本在原有硬门槛、内部数据预检、影响点驱动改造和回归测试基础上，新增“经验盘点 / Skill 规划 / 资产去重”触发边界，要求先做知识地图和资产去重，再决定复用、改造或新建。

## 历史稳定版

- `0.5.3`：恢复顶层 `AGENTS.md`、`CHANGELOG.md`、`VERSIONING.md` 作为维护文档。
- `0.5.2`：加入“静态策略扫描 + 模拟对话输出测试”双层回归。
- `0.5.1`：加入 8 个场景的脚本化静态回归测试，并把旧 Skill 改造改为影响点驱动。
- `0.5.0`：重写主 Skill 结构，建立硬门槛、交付闭环和创建边界。
- `0.4.2`：跨境运营经验转 Skill 的中文稳定版本，包含统一框架、交互式访谈、默认执行策略和治理能力。
- `0.1.0`：阅读并吸收《重新定义Skill开发》文章之前的初始版本，标签 `v0.1.0`，分支 `pre-article-initial`。

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
git commit -m "Update ops-creator-skill ..."
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
git show v0.5.0:SKILL.md
```

不要用 `git reset --hard` 或强制覆盖来恢复。需要回看旧版时，优先新建分支：

```bash
git switch -c inspect-v0.5.0 v0.5.0
```

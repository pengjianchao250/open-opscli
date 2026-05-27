# AGENTS.md instructions for ops-creator-skill

本目录是 `ops-creator-skill` 的本地稳定版本仓库。维护这个 Skill 时遵守：

- 修改前先查看 `git status --short` 和 `git log --oneline --decorate -5`。
- 不要静默覆盖用户已经确认的稳定版本；如果要大改，先说明将基于哪个 tag/commit 修改。
- 每次完成可用变更后，更新 `CHANGELOG.md`，并提交一个小而清楚的 commit。
- 用户确认新的稳定版后，再打新 tag，例如 `0.2.1`。
- 不要使用 `git reset --hard`、强制 checkout 或删除历史来恢复旧版；需要查看旧版时创建临时分支。
- `SKILL.md`、references、用户提示和输出模板默认中文；技术标识符保留英文或原文。

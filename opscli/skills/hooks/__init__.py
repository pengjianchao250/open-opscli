"""Skill 使用上报 Hook 模块。

提供 PostToolUse Hook 脚本、稳定 Runner，以及 Claude/Codex 配置注入器。
Codex 用户级 Hook 以 ~/.codex/config.toml 为唯一 canonical 表示；历史
~/.codex/hooks.json 条目可通过 `opscli skills hooks migrate` 迁移并回滚。
"""

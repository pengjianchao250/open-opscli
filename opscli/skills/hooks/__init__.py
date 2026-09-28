"""Skill 使用上报 Hook 模块。

提供 PostToolUse Hook 脚本、稳定 Runner，以及 Claude/Codex 配置注入器。
Codex 用户级 Hook 复用 ~/.codex/hooks.json 或 ~/.codex/config.toml 中已有的
有效表示，并可通过 `opscli skills hooks migrate` 收敛重复表示及回滚。
"""

"""MCP 工具模块包。

按工具类型分层：
- helpers.py  — 共享辅助函数（_ok / _err / 工厂函数）
- auth.py     — 认证授权相关工具（auth_*）
- query.py    — 数据查询相关工具（query_*）
- skills.py   — Skill 管理相关工具（skills_*）

每个工具模块暴露 register(mcp) 函数，由 server.py 统一调用注册。
"""

"""MCP 工具模块包。

按工具类型分层：
- helpers.py  — 共享辅助函数（_ok / _err / 工厂函数）
- auth.py     — 认证授权相关工具（auth_*）
- query.py    — 数据查询相关工具（query_*）
- dashboard.py — 仪表盘领域规范读取工具（dashboard_*_spec_must_read）
- skills.py   — Skill 管理相关工具（skills_*）
- amazon.py   — Amazon 商品抓取工具（amazon_*，需 playwright 可选依赖）
- amazon_rufus.py — Amazon Rufus 获取工具（amazon_rufus_*）
- chatgpt.py  — OpenAI Company Knowledge 兼容工具（search / fetch）

每个工具模块暴露 register(mcp) 函数，由 server.py 统一调用注册。
amazon 工具因依赖可选扩展 playwright，server.py 会用 try/except 条件注册。
"""

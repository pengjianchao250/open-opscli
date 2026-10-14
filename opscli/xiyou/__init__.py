"""西柚 OpenAPI v2 集成。

普通查询通过 ``opscli xiyou`` 代理远端 MCP，或由宿主直连 MCP 工具。
供应商 Provider 位于 ``opscli.xiyou.providers.xydc_openapi``，仅供服务端使用；
旧网页/爬虫命令和旧 xydc MCP Provider 已废弃并移除。
"""

from __future__ import annotations


---
name: ops-seller-sprite
mcp-version: v1.0.0
description: 使用 opscli MCP 工具采集卖家精灵关键词挖掘、高频词、页面截图、Markdown 和接口证据
---

# ops-seller-sprite (MCP 预留)

当前一期以 CLI 命令为主。MCP 模式保留同名 Skill 文档，用于后续接入 `seller_sprite_*` tools 时对齐调用语义。

---

## 预期工具

```python
seller_sprite_collect(asin="B00MA2T9BC", keyword="bed", site="us", period="30d", limit=50, frequency_phrase_count=1, trend_limit=0, trend_tabs="all")
seller_sprite_frequency(keyword="bed", site="us", period="30d", frequency_phrase_count=1)
seller_sprite_keyword_mining(keyword="bed", site="us", period="30d", limit=50, trend_limit=0, trend_tabs="all")
seller_sprite_keyword_reverse(asin="B07Z82895W", site="us", period="30d", limit=50, trend_limit=0, trend_tabs="all")
seller_sprite_schema()
```

---

## 当前边界

如果当前 MCP Server 未暴露 `seller_sprite_*` tools，应改用 CLI 模式的 `opscli seller-sprite ...` 命令。

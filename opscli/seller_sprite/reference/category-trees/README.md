# 卖家精灵类目树资料

本目录保存卖家精灵类目筛选使用的节点快照和名称映射。

- 类目筛选不是自由文本，接口最终使用 `nodeIdPaths`。
- 类目树来源接口为 `GET /v2/competitor-lookup/nodes`。
- 快照文件按 `{market}-{table}.json` 命名。
- `nodes` 保存已抓到的真实树节点。
- `categoryIndex` 保存名称到节点 ID 的映射，用于 skill 按用户输入匹配。
- `ambiguousTerms` 保存重名词，命中时必须让用户确认完整路径。
- 同一个名称可能对应多个节点时，不应自动选择，应要求用户明确类目路径。
- 当前 `US-bsr_sales_nearly.json` 为局部快照，已包含根类目，以及本次展开到的 `Appliances`、`Arts, Crafts & Sewing`、`Home & Kitchen` 等 2-5 级节点。

# 卖家精灵场景契约资料

本目录沉淀接口直连场景的回归资料。

- `manifest.json`：场景路由、接口、请求字段、响应行路径、核心指标和模板来源。
- `official-headers.json`：按官方导出模板整理的业务表头快照。
- `sample-response.json`：仅保留脱敏后的真实响应结构和代表性业务字段，不保存登录态。
- `../category-trees/*.json`：类目树节点快照和名称到 `nodeIdPaths` 的映射。

当前资料来自代码注册表、payload 构造逻辑、导出列定义和既有接入文档。官方 XLSX 原件未随代码提交时，仅记录原始文件名，不声明本地文件存在。

官网实际导出的只读 XLSX 统一归档在
`tests/fixtures/seller_sprite/official_exports/<scenario>/`，并通过该目录的
`index.json` 固定大小和 SHA-256。运行时参考目录只保存可发布的 JSON
契约和脱敏样例，不存放二进制工作簿。

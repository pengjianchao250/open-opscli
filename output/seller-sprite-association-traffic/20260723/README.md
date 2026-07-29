# 卖家精灵关联流量回归基线

本目录记录 2026-07-23 官网“关联流量”实测结果，供后续 MCP 回归、Skill 更新和导出格式校验。

## 查询样本

- 页面：`https://www.sellersprite.com/v3/relation-keyword`
- 站点：美国站，`market=1`
- 输入：5 个父/子体 ASIN
- 查询方式：用全部变体查询，`queryVariations=true`
- 弹窗统计：全部变体 375，当前变体 0
- 主查询：`POST /v3/api/relation/traffic`
- 响应路径：`data.pagerDto.items`
- 响应总数：375

结构化请求和代表性响应保存在：

- `../../../opscli/seller_sprite/reference/scenarios/association-traffic/sample-response.json`
- `../../../opscli/seller_sprite/reference/scenarios/association-traffic/manifest.json`

## 官方导出

- 原件：`../../RelatedProducts-US-B098T9ZFB5-batch(5)-260723.xlsx`
- 文件大小：240,906 字节
- SHA-256：`c06a014a4677857fe40d92fcb8f2aa77ca4966fc35628297aa8c51302b3fa7a9`
- 工作表：业务主表、`Notes`
- 主表：375 行数据、56 列、冻结窗格 `A2`
- 主表标题：`Related-B098T9ZFB5-batch(5)(31`，由 Excel 31 字符限制截断

本地 MCP 导出只生成 56 列业务主表，不复制官网的 `Notes` 客服说明页。

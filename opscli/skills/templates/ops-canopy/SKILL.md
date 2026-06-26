---
name: ops-canopy
description: Use when the user explicitly asks to query or export Amazon data through the public `opscli canopy` CLI backed by the remote Canopy beta MCP flow, especially product details, search, reviews, offers, variants, seller, category, deals, or best sellers.
---

# ops-canopy

用于把 Canopy 自然语言需求映射成正式 `opscli canopy ...` 命令，并沿着“本地 CLI -> 远端 MCP 配置 -> 远端 `beta_canopy_*` tool”这条公开链路完成查询和导出。

虽然远端工具名仍是 `beta_canopy_*`，但对用户公开的正式 CLI 入口已经收敛为 `opscli canopy ...`。
正式 CLI 依赖本机已完成 OPS 授权；若本机未登录或登录态过期，先完成 `opscli auth login` 再继续。

## 快速规则

1. 正式命令面默认只讲 `opscli canopy ...`，不要向用户暴露内部调试命令、本地 API key 文件或本地落盘目录。
2. 这是 Canopy/beta 服务的正式公开 CLI 壳；只有在用户明确要用 Canopy / beta 测试服务时才路由到这里。
3. 默认 `domain=US`，导出格式对用户只开放 `xls`；内部实际生成 `.xlsx`。
4. `product`、`product-variants`、`product-stock`、`product-sales`、`product-reviews`、`product-offers` 这类商品场景，至少提供 `asin`、`url`、`gtin` 三者之一。
5. `search` 和 `autocomplete` 需要 `searchTerm`；`category` 需要 `categoryId`；`seller` 需要 `sellerId`；`bestsellers` 需要 `categoryId` 或 `url`。
6. `product-reviews` 未给 `page` 时默认补 `page=1`；可用 `query/text/natural_language` 这类自然语言字段表达“差评”“已验证购买”等筛选意图。
7. 不向用户暴露 beta 工具名、API key、服务器本地路径、原始 JSON 或调试文件。
8. 如果当前宿主是远端 MCP 直连而不是 CLI 代理，继续看 [SKILL_MCP.md](SKILL_MCP.md)。

## 正式链路

- 本地 CLI 代理链路：`opscli canopy ...`
- 远端 MCP tools：`beta_canopy_scenarios`、`beta_canopy_run`、`beta_canopy_job_status`、`beta_canopy_export`
- 常见前置：确认本机 `opscli auth login` 已完成且登录态仍有效

## 命令面

1. 查看场景

```powershell
opscli canopy scenarios
```

2. 执行场景

```powershell
opscli canopy run product --domain US --params '{"asin":"B0B3JBVDYP"}'
```

可用参数：

- `scenario`：场景 ID，如 `product`、`search`、`product-reviews`
- `--domain`：Amazon 站点，默认 `US`
- `--params`：JSON 对象字符串
- `--job-id`：自定义任务 ID
- `--export-format`：仅公开 `xls`
- `--timeout-seconds`：远端请求超时时间，默认 `60`

3. 查任务结果

```powershell
opscli canopy job-status <job_id>
```

4. 查导出文件

```powershell
opscli canopy export <job_id>
```

## 最小工作流

1. 判断是商品详情、搜索、评论、报价、类目、卖家还是榜单场景
2. 只补当前场景缺失的主标识参数
3. 组织 `scenario + domain + params`，执行 `opscli canopy run ...`
4. 用户需要续查或只要文件链接时，再用 `job-status` / `export`

## 场景速查

| 用户意图 | scenario | 必填参数 | 常用可选参数 |
| --- | --- | --- | --- |
| 查商品详情 | `product` | `asin/url/gtin` 三选一 | 无 |
| ASIN 转 GTIN | `product-gtin-from-asin` | `asin` | 无 |
| GTIN 转 ASIN | `product-asin-from-gtin` | `gtin` | 无 |
| 查变体 | `product-variants` | `asin/url/gtin` 三选一 | 无 |
| 查库存估算 | `product-stock` | `asin/url/gtin` 三选一 | 无 |
| 查销量估算 | `product-sales` | `asin/url/gtin` 三选一 | 无 |
| 查评论 / VOC / 差评 | `product-reviews` | `asin/url/gtin` 三选一 | `page`, `rating`, `onlyVerifiedReviews`, `search` |
| 查报价 / Offer | `product-offers` | `asin/url/gtin` 三选一 | `page` |
| 搜商品 | `search` | `searchTerm` | `page`, `limit`, `categoryId`, `sort` |
| 搜索建议 | `autocomplete` | `searchTerm` | `category` |
| 查类目树 | `categories` | 无 | 无 |
| 查类目商品 | `category` | `categoryId` | `page`, `sort` |
| 查卖家 | `seller` | `sellerId` | `page` |
| 查作者 | `author` | `asin` | `page` |
| 查 Deals | `deals` | 无 | `page`, `limit`, `categoryIds` |
| 查 Best Sellers | `bestsellers` | `categoryId` 或 `url` | `page`, `limit` |
| 查榜单类目 | `bestseller-categories` | 无 | 无 |

## 常用示例

商品详情：

```powershell
opscli canopy run product --domain US --params '{"asin":"B0B3JBVDYP"}'
```

关键词搜索：

```powershell
opscli canopy run search --domain US --params '{"searchTerm":"coffee grinder","page":1,"limit":20}'
```

评论筛选：

```powershell
opscli canopy run product-reviews --domain US --params '{"asin":"B0B3JBVDYP","query":"查差评和已验证购买"}'
```

报价：

```powershell
opscli canopy run product-offers --domain US --params '{"asin":"B0B3JBVDYP","page":1}'
```

Best Sellers：

```powershell
opscli canopy run bestsellers --domain US --params '{"categoryId":"172282","page":1,"limit":20}'
```

## 回复规则

- 成功时只保留：场景、站点、查询对象、`job_id`、`row_count`、导出文件
- 若导出上传失败，只说明“云端上传失败，已保留服务端本地导出”，不要把本地路径包装成可下载链接
- 评论场景可以在回复里概括筛选条件，但不要打印完整 JSON 参数
- 不要主动展开 `beta_canopy_*` 工具名、Canopy API key 或测试服务内部实现

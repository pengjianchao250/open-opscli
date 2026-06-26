---
name: ops-beta-canopy-internal
mcp-version: v1.0.0
description: beta MCP 中文自然语言使用规范，用于通过 Canopy REST API 查询 Amazon 商品、搜索、评论、报价、类目、卖家、榜单等数据。
visibility: internal
---

# ops-beta Canopy MCP

这是 `beta_spec_must_read` 读取的内部 MCP 使用规范，位于
`opscli/skills/templates/ops-canopy/` 下，不再单独维护 `opscli/mcp/references/beta/` 副本。

`beta` 是测试阶段小模块名，当前封装 Canopy REST API。Canopy 官方接口细节见
`opscli/skills/templates/ops-canopy/references/OFFICIAL.md`。

## Agent 快速执行规则

0. **强制触发门槛**：只有当用户明确提到“beta”、“Canopy”、“测试服务”、“使用 beta 功能”、“beta 接口”等测试阶段能力时，才允许调用 `beta_*` MCP 工具。普通“查 Amazon 商品 / 查 ASIN / 搜关键词 / 查评论”请求不得自动路由到 beta，应优先使用正式模块或先询问用户是否要使用 beta。
1. 用户明确要求使用 beta/Canopy 查 Amazon 商品信息、查 ASIN、查商品详情时，使用 `product` 场景。
2. 用户明确要求使用 beta/Canopy 搜关键词、搜商品时，使用 `search` 场景，参数名用 `searchTerm`。
3. 用户明确要求使用 beta/Canopy 查评论、差评、VOC 时，使用 `product-reviews` 场景。
4. 用户明确要求使用 beta/Canopy 查报价、Offer、Buy Box、卖家报价时，使用 `product-offers` 场景。
5. 用户明确要求使用 beta/Canopy 查变体、父子体、颜色尺寸时，使用 `product-variants` 场景。
6. 用户明确要求使用 beta/Canopy 查库存、销量估算时，分别使用 `product-stock` / `product-sales` 场景。
7. 站点缺省用 `US`；Canopy 参数名是 `domain`，不要向 Canopy 发送 `country`。
8. 最终回复只给业务结果和必要说明，不展示任何认证配置细节。
9. 对用户只开放 MCP beta 查询能力，不提供 CLI、curl、Python 或直连 REST 调用方式。
10. 当前 beta 会为每次 `beta_canopy_run` 生成 Excel 导出；用户可见导出格式只能是 `xls`，内部按 Keepa 兼容模式生成 `.xlsx` 文件并返回 `export.url`。
11. `product-reviews` 未指定 `page` 时默认补 `page=1`，避免一次拉取过多评论导致 Canopy 或上游 Amazon 超时。
12. `beta_canopy_run` 默认超时为 60 秒；用户明确要求更短或更长时，可通过 `timeout_seconds` 覆盖。

## 工具列表

- `beta_spec_must_read`: 仅在用户明确提到 beta/Canopy/测试服务时读取本使用规范。
- `beta_canopy_scenarios`: 仅在用户明确提到 beta/Canopy/测试服务时列出当前支持的 Canopy API 场景。
- `beta_canopy_run`: 仅在用户明确提到 beta/Canopy/测试服务时按场景调用 Canopy REST API。

## 禁止自动调用场景

以下请求即使看起来能被 Canopy 覆盖，也不要直接调用 `beta_*` 工具：

- 用户只说“查 Amazon 商品”“查 ASIN”“查评论”“搜关键词”，但没有提到 beta/Canopy/测试服务。
- 用户正在使用 Keepa、Rufus、SellerSprite、西柚等正式工具上下文。
- 用户要求 CLI、curl、Python 示例、OpenAPI 细节或直连 REST 调用方式。

遇到上述情况，应使用正式工具或先追问：“是否要使用 beta/Canopy 测试接口？”不要向用户输出 CLI、curl、Python 或直连 REST 示例。

## 站点 domain

Canopy 使用 `domain` 表示 Amazon 站点，默认 `US`。

支持值：`US`, `UK`, `CA`, `DE`, `FR`, `IT`, `ES`, `AU`, `IN`, `MX`, `BR`, `JP`, `PL`。

## 场景和必填参数

| 用户说法 | scenario | 必填参数 | 常用可选参数 | 说明 |
| --- | --- | --- | --- | --- |
| 查商品详情、查 ASIN | `product` | `asin`/`url`/`gtin` 三选一 | `domain` | 获取商品标题、价格、评分、图片、卖家等。 |
| ASIN 转 GTIN | `product-gtin-from-asin` | `asin` | `domain` | 根据 ASIN 获取 GTIN。 |
| GTIN 转 ASIN | `product-asin-from-gtin` | `gtin` | `domain` | 根据 GTIN 获取 ASIN。 |
| 查变体、父子体 | `product-variants` | `asin`/`url`/`gtin` 三选一 | `domain` | 获取商品变体。 |
| 查库存估算 | `product-stock` | `asin`/`url`/`gtin` 三选一 | `domain` | 获取库存估算。 |
| 查销量估算 | `product-sales` | `asin`/`url`/`gtin` 三选一 | `domain` | 获取销量估算。 |
| 查评论、差评、VOC | `product-reviews` | `asin`/`url`/`gtin` 三选一 | `page`, `rating`, `onlyVerifiedReviews`, `search` | 获取商品评论。 |
| 查报价、Offer | `product-offers` | `asin`/`url`/`gtin` 三选一 | `page` | 获取报价与卖家 offer。 |
| 搜关键词、搜商品 | `search` | `searchTerm` | `page`, `limit`, `categoryId`, `sort` | 搜索 Amazon 商品。 |
| 搜索自动补全 | `autocomplete` | `searchTerm` | `category` | 获取搜索建议。 |
| 查类目树 | `categories` | 无 | `domain` | 获取类目 taxonomy。 |
| 查类目商品 | `category` | `categoryId` | `page`, `sort` | 获取指定类目信息。 |
| 查卖家 | `seller` | `sellerId` | `page` | 获取卖家信息与商品。 |
| 查作者 | `author` | `asin` | `page` | 获取作者信息。 |
| 查 Deals | `deals` | 无 | `page`, `limit`, `categoryIds` | 获取优惠商品。 |
| 查 Best Sellers | `bestsellers` | `categoryId`/`url` 二选一 | `page`, `limit` | 获取榜单商品。 |
| 查 Best Seller 类目 | `bestseller-categories` | 无 | `domain` | 获取榜单类目入口。 |

## 调用示例

商品详情：

```json
{
  "scenario": "product",
  "domain": "US",
  "params": {"asin": "B0B3JBVDYP"}
}
```

关键词搜索：

```json
{
  "scenario": "search",
  "domain": "US",
  "params": {"searchTerm": "coffee grinder", "page": 1, "limit": 20}
}
```

评论：

```json
{
  "scenario": "product-reviews",
  "domain": "US",
  "params": {"asin": "B0B3JBVDYP", "page": 1, "rating": "ONE_STAR", "onlyVerifiedReviews": true},
  "timeout_seconds": 60
}
```

### product-reviews 自然语言别名

`product-reviews` 支持在 `params.query`、`params.text`、`params.natural_language`、`params.naturalLanguage`、`params.user_input`、`params.userInput` 中放入简短自然语言筛选意图。工具会在不覆盖显式结构化参数的前提下补充 Canopy 官方参数：

- `差评`、`一星`、`1星`、`1 星`、`one star`、`1-star` → `rating=ONE_STAR`
- `二星/2星`、`三星/3星`、`四星/4星`、`五星/5星` 分别映射到对应星级枚举
- `已验证购买`、`验证购买`、`verified purchase`、`verified reviews`、`only verified` → `onlyVerifiedReviews=true`

如果已经显式传入 `rating` 或 `onlyVerifiedReviews`，以显式结构化参数为准。

示例：

```json
{
  "scenario": "product-reviews",
  "domain": "US",
  "params": {"asin": "B0B3JBVDYP", "query": "查差评和已验证购买"}
}
```

## 导出与任务落盘

`beta_canopy_run` 会按 Keepa 的兼容口径生成 Excel 导出：

- 用户可见参数 `export_format` 只能是 `xls`（空值也会归一为 `xls`）。
- 不接受 `xlsx`、`csv`、`json` 等其它用户导出格式。
- 内部实际使用 `openpyxl` 生成 Excel 兼容 `.xlsx` 文件，这是 Keepa 当前相同做法；`xls` 是用户侧兼容别名。
- 导出文件会复用 OPS 公共上传能力上传到服务器；上传成功时 `export.url` 是远端下载链接。
- 如果上传失败，`warnings` 会包含 `stage=file_upload`，回复中必须说明“导出文件上传失败，已保留服务端本地文件”，不要把本地 path 当成可交付下载链接。
- 默认任务目录：`opscli/beta/canopy/api_runs/{job_id}`。
- 内部文件：`params.json`、`raw.json`、`result.json`、`{job_id}.xlsx`。
- MCP 对外返回只暴露 `export.url` 和摘要，不暴露本地 path、`params_path`、`raw_path`、`result_path` 或认证配置。

## 回复模板

成功时按以下口径回复，保持简短，不展示本地路径、API key、认证细节或原始 JSON：

```text
已使用 beta/Canopy 查询 Amazon {domain} 商品 {asin} 的评论。

- 查询条件：page={page}，{rating/onlyVerifiedReviews/search 等筛选条件；没有则写“未额外筛选”}
- 评论行数：{row_count}
- 导出文件：{export.url}

{如有 warnings，用一句话说明；无 warnings 不写}
```

当 `export.url` 不是 `http://` 或 `https://` 远端链接时，不要包装成“已上传”；应明确说明当前只有服务端本地导出，需要根据 `warnings` 判断是否上传失败。

## 错误处理

- `400`: 参数错误，检查必填参数和字段名。
- `401`: Canopy 认证配置异常。
- `402`: 账号额度或付费问题。
- `500`: Canopy 服务端或 Amazon 上游异常。

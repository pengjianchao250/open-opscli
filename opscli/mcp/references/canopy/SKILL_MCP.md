# Canopy 测试调研服务 MCP 说明

> 官方文档：<https://rest.canopyapi.co/>  
> OpenAPI：<https://rest.canopyapi.co/api/v1/openapi.json>

## 服务定位

Canopy MCP 是 Amazon 数据的**测试调研服务**，用于验证第三方数据能力、接口参数和调研流程，不是默认生产数据源。

只有用户明确提到 `Canopy`、`beta` 或“测试服务”时才可调用。普通的 Amazon 商品、ASIN、评论或关键词查询不得自动路由到 Canopy。

## MCP 工具

| 工具 | 用途 |
| --- | --- |
| `beta_spec_must_read` | 读取本说明。 |
| `beta_canopy_scenarios` | 返回当前支持的场景、参数和接口路径。 |
| `beta_canopy_run` | 执行一个 Canopy 场景并生成 Excel 导出。 |
| `beta_canopy_job_status` | 根据 `job_id` 查询任务结果。 |
| `beta_canopy_export` | 根据 `job_id` 获取导出文件下载信息。 |

调用前先执行 `beta_spec_must_read`，再执行 `beta_canopy_scenarios` 核对实时场景元数据。

## 通用调用规则

- `domain` 表示 Amazon 站点，默认 `US`。
- 支持站点：`US`、`UK`、`CA`、`DE`、`FR`、`IT`、`ES`、`AU`、`IN`、`MX`、`BR`、`JP`、`PL`。
- `params` 只放场景业务参数，支持 JSON 对象或 JSON 字符串。
- `export_format` 当前只允许 `xls`；内部生成 Excel 兼容的 `.xlsx` 文件。
- `job_id` 可选；不传时自动生成。
- API Key、JWT、本地输出目录等属于服务端配置或内部调试参数，Agent 不应主动传入，也不得向用户展示。
- MCP 响应只返回公开摘要、数据预览和远端导出信息，不应包含凭证或服务端本地路径。

## 场景

| 场景 | 用途 | 必填业务参数 | 可选业务参数 |
| --- | --- | --- | --- |
| `product` | 商品详情 | `asin` / `url` / `gtin` 三选一 | — |
| `product-gtin-from-asin` | ASIN 转 GTIN | `asin` | — |
| `product-asin-from-gtin` | GTIN 转 ASIN | `gtin` | — |
| `product-variants` | 商品变体 | `asin` / `url` / `gtin` 三选一 | — |
| `product-stock` | 库存估算 | `asin` / `url` / `gtin` 三选一 | — |
| `product-sales` | 销量估算 | `asin` / `url` / `gtin` 三选一 | — |
| `product-reviews` | 商品评论 | `asin` / `url` / `gtin` 三选一 | `page`、`rating`、`onlyVerifiedReviews`、`search` |
| `product-offers` | 商品报价和 Buy Box | `asin` / `url` / `gtin` 三选一 | `page` |
| `search` | 商品搜索 | `searchTerm` | `page`、`limit`、`categoryId`、`minPrice`、`maxPrice`、`conditions`、`sort` |
| `autocomplete` | 搜索自动补全 | `searchTerm` | `category` |
| `categories` | Amazon 类目树 | — | — |
| `category` | 指定类目及商品 | `categoryId` | `page`、`sort` |
| `seller` | 卖家及卖家商品 | `sellerId` | `page` |
| `author` | 作者及图书 | `asin` | `page` |
| `deals` | 优惠商品 | — | `page`、`limit`、`categoryIds` |
| `bestsellers` | Best Sellers 榜单 | `categoryId` / `url` 二选一 | `page`、`limit` |
| `bestseller-categories` | Best Seller 顶级类目 | — | — |

以上业务必填约束包含 opscli 为避免无效请求增加的校验；官方 OpenAPI 对部分商品接口未声明“三选一”，但接口语义仍需商品定位参数。

## 搜索参数

`search` 场景支持：

- `searchTerm`：搜索词，必填。
- `categoryId`：类目 ID。
- `page`、`limit`：分页和返回数量。
- `minPrice`、`maxPrice`：价格范围。
- `conditions`：以逗号分隔的商品状态，可使用 `NEW`、`USED`、`RENEWED`。
- `sort`：`FEATURED`、`MOST_RECENT`、`PRICE_ASCENDING`、`PRICE_DESCENDING`、`AVERAGE_CUSTOMER_REVIEW`。

示例：

```json
{
  "scenario": "search",
  "domain": "US",
  "params": {
    "searchTerm": "coffee grinder",
    "page": 1,
    "limit": 20,
    "conditions": "NEW",
    "sort": "AVERAGE_CUSTOMER_REVIEW"
  }
}
```

## 评论参数

`product-reviews` 场景支持：

- `page`：页码，从 1 开始。
- `rating`：`ALL`、`FIVE_STAR`、`FOUR_STAR`、`THREE_STAR`、`TWO_STAR`、`ONE_STAR`。
- `onlyVerifiedReviews`：是否只返回已验证购买评论。
- `search`：评论内容关键词。

示例：

```json
{
  "scenario": "product-reviews",
  "domain": "US",
  "params": {
    "asin": "B0B3JBVDYP",
    "rating": "ONE_STAR",
    "onlyVerifiedReviews": true
  },
  "export_format": "xls"
}
```

## 商品详情示例

```json
{
  "scenario": "product",
  "domain": "US",
  "params": {
    "asin": "B0B3JBVDYP"
  }
}
```

## 任务与导出

1. `beta_canopy_run` 成功后保存返回的 `job_id`。
2. 需要续查时调用 `beta_canopy_job_status(job_id)`。
3. 需要下载文件时调用 `beta_canopy_export(job_id)`。
4. 若任务已生成文件但没有远端 URL，稍后重试；不得向用户返回 `file://` 地址或服务端本地路径。

## 错误处理

| 状态码/错误 | 含义 | 处理方式 |
| --- | --- | --- |
| `400` | 参数校验失败 | 根据场景元数据检查必填参数和格式。 |
| `401` | Canopy 认证失败 | 联系服务维护者检查服务端认证配置，不向用户索取或展示密钥。 |
| `402` | 部分端点的套餐或额度限制 | 当前官方 OpenAPI 仅在商品详情、ASIN 转 GTIN、GTIN 转 ASIN 端点明确声明。 |
| `500` | Canopy 服务端请求失败 | 保留脱敏后的场景、参数和错误摘要用于排障。 |
| 导出 URL 不可用 | 文件尚未上传或上传链路异常 | 稍后续查任务；持续失败时联系服务维护者。 |

MCP Tool 返回 `success=false` 时，按项目 `ops-feedback` 规范提交结构化失败反馈。

## MCP 开关

Canopy 默认注册到 MCP。全局关闭时，在 **MCP Server 进程环境**设置：

```text
OPSCLI_MCP_CANOPY_ENABLED=0
```

`0`、`false`、`no`、`off` 均表示关闭；未设置或其他值表示开启。修改后必须重启 MCP 服务，因为工具在进程启动时注册。

HTTP/SSE 部署还应在 MCP 后台停用或撤销以下历史工具授权，因为本地工具目录同步只新增、不自动删除历史记录：

```text
beta_spec_must_read
beta_canopy_scenarios
beta_canopy_run
beta_canopy_job_status
beta_canopy_export
```

只需对部分用户关闭时，不必关闭全局开关；从对应用户或角色的 `allowed_tools` 中移除以上工具即可。

恢复服务时删除该环境变量或设置 `OPSCLI_MCP_CANOPY_ENABLED=1`，重启 MCP 服务，并按需恢复后台工具状态和授权。

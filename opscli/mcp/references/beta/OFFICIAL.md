# Canopy REST API 官方口径整理

> 来源：`https://rest.canopyapi.co/api/v1/openapi.json` 与 `https://docs.canopyapi.co/examples/rest-python`。本文用于 beta MCP 工具口径整理，不包含真实 API key。

## 基础信息

- Base URL: `https://rest.canopyapi.co`
- OpenAPI: `3.1.0`
- Title: `Canopy API - REST Endpoints`
- Version: `1.0.0`
- 主要用途：Amazon 商品数据、搜索、类目、市场洞察。

## 认证方式

所有请求都需要 header：

```http
API-KEY: <YOUR_CANOPY_API_KEY>
Content-Type: application/json
```

OpenAPI schema 中没有定义标准 `components.securitySchemes`，而是把 `API-KEY` 作为每个接口的 header 参数描述。

## Python REST 示例

```python
import requests

url = "https://rest.canopyapi.co/api/amazon/product"

headers = {
    "API-KEY": "<YOUR_CANOPY_API_KEY>",
    "Content-Type": "application/json",
}

params = {
    "asin": "B0B3JBVDYP",
    "domain": "US",
}

response = requests.get(url, headers=headers, params=params)

if response.status_code == 200:
    data = response.json()
    print(data)
else:
    print(response.status_code, response.text)
```

## 站点参数

Canopy 使用 `domain` 表示 Amazon marketplace，不使用 `country`。

默认值：`US`

支持值：`US`, `UK`, `CA`, `DE`, `FR`, `IT`, `ES`, `AU`, `IN`, `MX`, `BR`, `JP`, `PL`。

## 接口总览

| 分组 | 场景 | Method | Path | 关键参数 | 说明 |
| --- | --- | --- | --- | --- | --- |
| P0 | `product` | GET | `/api/amazon/product` | `asin`/`url`/`gtin`, `domain` | 获取商品详情。 |
| P2 | `product-gtin-from-asin` | GET | `/api/amazon/product/gtin-from-asin` | `asin`, `domain` | ASIN 转 GTIN。 |
| P2 | `product-asin-from-gtin` | GET | `/api/amazon/product/asin-from-gtin` | `gtin`, `domain` | GTIN 转 ASIN。 |
| P0 | `product-variants` | GET | `/api/amazon/product/variants` | `asin`/`url`/`gtin`, `domain` | 获取商品变体。 |
| P0 | `product-stock` | GET | `/api/amazon/product/stock` | `asin`/`url`/`gtin`, `domain` | 获取库存估算。 |
| P0 | `product-sales` | GET | `/api/amazon/product/sales` | `asin`/`url`/`gtin`, `domain` | 获取销量估算。 |
| P0 | `product-reviews` | GET | `/api/amazon/product/reviews` | `asin`/`url`/`gtin`, `domain` | 获取商品评论。 |
| P0 | `product-offers` | GET | `/api/amazon/product/offers` | `asin`/`url`/`gtin`, `domain` | 获取商品报价与 offer。 |
| P0 | `search` | GET | `/api/amazon/search` | `searchTerm`, `domain` | 搜索 Amazon 商品。 |
| P1 | `autocomplete` | GET | `/api/amazon/autocomplete` | `searchTerm`, `domain` | 搜索自动补全。 |
| P1 | `categories` | GET | `/api/amazon/categories` | `domain` | 获取类目 taxonomy。 |
| P1 | `category` | GET | `/api/amazon/category` | `categoryId`, `domain` | 获取指定类目商品。 |
| P1 | `seller` | GET | `/api/amazon/seller` | `sellerId`, `domain` | 获取卖家信息。 |
| P2 | `author` | GET | `/api/amazon/author` | `asin`, `domain` | 获取作者信息。 |
| P1 | `deals` | GET | `/api/amazon/deals` | `domain` | 获取 Deals。 |
| P1 | `bestsellers` | GET | `/api/amazon/bestsellers` | `categoryId`/`url`, `domain` | 获取 Best Sellers。 |
| P1 | `bestseller-categories` | GET | `/api/amazon/bestseller-categories` | `domain` | 获取 Best Seller 类目。 |

## 常用参数

### 商品标识符

商品类接口通常至少需要以下参数之一：

- `asin`
- `url`
- `gtin`

### 搜索参数

- `searchTerm`: 搜索词。
- `page`: 页码。
- `limit`: 每页数量。
- `categoryId`: 类目 ID。
- `sort`: 排序方式。

常见排序值：

- `FEATURED`
- `MOST_RECENT`
- `PRICE_ASCENDING`
- `PRICE_DESCENDING`
- `AVERAGE_CUSTOMER_REVIEW`

### 评论参数

- `rating`: 评论星级筛选。
- `onlyVerifiedReviews`: 是否只看已验证购买评论。
- `search`: 评论内容搜索词。
- `page`: 页码。

常见 `rating` 值：

- `ALL`
- `FIVE_STAR`
- `FOUR_STAR`
- `THREE_STAR`
- `TWO_STAR`
- `ONE_STAR`

## 常见错误

| HTTP 状态码 | 含义 | 处理建议 |
| --- | --- | --- |
| 400 | 参数校验失败 | 检查必填参数和字段名。 |
| 401 | 未授权 | 检查 `API-KEY` 是否缺失、无效或仍为占位符。 |
| 402 | 付费或额度问题 | 检查 Canopy 账号套餐或额度。 |
| 500 | 服务端异常 | 稍后重试或保留请求参数排障。 |

错误响应常见形态：

```json
{
  "success": false,
  "errors": [
    {
      "code": 7003,
      "message": "Unauthorized"
    }
  ]
}
```

## beta MCP 映射

- Base URL 固定为 `https://rest.canopyapi.co`。
- `beta_canopy_run.scenario` 映射到上表场景。
- `beta_canopy_run.domain` 映射到 Canopy query 参数 `domain`。
- `beta_canopy_run.params` 原样合并到 query 参数。
- API key 通过 `API-KEY` header 发送，不放到 query string。
- `beta_canopy_run.export_format` 用户侧只允许 `xls`；内部生成 Excel 兼容 `.xlsx` 文件，并在 MCP 结果中返回 `export.url`。
- beta 本地测试会落盘 `params.json`、`raw.json`、`result.json` 和 `{job_id}.xlsx`，这些内部文件不保存真实 API key。

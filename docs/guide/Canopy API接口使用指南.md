# Canopy beta MCP 使用指南

本文说明测试调研阶段 `beta` MCP 模块如何查询 Amazon 商品、评论、搜索、报价、类目、卖家和榜单数据。接口参数以 [Canopy REST API](https://rest.canopyapi.co/) 和 [OpenAPI](https://rest.canopyapi.co/api/v1/openapi.json) 为准。

## 1. 使用边界

- 只有用户明确提到 `beta`、`Canopy` 或“测试服务”时，才使用 beta MCP。
- 对用户只开放 MCP 查询能力，不提供 CLI、curl、Python 或直连 REST 调用方式。
- 认证信息由项目/服务端本地配置维护，用户侧文档和 MCP 响应不展示认证配置细节。

## 2. MCP 工具

测试阶段对用户开放 5 个 MCP 工具：

```text
beta_spec_must_read
beta_canopy_scenarios
beta_canopy_run
beta_canopy_job_status
beta_canopy_export
```

完整 Agent 调用规范由 `opscli/mcp/references/canopy/SKILL_MCP.md` 维护。

### 2.1 读取内部规范

```json
{
  "tool": "beta_spec_must_read",
  "arguments": {}
}
```

### 2.2 查看场景列表

```json
{
  "tool": "beta_canopy_scenarios",
  "arguments": {}
}
```

### 2.3 执行查询

商品详情：

```json
{
  "tool": "beta_canopy_run",
  "arguments": {
    "scenario": "product",
    "domain": "US",
    "params": {
      "asin": "B0B3JBVDYP"
    }
  }
}
```

关键词搜索：

```json
{
  "tool": "beta_canopy_run",
  "arguments": {
    "scenario": "search",
    "domain": "US",
    "params": {
      "searchTerm": "coffee grinder",
      "page": 1,
      "limit": 20
    }
  }
}
```

一星评论：

```json
{
  "tool": "beta_canopy_run",
  "arguments": {
    "scenario": "product-reviews",
    "domain": "US",
    "params": {
      "asin": "B0B3JBVDYP",
      "rating": "ONE_STAR"
    },
    "export_format": "xls"
  }
}
```

## 3. 站点 domain

Canopy 使用 `domain` 表示 Amazon 站点，默认 `US`。

支持值：

```text
US, UK, CA, DE, FR, IT, ES, AU, IN, MX, BR, JP, PL
```

## 4. 场景列表

| 场景 | 用途 | 必填参数 |
| --- | --- | --- |
| `product` | 商品详情 | `asin` / `url` / `gtin` 三选一 |
| `product-gtin-from-asin` | ASIN 转 GTIN | `asin` |
| `product-asin-from-gtin` | GTIN 转 ASIN | `gtin` |
| `product-variants` | 商品变体 | `asin` / `url` / `gtin` 三选一 |
| `product-stock` | 库存估算 | `asin` / `url` / `gtin` 三选一 |
| `product-sales` | 销量估算 | `asin` / `url` / `gtin` 三选一 |
| `product-reviews` | 商品评论 | `asin` / `url` / `gtin` 三选一 |
| `product-offers` | 商品报价 | `asin` / `url` / `gtin` 三选一 |
| `search` | 商品搜索 | `searchTerm` |
| `autocomplete` | 搜索自动补全 | `searchTerm` |
| `categories` | 类目树 | 无 |
| `category` | 指定类目商品 | `categoryId` |
| `seller` | 卖家信息 | `sellerId` |
| `author` | 作者信息 | `asin` |
| `deals` | Deals | 无 |
| `bestsellers` | Best Sellers | `categoryId` / `url` 二选一 |
| `bestseller-categories` | Best Seller 类目 | 无 |

## 5. 评论筛选

`product-reviews` 常用参数：

- `page`: 页码。
- `rating`: 星级枚举：`ALL`、`ONE_STAR`、`TWO_STAR`、`THREE_STAR`、`FOUR_STAR`、`FIVE_STAR`。
- `onlyVerifiedReviews`: 是否只看已验证购买评论。
- `search`: 评论内容关键词。

也可以把简短自然语言筛选意图放入 `params.query`。工具会在不覆盖显式结构化参数的前提下补充官方参数：

- `差评`、`一星`、`1星`、`1 星`、`one star`、`1-star` → `rating=ONE_STAR`
- `二星/2星`、`三星/3星`、`四星/4星`、`五星/5星` 分别映射到对应星级枚举
- `已验证购买`、`验证购买`、`verified purchase`、`verified reviews`、`only verified` → `onlyVerifiedReviews=true`

## 6. 导出

`beta_canopy_run` 默认会生成 Excel 导出：

- 用户可见导出格式只允许 `xls`；空值会按 `xls` 处理。
- 内部实际生成 Excel 兼容 `.xlsx` 文件。
- MCP 返回 `export.url` 和摘要，不返回本地 path、`params_path`、`raw_path`、`result_path` 或认证配置。
- 默认内部任务目录：`opscli/beta/canopy/api_runs/{job_id}`。

## 7. 常见错误

| 状态码 | 含义 | 处理方式 |
| --- | --- | --- |
| 400 | 参数错误 | 检查 `params` 是否包含必填参数。 |
| 401 | 认证配置异常 | 检查项目/服务端本地认证配置。 |
| 402 | 部分端点的套餐或额度问题 | 当前官方 OpenAPI 仅在商品详情、ASIN 转 GTIN、GTIN 转 ASIN 端点明确声明。 |
| 500 | 服务端异常 | 保留请求参数和响应摘要排障。 |

## 8. MCP 服务开关

Canopy 是测试调研服务，但为兼容现有调用默认开启。全局关闭时，在 MCP Server 进程环境设置：

```text
OPSCLI_MCP_CANOPY_ENABLED=0
```

`0`、`false`、`no`、`off` 均表示关闭；修改后必须重启 MCP 服务。恢复时删除该环境变量或设置为 `1`，然后重启服务。

HTTP/SSE 部署还需在 MCP 后台停用或撤销 5 个 `beta_*` 工具的历史授权，因为工具目录同步不会自动删除历史记录。若只对部分用户关闭，可仅从对应用户或角色的 `allowed_tools` 中移除这些工具。

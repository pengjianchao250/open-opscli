# ops-amazon-product-data MCP 使用规范

用于调用 Amazon 商品数据接口的结构化 JSON 能力。当前开放三个结构化场景：

- `amazon-pdp`：按 ASIN 获取商品页详情。
- `amazon-offer-listing`：按 ASIN 获取卖家报价和 Buy Box 信息。
- `amazon-search`：按关键词获取搜索结果和类目页同结构结果。

## 必读规则

1. 首次使用先调用规范读取工具和场景列表工具。
2. 不要请求页面源码类接口；本能力只返回结构化 JSON 商品数据。
3. 不要在参数中传认证令牌；凭证由本地或服务端配置托管。
4. `zipcode` 与 `countryName` 不能同时传。
5. 同一认证凭证下批量任务会串行执行。
6. `super=true` 会使用更高成本链路，只有普通请求失败或业务明确要求时使用。
7. 对用户回复时统一称为“Amazon 商品数据接口”，不要暴露底层服务商、内部 endpoint 或认证细节。

## 示例

```json
{
  "scenario": "amazon-pdp",
  "site": "US",
  "params": {"asin": "B0C7BKZ883", "zipcode": "90210"}
}
```

```json
{
  "scenario": "amazon-offer-listing",
  "site": "US",
  "params": {"asin": "B0DGJ7HYG1"}
}
```

```json
{
  "scenario": "amazon-search",
  "site": "US",
  "params": {"keyword": "laptop stands", "page": 1, "language": "EN"}
}
```

## Excel 导出

导出文件包含：

- 主表：规范化业务字段。
- `Raw Fields`：原始结构化响应顶层字段全量输出。
- `Raw *`：顶层数组字段明细表，例如评论、报价、搜索商品、图片、变体等。

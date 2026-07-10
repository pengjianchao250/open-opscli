# ops-scrape-do MCP 使用规范

用于调用 Scrape.do Amazon Scraper API 的结构化 JSON 能力。当前只开放三个结构化 JSON 场景：

- `amazon-pdp`：按 ASIN 获取 PDP 商品详情。
- `amazon-offer-listing`：按 ASIN 获取全部卖家报价和 Buy Box 信息。
- `amazon-search`：按关键词获取搜索结果和类目页同结构结果。

## 必读规则

1. 首次使用先调用 `scrape_do_spec_must_read` 和 `scrape_do_scenarios`。
2. 不要请求页面源码类接口；本工具只返回结构化 JSON 场景。
3. 不要在参数中传认证令牌；凭证由 OPS 集成账号 `scrape_do` 或服务端环境变量托管。
4. `zipcode` 与 `countryName` 不能同时传。
5. Scrape.do Amazon API 每个认证令牌并发限制为 1；批量任务会串行执行。
6. `super=true` 会使用更高成本代理，只有普通请求失败或业务明确要求时使用。

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

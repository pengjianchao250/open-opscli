---
name: ops-amazon-listing-intelligence
description: 使用 amazon_listing_intelligence_* MCP tools 为 Amazon Listing 优化服务生成数据源接入计划，拆分 SellerSprite、Amazon、Google Trends、Reddit、Keepa 等数据源 TODO，并指导后续取数顺序。
---

# ops-amazon-listing-intelligence

用于 Amazon Listing 优化服务的数据源编排。该 Skill 不直接抓取外部网页，不生成完整可上线 Listing 文案。

## 工作流

1. 首次使用先调用 `amazon_listing_intelligence_spec_must_read`。
2. 需要了解数据源时调用 `amazon_listing_intelligence_data_sources`。
3. 需要开始一次分析时调用 `amazon_listing_intelligence_intake_plan`。
4. 真实取数优先调用已有 `seller_sprite_*` MCP tools。
5. 没有证据数据时，只输出接入计划和待补充材料，不输出确定性优化结论。

## 常用目标

- `listing_audit`：Listing 表达、关键词覆盖、Review/Q&A 缺口。
- `keyword_opportunity`：关键词机会和搜索趋势。
- `buyer_insight`：用户痛点、购买动机和购买障碍。
- `competitor_positioning`：竞品池、价格带和差异点。
- `category_intelligence`：类目趋势和新品机会。

## 输出边界

- 可以输出数据源 TODO、账号申请事项、取数顺序、证据缺口。
- 可以输出问题定位、优化方向、修改示例。
- 禁止自动替换 Listing。
- 禁止输出完整可直接上线文案。
- 禁止在没有数据证据时给确定性结论。

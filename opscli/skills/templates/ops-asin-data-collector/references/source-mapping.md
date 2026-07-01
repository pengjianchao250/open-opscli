# Source Mapping

## SellerSprite

Use `opscli seller-sprite run`.

| Purpose | Scenario | Required params |
| --- | --- | --- |
| Keyword reverse by ASIN | `keyword-reverse` | `asin` |
| Keyword mining | `keyword-miner` | `keyword` |
| AI listing panorama analysis | `listing-analysis` | `asin` |

Examples:

```bash
opscli seller-sprite run keyword-reverse --site US --period 30d --params "{\"asin\":\"B0XXXXXXX\"}" --export-format json
opscli seller-sprite run keyword-miner --site US --period 30d --params "{\"keyword\":\"flashlight\"}" --export-format json
opscli seller-sprite run listing-analysis --site US --period 30d --params "{\"asin\":\"B0XXXXXXX\",\"station\":\"GLOBAL\"}" --export-format json
```

Keyword-miner cannot run from ASIN alone. The collector normalizes `keyword`, `keywords`, or `关键词` columns into `input.keywords`, then uses this priority:

1. Input `keyword` column.
2. First keyword derived from keyword-reverse result when `--keyword-source reverse_top`.
3. Skip keyword-miner.

When a table cell contains multiple keywords, separate them with comma, semicolon, pipe, or newline. The collector runs at most `--max-miner-keywords` seed keywords per ASIN and writes the selected seeds to `seller_sprite.keyword_miner.seed_keywords`.

`listing-analysis` creates an asynchronous SellerSprite AI task. The SellerSprite manager polls the task result and exports the final row. The collector reads the exported row and returns the full `content` under both:

- `seller_sprite.listing_analysis.content`
- `frontend_data.卖家精灵AI全景分析数据.content`

The content is passed through as the complete report payload. It is not summarized or converted into selected highlights.

## Rufus Optimization Suggestions

Use `opscli amazon-rufus` official commands. The collector does not read Rufus browser state, cookies, headers, payload templates, or saved request seeds directly.

Before fetching each ASIN, the collector records:

```bash
opscli amazon-rufus remote-consent status US --pretty
opscli amazon-rufus login-status US --pretty
```

When login state is ready, it fetches the default collector questions through:

```bash
opscli amazon-rufus get-backend B0XXXXXXX US --skills-dir .agents/skills \
  -q "分析这个ASIN B0XXXXXXX的标题是否清楚，是否能让买家搜索到产品并愿意点击查看详情？按这个格式输出：
1、当前标题内容
2、问题逐项分析
问题类型｜具体问题 ｜ 问题依据｜建议修改
3、建议优化标题
4、优化核心逻辑总结" \
  -q "分析这个ASIN B0XXXXXXX 的五点卖点，从消费者决策路径与商品信息表达优化的角度，对该商品进行系统分析。按这个格式输出：
1、当前五点内容
2、问题逐项分析 
五点序号｜问题类型｜具体问题 ｜ 问题依据｜建议修改
3、建议优化五点
4、优化核心逻辑总结" \
  -q "分析这个ASIN B0XXXXXXX 的图片是否解决买家购买疑问，从消费者决策路径与商品信息表达优化的角度。按这个格式输出：
1、当前图片整体问题 
2、问题逐项分析 
每张图序号｜目标｜具体问题 ｜ 核心依据｜优化方案
3、优化优先级总结
优先级｜图片序号｜核心价值
4、优化核心逻辑总结" \
  -q "分析这个ASIN B0XXXXXXX 的 A+ 是否补充了关键信息、增强购买信任。按这个格式输出：
1、当前A+内容整体问题
2、问题逐项分析 
每个模块｜目标｜具体问题 ｜ 核心依据｜优化方案
3、优化优先级总结
优先级｜优化项｜预期效果
4、优化核心逻辑总结" \
  -q "分析这个ASIN B0XXXXXXX 的评论中买家最常夸和最常抱怨的点，判断产品页面是否提前说明，并且需如何优化产品，按这个格式输出：
1、评价整体总结分析
2、问题逐项分析
问题类型｜风险等级｜影响范围｜评论依据｜产品页面现状｜优化方案
3、优化优先级总结
优先级｜优化项｜预期效果
4、优化核心逻辑总结" \
  -q "从标题、五点、图片、A+、评论中，找出这个 ASIN B0XXXXXXX 最优先修改的一处。按这个格式输出：
1、核心问题定位
2、最优先修改原因
问题维度｜影响范围｜具体分析｜建议方案
3、总体执行修改方案
4、优化核心逻辑总结" \
  --no-upload-payload
```

If login state is missing and login recovery is not disabled, it uses:

```bash
opscli amazon-rufus watch-login B0XXXXXXX US --launch-if-needed --close-browser
```

The collector reads only the report path printed by the current `get-backend` command, then parses that Markdown report into `rufus.answers` and `frontend_data.Rufus优化建议数据.数据`.

Frontend-facing structure:

```json
{
  "Rufus优化建议数据": {
    "状态": "成功",
    "接入状态": "已接入",
    "国家站点": "US",
    "问题列表": [
      "分析这个ASIN B0XXXXXXX的标题是否清楚，是否能让买家搜索到产品并愿意点击查看详情？按这个格式输出：\n1、当前标题内容\n2、问题逐项分析\n问题类型｜具体问题 ｜ 问题依据｜建议修改\n3、建议优化标题\n4、优化核心逻辑总结",
      "分析这个ASIN B0XXXXXXX 的五点卖点，从消费者决策路径与商品信息表达优化的角度，对该商品进行系统分析。按这个格式输出：\n1、当前五点内容\n2、问题逐项分析 \n五点序号｜问题类型｜具体问题 ｜ 问题依据｜建议修改\n3、建议优化五点\n4、优化核心逻辑总结",
      "分析这个ASIN B0XXXXXXX 的图片是否解决买家购买疑问，从消费者决策路径与商品信息表达优化的角度。按这个格式输出：\n1、当前图片整体问题 \n2、问题逐项分析 \n每张图序号｜目标｜具体问题 ｜ 核心依据｜优化方案\n3、优化优先级总结\n优先级｜图片序号｜核心价值\n4、优化核心逻辑总结",
      "分析这个ASIN B0XXXXXXX 的 A+ 是否补充了关键信息、增强购买信任。按这个格式输出：\n1、当前A+内容整体问题\n2、问题逐项分析 \n每个模块｜目标｜具体问题 ｜ 核心依据｜优化方案\n3、优化优先级总结\n优先级｜优化项｜预期效果\n4、优化核心逻辑总结",
      "分析这个ASIN B0XXXXXXX 的评论中买家最常夸和最常抱怨的点，判断产品页面是否提前说明，并且需如何优化产品，按这个格式输出：\n1、评价整体总结分析\n2、问题逐项分析\n问题类型｜风险等级｜影响范围｜评论依据｜产品页面现状｜优化方案\n3、优化优先级总结\n优先级｜优化项｜预期效果\n4、优化核心逻辑总结",
      "从标题、五点、图片、A+、评论中，找出这个 ASIN B0XXXXXXX 最优先修改的一处。按这个格式输出：\n1、核心问题定位\n2、最优先修改原因\n问题维度｜影响范围｜具体分析｜建议方案\n3、总体执行修改方案\n4、优化核心逻辑总结"
    ],
    "答案数量": 2,
    "报告路径": "output/amazon-rufus/B0XXXXXXX-20260608-180214.md",
    "数据": []
  }
}
```

## Amazon

Use `opscli amazon scrape`.

```bash
opscli amazon scrape --asin B0XXXXXXX
```

The collector stores the normalized JSON response in each ASIN record.

## BI Sales Dataset

Default:

- `table_id`: `1`
- `dataset_alias`: `ds_d35ac6f3910c`
- dataset name: `order_sale_trend_adv_traffic_inv_set`

Default dimensions:

- `ds_d35ac6f3910c.asin`
- `ds_d35ac6f3910c.product_name`

Default metrics:

- `ds_d35ac6f3910c.order_qty` as `SUM`
- `ds_d35ac6f3910c.orders` as `SUM`
- `ds_d35ac6f3910c.sessions` as `SUM`
- `ds_d35ac6f3910c.page_views` as `SUM`
- `AVG(ds_d35ac6f3910c.convert_percent)`
- `ds_d35ac6f3910c.original_price` as `SUM`
- `ds_d35ac6f3910c.price` as `SUM`
- `AVG(ds_d35ac6f3910c.avg_price)`
- `ds_d35ac6f3910c.advertising_fee` as `SUM`
- `ds_d35ac6f3910c.ads_sales_cny` as `SUM`
- `AVG(ds_d35ac6f3910c.ads_acos)`
- `ds_d35ac6f3910c.ads_clicks` as `SUM`
- `ds_d35ac6f3910c.ads_impressions` as `SUM`
- `ds_d35ac6f3910c.refund` as `SUM`
- `ds_d35ac6f3910c.refund_qty` as `SUM`
- `AVG(ds_d35ac6f3910c.refund_percent)`

Default filters:

- `asin in <batch ASINs>`
- optional `date_id between <sales-start, sales-end>`

## Crawler Listing Dataset

Default dataset alias:

- `ds_icw50TLOFu4F`

The collector resolves its `table_id` with `opscli query metadata --dataset ds_icw50TLOFu4F` unless `--crawler-table-id` is supplied.
If metadata resolution fails in the current environment, pass a known `--crawler-table-id` or use `--skip-crawler-query` while validating other sources.
Crawler query results are ordered by `f_date_id` descending and then reduced to the latest `date_id` per ASIN before writing `asin-data.jsonl` and `frontend-data.json`.

Verified metadata:

- `table_id`: `43`
- `dataset_name`: `custom_crawler_amazon_details`
- `description`: `ASIN明细表`

Default dimensions:

- `asin`
- `date_id`
- `country`
- `currency`
- `listing` as `f_product_name`
- `link`
- `image`
- `description`
- `a_image`
- `a_description`
- `product_details`
- `five_point_description`
- `qa`
- `review_list`
- `brand`
- `seller_id`
- `price_scribe`
- `original_price`
- `unit_price`
- `reduction`
- `coupon`
- `promo_code_value`
- `promo_code`
- `deal`
- `major_name`
- `major_rank`
- `subclass_name`
- `subclass_rank`
- `deal_type`

Default metrics:

- `price` as `AVG`
- `rating` as `AVG`
- `rating_count` as `MAX`
- `review_count` as `MAX`
- `stock_qty` as `MAX`
- `sales_status` as `MAX`
- `in_stock` as `MAX`
- `subplot_count` as `MAX`
- `video_count` as `MAX`
- `five_point_description_count` as `MAX`
- `a_image_count` as `MAX`
- `variant_count` as `MAX`
- `cs_count` as `MAX`
- `qa_count` as `MAX`
- `timestamp` as `MAX`

If metadata or fields are unavailable, the crawler source is marked `failed` or `skipped` and other sources continue. Failed query chunks are mapped back to the ASINs in that chunk.

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
  -q "这个产品ASIN B0XXXXXXX，标题写得清楚吗？如果我要找这个产品ASIN B0XXXXXXX，一般搜什么词能找到他？" \
  -q "这个产品ASIN B0XXXXXXX五点卖点描述里，最重要的一条是什么？有没有买家很想知道但没写进去的事？" \
  -q "看完这个产品ASIN B0XXXXXXX这些图，还有什么是我想知道但看不出来的？要是再加一张图，加什么最有用？" \
  -q "这个产品ASIN B0XXXXXXX下面那个长的图文介绍，跟上面五点说的有区别吗？看完能让我更放心买吗？还少介绍了什么？" \
  -q "这个产品ASIN B0XXXXXXX评价里大家最常夸和最常抱怨的是什么？这些在介绍里提前说清楚了吗？" \
  -q "这个产品ASIN B0XXXXXXX如果让你给这个产品页面只提一个最着急改的地方，会是什么？" \
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
      "这个产品ASIN B0XXXXXXX，标题写得清楚吗？如果我要找这个产品ASIN B0XXXXXXX，一般搜什么词能找到他？",
      "这个产品ASIN B0XXXXXXX五点卖点描述里，最重要的一条是什么？有没有买家很想知道但没写进去的事？",
      "看完这个产品ASIN B0XXXXXXX这些图，还有什么是我想知道但看不出来的？要是再加一张图，加什么最有用？",
      "这个产品ASIN B0XXXXXXX下面那个长的图文介绍，跟上面五点说的有区别吗？看完能让我更放心买吗？还少介绍了什么？",
      "这个产品ASIN B0XXXXXXX评价里大家最常夸和最常抱怨的是什么？这些在介绍里提前说清楚了吗？",
      "这个产品ASIN B0XXXXXXX如果让你给这个产品页面只提一个最着急改的地方，会是什么？"
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

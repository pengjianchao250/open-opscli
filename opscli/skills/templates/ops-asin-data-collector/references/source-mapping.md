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

Keyword-miner cannot run from ASIN alone. The collector normalizes `keyword`, `keywords`, or `鍏抽敭璇峘 columns into `input.keywords`, then uses this priority:

1. Input `keyword` column.
2. First keyword derived from keyword-reverse result when `--keyword-source reverse_top`.
3. Skip keyword-miner.

When a table cell contains multiple keywords, separate them with comma, semicolon, pipe, or newline. The collector runs at most `--max-miner-keywords` seed keywords per ASIN and writes the selected seeds to `seller_sprite.keyword_miner.seed_keywords`.

`listing-analysis` creates an asynchronous SellerSprite AI task. The SellerSprite manager polls the task result and exports the final row. The collector reads the exported row and returns the full `content` under both:

- `seller_sprite.listing_analysis.content`
- `frontend_data.鍗栧绮剧伒AI鍏ㄦ櫙鍒嗘瀽鏁版嵁.content`

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
  -q "鍒嗘瀽杩欎釜ASIN B0XXXXXXX鐨勬爣棰樻槸鍚︽竻妤氾紝鏄惁鑳借涔板鎼滅储鍒颁骇鍝佸苟鎰挎剰鐐瑰嚮鏌ョ湅璇︽儏锛熸寜杩欎釜鏍煎紡杈撳嚭锛?
1銆佸綋鍓嶆爣棰樺唴瀹?
2銆侀棶棰橀€愰」鍒嗘瀽
闂绫诲瀷锝滃叿浣撻棶棰?锝?闂渚濇嵁锝滃缓璁慨鏀?
3銆佸缓璁紭鍖栨爣棰?
4銆佷紭鍖栨牳蹇冮€昏緫鎬荤粨" \
  -q "鍒嗘瀽杩欎釜ASIN B0XXXXXXX 鐨勪簲鐐瑰崠鐐癸紝浠庢秷璐硅€呭喅绛栬矾寰勪笌鍟嗗搧淇℃伅琛ㄨ揪浼樺寲鐨勮搴︼紝瀵硅鍟嗗搧杩涜绯荤粺鍒嗘瀽銆傛寜杩欎釜鏍煎紡杈撳嚭锛?
1銆佸綋鍓嶄簲鐐瑰唴瀹?
2銆侀棶棰橀€愰」鍒嗘瀽
浜旂偣搴忓彿锝滈棶棰樼被鍨嬶綔鍏蜂綋闂 锝?闂渚濇嵁锝滃缓璁慨鏀?
3銆佸缓璁紭鍖栦簲鐐?
4銆佷紭鍖栨牳蹇冮€昏緫鎬荤粨" \
  -q "鍒嗘瀽杩欎釜ASIN B0XXXXXXX 鐨勫浘鐗囨槸鍚﹁В鍐充拱瀹惰喘涔扮枒闂紝浠庢秷璐硅€呭喅绛栬矾寰勪笌鍟嗗搧淇℃伅琛ㄨ揪浼樺寲鐨勮搴︺€傛寜杩欎釜鏍煎紡杈撳嚭锛?
1銆佸綋鍓嶅浘鐗囨暣浣撻棶棰?
2銆侀棶棰橀€愰」鍒嗘瀽
姣忓紶鍥惧簭鍙凤綔鐩爣锝滃叿浣撻棶棰?锝?鏍稿績渚濇嵁锝滀紭鍖栨柟妗?
3銆佷紭鍖栦紭鍏堢骇鎬荤粨
浼樺厛绾э綔鍥剧墖搴忓彿锝滄牳蹇冧环鍊?
4銆佷紭鍖栨牳蹇冮€昏緫鎬荤粨" \
  -q "鍒嗘瀽杩欎釜ASIN B0XXXXXXX 鐨?A+ 鏄惁琛ュ厖浜嗗叧閿俊鎭€佸寮鸿喘涔颁俊浠汇€傛寜杩欎釜鏍煎紡杈撳嚭锛?
1銆佸綋鍓岮+鍐呭鏁翠綋闂
2銆侀棶棰橀€愰」鍒嗘瀽
姣忎釜妯″潡锝滅洰鏍囷綔鍏蜂綋闂 锝?鏍稿績渚濇嵁锝滀紭鍖栨柟妗?
3銆佷紭鍖栦紭鍏堢骇鎬荤粨
浼樺厛绾э綔浼樺寲椤癸綔棰勬湡鏁堟灉
4銆佷紭鍖栨牳蹇冮€昏緫鎬荤粨" \
  -q "鍒嗘瀽杩欎釜ASIN B0XXXXXXX 鐨勮瘎璁轰腑涔板鏈€甯稿じ鍜屾渶甯告姳鎬ㄧ殑鐐癸紝鍒ゆ柇浜у搧椤甸潰鏄惁鎻愬墠璇存槑锛屽苟涓旈渶濡備綍浼樺寲浜у搧锛屾寜杩欎釜鏍煎紡杈撳嚭锛?
1銆佽瘎浠锋暣浣撴€荤粨鍒嗘瀽
2銆侀棶棰橀€愰」鍒嗘瀽
闂绫诲瀷锝滈闄╃瓑绾э綔褰卞搷鑼冨洿锝滆瘎璁轰緷鎹綔浜у搧椤甸潰鐜扮姸锝滀紭鍖栨柟妗?
3銆佷紭鍖栦紭鍏堢骇鎬荤粨
浼樺厛绾э綔浼樺寲椤癸綔棰勬湡鏁堟灉
4銆佷紭鍖栨牳蹇冮€昏緫鎬荤粨" \
  -q "浠庢爣棰樸€佷簲鐐广€佸浘鐗囥€丄+銆佽瘎璁轰腑锛屾壘鍑鸿繖涓?ASIN B0XXXXXXX 鏈€浼樺厛淇敼鐨勪竴澶勩€傛寜杩欎釜鏍煎紡杈撳嚭锛?
1銆佹牳蹇冮棶棰樺畾浣?
2銆佹渶浼樺厛淇敼鍘熷洜
闂缁村害锝滃奖鍝嶈寖鍥达綔鍏蜂綋鍒嗘瀽锝滃缓璁柟妗?
3銆佹€讳綋鎵ц淇敼鏂规
4銆佷紭鍖栨牳蹇冮€昏緫鎬荤粨" \
  --no-upload-payload
```

If login state is missing and login recovery is not disabled, it uses:

```bash
opscli amazon-rufus watch-login B0XXXXXXX US --launch-if-needed --close-browser
```

The collector reads only the report path printed by the current `get-backend` command, then parses that Markdown report into `rufus.answers` and `frontend_data.Rufus浼樺寲寤鸿鏁版嵁.鏁版嵁`.

Frontend-facing structure:

```json
{
  "Rufus浼樺寲寤鸿鏁版嵁": {
    "鐘舵€?: "鎴愬姛",
    "鎺ュ叆鐘舵€?: "宸叉帴鍏?,
    "鍥藉绔欑偣": "US",
    "闂鍒楄〃": [
      "鍒嗘瀽杩欎釜ASIN B0XXXXXXX鐨勬爣棰樻槸鍚︽竻妤氾紝鏄惁鑳借涔板鎼滅储鍒颁骇鍝佸苟鎰挎剰鐐瑰嚮鏌ョ湅璇︽儏锛熸寜杩欎釜鏍煎紡杈撳嚭锛歕n1銆佸綋鍓嶆爣棰樺唴瀹筡n2銆侀棶棰橀€愰」鍒嗘瀽\n闂绫诲瀷锝滃叿浣撻棶棰?锝?闂渚濇嵁锝滃缓璁慨鏀筡n3銆佸缓璁紭鍖栨爣棰榎n4銆佷紭鍖栨牳蹇冮€昏緫鎬荤粨",
      "鍒嗘瀽杩欎釜ASIN B0XXXXXXX 鐨勪簲鐐瑰崠鐐癸紝浠庢秷璐硅€呭喅绛栬矾寰勪笌鍟嗗搧淇℃伅琛ㄨ揪浼樺寲鐨勮搴︼紝瀵硅鍟嗗搧杩涜绯荤粺鍒嗘瀽銆傛寜杩欎釜鏍煎紡杈撳嚭锛歕n1銆佸綋鍓嶄簲鐐瑰唴瀹筡n2銆侀棶棰橀€愰」鍒嗘瀽 \n浜旂偣搴忓彿锝滈棶棰樼被鍨嬶綔鍏蜂綋闂 锝?闂渚濇嵁锝滃缓璁慨鏀筡n3銆佸缓璁紭鍖栦簲鐐筡n4銆佷紭鍖栨牳蹇冮€昏緫鎬荤粨",
      "鍒嗘瀽杩欎釜ASIN B0XXXXXXX 鐨勫浘鐗囨槸鍚﹁В鍐充拱瀹惰喘涔扮枒闂紝浠庢秷璐硅€呭喅绛栬矾寰勪笌鍟嗗搧淇℃伅琛ㄨ揪浼樺寲鐨勮搴︺€傛寜杩欎釜鏍煎紡杈撳嚭锛歕n1銆佸綋鍓嶅浘鐗囨暣浣撻棶棰?\n2銆侀棶棰橀€愰」鍒嗘瀽 \n姣忓紶鍥惧簭鍙凤綔鐩爣锝滃叿浣撻棶棰?锝?鏍稿績渚濇嵁锝滀紭鍖栨柟妗圽n3銆佷紭鍖栦紭鍏堢骇鎬荤粨\n浼樺厛绾э綔鍥剧墖搴忓彿锝滄牳蹇冧环鍊糪n4銆佷紭鍖栨牳蹇冮€昏緫鎬荤粨",
      "鍒嗘瀽杩欎釜ASIN B0XXXXXXX 鐨?A+ 鏄惁琛ュ厖浜嗗叧閿俊鎭€佸寮鸿喘涔颁俊浠汇€傛寜杩欎釜鏍煎紡杈撳嚭锛歕n1銆佸綋鍓岮+鍐呭鏁翠綋闂\n2銆侀棶棰橀€愰」鍒嗘瀽 \n姣忎釜妯″潡锝滅洰鏍囷綔鍏蜂綋闂 锝?鏍稿績渚濇嵁锝滀紭鍖栨柟妗圽n3銆佷紭鍖栦紭鍏堢骇鎬荤粨\n浼樺厛绾э綔浼樺寲椤癸綔棰勬湡鏁堟灉\n4銆佷紭鍖栨牳蹇冮€昏緫鎬荤粨",
      "鍒嗘瀽杩欎釜ASIN B0XXXXXXX 鐨勮瘎璁轰腑涔板鏈€甯稿じ鍜屾渶甯告姳鎬ㄧ殑鐐癸紝鍒ゆ柇浜у搧椤甸潰鏄惁鎻愬墠璇存槑锛屽苟涓旈渶濡備綍浼樺寲浜у搧锛屾寜杩欎釜鏍煎紡杈撳嚭锛歕n1銆佽瘎浠锋暣浣撴€荤粨鍒嗘瀽\n2銆侀棶棰橀€愰」鍒嗘瀽\n闂绫诲瀷锝滈闄╃瓑绾э綔褰卞搷鑼冨洿锝滆瘎璁轰緷鎹綔浜у搧椤甸潰鐜扮姸锝滀紭鍖栨柟妗圽n3銆佷紭鍖栦紭鍏堢骇鎬荤粨\n浼樺厛绾э綔浼樺寲椤癸綔棰勬湡鏁堟灉\n4銆佷紭鍖栨牳蹇冮€昏緫鎬荤粨",
      "浠庢爣棰樸€佷簲鐐广€佸浘鐗囥€丄+銆佽瘎璁轰腑锛屾壘鍑鸿繖涓?ASIN B0XXXXXXX 鏈€浼樺厛淇敼鐨勪竴澶勩€傛寜杩欎釜鏍煎紡杈撳嚭锛歕n1銆佹牳蹇冮棶棰樺畾浣峔n2銆佹渶浼樺厛淇敼鍘熷洜\n闂缁村害锝滃奖鍝嶈寖鍥达綔鍏蜂綋鍒嗘瀽锝滃缓璁柟妗圽n3銆佹€讳綋鎵ц淇敼鏂规\n4銆佷紭鍖栨牳蹇冮€昏緫鎬荤粨"
    ],
    "绛旀鏁伴噺": 2,
    "鎶ュ憡璺緞": "output/amazon-rufus/B0XXXXXXX-20260608-180214.md",
    "鏁版嵁": []
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
- `description`: `ASIN鏄庣粏琛╜

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

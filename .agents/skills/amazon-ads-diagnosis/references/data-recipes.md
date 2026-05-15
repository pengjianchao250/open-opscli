# 数据取数模板

优先使用 `ops-dataset-query` 做数据集选择、字段校验和远端查询。本文件记录 Amazon 广告诊断已验证可用的数据集、字段和通用查询模板；当 catalog 不可用或信息不完整时，可作为兜底参考。

本文档不绑定任何固定部门。所有部门、渠道、国家、平台和周期都应作为运行时参数传入。

## 数据集一：广告类型 + ASIN 明细

数据集：
- alias：`ds_j7mYcAr6j7YD`
- name：`custom_type_advertising_list`
- 说明：广告类型花费数据集

维度：
- `platform_name:platform`
- `channel_name:channel`
- `large_team_name:large_team`
- `team_name:team`
- `ads_type:ad_type`
- `asin:asin`
- `product_name:product`
- `amazon_cat:amazon_cat`
- `category:category`

指标：
- `total_spend_cny:sum:ad_spend`
- `sales_cny:sum:ad_sales`
- `conversions:sum:ad_orders`
- `clicks:sum:clicks`
- `impressions:sum:impressions`

常用过滤：
- `date_id|between|["{开始日期}","{结束日期}"]`
- `dept_name|eq|"{目标部门}"`
- `country_name|eq|"{目标国家}"`
- `platform_name|in|["Amazon","Amazon VC"]`

## 数据集二：经营 / 利润明细

数据集：
- alias：`ds_d35ac6f3910c`
- name：`order_sale_trend_adv_traffic_inv_set`
- 说明：即时综合数据集

维度：
- `platform_name:platform`
- `channel_name:channel`
- `large_team_name:large_team`
- `team_name:team`
- `asin:asin`
- `product_name:product`
- `amazon_cat:amazon_cat`
- `category:category`

指标：
- `price:sum:total_sales`
- `order_qty:sum:total_orders`
- `gross_profit:sum:gross_profit`
- `advertising_fee:sum:ad_spend`
- `sessions:sum:sessions`
- `page_views:sum:page_views`

过滤条件通常与广告类型明细一致。

## 数据集三：广告活动明细

数据集：
- alias：`ds_S0CgT7ArBdBs`
- name：`custom_sp_sd_sb_ads_set`
- 说明：SP+SD+SB 广告数据集

维度：
- `platform_name:platform`
- `channel_name:channel`
- `ad_type:ad_type`
- `campaign_name:campaign`

指标：
- `cost_cny:sum:ad_spend`
- `sales_cny:sum:ad_sales`
- `units_sold:sum:ad_orders`
- `clicks:sum:clicks`
- `impressions:sum:impressions`

常用过滤：
- `date_id|between|["{开始日期}","{结束日期}"]`
- `country_name|eq|"{目标国家}"`
- `platform_name|in|["Amazon","Amazon VC"]`
- `channel_name|in|[{目标渠道列表}]`

注意：活动层数据不一定有 `dept_name`。标准做法是先从广告类型明细中发现 `{目标部门}` 对应的渠道，再用这些渠道过滤活动层数据。

## 通用查询模板

每个当前期 / 对比期分别查询一次，`limit` 不超过 `10000`。

```bash
opscli query build --dataset ds_j7mYcAr6j7YD --skills-dir <skills_dir> \
  --dimension platform_name:platform \
  --dimension channel_name:channel \
  --dimension large_team_name:large_team \
  --dimension team_name:team \
  --dimension ads_type:ad_type \
  --dimension asin:asin \
  --dimension product_name:product \
  --dimension amazon_cat:amazon_cat \
  --dimension category:category \
  --metric total_spend_cny:sum:ad_spend \
  --metric sales_cny:sum:ad_sales \
  --metric conversions:sum:ad_orders \
  --metric clicks:sum:clicks \
  --metric impressions:sum:impressions \
  --where 'date_id|between|["{开始日期}","{结束日期}"]' \
  --where 'dept_name|eq|"{目标部门}"' \
  --where 'country_name|eq|"{目标国家}"' \
  --where 'platform_name|in|["Amazon","Amazon VC"]' \
  --order-by ad_spend:desc \
  --limit 10000 \
  --run --pretty
```

## 口径校验

- 广告类型明细的 `ad_spend` 与经营明细的 `advertising_fee` 通常应接近。
- 差异较小时，可视作来源时点或归因颗粒度差异。
- 差异明显时，保留两套口径，在 `01_口径校验` 标出，不要强行改数。

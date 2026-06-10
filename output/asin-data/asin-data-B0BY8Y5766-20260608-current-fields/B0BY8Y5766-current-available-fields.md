# ASIN取数数据

## 运行信息

- ASIN：B0BY8Y5766
- 站点：US
- 生成时间：2026-06-08 17:10:00
- 数据源：`order_sale_trend_adv_traffic_inv_set` + `custom_crawler_amazon_details`
- 输出说明：当前后端不支持 `ds_icw50TLOFu4F.a_image` 等明细字段，已降级输出后端可查询字段。
- 反馈编号：`ae636d4c-c4c4-4d85-904b-71dc6b41316d`

## 基础数据

### BI销售数据

```json
{
  "状态": "成功",
  "数据集": "order_sale_trend_adv_traffic_inv_set",
  "dataset_alias": "ds_d35ac6f3910c",
  "行数": 0,
  "明细": [],
  "说明": "按 ASIN B0BY8Y5766 查询即时综合数据集，当前返回 0 行。"
}
```

### 爬虫Listing数据

```json
{
  "状态": "成功",
  "数据集": "custom_crawler_amazon_details",
  "dataset_alias": "ds_icw50TLOFu4F",
  "取数规则": "按 f_date_id 倒序，仅保留最新日期 1 条",
  "行数": 1,
  "明细": [
    {
      "ASIN": "B0BY8Y5766",
      "快照日期": "2026-06-08",
      "国家": "CA",
      "币种": "$",
      "产品名称": "ANCTOR Full Size Bed Frame with 3 Drawers, Upholstered Platform Bed with Storage Headboard and Charging Station, No Box Spring Needed, Easy Assembly",
      "商品链接": "https://www.amazon.ca/ANCTOR-Upholstered-Platform-Headboard-Charging/dp/B0BY8XR8RG",
      "主图": "https://m.media-amazon.com/images/I/91Khhn4RpEL._AC_SX300_SY300_QL70_ML2_.jpg",
      "品牌": "ANCTOR",
      "卖家ID": "A15CBTP5BTSNTZ",
      "到手价文案": "$472.25",
      "划线价": "",
      "售价": "472.2500",
      "折扣百分比": "",
      "Deal": "0",
      "大类名称": "Home",
      "大类排名": "314376",
      "小类名称": "Bed Frames",
      "小类排名": "1479",
      "Deal类型": "",
      "星级": "4.4000",
      "评分数": 970,
      "评论数": 12,
      "库存数": 3,
      "销售状态": 1,
      "是否有库存": 1,
      "子图数量": 9,
      "视频数量": 0,
      "五点描述数量": 7,
      "A+图片数量": 7,
      "变体数量": 0,
      "CS数量": 0,
      "QA数量": 0,
      "时间戳": 1780861418
    }
  ]
}
```

## 本次未返回字段

```json
{
  "A+图片": "后端当前不支持字段 ds_icw50TLOFu4F.a_image，仅返回 A+图片数量 f_a_image_count=7",
  "A+文案": "后端当前不支持字段 ds_icw50TLOFu4F.a_description",
  "产品详情": "后端当前不支持字段 ds_icw50TLOFu4F.product_details",
  "五点描述": "后端当前不支持字段 ds_icw50TLOFu4F.five_point_description，仅返回五点描述数量 f_five_point_description_count=7",
  "QA": "后端当前不支持字段 ds_icw50TLOFu4F.qa，仅返回 QA数量 f_qa_count=0",
  "评论": "后端当前不支持字段 ds_icw50TLOFu4F.review_list，仅返回评论数 f_review_count=12",
  "流量/转化率/广告/退货扩展字段": "完整扩展查询返回 REMOTE_BUSINESS_ERROR: 参数验证失败；已提交反馈"
}
```


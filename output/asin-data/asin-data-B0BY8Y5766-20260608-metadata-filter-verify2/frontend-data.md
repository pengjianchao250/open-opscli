# ASIN取数完整数据

## 运行信息

- 运行ID：asin-data-B0BY8Y5766-20260608-metadata-filter-verify2
- 开始时间：2026-06-08T21:14:33
- 结束时间：2026-06-08T21:14:45
- 输出目录：output\asin-data\asin-data-B0BY8Y5766-20260608-metadata-filter-verify2
- ASIN数量：1
- 失败ASIN数量：1

## 数据结构

每个 ASIN 固定返回四段：

- `基础数据`：中文字段，包含输入信息、BI 销售、爬虫 Listing 和错误列表。
- `卖家精灵关键词数据`：关键词反查和关键词挖掘任务信息。
- `卖家精灵AI全景分析数据`：直接返回 SellerSprite AI 全景分析的完整 `content`。
- `Rufus优化建议数据`：Amazon Rufus 问答数据、报告路径和答案明细。

## ASIN汇总

| ASIN | 站点 | 输入关键词 | 基础数据 | 关键词数据 | AI全景分析 | Rufus |
| --- | --- | --- | --- | --- | --- | --- |
| B0BY8Y5766 | US |  | 有错误 | 跳过 | 跳过 | 跳过 |

## 1. ASIN B0BY8Y5766

### 基础数据

- ASIN：B0BY8Y5766
- 站点：US
- 输入关键词：
- 输入关键词列表：
```json
[]
```
- 关键词数量：0
- 关键词来源：未提供
- 输入行号：1
- 来源文件：.tmp\asin-data-B0BY8Y5766-input.csv

#### BI销售数据

```json
{
  "状态": "失败",
  "原始状态": "failed",
  "行数": 0,
  "明细": [],
  "原因": "REMOTE_BUSINESS_ERROR: 参数验证失败"
}
```

#### 爬虫Listing数据

```json
{
  "状态": "成功",
  "原始状态": "success",
  "行数": 1,
  "明细": [
    {
      "ASIN": "B0BY8Y5766",
      "快照日期": "2026-06-08",
      "国家": "US",
      "币种": "$",
      "产品名称": "ANCTOR Queen Size Bed Frame with 3 Drawers, Upholstered Platform Bed with Storage Headboard and Charging Station for Bedroom, No Box Spring Needed, Easy Assembly, Beige",
      "商品链接": "https://www.amazon.com/ANCTOR-Upholstered-Platform-Headboard-Charging/dp/B0BY8Y5766",
      "主图": "https://m.media-amazon.com/images/I/81KXBYIgFJL._AC_SX300_SY300_QL70_FMwebp_.jpg",
      "A+图片": null,
      "A+文案": null,
      "产品详情": null,
      "五点描述": null,
      "QA": null,
      "评论": null,
      "星级": "4.4000",
      "划线价": null,
      "售价": "199.9900",
      "折扣百分比": null,
      "评论数": 13,
      "描述": null,
      "品牌": "ANCTOR",
      "卖家ID": "AFW8VX6NB710",
      "到手价文案": "$199.99",
      "单价": null,
      "优惠券": null,
      "促销码金额": null,
      "促销码": null,
      "Deal": "0",
      "大类名称": "Home & Kitchen",
      "大类排名": "399401",
      "小类名称": "Bed Frames",
      "小类排名": "1683",
      "Deal类型": null,
      "评分数": 995,
      "库存数": null,
      "销售状态": 1,
      "是否有库存": 1,
      "子图数量": 9,
      "视频数量": null,
      "五点描述数量": 7,
      "A+图片数量": 13,
      "变体数量": 1,
      "CS数量": null,
      "QA数量": 2,
      "时间戳": 1780861420
    }
  ]
}
```

#### 错误列表

```json
[
  {
    "来源": "query.sales",
    "状态": "失败",
    "原始状态": "failed",
    "原因": "REMOTE_BUSINESS_ERROR: 参数验证失败"
  }
]
```

### 卖家精灵关键词数据

#### 关键词反查

```json
{
  "状态": "跳过",
  "原始状态": "skipped",
  "任务ID": null,
  "行数": null,
  "结果数据": [],
  "原因": "seller sprite skipped"
}
```

#### 关键词挖掘

```json
{
  "状态": "跳过",
  "原始状态": "skipped",
  "种子关键词": [],
  "任务列表": [],
  "原因": "keyword miner skipped"
}
```

### 卖家精灵AI全景分析数据

- 状态：跳过
- 原始状态：skipped
- 任务ID：
- 报告任务ID：
- 报告状态：
- 完成时间：
- 过期时间：
- html状态：
- 原因：seller sprite skipped

#### content

```json
null
```

### Rufus优化建议数据

```json
{
  "状态": "跳过",
  "原始状态": "skipped",
  "接入状态": "已接入",
  "国家站点": "US",
  "问题列表": [
    "这个产品ASIN B0BY8Y5766，标题写得清楚吗？如果我要找这个产品ASIN B0BY8Y5766，一般搜什么词能找到他？",
    "这个产品ASIN B0BY8Y5766五点卖点描述里，最重要的一条是什么？有没有买家很想知道但没写进去的事？",
    "看完这个产品ASIN B0BY8Y5766这些图，还有什么是我想知道但看不出来的？要是再加一张图，加什么最有用？",
    "这个产品ASIN B0BY8Y5766下面那个长的图文介绍，跟上面五点说的有区别吗？看完能让我更放心买吗？还少介绍了什么？",
    "这个产品ASIN B0BY8Y5766评价里大家最常夸和最常抱怨的是什么？这些在介绍里提前说清楚了吗？",
    "这个产品ASIN B0BY8Y5766如果让你给这个产品页面只提一个最着急改的地方，会是什么？"
  ],
  "问题数量": 6,
  "答案数量": 0,
  "报告路径": null,
  "数据": [],
  "原因": "rufus skipped"
}
```


完整机器可读 JSON 数据见同目录 `frontend-data.json`。

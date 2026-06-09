# ASIN取数完整数据

## 运行信息

- 运行ID：asin-data-B0BY8Y5766-20260608-chenbenli-full2
- 开始时间：2026-06-08T21:58:15
- 结束时间：2026-06-08T21:58:54
- 输出目录：output\asin-data\asin-data-B0BY8Y5766-20260608-chenbenli-full2
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
| B0BY8Y5766 | US |  | 有错误 | 失败 | 失败 | 失败 |

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
  "状态": "成功",
  "原始状态": "success",
  "行数": 1,
  "明细": [
    {
      "产品名称": "ACT 米色层架软包带三抽屉带排插queen码-枫木色",
      "ASIN": "B0BY8Y5766",
      "订单量": 7496,
      "销量": 7546,
      "流量": 425435,
      "浏览量": 663789,
      "原价销售额": "14342020.1115",
      "退款金额": "547247.0156",
      "广告费": "1479772.5464",
      "广告销售额(CNY)": "6988611.676552",
      "广告点击量": 267783,
      "广告曝光量": 48849408,
      "销售额": "13642759.4186"
    }
  ]
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
    "来源": "seller_sprite.keyword_reverse",
    "状态": "失败",
    "原始状态": "failed",
    "原因": null
  },
  {
    "来源": "seller_sprite.listing_analysis",
    "状态": "失败",
    "原始状态": "failed",
    "原因": null
  },
  {
    "来源": "rufus.qa",
    "状态": "失败",
    "原始状态": "failed",
    "原因": "Usage: opscli amazon-rufus [OPTIONS] COMMAND [ARGS]...\nTry 'opscli amazon-rufus --help' for help.\n┌─ Error ─────────────────────────────────────────────────────────────────────┐\n│ No such command 'remote-consent'.                                           │\n└─────────────────────────────────────────────────────────────────────────────┘"
  }
]
```

### 卖家精灵关键词数据

#### 关键词反查

```json
{
  "状态": "失败",
  "原始状态": "failed",
  "任务ID": null,
  "行数": null,
  "结果数据": [],
  "错误信息": "┌───────────────────── Traceback (most recent call last) ─────────────────────┐\n│ C:\\Users\\AA\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\opscl │\n│ i\\seller_sprite\\cli.py:47 in run_scenario                                   │\n│                                                                             │\n│   44 │   │   output_dir=output_dir,                                         │\n│   45 │   │   export_format=export_format,                                   │\n│   46 │   )                                                                  │\n│ > 47 │   result = asyncio.run(SellerSpriteApiManager().run(request))        │\n│   48 │   typer.echo(json.dumps(result.to_dict(), ensure_ascii=False,        │\n│      indent=2))                                                             │\n│   49                                                                        │\n│   50                                                                        │\n│                                                                             │\n│ C:\\Users\\AA\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\asyncio\\runners.py: │\n│ 194 in run                                                                  │\n│                                                                             │\n│   191 │   │   │   \"asyncio.run() cannot be called from a running event      │\n│       loop\")                                                                │\n│   192 │                                                                     │\n│   193 │   with Runner(debug=debug, loop_factory=loop_factory) as runner:    │\n│ > 194 │   │   return runner.run(main)                                       │\n│   195                                                                       │\n│   196                                                                       │\n│   197 def _cancel_all_tasks(loop):                                          │\n│                                                                             │\n│ C:\\Users\\AA\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\asyncio\\runners.py: │\n│ 118 in run                                                                  │\n│                                                                             │\n│   115 │   │                                                                 │\n│   116 │   │   self._interrupt_count = 0                                     │\n│   117 │   │   try:                                                          │\n│ > 118 │   │   │   return self._loop.run_until_complete(task)                │\n│   119 │   │   except exceptions.CancelledError:                             │\n│   120 │   │   │   if self._interrupt_count > 0:                             │\n│   121 │   │   │   │   uncancel = getattr(task, \"uncancel\", None)            │\n│                                                                             │\n│ C:\\Users\\AA\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\asyncio\\base_events │\n│ .py:686 in run_until_complete                                               │\n│                                                                             │\n│    683 │   │   if not future.done():                                        │\n│    684 │   │   │   raise RuntimeError('Event loop stopped before Future     │\n│        completed.')                                                         │\n│    685 │   │                                                                │\n│ >  686 │   │   return future.result()                                       │\n│    687 │                                                                    │\n│    688 │   def stop(self):                                                  │\n│    689 │   │   \"\"\"Stop running the event loop.                              │\n│                                                                             │\n│ D:\\workspace\\open-opscli\\opscli/seller_sprite/services/api_manager.py:173   │\n│ in run                                                                      │\n│                                                                             │\n│   170 │   │   │   \"scenario\": request.scenario,                             │\n│   171 │   │   │   \"login\": login,                                           │\n│   172 │   │   │   \"payload\": payload,                                       │\n│ > 173 │   │   │   \"response\": main_response,                                │\n│   174 │   │   │   \"high_frequency_response\": high_frequency_response,       │\n│   175 │   │   │   \"warnings\": warnings,                                     │\n│   176 │   │   }                                                             │\n│                                                                             │\n│ D:\\workspace\\open-opscli\\opscli/seller_sprite/services/api_manager.py:507   │\n│ in opscli.seller_sprite.services.api_manager._export_rows_to_json           │\n│                                                                             │\n│   504 │   items = data.get(\"items\")                                         │\n│   505 │   if not isinstance(items, list) or len(items) != 20:               │\n│   506 │   │   return False                                                  │\n│ > 507 │   total = _int(data.get(\"total\"), 0)                                │\n│   508 │   pages = _int(data.get(\"pages\"), 0)                                │\n│   509 │   size = _int(data.get(\"size\"), 0)                                  │\n│   510 │   return bool(                                                      │\n│                                                                             │\n│ D:\\workspace\\open-opscli\\opscli/seller_sprite/services/api_manager.py:570   │\n│ in opscli.seller_sprite.services.api_manager._write_json                    │\n│                                                                             │\n│   567 │   │   return _sanitize_filename_part(params.get(\"asin\"))            │\n│   568 │   if scenario == \"listing-analysis\":                                │\n│   569 │   │   return _sanitize_filename_part(params.get(\"asin\"))            │\n│ > 570 │   if scenario == \"keyword-miner\":                                   │\n│   571 │   │   return _sanitize_filename_part(params.get(\"keyword\"))         │\n│   572 │   if scenario == \"traffic-source\":                                  │\n│   573 │   │   return _sanitize_filename_part(                               │\n│                                                                             │\n│ C:\\Users\\AA\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\pathlib.py:1047 in  │\n│ write_text                                                                  │\n│                                                                             │\n│   1044 │   │   │   raise TypeError('data must be str, not %s' %             │\n│   1045 │   │   │   │   │   │   │   data.__class__.__name__)                 │\n│   1046 │   │   encoding = io.text_encoding(encoding)                        │\n│ > 1047 │   │   with self.open(mode='w', encoding=encoding, errors=errors,   │\n│        newline=newline) as f:                                               │\n│   1048 │   │   │   return f.write(data)                                     │\n│   1049 │                                                                    │\n│   1050 │   def iterdir(self):                                               │\n│                                                                             │\n│ C:\\Users\\AA\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\pathlib.py:1013 in  │\n│ open                                                                        │\n│                                                                             │\n│   1010 │   │   \"\"\"                                                          │\n│   1011 │   │   if \"b\" not in mode:                                          │\n│   1012 │   │   │   encoding = io.text_encoding(encoding)                    │\n│ > 1013 │   │   return io.open(self, mode, buffering, encoding, errors,      │\n│        newline)                                                             │\n│   1014 │                                                                    │\n│   1015 │   def read_bytes(self):                                            │\n│   1016 │   │   \"\"\"                                                          │\n└─────────────────────────────────────────────────────────────────────────────┘\nFileNotFoundError: [Errno 2] No such file or directory: \n'D:\\\\workspace\\\\open-opscli\\\\output\\\\asin-data\\\\asin-data-B0BY8Y5766-20260608-c\nhenbenli-full2\\\\seller-sprite\\\\B0BY8Y5766\\\\SellerSprite-ReverseASIN-US-B0BY8Y57\n66-Last-30-days-20260608-215830-c45658\\\\SellerSprite-ReverseASIN-US-B0BY8Y5766-\nLast-30-days-20260608-215830-c45658.json'"
}
```

#### 关键词挖掘

```json
{
  "状态": "跳过",
  "原始状态": "skipped",
  "种子关键词": [],
  "任务列表": [],
  "原因": "keyword is missing"
}
```

### 卖家精灵AI全景分析数据

- 状态：失败
- 原始状态：failed
- 任务ID：
- 报告任务ID：
- 报告状态：
- 完成时间：
- 过期时间：
- html状态：
- 错误信息：┌───────────────────── Traceback (most recent call last) ─────────────────────┐
│ C:\Users\AA\AppData\Local\Programs\Python\Python312\Lib\site-packages\opscl │
│ i\seller_sprite\cli.py:47 in run_scenario                                   │
│                                                                             │
│   44 │   │   output_dir=output_dir,                                         │
│   45 │   │   export_format=export_format,                                   │
│   46 │   )                                                                  │
│ > 47 │   result = asyncio.run(SellerSpriteApiManager().run(request))        │
│   48 │   typer.echo(json.dumps(result.to_dict(), ensure_ascii=False,        │
│      indent=2))                                                             │
│   49                                                                        │
│   50                                                                        │
│                                                                             │
│ C:\Users\AA\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py: │
│ 194 in run                                                                  │
│                                                                             │
│   191 │   │   │   "asyncio.run() cannot be called from a running event      │
│       loop")                                                                │
│   192 │                                                                     │
│   193 │   with Runner(debug=debug, loop_factory=loop_factory) as runner:    │
│ > 194 │   │   return runner.run(main)                                       │
│   195                                                                       │
│   196                                                                       │
│   197 def _cancel_all_tasks(loop):                                          │
│                                                                             │
│ C:\Users\AA\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py: │
│ 118 in run                                                                  │
│                                                                             │
│   115 │   │                                                                 │
│   116 │   │   self._interrupt_count = 0                                     │
│   117 │   │   try:                                                          │
│ > 118 │   │   │   return self._loop.run_until_complete(task)                │
│   119 │   │   except exceptions.CancelledError:                             │
│   120 │   │   │   if self._interrupt_count > 0:                             │
│   121 │   │   │   │   uncancel = getattr(task, "uncancel", None)            │
│                                                                             │
│ C:\Users\AA\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events │
│ .py:686 in run_until_complete                                               │
│                                                                             │
│    683 │   │   if not future.done():                                        │
│    684 │   │   │   raise RuntimeError('Event loop stopped before Future     │
│        completed.')                                                         │
│    685 │   │                                                                │
│ >  686 │   │   return future.result()                                       │
│    687 │                                                                    │
│    688 │   def stop(self):                                                  │
│    689 │   │   """Stop running the event loop.                              │
│                                                                             │
│ D:\workspace\open-opscli\opscli/seller_sprite/services/api_manager.py:50 in │
│ run                                                                         │
│                                                                             │
│    47 │   │   │   self.settings,                                            │
│    48 │   │   │   integration_client=IntegrationAccountClient(jwt=jwt,      │
│       session_id=session_id),                                               │
│    49 │   │   )                                                             │
│ >  50 │                                                                     │
│    51 │   def scenarios(self) -> list[dict[str, Any]]:                      │
│    52 │   │   """列出支持的接口场景。"""                                    │
│    53 │   │   return list_scenarios()                                       │
│                                                                             │
│ D:\workspace\open-opscli\opscli/seller_sprite/api/scenarios.py:142 in       │
│ opscli.seller_sprite.api.scenarios.get_scenario                             │
│                                                                             │
│   139 │   │   payload_builder=make_listing_analysis_payload,                │
│   140 │   ),                                                                │
│   141 }                                                                     │
│ > 142                                                                       │
│   143                                                                       │
│   144 def list_scenarios() -> list[dict[str, Any]]:                         │
│   145 │   """列出可用场景。"""                                              │
└─────────────────────────────────────────────────────────────────────────────┘
SellerSpriteConfigError: 未知卖家精灵场景：listing-analysis

#### content

```json
null
```

### Rufus优化建议数据

```json
{
  "状态": "失败",
  "原始状态": "failed",
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
  "原因": "Usage: opscli amazon-rufus [OPTIONS] COMMAND [ARGS]...\nTry 'opscli amazon-rufus --help' for help.\n┌─ Error ─────────────────────────────────────────────────────────────────────┐\n│ No such command 'remote-consent'.                                           │\n└─────────────────────────────────────────────────────────────────────────────┘"
}
```


完整机器可读 JSON 数据见同目录 `frontend-data.json`。

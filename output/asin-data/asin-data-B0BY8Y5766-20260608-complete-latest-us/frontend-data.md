# ASIN取数完整数据

## 运行信息

- 运行ID：asin-data-B0BY8Y5766-20260608-complete-latest-us
- 开始时间：2026-06-08T17:29:42
- 结束时间：2026-06-08T17:30:38
- 输出目录：output\asin-data\asin-data-B0BY8Y5766-20260608-complete-latest-us
- ASIN数量：1
- 失败ASIN数量：1

## 数据结构

每个 ASIN 固定返回四段：

- `基础数据`：中文字段，包含输入信息、BI 销售、爬虫 Listing 和错误列表。
- `卖家精灵关键词数据`：关键词反查和关键词挖掘任务信息。
- `卖家精灵AI全景分析数据`：直接返回 SellerSprite AI 全景分析的完整 `content`。
- `Rufus优化建议数据`：暂未接入接口，返回预留占位结构。

## ASIN汇总

| ASIN | 站点 | 基础数据 | 关键词数据 | AI全景分析 | Rufus |
| --- | --- | --- | --- | --- | --- |
| B0BY8Y5766 | US | 有错误 | 失败 | 失败 | 预留 |

## 1. ASIN B0BY8Y5766

### 基础数据

- ASIN：B0BY8Y5766
- 站点：US
- 输入关键词：
- 关键词来源：未提供
- 输入行号：1
- 来源文件：.tmp\asin-data-B0BY8Y5766-input.csv

#### BI销售数据

```json
{
  "状态": "成功",
  "原始状态": "success",
  "行数": 0,
  "明细": []
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
  "错误信息": "opscli 有新版本可用，建议更新最新版本: v0.0.22 → v0.0.86\n请按以下步骤更新：\n  1. pip install --upgrade aukeys-opscli\n  2. opscli skills install --force\n  3. opscli skills upgrade\n\n┌───────────────────── Traceback (most recent call last) ─────────────────────┐\n│ D:\\workspace\\open-opscli\\opscli\\seller_sprite\\cli.py:47 in run_scenario     │\n│                                                                             │\n│   44 │   │   output_dir=output_dir,                                         │\n│   45 │   │   export_format=export_format,                                   │\n│   46 │   )                                                                  │\n│ > 47 │   result = asyncio.run(SellerSpriteApiManager().run(request))        │\n│   48 │   typer.echo(json.dumps(result.to_dict(), ensure_ascii=False,        │\n│      indent=2))                                                             │\n│   49                                                                        │\n│   50                                                                        │\n│                                                                             │\n│ C:\\Users\\AA\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\asyncio\\runners.py: │\n│ 194 in run                                                                  │\n│                                                                             │\n│   191 │   │   │   \"asyncio.run() cannot be called from a running event      │\n│       loop\")                                                                │\n│   192 │                                                                     │\n│   193 │   with Runner(debug=debug, loop_factory=loop_factory) as runner:    │\n│ > 194 │   │   return runner.run(main)                                       │\n│   195                                                                       │\n│   196                                                                       │\n│   197 def _cancel_all_tasks(loop):                                          │\n│                                                                             │\n│ C:\\Users\\AA\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\asyncio\\runners.py: │\n│ 118 in run                                                                  │\n│                                                                             │\n│   115 │   │                                                                 │\n│   116 │   │   self._interrupt_count = 0                                     │\n│   117 │   │   try:                                                          │\n│ > 118 │   │   │   return self._loop.run_until_complete(task)                │\n│   119 │   │   except exceptions.CancelledError:                             │\n│   120 │   │   │   if self._interrupt_count > 0:                             │\n│   121 │   │   │   │   uncancel = getattr(task, \"uncancel\", None)            │\n│                                                                             │\n│ C:\\Users\\AA\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\asyncio\\base_events │\n│ .py:686 in run_until_complete                                               │\n│                                                                             │\n│    683 │   │   if not future.done():                                        │\n│    684 │   │   │   raise RuntimeError('Event loop stopped before Future     │\n│        completed.')                                                         │\n│    685 │   │                                                                │\n│ >  686 │   │   return future.result()                                       │\n│    687 │                                                                    │\n│    688 │   def stop(self):                                                  │\n│    689 │   │   \"\"\"Stop running the event loop.                              │\n│                                                                             │\n│ D:\\workspace\\open-opscli\\opscli\\seller_sprite\\services\\api_manager.py:193   │\n│ in run                                                                      │\n│                                                                             │\n│   190 │   │   │   │   high_frequency_rows=high_frequency_rows,              │\n│   191 │   │   │   )                                                         │\n│   192 │   │   else:                                                         │\n│ > 193 │   │   │   export = _export_rows_to_json(                            │\n│   194 │   │   │   │   output_path=root_dir / f\"{job_id}.json\",              │\n│   195 │   │   │   │   job_id=job_id,                                        │\n│   196 │   │   │   │   scenario=request.scenario,                            │\n│                                                                             │\n│ D:\\workspace\\open-opscli\\opscli\\seller_sprite\\services\\api_manager.py:669   │\n│ in _export_rows_to_json                                                     │\n│                                                                             │\n│   666 │   │   \"high_frequency_rows\": high_frequency_rows,                   │\n│   667 │   │   \"warnings\": warnings,                                         │\n│   668 │   }                                                                 │\n│ > 669 │   _write_json(output_path, payload)                                 │\n│   670 │   resolved_output = output_path.resolve()                           │\n│   671 │   return SellerSpriteExportResult(                                  │\n│   672 │   │   path=str(resolved_output),                                    │\n│                                                                             │\n│ D:\\workspace\\open-opscli\\opscli\\seller_sprite\\services\\api_manager.py:732   │\n│ in _write_json                                                              │\n│                                                                             │\n│   729                                                                       │\n│   730 def _write_json(path: Path, payload: Any) -> None:                    │\n│   731 │   path.parent.mkdir(parents=True, exist_ok=True)                    │\n│ > 732 │   path.write_text(json.dumps(payload, ensure_ascii=False,           │\n│       indent=2), encoding=\"utf-8\")                                          │\n│   733                                                                       │\n│                                                                             │\n│ C:\\Users\\AA\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\pathlib.py:1047 in  │\n│ write_text                                                                  │\n│                                                                             │\n│   1044 │   │   │   raise TypeError('data must be str, not %s' %             │\n│   1045 │   │   │   │   │   │   │   data.__class__.__name__)                 │\n│   1046 │   │   encoding = io.text_encoding(encoding)                        │\n│ > 1047 │   │   with self.open(mode='w', encoding=encoding, errors=errors,   │\n│        newline=newline) as f:                                               │\n│   1048 │   │   │   return f.write(data)                                     │\n│   1049 │                                                                    │\n│   1050 │   def iterdir(self):                                               │\n│                                                                             │\n│ C:\\Users\\AA\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\pathlib.py:1013 in  │\n│ open                                                                        │\n│                                                                             │\n│   1010 │   │   \"\"\"                                                          │\n│   1011 │   │   if \"b\" not in mode:                                          │\n│   1012 │   │   │   encoding = io.text_encoding(encoding)                    │\n│ > 1013 │   │   return io.open(self, mode, buffering, encoding, errors,      │\n│        newline)                                                             │\n│   1014 │                                                                    │\n│   1015 │   def read_bytes(self):                                            │\n│   1016 │   │   \"\"\"                                                          │\n└─────────────────────────────────────────────────────────────────────────────┘\nFileNotFoundError: [Errno 2] No such file or directory: \n'D:\\\\workspace\\\\open-opscli\\\\output\\\\asin-data\\\\asin-data-B0BY8Y5766-20260608-c\nomplete-latest-us\\\\seller-sprite\\\\B0BY8Y5766\\\\SellerSprite-ReverseASIN-US-B0BY8\nY5766-Last-30-days-20260608-172953-d17388\\\\SellerSprite-ReverseASIN-US-B0BY8Y57\n66-Last-30-days-20260608-172953-d17388.json'"
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
- 错误信息：opscli 有新版本可用，建议更新最新版本: v0.0.22 → v0.0.86
请按以下步骤更新：
  1. pip install --upgrade aukeys-opscli
  2. opscli skills install --force
  3. opscli skills upgrade

┌───────────────────── Traceback (most recent call last) ─────────────────────┐
│ D:\workspace\open-opscli\opscli\seller_sprite\services\api_manager.py:397   │
│ in _request_with_session_retry                                              │
│                                                                             │
│   394 │   action,                                                           │
│   395 ) -> dict[str, Any]:                                                  │
│   396 │   try:                                                              │
│ > 397 │   │   return await action()                                         │
│   398 │   except SellerSpriteApiError as exc:                               │
│   399 │   │   if not exc.is_session_expired():                              │
│   400 │   │   │   raise                                                     │
│                                                                             │
│ D:\workspace\open-opscli\opscli\seller_sprite\services\api_manager.py:313   │
│ in _poll_ai_task_result                                                     │
│                                                                             │
│   310 │   endpoint = result_endpoint_template.format(task_id=task_id)       │
│   311 │   last_response: dict[str, Any] | None = None                       │
│   312 │   for attempt in range(attempts):                                   │
│ > 313 │   │   task_response = await client.get_json(endpoint, {},           │
│       referer=referer)                                                      │
│   314 │   │   last_response = task_response                                 │
│   315 │   │   if _ai_task_has_content(task_response) or                     │
│       _ai_task_is_done(task_response):                                      │
│   316 │   │   │   return _merge_ai_task_response(                           │
│                                                                             │
│ D:\workspace\open-opscli\opscli\seller_sprite\api\client.py:173 in get_json │
│                                                                             │
│   170 │   │   │   │   "Accept": "application/json, text/plain, */*",        │
│   171 │   │   │   },                                                        │
│   172 │   │   )                                                             │
│ > 173 │   │   return self._parse_json_response(response)                    │
│   174 │                                                                     │
│   175 │   async def category_nodes(                                         │
│   176 │   │   self,                                                         │
│                                                                             │
│ D:\workspace\open-opscli\opscli\seller_sprite\api\client.py:255 in          │
│ _parse_json_response                                                        │
│                                                                             │
│   252 │   │   │   api_message = None                                        │
│   253 │   │   │   if isinstance(payload, dict):                             │
│   254 │   │   │   │   api_message = payload.get("message") or               │
│       payload.get("msg")                                                    │
│ > 255 │   │   │   raise SellerSpriteApiError(                               │
│   256 │   │   │   │   f"卖家精灵接口返回错误：{code}",                      │
│   257 │   │   │   │   status_code=response.status_code,                     │
│   258 │   │   │   │   response_excerpt=text[:1000],                         │
└─────────────────────────────────────────────────────────────────────────────┘
SellerSpriteApiError: 卖家精灵接口返回错误：ERR_GLOBAL_SESSION_EXPIRED

During handling of the above exception, another exception occurred:

┌───────────────────── Traceback (most recent call last) ─────────────────────┐
│ D:\workspace\open-opscli\opscli\seller_sprite\cli.py:47 in run_scenario     │
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
│ D:\workspace\open-opscli\opscli\seller_sprite\services\api_manager.py:113   │
│ in run                                                                      │
│                                                                             │
│   110 │   │   │   │   ),                                                    │
│   111 │   │   │   )                                                         │
│   112 │   │   │   if scenario.task_result_endpoint:                         │
│ > 113 │   │   │   │   main_response = await _request_with_session_retry(    │
│   114 │   │   │   │   │   client=client,                                    │
│   115 │   │   │   │   │   warnings=warnings,                                │
│   116 │   │   │   │   │   stage="ai_task",                                  │
│                                                                             │
│ D:\workspace\open-opscli\opscli\seller_sprite\services\api_manager.py:410   │
│ in _request_with_session_retry                                              │
│                                                                             │
│   407 │   │   │   │   "relogin": login,                                     │
│   408 │   │   │   }                                                         │
│   409 │   │   )                                                             │
│ > 410 │   │   return await action()                                         │
│   411                                                                       │
│   412                                                                       │
│   413 async def _login_with_account_refresh(                                │
│                                                                             │
│ D:\workspace\open-opscli\opscli\seller_sprite\services\api_manager.py:313   │
│ in _poll_ai_task_result                                                     │
│                                                                             │
│   310 │   endpoint = result_endpoint_template.format(task_id=task_id)       │
│   311 │   last_response: dict[str, Any] | None = None                       │
│   312 │   for attempt in range(attempts):                                   │
│ > 313 │   │   task_response = await client.get_json(endpoint, {},           │
│       referer=referer)                                                      │
│   314 │   │   last_response = task_response                                 │
│   315 │   │   if _ai_task_has_content(task_response) or                     │
│       _ai_task_is_done(task_response):                                      │
│   316 │   │   │   return _merge_ai_task_response(                           │
│                                                                             │
│ D:\workspace\open-opscli\opscli\seller_sprite\api\client.py:173 in get_json │
│                                                                             │
│   170 │   │   │   │   "Accept": "application/json, text/plain, */*",        │
│   171 │   │   │   },                                                        │
│   172 │   │   )                                                             │
│ > 173 │   │   return self._parse_json_response(response)                    │
│   174 │                                                                     │
│   175 │   async def category_nodes(                                         │
│   176 │   │   self,                                                         │
│                                                                             │
│ D:\workspace\open-opscli\opscli\seller_sprite\api\client.py:255 in          │
│ _parse_json_response                                                        │
│                                                                             │
│   252 │   │   │   api_message = None                                        │
│   253 │   │   │   if isinstance(payload, dict):                             │
│   254 │   │   │   │   api_message = payload.get("message") or               │
│       payload.get("msg")                                                    │
│ > 255 │   │   │   raise SellerSpriteApiError(                               │
│   256 │   │   │   │   f"卖家精灵接口返回错误：{code}",                      │
│   257 │   │   │   │   status_code=response.status_code,                     │
│   258 │   │   │   │   response_excerpt=text[:1000],                         │
└─────────────────────────────────────────────────────────────────────────────┘
SellerSpriteApiError: 卖家精灵接口返回错误：ERR_GLOBAL_SESSION_EXPIRED

#### content

```json
null
```

### Rufus优化建议数据

```json
{
  "状态": "预留",
  "接入状态": "暂未接入",
  "数据": null,
  "说明": "当前 ASIN 取数服务暂未接入 Rufus 优化建议接口，先保留固定结构给前端渲染。"
}
```


完整机器可读 JSON 数据见同目录 `frontend-data.json`。

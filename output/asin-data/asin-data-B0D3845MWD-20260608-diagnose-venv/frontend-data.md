# ASIN取数完整数据

## 运行信息

- 运行ID：asin-data-B0D3845MWD-20260608-diagnose-venv
- 开始时间：2026-06-08T18:33:09
- 结束时间：2026-06-08T18:33:13
- 输出目录：output\asin-data\asin-data-B0D3845MWD-20260608-diagnose-venv
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
| B0D3845MWD | US |  | 有错误 | 失败 | 失败 | 跳过 |

## 1. ASIN B0D3845MWD

### 基础数据

- ASIN：B0D3845MWD
- 站点：US
- 输入关键词：
- 输入关键词列表：
```json
[]
```
- 关键词数量：0
- 关键词来源：未提供
- 输入行号：1
- 来源文件：.tmp\asin-data-B0D3845MWD-input.csv

#### BI销售数据

```json
{
  "状态": "跳过",
  "原始状态": "skipped",
  "行数": 0,
  "明细": []
}
```

#### 爬虫Listing数据

```json
{
  "状态": "跳过",
  "原始状态": "skipped",
  "行数": 0,
  "明细": []
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
  "错误信息": "opscli 有新版本可用，建议更新最新版本: v0.0.84 → v0.0.86\n请按以下步骤更新：\n  1. pip install --upgrade aukeys-opscli\n  2. opscli skills install --force\n  3. opscli skills upgrade\n\n┌───────────────────── Traceback (most recent call last) ─────────────────────┐\n│ D:\\workspace\\open-opscli\\opscli\\seller_sprite\\cli.py:47 in run_scenario     │\n│                                                                             │\n│   44 │   │   output_dir=output_dir,                                         │\n│   45 │   │   export_format=export_format,                                   │\n│   46 │   )                                                                  │\n│ > 47 │   result = asyncio.run(SellerSpriteApiManager().run(request))        │\n│   48 │   typer.echo(json.dumps(result.to_dict(), ensure_ascii=False,        │\n│      indent=2))                                                             │\n│   49                                                                        │\n│   50                                                                        │\n│                                                                             │\n│ C:\\Users\\AA\\AppData\\Roaming\\uv\\python\\cpython-3.13-windows-x86_64-none\\Lib\\ │\n│ asyncio\\runners.py:195 in run                                               │\n│                                                                             │\n│   192 │   │   │   \"asyncio.run() cannot be called from a running event      │\n│       loop\")                                                                │\n│   193 │                                                                     │\n│   194 │   with Runner(debug=debug, loop_factory=loop_factory) as runner:    │\n│ > 195 │   │   return runner.run(main)                                       │\n│   196                                                                       │\n│   197                                                                       │\n│   198 def _cancel_all_tasks(loop):                                          │\n│                                                                             │\n│ C:\\Users\\AA\\AppData\\Roaming\\uv\\python\\cpython-3.13-windows-x86_64-none\\Lib\\ │\n│ asyncio\\runners.py:118 in run                                               │\n│                                                                             │\n│   115 │   │                                                                 │\n│   116 │   │   self._interrupt_count = 0                                     │\n│   117 │   │   try:                                                          │\n│ > 118 │   │   │   return self._loop.run_until_complete(task)                │\n│   119 │   │   except exceptions.CancelledError:                             │\n│   120 │   │   │   if self._interrupt_count > 0:                             │\n│   121 │   │   │   │   uncancel = getattr(task, \"uncancel\", None)            │\n│                                                                             │\n│ C:\\Users\\AA\\AppData\\Roaming\\uv\\python\\cpython-3.13-windows-x86_64-none\\Lib\\ │\n│ asyncio\\base_events.py:725 in run_until_complete                            │\n│                                                                             │\n│    722 │   │   if not future.done():                                        │\n│    723 │   │   │   raise RuntimeError('Event loop stopped before Future     │\n│        completed.')                                                         │\n│    724 │   │                                                                │\n│ >  725 │   │   return future.result()                                       │\n│    726 │                                                                    │\n│    727 │   def stop(self):                                                  │\n│    728 │   │   \"\"\"Stop running the event loop.                              │\n│                                                                             │\n│ D:\\workspace\\open-opscli\\opscli\\seller_sprite\\services\\api_manager.py:64 in │\n│ run                                                                         │\n│                                                                             │\n│    61 │   │   root_dir = self._build_root_dir(request, job_id)              │\n│    62 │   │   root_dir.mkdir(parents=True, exist_ok=True)                   │\n│    63 │   │   page_size = request.page_size or self.settings.page_size      │\n│ >  64 │   │   account = self.account_provider.get_default()                 │\n│    65 │   │   warnings: list[dict[str, Any]] = []                           │\n│    66 │   │   async with SellerSpriteApiClient(account=account) as client:  │\n│    67 │   │   │   login = {\"mode\": \"cached\", \"cookie_names\":                │\n│       client.cookie_names()}                                                │\n│                                                                             │\n│ D:\\workspace\\open-opscli\\opscli\\seller_sprite\\accounts.py:61 in get_default │\n│                                                                             │\n│    58 │   │   │   raise                                                     │\n│       SellerSpriteConfigError(f\"账号池中不存在默认账号：{self.settings.acco │\n│       unt_name}\")                                                           │\n│    59 │   │                                                                 │\n│    60 │   │   if self._remote_error:                                        │\n│ >  61 │   │   │   raise SellerSpriteConfigError(                            │\n│    62 │   │   │   │   f\"获取卖家精灵集成账号失败：{self._remote_error}。\"   │\n│    63 │   │   │   │   \"请检查 OPS 授权：MCP 模式需携带有效                  │\n│       X-MCP-API-Key，CLI 模式执行 opscli auth login。\"                      │\n│    64 │   │   │   )                                                         │\n└─────────────────────────────────────────────────────────────────────────────┘\nSellerSpriteConfigError: 获取卖家精灵集成账号失败：用户不存在。请检查 OPS \n授权：MCP 模式需携带有效 X-MCP-API-Key，CLI 模式执行 opscli auth login。"
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

- 状态：失败
- 原始状态：failed
- 任务ID：
- 报告任务ID：
- 报告状态：
- 完成时间：
- 过期时间：
- html状态：
- 错误信息：opscli 有新版本可用，建议更新最新版本: v0.0.84 → v0.0.86
请按以下步骤更新：
  1. pip install --upgrade aukeys-opscli
  2. opscli skills install --force
  3. opscli skills upgrade

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
│ C:\Users\AA\AppData\Roaming\uv\python\cpython-3.13-windows-x86_64-none\Lib\ │
│ asyncio\runners.py:195 in run                                               │
│                                                                             │
│   192 │   │   │   "asyncio.run() cannot be called from a running event      │
│       loop")                                                                │
│   193 │                                                                     │
│   194 │   with Runner(debug=debug, loop_factory=loop_factory) as runner:    │
│ > 195 │   │   return runner.run(main)                                       │
│   196                                                                       │
│   197                                                                       │
│   198 def _cancel_all_tasks(loop):                                          │
│                                                                             │
│ C:\Users\AA\AppData\Roaming\uv\python\cpython-3.13-windows-x86_64-none\Lib\ │
│ asyncio\runners.py:118 in run                                               │
│                                                                             │
│   115 │   │                                                                 │
│   116 │   │   self._interrupt_count = 0                                     │
│   117 │   │   try:                                                          │
│ > 118 │   │   │   return self._loop.run_until_complete(task)                │
│   119 │   │   except exceptions.CancelledError:                             │
│   120 │   │   │   if self._interrupt_count > 0:                             │
│   121 │   │   │   │   uncancel = getattr(task, "uncancel", None)            │
│                                                                             │
│ C:\Users\AA\AppData\Roaming\uv\python\cpython-3.13-windows-x86_64-none\Lib\ │
│ asyncio\base_events.py:725 in run_until_complete                            │
│                                                                             │
│    722 │   │   if not future.done():                                        │
│    723 │   │   │   raise RuntimeError('Event loop stopped before Future     │
│        completed.')                                                         │
│    724 │   │                                                                │
│ >  725 │   │   return future.result()                                       │
│    726 │                                                                    │
│    727 │   def stop(self):                                                  │
│    728 │   │   """Stop running the event loop.                              │
│                                                                             │
│ D:\workspace\open-opscli\opscli\seller_sprite\services\api_manager.py:64 in │
│ run                                                                         │
│                                                                             │
│    61 │   │   root_dir = self._build_root_dir(request, job_id)              │
│    62 │   │   root_dir.mkdir(parents=True, exist_ok=True)                   │
│    63 │   │   page_size = request.page_size or self.settings.page_size      │
│ >  64 │   │   account = self.account_provider.get_default()                 │
│    65 │   │   warnings: list[dict[str, Any]] = []                           │
│    66 │   │   async with SellerSpriteApiClient(account=account) as client:  │
│    67 │   │   │   login = {"mode": "cached", "cookie_names":                │
│       client.cookie_names()}                                                │
│                                                                             │
│ D:\workspace\open-opscli\opscli\seller_sprite\accounts.py:61 in get_default │
│                                                                             │
│    58 │   │   │   raise                                                     │
│       SellerSpriteConfigError(f"账号池中不存在默认账号：{self.settings.acco │
│       unt_name}")                                                           │
│    59 │   │                                                                 │
│    60 │   │   if self._remote_error:                                        │
│ >  61 │   │   │   raise SellerSpriteConfigError(                            │
│    62 │   │   │   │   f"获取卖家精灵集成账号失败：{self._remote_error}。"   │
│    63 │   │   │   │   "请检查 OPS 授权：MCP 模式需携带有效                  │
│       X-MCP-API-Key，CLI 模式执行 opscli auth login。"                      │
│    64 │   │   │   )                                                         │
└─────────────────────────────────────────────────────────────────────────────┘
SellerSpriteConfigError: 获取卖家精灵集成账号失败：用户不存在。请检查 OPS 
授权：MCP 模式需携带有效 X-MCP-API-Key，CLI 模式执行 opscli auth login。

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
    "这是什么商品",
    "这个商品评价如何？"
  ],
  "问题数量": 2,
  "答案数量": 0,
  "报告路径": null,
  "数据": [],
  "原因": "rufus skipped"
}
```


完整机器可读 JSON 数据见同目录 `frontend-data.json`。

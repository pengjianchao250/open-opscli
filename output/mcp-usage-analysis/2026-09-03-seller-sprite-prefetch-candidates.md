# SellerSprite 06:00 预取候选名单

分析日期：2026-09-03

## 结论

SellerSprite 存在稳定的每日高频任务族。补导 `collection_runs.request_params` 后，已经可以
按完整规范请求识别具体 ASIN、ASIN 组合和关键词：

- `mcp_call_events` 只有用户散列、场景、站点和周期，没有业务 `params`。
- 初始 `collection_runs` 导出没有 `request_params`，无法区分同场景下的具体查询。
- 2026-09-03 补导文件恢复出 47 个不重复规范请求，其中 21 个在观察窗口 14 天全部活跃。
- 所有 47 个参数 JSON 均可解析、候选键无重复，因此可以生成精确预热名单。

首批计划统一设置为北京时间 `06:00`。现有共享缓存新鲜度为 24 小时，06:00 完成的结果
可以覆盖当天主要工作时段，并在次日 06:00 由新结果接替。

## 每日任务族

以下只统计 `runtime_role=executor`，日期按 UTC+8 转为北京时间。事件窗口为
2026-08-24 18:38 至 2026-09-03 11:36，其中完整可比较窗口从 2026-08-26 开始。

| 优先级 | 场景 / 站点 / 周期 | 活跃天数 | 调用数 | 用户数 | 每日调用 | 结果非空率 | 结果 P95 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| P0 | `keyword-reverse / US / 30d` | 9/9 | 676 | 30 | 75.1 | 96.2% | 93s |
| P0 | `competitor-lookup / US / 30d` | 9/9 | 330 | 34 | 36.7 | 95.5% | 42s |
| P1 | `keyword-miner / US / 30d` | 7/9 | 206 | 15 | 29.4 | 97.1% | 75s |
| P1 | `product-research / US / 30d` | 9/9 | 79 | 14 | 8.8 | 80.8% | 59s |
| P1 | `traffic-source / US / 30d` | 7/9 | 57 | 17 | 8.1 | 96.6% | 71s |
| 观察 | `market-research / US / 30d` | 6/9 | 54 | 15 | 9.0 | 51.6% | 76s |

`market-research` 的非空率只有 51.6%，先观察，不进入第一批计划。`listing-analysis`
即使历史上多天出现，也属于用户显式授权场景，禁止自动预取。

## 生产参数试点

生产 `collection_runs` 补导得到以下四条高频请求。它们全部保持禁用，先核验来源任务使用
共享账号池，再只启用第 1 条走通缓存复用流程。

| 顺序 | 场景 | 参数 | 活跃天数 | 成功次数 | 平均结果行 | 非空率 | 用途 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `keyword-reverse` | `asin=B0B8VQLN6Y` | 14 | 30 | 93.3 | 100% | 第一条灰度计划 |
| 2 | `keyword-reverse` | `asin=B0GHMCCBGQ` | 14 | 29 | 79.6 | 100% | 备选 |
| 3 | `competitor-lookup` | `asins=B0B8VQLN6Y,B0GHMCCBGQ,B0FHV8MSVT` | 14 | 28 | 58.1 | 100% | 备选 |
| 4 | `competitor-lookup` | `asins=B0GK189P5P,B0BGLV4F6X,B09Q1YHXLP` | 14 | 27 | 87.5 | 100% | 备选 |

机器可读名单保存在
`tests/fixtures/prefetch/seller_sprite_pilot_schedules.json`，所有计划默认 `enabled=false`，
并由单元测试持续验证参数仍符合计划任务合同。历史调用使用 `export_format=xls`，缓存指纹
包含导出格式，因此预热计划也必须保持 `xls`，不能改成 `json` 后期待命中原请求。

## 测试流程

1. 生产 MySQL 升级至 Schema v3，通用 MCP 和 Collector MCP 启用预取调度器。
2. 使用名单第 1 条创建禁用计划，时间设置为 `06:00 / Asia/Shanghai`。
3. 调用 `prefetch_schedule_run_now`，确认运行进入 `succeeded`，来源任务 ID 为
   `Prefetch-seller-sprite-<run_id>`。
4. 确认 `collection_runs` 已写入非空 `request_fingerprint`、`cache_scope=shared_pool` 和结果。
5. 用相同参数及 `export_format=xls` 调用 `seller_sprite_run`，应直接返回当前用户的
   `succeeded` 合成任务，
   不再进入普通采集队列。
6. 确认缓存命中后再启用计划；先只启用一条，连续观察 3 天。

## 账号路由核验

生产参数补导已经完成。配套只读 SQL 兼容尚未增加缓存指纹列的 Schema v1，位于
`output/mcp-usage-analysis/seller-sprite-prefetch-candidate-export.sql`，后续可以重复导出并
更新候选名单。

严格入选条件：同一规范请求 14 天内至少活跃 3 天、至少运行 3 次、场景可重放，
并排除 `listing-analysis`。当前 Schema v1 仍无法证明任务来自共享账号池，47 个导出项
统一标记为 `requires_shared_pool_verification`，只能进入禁用观察名单；需要结合 Collector
任务队列确认
`account_route=shared_pool`，或升级后重新观察非空 `cache_scope/request_fingerprint`，
通过审核后才能创建为默认禁用的试点计划。

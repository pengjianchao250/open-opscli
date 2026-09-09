# opscli MCP 高频任务与预取分析

分析日期：2026-09-03

## 数据范围

- MCP 事件 20,246 条，覆盖 2026-08-24 10:38:18 至 2026-09-03 03:36:01 UTC。
- 执行端事件 11,869 条，网关代理事件 8,377 条，脱敏用户 134 个。
- 采集成功记录 6,088 条，覆盖 2026-08-17 至 2026-09-03。
- `collection_runs` 只保存成功结果，不能据此推导整体业务成功率。
- 6,088 条记录的 `request_fingerprint` 和 `cache_scope` 全为空，当前无法识别相同 ASIN、关键词或参数组合是否跨天重复。
- MCP 公共遥测状态固定为 `called`，不能从该表判断业务失败、无数据或额度拒绝。

## 核心结论

1. SellerSprite 执行端共 6,215 次调用，其中状态、批量状态、结果和导出类调用 3,628 次，占 58.4%，平均每次 `seller_sprite_run` 对应 1.71 次后续轮询。
2. SellerSprite 网关相对执行端存在稳定的 2.2 至 3.9 秒中位额外耗时。轻量的 scenarios/quota 操作也有同样延迟，应优先排查代理链路。
3. 适合预取的场景集中在 Keepa Product、SellerSprite 关键词/竞品场景和 Google Trends。它们已有共享结果缓存接入，但必须先恢复请求指纹沉淀。
4. `scrape_do amazon-pdp` 是第二大等待热点，但尚未接入共享结果缓存，应先增加缓存再做预取。
5. 调用集中在北京时间 09:00-18:59。计划任务应在 08:00-08:30 和 13:30-14:00 分批预热，而不是统一凌晨执行。

## 服务分布

只统计 `runtime_role=executor`：

| 服务 | 调用数 | 用户数 | 占比 |
| --- | ---: | ---: | ---: |
| seller_sprite | 6,215 | 78 | 52.4% |
| keepa | 2,251 | 67 | 19.0% |
| query | 1,342 | 48 | 11.3% |
| scrape_do | 1,033 | 39 | 8.7% |
| asin_data | 275 | 16 | 2.3% |
| feedback | 192 | 23 | 1.6% |
| external_pnd | 173 | 4 | 1.5% |

Top 1 用户占 10.4%，Top 5 占 30.5%，Top 10 占 44.0%，用户调用中位数为 35 次。应优先使用跨用户共享缓存，而不是只为单一重度用户预热。

## 高频工具与等待热点

| 工具 | 调用数 | 用户数 | P50 | P95 | 建议 |
| --- | ---: | ---: | ---: | ---: | --- |
| seller_sprite_job_status | 2,888 | 71 | 0.68s | 12.02s | 优化轮询，不做预取 |
| seller_sprite_run | 2,121 | 74 | 0.51s | 0.95s | 只是入队耗时 |
| keepa_run | 1,569 | 63 | 4.88s | 54.79s | 高优先级预取候选 |
| scrape_do_run | 947 | 37 | 15.31s | 81.61s | 先接共享缓存 |
| query_simple | 576 | 39 | 1.49s | 5.02s | 后端查询缓存或物化 |
| seller_sprite_jobs_status | 499 | 35 | 0.77s | 31.12s | 优化批量轮询 |
| query_flow | 314 | 35 | 3.10s | 17.35s | 优化规划器和元数据缓存 |
| asin_data_live_data | 252 | 16 | 2.35s | 15.92s | 先接共享缓存 |

## 预取候选

| 场景 | 调用数 | 用户数 | 当前耗时 | 优先级 |
| --- | ---: | ---: | ---: | --- |
| Keepa product / US | 1,059 | 50 | MCP P95 59.84s | 最高，需具体参数指纹 |
| SellerSprite keyword-reverse / US / 30d | 676 | 30 | 任务 P95 93s | 高 |
| SellerSprite competitor-lookup / US / 30d | 330 | 34 | 任务 P95 42s | 高 |
| SellerSprite keyword-miner / US / 30d | 206 | 15 | 任务 P95 75s | 中高 |
| Keepa product-search / US | 130 | 8 | MCP P95 181.40s | 中高，需确认重复率 |
| SellerSprite product-research / US / 30d | 79 | 14 | 任务 P95 59s | 中 |
| SellerSprite market-research / US / 30d | 54 | 15 | 任务 P95 76s | 中 |
| Google Trends trends | 42 | 12 | MCP P95 10.46s | 低成本试点 |

需要先接共享缓存的场景：ScrapeDo amazon-pdp US（740 次、30 用户、P95 83.48s）、ScrapeDo amazon-search US（64 次、15 用户、P95 34.59s）和 `asin_data_live_data`（252 次、16 用户、P95 15.92s）。

不建议每日预取：任务状态和导出轮询、auth/quota/scenarios/spec/health、任意自然语言 `query_flow`、高度个性化 `query_simple` 和 Rufus 交互任务。

## 流量时间分布

完整工作日执行调用分别为 992、1,356、2,114、1,890、1,597、1,259、1,733，平均约 1,563 次。周末 2026-08-29 和 2026-08-30 分别只有 277 和 255 次，可将周末预取预算降到工作日的 20%-30%。

| 北京时间小时 | 调用数 | 占比 |
| --- | ---: | ---: |
| 18:00 | 1,320 | 11.1% |
| 09:00 | 1,250 | 10.5% |
| 16:00 | 1,238 | 10.4% |
| 15:00 | 1,122 | 9.5% |
| 10:00 | 1,110 | 9.4% |
| 12:00 | 1,098 | 9.3% |
| 17:00 | 1,096 | 9.2% |

## SellerSprite 网关额外耗时

| 操作 | 执行端 P50 | 网关 P50 | 额外耗时 |
| --- | ---: | ---: | ---: |
| seller_sprite_run | 505ms | 3,043ms | 2,538ms |
| seller_sprite_job_status | 681ms | 3,560ms | 2,879ms |
| seller_sprite_jobs_status | 771ms | 4,653ms | 3,882ms |
| seller_sprite_scenarios | 2ms | 2,317ms | 2,315ms |
| seller_sprite_quota_status | 3ms | 2,507ms | 2,504ms |
| seller_sprite_export | 559ms | 2,771ms | 2,212ms |

建议检查远程 MCP 客户端是否每次重建连接、OPS 配置发现、鉴权验证、DNS/TLS 建连和代理重试。

## 必须先修的数据能力

2026-09-03 已在代码中完成修复：采集 Schema v2 为 `collection_runs` 增加显式
`request_fingerprint/cache_scope` 和缓存查询索引，Keepa、Google Trends 的旧 Outbox
与宕机对账任务可从 `params.json` 恢复指纹。生产环境仍需先执行 v1→v2 数据库升级，
重启新版 MCP 后再导出至少 7 天数据验证覆盖率；更早且没有 `request_params._cache`
的历史记录无法可靠反推指纹，将继续保持空值。

建议为 `mcp_call_events` 增加：

- `request_fingerprint CHAR(64) NULL`：使用现有 SHA-256 cache key，不保存原始参数。
- `cache_hit TINYINT NULL`：是否命中共享结果缓存。
- 可选 `queue_wait_ms/execution_ms`：区分入队、排队和真实执行。

## 实施顺序

1. 排查 SellerSprite 网关固定 2-3 秒开销。
2. Agent 默认使用批量状态或带等待参数的状态查询，减少紧密轮询。
3. 已完成代码修复；执行生产 Schema v2 升级并验证真实缓存命中。
4. 在调用遥测中记录 `request_fingerprint/cache_hit`。
5. 观察 7-14 天，再按 fingerprint 选首批 5-10 个预取任务。

候选门槛：同一 fingerprint 在 14 天内至少出现 3 天；至少 3 个用户调用或单一用户不少于 10 次；实时 P95 不低于 5 秒；TTL 覆盖访问峰值；缓存作用域可共享且额度成本可控。

首批计划在 08:00-08:30 预热上午请求，13:30-14:00 刷新下午请求；设置最大调用数、额度和并发；连续 3 次无人命中时自动退出预取集合。

建议试点目标：至少 60% 的预取任务在 TTL 内被真实用户命中，目标场景等待 P95 降低 50% 以上，无人命中预取低于 20%。

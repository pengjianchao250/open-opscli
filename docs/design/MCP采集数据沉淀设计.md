# MCP 采集数据沉淀设计

## 1. 范围

当前处理通用 MCP 中 Keepa 与 Collector MCP 中 SellerSprite 新产生的成功任务。历史生产任务迁移仅保留 TODO。

## 2. 模块接口

共享模块位于 `opscli/shared/collection_storage/`，不依赖任何 MCP 宿主或采集来源。这里的“共享”是指两个部署包复用同一套代码和 MySQL 表合同，不是跨服务器共享 Python Runtime、SQLite 文件或本地目录。它对通用 MCP 和 Collector MCP 提供以下接口：

```text
CollectionSubmission  成功采集任务引用
CollectionParser      来源文件到逻辑 Dataset 的解析接口
CollectionReconciler  live cutover 后成功任务的补偿对账接口
CollectionStorageRuntime.register_source(parser, reconciler)
CollectionStorageRuntime.submit(submission)
build_collection_storage_runtime(runtime_id)
collection_storage_lifespan(runtime)
```

后台 Worker 只依赖 `source_system -> Parser -> Repository`，不包含宿主或来源场景分支。Keepa 与 SellerSprite 分别在自己的模块内实现 Parser、Submitter 和 Reconciler Adapter。

`parser_utils.py` 统一提供任务目录边界校验、Artifact SHA-256、JSON/XLSX Dataset、重复列名、JSON 安全值和 Record Hash，来源 Parser 只处理自己的成功结果合同。

## 3. 在线链路

```text
SellerSprite Scheduler 提交 succeeded
  -> SellerSprite Submitter
  -> Collector SQLite Outbox
  -> 共享 Parser Registry / Worker

KeepaApiManager 完成 result.json 和 XLSX
  -> Keepa Submitter
  -> 通用 MCP SQLite Outbox
  -> 共享 Parser Registry / Worker

两个服务器上的独立 Outbox / Worker
  -> 各自的 MySQL Repository 实例
  -> 同一个 MySQL schema 和结果表合同

用户手动创建每日预取计划
  -> collection_prefetch_schedules
  -> 到期时写入 collection_prefetch_runs
  -> 通用 MCP 只领取 Keepa / Google Trends
  -> Collector MCP 只领取 SellerSprite
  -> 强制 live 采集并进入原有结果沉淀链路
```

采集状态和沉淀状态相互独立。MySQL 故障只重试沉淀，不允许重新调用 SellerSprite 或 Keepa。Keepa 原始响应仍只登记文件 URI、大小和 SHA-256，格式化 XLSX 每个工作表作为独立 Dataset 入库。

## 4. 场景和文件

| 输出 | 处理方式 |
|---|---|
| JSON 主表 `columns + rows` | `dataset_code=main` |
| JSON `additional_sheets` | 每个 Sheet 一个 `additional_n` Dataset |
| 官方或格式化 XLSX | 每个工作表一个 Dataset，首行为表头 |
| `params.json` | 登记文件并将请求参数写入 `collection_runs` |
| `raw.json` | 只登记 URI、大小和 SHA-256，不写入 MySQL BLOB |
| `result.json` | 作为成功结果合同和文件索引 |
| 导出 JSON/XLSX | 登记交付文件并解析格式化记录 |

重复表头通过 `字段名__2` 形成稳定 JSON key，原始表头顺序同时保存在 `columns_json`。

## 5. MySQL 表

```text
collection_schema_versions
collection_runs
collection_prefetch_schedules
collection_prefetch_runs
collection_artifacts
collection_datasets
collection_records
```

任务幂等键：

```text
(data_environment, source_system, source_job_id)
```

同一个任务重放时，在一个 MySQL 事务中保留 `collection_runs` ID，并替换其文件、Dataset 和记录，覆盖 Worker 在提交确认间隙重启的情况。

`collection_runs.request_fingerprint` 保存规范化业务请求的 SHA-256 摘要，
`cache_scope` 保存共享池或专属账号隔离范围。两者均不保存 ASIN、关键词等原始值，
并通过 `ix_collection_runs_cache_lookup` 支撑精确的新鲜结果查询；
`request_params._cache` 继续保留结果重建所需的版本和低敏摘要。

预取计划只支持每日固定时间，`next_run_at` 统一保存 UTC，`run_time` 与 `timezone`
保留用户口径。到期计划先生成独立运行记录，再由所属宿主通过
`FOR UPDATE SKIP LOCKED` 和执行租约领取；长任务周期续租，进程中断后复用同一运行 ID
和确定性来源 `job_id` 重试。计划参数禁止出现 JWT、Session、API Key、Cookie、密码或
其他 Token；执行时只读取部署环境显式配置的服务凭证作用域。SellerSprite 仅允许共享
账号池的可重放场景，用户专属账号和 `listing-analysis` 不进入自动计划。

## 6. 环境和历史边界

`data_environment` 只能来自 MCP 宿主进程配置：

```text
production
debug
```

不得从文件名、目录或主机名推断。每个宿主 Outbox 首次启用时独立固定 `live_cutover_at`。SellerSprite 在任务成功事务内追加独立自增成功事件，对账游标按成功事件顺序推进。Keepa 在完整写入结果文件后直接提交通用 MCP Outbox；Reconciler 扫描默认 Keepa 输出目录中 cutover 后且尚未存在于 Outbox 的 `result.json`。通用 MCP 与 Collector MCP 部署在不同服务器：`mcp.sqlite3` 只存在于通用 MCP 服务器，`collector.sqlite3` 只存在于 Collector 服务器，禁止通过 NFS、文件同步或复制运行中数据库的方式共享 Outbox。

两台服务器必须分别配置并验证到 MySQL 的网络、DNS、账号和 TLS 连通性。生产 MySQL 连接必须配置受信任 CA，并验证服务端证书和主机身份；当前内网测试数据库只能在两台服务器都具备内网路由时用于联调。后续切换内外网可达的统一数据库时，分别更换两台服务器的连接、Secret 和 CA 配置，不改变来源 Parser 或数据库表合同。

TODO：未来单独实现历史 backfill，只扫描生产环境状态为 `succeeded` 的任务，先 dry-run，再以 `ingestion_mode=backfill` 幂等导入。

# MCP 采集数据沉淀设计

## 1. 范围

当前处理通用 MCP 中 Keepa 与 Collector MCP 中 SellerSprite 新产生的成功任务。历史生产任务迁移仅保留 TODO。

## 2. 模块接口

共享模块位于 `opscli/shared/collection_storage/`，不依赖任何 MCP 宿主或采集来源。它对通用 MCP 和 Collector MCP 提供以下接口：

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

两个独立 Outbox
  -> 同一个 MySQL Repository 和五表合同
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
collection_artifacts
collection_datasets
collection_records
```

任务幂等键：

```text
(data_environment, source_system, source_job_id)
```

同一个任务重放时，在一个 MySQL 事务中保留 `collection_runs` ID，并替换其文件、Dataset 和记录，覆盖 Worker 在提交确认间隙重启的情况。

## 6. 环境和历史边界

`data_environment` 只能来自 MCP 宿主进程配置：

```text
production
debug
```

不得从文件名、目录或主机名推断。每个宿主 Outbox 首次启用时独立固定 `live_cutover_at`。SellerSprite 在任务成功事务内追加独立自增成功事件，对账游标按成功事件顺序推进。Keepa 在完整写入结果文件后直接提交通用 MCP Outbox；Reconciler 扫描默认 Keepa 输出目录中 cutover 后且尚未存在于 Outbox 的 `result.json`。两个宿主不得共用 SQLite 文件，默认分别使用 `collector.sqlite3` 和 `mcp.sqlite3`。

生产 MySQL 连接必须配置受信任 CA，并验证服务端证书和主机身份；当前内网测试数据库可以按受控网络能力关闭 TLS。后续切换内外网可达的统一数据库时，只更换连接、Secret 和 CA 配置，不改变来源 Parser 或数据库表合同。

TODO：未来单独实现历史 backfill，只扫描生产环境状态为 `succeeded` 的任务，先 dry-run，再以 `ingestion_mode=backfill` 幂等导入。

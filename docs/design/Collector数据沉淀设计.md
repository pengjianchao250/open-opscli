# Collector 数据沉淀设计

## 1. 范围

一期只处理 Collector MCP 中卖家精灵新产生的成功任务。Keepa 不迁移、不接入 MySQL；历史生产任务迁移仅保留 TODO。

## 2. 模块接口

共享模块位于 `opscli/collector_mcp/storage/`，对来源 Bundle 提供三类接口：

```text
CollectionSubmission  成功采集任务引用
CollectionParser      来源文件到逻辑 Dataset 的解析接口
CollectionReconciler  live cutover 后成功任务的补偿对账接口
```

后台 Worker 只依赖 `source_system -> Parser -> Repository`，不包含卖家精灵场景分支。后续采集模块只需注册自己的 Submitter、Parser 和 Reconciler。

## 3. 在线链路

```text
SellerSprite Scheduler 提交 succeeded
  -> SellerSprite Submitter
  -> Collector SQLite Outbox
  -> Parser Registry
  -> SellerSprite JSON/XLSX Parser
  -> MySQL Repository
```

采集状态和沉淀状态相互独立。MySQL 故障只重试沉淀，不允许重新调用卖家精灵。

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

`data_environment` 只能来自 Collector 进程配置：

```text
production
debug
```

不得从文件名、目录或主机名推断。Outbox 首次启用时固定 `live_cutover_at`。SellerSprite 在任务成功事务内追加独立自增成功事件，对账游标按成功事件顺序推进，不依赖可能乱序完成的任务创建 ID；自动对账只覆盖 cutover 之后的新成功任务。

生产 MySQL 连接必须配置受信任 CA，并验证服务端证书和主机身份；调试环境可以按本地数据库能力关闭 TLS。

TODO：未来单独实现历史 backfill，只扫描生产环境状态为 `succeeded` 的任务，先 dry-run，再以 `ingestion_mode=backfill` 幂等导入。

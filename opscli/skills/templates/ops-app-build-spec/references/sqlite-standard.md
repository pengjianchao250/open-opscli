# SQLite 使用规范

本文是 `docs/开发指南/SQLite数据库使用通用规范.md` 的执行摘要，只覆盖 ops-app 后端在 FastAPI + SQLAlchemy 2.0 异步栈下必须遵守的规则。需要完整论述、12 步安全改表法、反模式清单或故障速查表时读全文；两者冲突时以全文为准。

## 适用边界

SQLite 只解决读写互斥，不解决写并发：任何时刻只能有一个写事务。以下场景停止并联系 IT 评估服务端数据库，不得用调大超时或多实例硬扛：

- 多个服务或多个容器副本需要同时写同一个库。
- 持续写入并发大于个位数 QPS，或单库文件预期超过数十 GB。
- 需要跨机器共享库文件（网络文件系统会造成静默数据损坏）。

Compose 中 SQLite 服务固定单副本，禁止横向扩展写入实例。

## 路径

- 库文件路径只能来自 `Settings`，容器默认 `/data/app.db`，本地开发用 `.env` 覆盖为项目外或 `./data/` 下的绝对路径。禁止在代码中硬编码相对路径、`/tmp` 或源码目录。
- 库文件必须落在 Compose 管理的持久卷上，绝不能进入镜像层或代码目录。
- `.gitignore` 必须排除 `*.db`、`*.sqlite`、`*.sqlite3`、`*-wal`、`*-shm`。
- 禁止放在 NFS、SMB、CIFS 或部分容器共享卷上。
- 库文件权限 0600，所在目录 0700；备份文件同等保护。

## 连接基线

PRAGMA 是连接级设置（`journal_mode` 除外），必须在每个新连接建立时注入，SQLAlchemy 下挂在 `connect` 事件上：

```python
_PRAGMAS = (
    ("journal_mode", "WAL"),        # 读写不互斥，并发能力的关键
    ("synchronous", "NORMAL"),      # WAL 下不强制每事务 fsync，崩溃不损坏库
    ("foreign_keys", "ON"),         # 默认关闭，不开则 FOREIGN KEY 形同虚设
    ("busy_timeout", "5000"),       # 遇写锁等待 5 秒再抛 database is locked
    ("temp_store", "MEMORY"),
    ("cache_size", "-64000"),       # 64MB 页缓存，负数表示 KB
)


@event.listens_for(engine.sync_engine, "connect")
def _set_pragmas(dbapi_conn, _record):
    """每个新连接建立时注入 PRAGMA 基线。"""
    cur = dbapi_conn.cursor()
    for name, value in _PRAGMAS:
        cur.execute(f"PRAGMA {name}={value}")
    cur.close()
```

- 引擎使用 `sqlite+aiosqlite:///<绝对路径>`，`poolclass=NullPool`，`connect_args={"timeout": 5}`。SQLite 不需要连接池，长期持有连接会让 WAL 文件无法 checkpoint 收缩。
- 禁止在 `async def` 中直接调用同步 `sqlite3`；只允许 `aiosqlite` 驱动或 `asyncio.to_thread`。同一连接不得多线程并发使用。
- 写事务必须以 `BEGIN IMMEDIATE` 开始：默认 DEFERRED 事务在第一次写时才升级写锁，升级失败会立即抛 `SQLITE_BUSY` 且不受 `busy_timeout` 保护。SQLAlchemy 下按官方 pysqlite / aiosqlite 文档的事务配方实现：`connect` 事件把 DBAPI 连接的 `isolation_level` 置为 `None`，`begin` 事件执行 `BEGIN IMMEDIATE`。
- `with sqlite3.connect(...) as conn` 只提交事务不关闭连接；直接使用 `sqlite3` 的脚本必须显式 `close()`。

## 事务

- 事务要短：一次业务操作等于一次完整读或写，做完立即提交。禁止在事务中做网络调用、等待用户输入或耗时计算，这是 `database is locked` 的头号原因。
- 批量写用 `executemany` 或 ORM 批量语句放在单个事务内；超过 10 万行时分批提交，每批 5000 到 10000 行。
- 列表查询必须带 `LIMIT`（建议不超过 500）和显式 `ORDER BY`，并含唯一列兜底。只取需要的列。
- `database is locked` 排查顺序固定为：事务是否够短 → 是否 `BEGIN IMMEDIATE` → `busy_timeout` 是否生效 → 是否连接泄漏 → 是否多进程写 → 是否 WAL → 是否在网络文件系统。禁止一上来就调大 `busy_timeout`。

## 数据结构

- SQLite 3.37+ 建表使用 `STRICT`；低版本用 `CHECK` 补类型校验。列类型只用 `INTEGER`、`REAL`、`TEXT`、`BLOB`、`ANY`，禁止写 `VARCHAR(n)`、`DECIMAL(18,2)`、`DATETIME`、`BOOLEAN`。
- 金额用 `INTEGER` 存最小单位（分或厘），列名带单位后缀如 `amount_cent`；禁止 `REAL`。SQLAlchemy 模型用 `Integer` 而非 `Numeric`。
- 时间统一存 UTC，全项目只用一种表示：ISO-8601 `TEXT` 或整数时间戳。禁止 `datetime('now','localtime')` 默认值，禁止混用多种时间格式。
- 每列显式 `NOT NULL` 或明确可空；枚举列用 `CHECK` 列全取值；布尔用 `INTEGER` 0/1 并 `CHECK`。
- 使用外键时 `foreign_keys=ON` 必须生效，同库外键明确 `ondelete`。
- JSON 列必须 `CHECK (json_valid(col))`；需要过滤或排序的字段提取成独立列或生成列并建索引，禁止把 JSON 当规避建表的手段。
- 外键列与高频过滤列必须建索引；索引注释写明专供哪个查询；用 `EXPLAIN QUERY PLAN` 确认命中。
- SQLite 不支持 `COMMENT`：表与关键列的中文注释写在迁移文件的行内注释中，与 ORM 模型的 `comment=` 共用同一份文案常量。

命名：

| 对象 | 规则 | 示例 |
| --- | --- | --- |
| 表 | 蛇形复数，无前缀或统一前缀 | `user_notes` |
| 列 | 蛇形；布尔 `is_` / `has_`；时间 `_at`；金额带单位 | `is_archived`、`created_at`、`amount_cent` |
| 主键 | `id` | `id` |
| 外键 | `<引用表单数>_id` | `owner_id` |
| 索引 | `idx_<表>_<列组合>` | `idx_tasks_owner_status` |
| 唯一约束 | `uq_<表>_<语义>` | `uq_tasks_owner_title` |
| 触发器 | `trg_<表>_<动作>` | `trg_tasks_updated_at` |

## 迁移

- 迁移机制全项目只用 Alembic。应用代码中出现 `CREATE TABLE`、`ALTER TABLE`、`DROP` 一律打回；禁止在应用代码写 `CREATE TABLE IF NOT EXISTS`。
- 应用启动时的 `init_database()` 只做三件事：确保目录存在、连通性校验、`alembic upgrade head`。必须幂等，首次创建与后续启动走同一条代码路径。
- `env.py` 必须 `render_as_batch=True`：SQLite 的 `ALTER TABLE` 只支持 `RENAME TO`、`ADD COLUMN`、`RENAME COLUMN`（3.25+）、`DROP COLUMN`（3.35+，有限制）；改列类型、约束、主键外键或列顺序必须走 batch 重建。`ADD COLUMN` 的非空列必须给常量默认值。
- 重建表的迁移必须显式重建索引和触发器（`DROP TABLE` 会连带删除），`PRAGMA foreign_keys` 开关必须在事务之外，提交后必须跑 `PRAGMA foreign_key_check`。
- 迁移铁律：已发布迁移永不修改；改错了新增更大序号的修正迁移；一个迁移一件事；DDL 放事务里；数据回填幂等；只加不减；不得 import ORM 模型；大表回填分批。
- 每个迁移配测试：空库应用、重复应用幂等、重建表迁移断言数据一致且索引触发器已重建。测试库结构必须由同一套迁移建立。

## 备份与维护

- 禁止直接 `cp` 或 `rsync` 正在使用的库文件。在线备份只用两种方式之一：

```python
def backup_database(dst: Path) -> None:
    """在线备份到 dst，不中断正在进行的读写。"""
    with get_conn() as src, sqlite3.connect(dst) as dst_conn:
        src.backup(dst_conn, pages=1000, sleep=0.05)
```

```sql
VACUUM INTO '/backup/app-20260902.db';
```

- 备份策略必须写进 `docs/ops-app/deployment.md`：频率、保留份数、异地存放、恢复演练周期。备份与库文件不放同一块磁盘；备份后 `PRAGMA integrity_check` 返回 `ok`。
- 恢复顺序固定：停止应用 → 备份当前现场 → 替换库文件并清理 `-wal`、`-shm` → 校验完整性 → 启动应用。
- 维护动作：`PRAGMA optimize`（关闭连接前）、`ANALYZE`（数据分布变化后）、`wal_checkpoint(TRUNCATE)`；`VACUUM` 只在维护窗口执行。容量监控库文件大小、`-wal` 大小、单表行数增长速率。
- 备份与维护通过 `python cli.py ops ...` 或注册表中的 `manual_only` 任务执行，与自动任务共用同一实现。

## 安全

- 所有值走占位符，表名列名走白名单；禁止把用户输入拼进 `PRAGMA` 或 `ATTACH DATABASE`。
- 禁止明文存密码、token、密钥、身份证、银行卡；静态加密用 SQLCipher 或磁盘加密，禁止自实现字段加密而不做密钥管理。
- 多租户隔离完全是应用责任，查询必须带归属条件。

## 测试替身边界

- 单元与集成测试用内存库 `sqlite+aiosqlite:///:memory:`，配 `StaticPool`，跳过 `journal_mode`。
- 禁止只靠 SQLite 验证并发、锁、死锁、大数据量性能、方言 SQL、字符集排序规则或真实索引选择；这些场景在 SQLite 上测不出问题。

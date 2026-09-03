# SQLite 数据库使用通用规范

> **文档性质**：团队级强制规范，适用于所有使用 SQLite 的 Python 服务、工具、桌面/边缘应用与测试环境。
> **约束等级**：`【必须】` 违反即评审不通过 · `【应当】` 需在 PR 中说明理由才可豁免 · `【建议】` 推荐做法。
> **配套文档**：《FastAPI 后端开发通用规范》（分层、迁移流程、测试分层等通用工程约束以那份为准，本文只讲 SQLite 特有部分）。
> **适用版本**：SQLite **3.35+**（`ALTER TABLE DROP COLUMN`、`RETURNING`、`VACUUM INTO` 的下限）；推荐 **3.37+**（`STRICT` 表）。低于此版本的条目会单独标注。

---

## 目录

- [0. 选型：你真的需要 SQLite 吗](#0-选型你真的需要-sqlite-吗)
- [1. 初始化与连接](#1-初始化与连接)
- [2. 数据结构规范](#2-数据结构规范)
- [3. 表结构更新（迁移）](#3-表结构更新迁移)
- [4. 读写规范](#4-读写规范)
- [5. 并发与锁](#5-并发与锁)
- [6. 异步应用中的 SQLite](#6-异步应用中的-sqlite)
- [7. 备份、恢复与维护](#7-备份恢复与维护)
- [8. 安全规范](#8-安全规范)
- [9. 测试中的 SQLite](#9-测试中的-sqlite)
- [10. 何时该换成服务端数据库](#10-何时该换成服务端数据库)
- [附录 A：建表模板](#附录-a建表模板)
- [附录 B：发布前检查清单](#附录-b发布前检查清单)
- [附录 C：反模式清单](#附录-c反模式清单)
- [附录 D：故障速查表](#附录-d故障速查表)

---

## 0. 选型：你真的需要 SQLite 吗

### 0.1 SQLite 适合与不适合的场景

| 场景 | 结论 |
|---|---|
| 单机应用的本地状态（配置、缓存、任务记录、审计） | ✅ 首选 |
| 桌面 / CLI / 边缘设备的嵌入式存储 | ✅ 首选 |
| 单实例 Web 服务的中低写入量业务数据 | ✅ 可用（注意 §5 单写者约束） |
| 测试环境替代生产数据库 | ⚠️ 可用但有方言陷阱，见 §9 |
| 只读的数据分发（配置包、词典、模型元数据） | ✅ 非常适合（只读时并发无限制） |
| 多进程/多实例并发写入 | ❌ 换 PostgreSQL / MySQL |
| 需要跨网络访问同一个库 | ❌ **绝对禁止**（NFS/SMB 上的锁不可靠，必然损坏） |
| 高频写入（持续 > 数百 TPS 写事务） | ❌ 换服务端数据库 |
| 任务队列 | ❌ 换 Redis / MQ（见 §10） |
| 大文件、大 BLOB 存储 | ❌ 用对象存储，库里只存引用 |
| 需要行级权限、多租户强隔离 | ❌ 换服务端数据库 |

### 0.2 与其他存储的边界

| 需求 | 用什么 |
|---|---|
| 进程内、重启即弃的临时状态 | 内存变量 |
| 需要持久化的结构化小数据 | **SQLite** |
| 需要多进程共享的高频读写 | Redis |
| 需要跨服务共享、强一致、行级权限 | PostgreSQL / MySQL |
| 二进制文件（图片、导出文件、附件） | 对象存储 + 库里存 key |

【必须】**不需要持久化就不要引入 SQLite**。多一个数据库就多一份迁移、备份、并发、容量的负担。

---

## 1. 初始化与连接

### 1.1 数据库文件路径

【必须】库文件路径**只能来自配置**（环境变量 / Settings），代码中**禁止出现硬编码的相对路径**。

```python
# ✅ 正确：路径来自配置，且是绝对路径
DB_PATH = Path(settings.sqlite_path).expanduser().resolve()

# ❌ 以下全部禁止
sqlite3.connect("app.db")             # 相对路径 → 依赖启动时的 cwd，换个目录启动就是另一个库
sqlite3.connect("./data/app.sqlite")  # 同上
sqlite3.connect("/tmp/cache.db")      # 临时目录 → 重启/清理即丢
```

【必须】库文件必须放在**持久化目录**：
- 容器部署 → 挂载的数据卷，**绝不能放在镜像层或代码目录**（每次发布容器重建，数据清零）；
- 桌面应用 → 平台标准用户数据目录（`~/.local/share/<app>/`、`%APPDATA%\<app>\`、`~/Library/Application Support/<app>/`）；
- 服务器部署 → 独立的 data 目录，与代码目录分离，且在备份范围内。

【必须】`.gitignore` 中排除 `*.db` / `*.sqlite` / `*.sqlite3` / `*-wal` / `*-shm`；**代码仓库里不得出现库文件**。

【禁止】把库文件放在网络文件系统（NFS、SMB、CIFS、部分容器共享卷）上——SQLite 依赖的文件锁在这些系统上不可靠，会导致**静默数据损坏**。这是 SQLite 官方明确列出的禁忌。

### 1.2 PRAGMA 基线（每个连接都必须设置）

```python
_PRAGMAS = (
    # WAL 模式：读写不互斥（读不再阻塞写、写不再阻塞读），并发能力的关键。
    # 只需设置一次并持久化在库文件里，但每次连接都设无害且更保险。
    ("journal_mode", "WAL"),
    # NORMAL：WAL 模式下每次事务不强制 fsync，靠 checkpoint 落盘。
    # 崩溃时最多丢失最近几个事务但不会损坏库；FULL 更安全但写性能差一个数量级。
    ("synchronous", "NORMAL"),
    # 外键约束默认关闭（历史兼容），必须显式开启，否则 FOREIGN KEY 声明形同虚设。
    ("foreign_keys", "ON"),
    # 遇到写锁时最多等待 5 秒再抛 "database is locked"，而不是立即失败。
    ("busy_timeout", "5000"),
    # 临时表/排序结果放内存，减少磁盘 IO。
    ("temp_store", "MEMORY"),
    # 页缓存 64MB（负数 = KB 数）。按库大小与内存预算调整。
    ("cache_size", "-64000"),
)
```

| PRAGMA | 取值 | 为什么 |
|---|---|---|
| `journal_mode` | **`WAL`** | 默认 `DELETE` 模式下读写互斥，一个慢查询就会阻塞所有写入 |
| `synchronous` | **`NORMAL`** | WAL + NORMAL 是官方推荐组合；`FULL` 写性能差一个数量级，`OFF` 崩溃会损坏库 |
| `foreign_keys` | **`ON`** | **默认是关闭的**——不显式开启，所有外键声明都不生效，这是最常见的"约束没生效"原因 |
| `busy_timeout` | **≥ 5000** | 不设置时遇锁立即抛错；设置后会自动重试等待 |
| `temp_store` | `MEMORY` | 排序/临时表走内存 |
| `cache_size` | 按需 | 负数表示 KB；默认 2MB 通常偏小 |
| `mmap_size` | 【建议】`268435456`(256MB) | 只读多的场景收益明显；写多场景收益有限 |

【必须】WAL 模式下库文件旁会出现 `-wal` 与 `-shm` 两个伴生文件。**备份、拷贝、迁移必须三个文件一起处理，或使用 §7 的在线备份方式**——只拷 `.db` 会丢失未 checkpoint 的数据。

### 1.3 连接工厂（标准写法）

```python
"""SQLite 连接管理：路径、PRAGMA、行工厂的单一事实来源。"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import settings

_PRAGMAS = (...)   # 见 1.2


def _connect() -> sqlite3.Connection:
    """建立一个已配置好的 SQLite 连接。

    isolation_level=None 关闭 Python 层的隐式事务管理，改由代码显式 BEGIN/COMMIT。
    为什么：sqlite3 模块默认会在 INSERT/UPDATE 前偷偷 BEGIN，且在 SELECT 前偷偷
    COMMIT，事务边界完全不可控——显式管理才能保证"一次业务操作 = 一个事务"。
    """
    conn = sqlite3.connect(
        settings.sqlite_path,
        timeout=settings.sqlite_busy_timeout_seconds,
        isolation_level=None,
        check_same_thread=False,   # 允许跨线程使用；并发安全由调用方按 §5 保证
    )
    conn.row_factory = sqlite3.Row      # 结果按列名访问，避免下标魔法数字
    for name, value in _PRAGMAS:
        conn.execute(f"PRAGMA {name}={value}")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """获取连接的标准入口：用完必关。

    注意：`with sqlite3.connect(...) as conn` 只提交事务，**不关闭连接**——
    这是 sqlite3 模块的经典陷阱，直接这么用会造成连接泄漏。本函数显式 close。
    """
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """写事务入口：BEGIN IMMEDIATE 立即取写锁，异常自动回滚。

    为什么用 IMMEDIATE 而不是默认的 DEFERRED：DEFERRED 事务在第一次写时才
    尝试升级为写锁，若此时另一个连接已持有写锁，会立即抛 SQLITE_BUSY 且
    **不受 busy_timeout 保护**（锁升级失败无法重试，否则会死锁）。
    IMMEDIATE 在开始就取写锁，能正常走 busy_timeout 等待重试。
    """
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
```

【必须】**写事务一律用 `BEGIN IMMEDIATE`**。这是 SQLite 并发问题里最反直觉、也最值得记住的一条：默认的 `DEFERRED` 事务在锁升级失败时**绕过 `busy_timeout` 直接报错**，表现为「明明设了 5 秒超时，还是瞬间 database is locked」。

【必须】用 `with sqlite3.connect(...)` 时要清楚它**只提交不关闭**；统一走上面的 `get_conn()` 封装。

### 1.4 初始化：幂等 bootstrap

【必须】应用启动时的初始化必须**幂等**（重复执行结果一致），且**只做建库目录 + 连通性校验 + 执行迁移**三件事，不做业务数据写入。

```python
def init_database() -> None:
    """初始化数据库：确保目录存在、库可连、迁移已应用到最新。

    幂等：可在每次进程启动时无条件调用。
    调用时机：应用 lifespan 启动阶段、CLI 命令入口、测试 fixture。
    """
    db_path = Path(settings.sqlite_path).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)   # 目录不存在时 sqlite3 会报 "unable to open database file"

    with get_conn() as conn:
        # 校验：新库或已有库都要能正常读到 schema 版本
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        logger.info("SQLite 就绪 path=%s schema_version=%s", db_path, current)

    run_migrations()      # 见 §3
```

【必须】**首次创建与后续启动走同一条代码路径**——不要写「如果库不存在就执行 init.sql，否则执行迁移」的分叉逻辑。分叉会导致新库与老库的结构长期不一致（新库少了历史迁移里的修正，老库少了 init.sql 里后加的东西）。**正确做法：库永远从空开始，全部结构由迁移逐条建立。**

【禁止】把建表语句写在应用代码里的 `CREATE TABLE IF NOT EXISTS`。表结构的唯一入口是迁移（§3）。

### 1.5 SQLAlchemy 接入

使用 SQLAlchemy 时，PRAGMA 必须通过连接事件注入（`connect()` 参数无法设置 PRAGMA）：

```python
from sqlalchemy import create_engine, event

engine = create_engine(
    f"sqlite:///{settings.sqlite_path}",
    # SQLite 不需要连接池（无网络握手开销），但默认的 QueuePool 会缓存连接，
    # 长期持有会让 WAL 文件无法 checkpoint 收缩；小型应用用 NullPool 更省心。
    poolclass=NullPool,
    connect_args={"timeout": 5, "check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_pragmas(dbapi_conn, _record):
    """每个新连接建立时注入 PRAGMA 基线（PRAGMA 是连接级设置，必须每连接设置）。"""
    cur = dbapi_conn.cursor()
    for name, value in _PRAGMAS:
        cur.execute(f"PRAGMA {name}={value}")
    cur.close()
```

【必须】PRAGMA 是**连接级**设置（`journal_mode` 除外，它持久化在库文件中），换连接就失效，因此必须挂在 `connect` 事件上而不是执行一次。

---

## 2. 数据结构规范

### 2.1 首选 STRICT 表（SQLite 3.37+）

SQLite 默认是**动态类型**的：声明 `INTEGER` 的列可以存进字符串，声明 `VARCHAR(10)` 也不限制长度。这是最大的数据质量风险来源。

【必须】SQLite ≥ 3.37 时**建表一律加 `STRICT`**：

```sql
CREATE TABLE user_note (
  id          INTEGER PRIMARY KEY,
  user_id     TEXT    NOT NULL,
  note        TEXT    NOT NULL DEFAULT '',
  created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
```

`STRICT` 表的约束：
- 列类型只能是 `INT` / `INTEGER` / `REAL` / `TEXT` / `BLOB` / `ANY` 六种，写 `VARCHAR(50)` 会**建表失败**（早暴露好过晚出错）；
- 插入不匹配类型的值直接报错，而不是静默转换或原样存入；
- `NOT NULL` 的 `PRIMARY KEY` 真正生效（非 STRICT 表里 `INTEGER PRIMARY KEY` 之外的主键列允许 NULL，这是历史 bug 级行为）。

【必须】无法用 STRICT（版本低于 3.37）时，必须用 `CHECK` 约束补上类型校验，并在表注释中写明原因。

### 2.2 类型选择

只有五种存储类：`NULL` / `INTEGER` / `REAL` / `TEXT` / `BLOB`。业务类型映射：

| 业务类型 | 存储 | 规则 |
|---|---|---|
| **主键** | `INTEGER PRIMARY KEY` | 固定写法，它是 rowid 的别名，查询最快 |
| **金额** | `INTEGER`（最小单位：分/厘） | **【禁止】用 `REAL` 存金额**——二进制浮点无法精确表示 0.1，累加必然产生误差 |
| **时间** | `TEXT` ISO-8601 **UTC** | `2026-09-02T14:30:00.000Z`；见 2.3 |
| **布尔** | `INTEGER` 0/1 | SQLite 无 BOOLEAN 类型；加 `CHECK (col IN (0,1))` |
| **枚举** | `TEXT` + `CHECK` | `CHECK (status IN ('open','done','cancelled'))` |
| **UUID** | `TEXT`（36 位带连字符）或 `BLOB(16)` | 全项目统一一种；`TEXT` 可读性好，`BLOB` 省一半空间 |
| **JSON** | `TEXT` + `CHECK (json_valid(col))` | 见 2.5 |
| **小二进制** | `BLOB`，**≤ 100KB** | 超过就放对象存储，库里存 key |
| **大文件** | ❌ 不入库 | 见 §0.1 |

【必须】**金额禁用 `REAL`**。SQLite 没有 `DECIMAL`/`NUMERIC` 的精确实现（`NUMERIC` 只是类型亲和性，底层仍是 INTEGER/REAL）。

【禁止】写 `VARCHAR(n)` / `DECIMAL(18,2)` / `DATETIME` / `BOOLEAN` 这类"看起来像 MySQL"的类型名——SQLite 会按亲和性规则转成五种存储类之一，**长度和精度完全不生效**，只会给读代码的人造成"有约束"的错觉。

### 2.3 时间规范

【必须】全项目统一一种时间表示，二选一并写进本规范：

| 方案 | 写法 | 优点 | 缺点 |
|---|---|---|---|
| **ISO-8601 文本（推荐）** | `TEXT`，`'2026-09-02T14:30:00.000Z'` | 可读、可直接字符串排序比较、跨语言无歧义 | 占 24 字节 |
| Unix 时间戳 | `INTEGER`（秒或毫秒，全项目统一） | 省空间、算术方便 | 不可读，需转换才能看 |

【必须】**一律存 UTC**，时区转换只在展示层做。

【禁止】使用 `datetime('now','localtime')` 作为默认值——它写入的是**服务器本地时间且不带时区标识**，服务器换时区、容器时区与宿主不一致、夏令时切换，都会让历史数据无法解释。正确写法：

```sql
created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))   -- UTC，带毫秒与 Z 标识
```

【禁止】同一个库里混用多种时间格式——排序与比较会静默出错（`'2026-09-02'` 与 `'2026/09/02'` 的字符串序完全不同）。

### 2.4 约束

```sql
CREATE TABLE task (
  id          INTEGER PRIMARY KEY,
  owner_id    TEXT    NOT NULL,
  title       TEXT    NOT NULL,
  status      TEXT    NOT NULL DEFAULT 'pending'
              CHECK (status IN ('pending','running','done','failed')),   -- 枚举用 CHECK 兜住
  priority    INTEGER NOT NULL DEFAULT 0 CHECK (priority BETWEEN 0 AND 9),
  amount_cent INTEGER NOT NULL DEFAULT 0 CHECK (amount_cent >= 0),
  is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0,1)),
  created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

  UNIQUE (owner_id, title),
  FOREIGN KEY (owner_id) REFERENCES app_user(id) ON DELETE CASCADE
) STRICT;
```

【必须】每一列都显式写 `NOT NULL` 或明确允许 NULL；**不要靠默认（默认允许 NULL）**。
【必须】枚举列必须有 `CHECK` 约束列全取值——SQLite 没有 ENUM 类型，`CHECK` 是唯一防线。
【必须】用到外键就必须在连接上开 `PRAGMA foreign_keys=ON`（§1.2），否则约束不生效。
【必须】`updated_at` 靠**触发器**或应用代码维护——SQLite **没有** MySQL 的 `ON UPDATE CURRENT_TIMESTAMP`：

```sql
CREATE TRIGGER trg_task_updated_at
AFTER UPDATE ON task
FOR EACH ROW
BEGIN
  UPDATE task SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = OLD.id;
END;
```

【建议】优先在应用层维护 `updated_at`（显式、可测、无隐藏副作用），触发器仅用于无法覆盖所有写入路径的场景。

### 2.5 JSON 列

SQLite 内置 JSON 函数（json1，3.38+ 起默认编译进核心）：

```sql
CREATE TABLE event (
  id      INTEGER PRIMARY KEY,
  payload TEXT NOT NULL CHECK (json_valid(payload)),        -- 保证存进去的是合法 JSON
  -- 生成列：把 JSON 里的高频查询字段"提"出来并建索引
  kind    TEXT GENERATED ALWAYS AS (json_extract(payload,'$.kind')) VIRTUAL
) STRICT;

CREATE INDEX idx_event_kind ON event(kind);
```

【必须】JSON 列加 `CHECK (json_valid(...))`。
【必须】**需要过滤/排序/聚合的字段必须提取成独立列或生成列并建索引**，不要在 `WHERE` 里直接 `json_extract`（无法走索引，全表扫描）。
【禁止】把 JSON 当作规避建表的手段——「先全塞 JSON 以后再说」的结果是无法查询、无法约束、无法迁移。

### 2.6 索引

```sql
-- 复合索引：列顺序按「等值列 → 范围列 → 排序列」
CREATE INDEX idx_task_owner_status_created ON task(owner_id, status, created_at DESC);

-- 部分索引：只索引热数据，体积小、维护成本低（SQLite 特有优势，善用）
CREATE INDEX idx_task_pending ON task(created_at) WHERE status = 'pending';

-- 表达式索引：查询里怎么写，索引就怎么建
CREATE INDEX idx_task_title_lower ON task(lower(title));

-- 覆盖索引：查询涉及的列都在索引里，无需回表
CREATE INDEX idx_task_cover ON task(owner_id, status, title);
```

【必须】所有外键列、所有高频过滤列建索引。
【必须】在迁移文件的注释中写明**该索引专供哪个查询**，否则后人不敢删。
【必须】用 `EXPLAIN QUERY PLAN` 确认索引确实被用上：

```sql
EXPLAIN QUERY PLAN SELECT * FROM task WHERE owner_id=? AND status=? ORDER BY created_at DESC;
-- 期望看到 "USING INDEX idx_task_owner_status_created"
-- 看到 "SCAN task" 就是全表扫描，索引没生效
```

【应当】善用**部分索引**（`WHERE` 条件的索引）——这是 SQLite 相对 MySQL 的明显优势，「只有 pending 状态需要频繁查」的场景下索引体积可能只有百分之一。
【必须】数据量或分布显著变化后跑一次 `ANALYZE`（更新统计信息，让查询规划器选对索引）；【建议】关闭前执行 `PRAGMA optimize`。

### 2.7 命名规范

| 对象 | 规则 | 示例 |
|---|---|---|
| 表 | 蛇形**单数**或复数（全项目统一），无前缀或统一前缀 | `user_note` |
| 列 | 蛇形；布尔 `is_/has_`；时间 `_at`；金额带单位 `_cent` | `is_archived`、`created_at`、`amount_cent` |
| 主键 | 固定 `id` | `id` |
| 外键 | `<引用表单数>_id` | `owner_id` |
| 索引 | `idx_<表>_<列组合>` | `idx_task_owner_status` |
| 唯一约束 | `uq_<表>_<语义>` | `uq_task_owner_title` |
| 触发器 | `trg_<表>_<动作>` | `trg_task_updated_at` |

【必须】所有表与关键列**必须有中文注释**。SQLite 不支持 `COMMENT` 语法，用 SQL 行内注释代替，且**注释必须与迁移文件一起维护**：

```sql
CREATE TABLE task (                                     -- 任务表：记录用户提交的异步任务
  id       INTEGER PRIMARY KEY,                         -- 任务自增主键
  status   TEXT NOT NULL DEFAULT 'pending'              -- 状态：pending=待执行/running=执行中/done=成功/failed=失败
           CHECK (status IN ('pending','running','done','failed'))
) STRICT;
```

---

## 3. 表结构更新（迁移）

### 3.1 唯一入口

【必须】**所有 DDL 只能通过迁移文件执行**。应用代码里出现 `CREATE TABLE` / `ALTER TABLE` / `DROP` 一律打回。

理由：表结构一旦取决于「哪段代码先跑到」，就没有任何人能说清库里现在是什么结构，也无法保证两个环境一致。

### 3.2 迁移机制三选一

| 方案 | 适用 | 说明 |
|---|---|---|
| **A. 顺序 SQL 文件 + 版本表** | 轻量应用、无 ORM | 最简单，无额外依赖，见 3.3 |
| **B. Alembic** | 已用 SQLAlchemy 的服务 | 与主库迁移体系统一；注意 SQLite 的 `batch_alter_table` |
| **C. `PRAGMA user_version`** | 嵌入式、单文件分发 | 版本号存在库头，零额外表；不记录执行历史 |

【必须】全项目**只用一种**，写进本规范并在 README 中说明。

### 3.3 方案 A：顺序 SQL 文件（推荐给轻量应用）

```
migrations/
├── 0001_init.sql
├── 0002_create_task.sql
├── 0003_add_task_priority.sql
└── 0004_backfill_task_status.sql
```

```python
def run_migrations() -> None:
    """按文件名顺序执行尚未应用的迁移，记录到 schema_migrations 表。

    幂等：已执行的文件跳过；每个文件在**独立事务**内执行——SQLite 的 DDL 支持事务，
    迁移中途失败会整体回滚，不会留下"改了一半"的结构（这是相对 MySQL 的优势）。
    """
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
              filename   TEXT PRIMARY KEY,
              checksum   TEXT NOT NULL,
              applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )
        """)
        applied = {r["filename"]: r["checksum"]
                   for r in conn.execute("SELECT filename, checksum FROM schema_migrations")}

        for f in files:
            sql = f.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            if f.name in applied:
                # 已执行的迁移内容被改动 → 立即失败。历史迁移必须不可变，
                # 否则新环境与老环境的结构会静默分叉（老环境不会重跑改动后的文件）。
                if applied[f.name] != checksum:
                    raise RuntimeError(f"已应用的迁移被修改：{f.name}（历史迁移不可变）")
                continue
            logger.info("应用迁移 %s", f.name)
            conn.execute("BEGIN")
            try:
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_migrations(filename, checksum) VALUES(?,?)",
                    (f.name, checksum),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
```

【必须】记录 **checksum** 并在每次启动时校验——这是「已发布的迁移不可修改」这条纪律唯一可自动强制的手段。

### 3.4 迁移铁律

| # | 规则 | 违反后果 |
|---|---|---|
| 1 | **已发布的迁移文件永不修改** | 老环境不会重跑，新老结构静默分叉 |
| 2 | 改错了 = **新增一个更大序号的修正迁移** | — |
| 3 | **一个迁移只做一件事**，文件名说清做了什么 | 失败时无法定位、无法部分回滚 |
| 4 | **DDL 放在事务里**（SQLite 支持事务 DDL） | 中途失败留下半成品结构 |
| 5 | **数据回填必须幂等**（带 `WHERE` 守卫） | 重跑产生重复数据 |
| 6 | **只加不减**：加表/加列/加索引 ✅；删列/改类型 ⚠️ 走 3.6 的安全流程 | 见 3.5 |
| 7 | 迁移中**不得 import 应用的 ORM 模型** | 模型随代码演进，历史迁移会失效 |
| 8 | 大表回填**分批**（每批 1000~5000 行） | 长事务阻塞所有写入 |

### 3.5 SQLite `ALTER TABLE` 的能力边界

SQLite 的 `ALTER TABLE` **只支持四种操作**：

| 操作 | 支持 | 版本要求 |
|---|---|---|
| `RENAME TO`（改表名） | ✅ | 全版本 |
| `ADD COLUMN`（加列） | ✅ | 全版本 |
| `RENAME COLUMN`（改列名） | ✅ | **3.25+** |
| `DROP COLUMN`（删列） | ✅ | **3.35+**，且有限制* |
| **改列类型 / 改约束 / 加删主键或外键 / 改列顺序** | ❌ | 必须走 3.6 的重建流程 |

\* `DROP COLUMN` 不能删除：主键列、`UNIQUE` 约束涉及的列、被索引引用的列、被 `CHECK`/生成列/视图/触发器引用的列。

【必须】`ADD COLUMN` 加非空列时**必须给常量默认值**（不能是 `CURRENT_TIMESTAMP` 之类的非常量表达式）：

```sql
-- ✅
ALTER TABLE task ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;

-- ❌ 非常量默认值会报错
ALTER TABLE task ADD COLUMN created_at TEXT NOT NULL DEFAULT (datetime('now'));

-- ✅ 正确做法：分两步——先加可空列，再回填，（如需）再走重建流程加约束
ALTER TABLE task ADD COLUMN created_at TEXT;
UPDATE task SET created_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE created_at IS NULL;
```

### 3.6 安全改表流程（官方推荐的 12 步法）

要改列类型、改约束、删除主键/外键、重排列顺序时，**唯一安全的做法是重建表**。必须严格按以下顺序：

```sql
-- ① 关闭外键（重建期间引用会临时失效；必须在事务外设置，PRAGMA 在事务内不生效）
PRAGMA foreign_keys = OFF;

BEGIN;

-- ② 建新表（用最终想要的结构，注意用临时名）
CREATE TABLE task_new (
  id          INTEGER PRIMARY KEY,
  owner_id    TEXT    NOT NULL,
  status      TEXT    NOT NULL DEFAULT 'pending'
              CHECK (status IN ('pending','running','done','failed','cancelled')),  -- 新增枚举值
  amount_cent INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT    NOT NULL
) STRICT;

-- ③ 迁数据（列名显式对应，禁止 SELECT *；类型/默认值在此处转换）
INSERT INTO task_new (id, owner_id, status, amount_cent, created_at)
SELECT id, owner_id, status, CAST(ROUND(amount * 100) AS INTEGER), created_at FROM task;

-- ④ 删旧表
DROP TABLE task;

-- ⑤ 改名
ALTER TABLE task_new RENAME TO task;

-- ⑥ 重建索引、触发器、视图（DROP TABLE 会一并删掉它们，必须显式重建）
CREATE INDEX idx_task_owner_status ON task(owner_id, status);

COMMIT;

-- ⑦ 校验外键完整性（重建期间可能产生悬空引用）
PRAGMA foreign_key_check;

-- ⑧ 恢复外键
PRAGMA foreign_keys = ON;
```

【必须】严格遵守的三点：
1. **`PRAGMA foreign_keys` 的开关必须在事务之外**——在事务内设置是无效的（静默不生效，这是最常见的错误）；
2. **`DROP TABLE` 会连带删除该表的索引、触发器**，重建流程里必须显式重建，漏建索引会让线上查询突然全表扫描；
3. **`COMMIT` 后必须跑 `PRAGMA foreign_key_check`**，确认没有产生悬空引用。

【必须】重建大表前评估耗时与磁盘空间（重建期间新旧两份数据同时存在，磁盘需求翻倍）。

【应当】使用 Alembic 时用 `batch_alter_table`，它会自动生成上述重建流程：

```python
def upgrade() -> None:
    """将 amount 由 REAL 改为 INTEGER 分单位（SQLite 需重建表，batch 模式自动处理）。"""
    with op.batch_alter_table("task", schema=None) as batch:
        batch.alter_column("amount_cent", existing_type=sa.REAL(), type_=sa.Integer(), nullable=False)
```

### 3.7 迁移测试

【必须】每个迁移配测试，至少覆盖：

```python
def test_migrations_apply_to_empty_db(tmp_path):
    """空库上顺序执行全部迁移应成功，且最终结构符合预期。"""
    ...
    assert _table_names(conn) >= {"task", "user_note", "schema_migrations"}


def test_migrations_are_idempotent(tmp_path):
    """重复执行 run_migrations 不产生任何变化（幂等）。"""
    run_migrations(); first = _schema_dump(conn)
    run_migrations(); assert _schema_dump(conn) == first


def test_applied_migration_is_immutable(tmp_path):
    """篡改已应用的迁移文件必须导致启动失败（历史迁移不可变）。"""
    ...
    with pytest.raises(RuntimeError, match="历史迁移不可变"):
        run_migrations()


def test_rebuild_migration_preserves_data(tmp_path):
    """重建表类迁移必须完整保留数据，且索引已重建。"""
    ...
    assert _index_names(conn, "task") == {"idx_task_owner_status"}
```

【必须】涉及**重建表**的迁移，测试必须断言：数据行数一致、关键字段值一致、**索引与触发器已重建**。

---

## 4. 读写规范

### 4.1 参数化（安全底线）

```python
# ✅
conn.execute("SELECT * FROM task WHERE owner_id = ? AND status = ?", (owner_id, status))

# ✅ 命名参数（参数多时可读性更好）
conn.execute("SELECT * FROM task WHERE owner_id = :owner AND status = :status",
             {"owner": owner_id, "status": status})

# ❌ 绝对禁止
conn.execute(f"SELECT * FROM task WHERE owner_id = '{owner_id}'")
```

【必须】所有值都走占位符。表名/列名无法参数化时，**必须走白名单校验**：

```python
_SORTABLE = {"created_at", "priority", "id"}      # 白名单是唯一安全做法

def build_order_by(field: str, desc: bool) -> str:
    """构造排序子句；字段名必须在白名单内，否则拒绝。"""
    if field not in _SORTABLE:
        raise ValueError(f"不允许的排序字段: {field}")
    return f"ORDER BY {field} {'DESC' if desc else 'ASC'}"
```

### 4.2 事务

【必须】事务要**短**：一次业务操作 = 一次完整读或写，做完立即提交。
【禁止】在事务中做网络调用、等待用户输入、执行耗时计算——SQLite 只有一个写者，长事务会阻塞全部写入（`database is locked` 的头号原因）。
【必须】写事务用 `BEGIN IMMEDIATE`（原因见 §1.3）。

```python
# ✅ 写操作
with transaction() as conn:
    conn.execute("UPDATE task SET status='done' WHERE id=?", (task_id,))

# ✅ 只读操作不需要显式事务
with get_conn() as conn:
    rows = conn.execute("SELECT ... LIMIT 100").fetchall()
```

### 4.3 批量写

```python
# ✅ 一个事务 + executemany，千条数据毫秒级
with transaction() as conn:
    conn.executemany("INSERT INTO task(owner_id, title) VALUES(?,?)", rows)

# ❌ 循环内逐条提交，慢 100 倍（每次 commit 都要 fsync）
for r in rows:
    with transaction() as conn:
        conn.execute("INSERT ...", r)
```

【必须】批量写用 `executemany` + 单事务。
【必须】超大批量（> 10 万行）**分批提交**（每批 5000~10000 行），避免单个事务把 WAL 撑到几 GB。

### 4.4 UPSERT 与 RETURNING

```sql
-- UPSERT（3.24+）：幂等写入的标准姿势
INSERT INTO cache(key, payload, expires_at) VALUES(?,?,?)
ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, expires_at=excluded.expires_at;

-- RETURNING（3.35+）：一次往返拿到写入结果，免去二次查询
INSERT INTO task(owner_id, title) VALUES(?,?) RETURNING id, created_at;
```

【应当】幂等写入优先用 `ON CONFLICT DO UPDATE`，而不是「先 SELECT 再决定 INSERT/UPDATE」——后者在并发下有竞态。

### 4.5 查询

【必须】列表查询**必带 `LIMIT`**（建议默认 ≤ 500）；无上限的 `SELECT *` 是页面变慢的首要原因。
【必须】**显式 `ORDER BY`**，且包含唯一列兜底（如 `ORDER BY created_at DESC, id DESC`），否则分页会出现重复/遗漏行。
【必须】只取需要的列，避免 `SELECT *`（也让覆盖索引可能生效）。
【应当】深翻页用**游标分页**（`WHERE id < ? ORDER BY id DESC LIMIT n`），不要 `OFFSET`——`OFFSET 10000` 需要真的扫过前 10000 行。

### 4.6 缓存表

```sql
CREATE TABLE cache_entry (
  key        TEXT PRIMARY KEY,
  payload    TEXT NOT NULL CHECK (json_valid(payload)),
  expires_at TEXT NOT NULL                       -- ISO-8601 UTC
) STRICT;

CREATE INDEX idx_cache_expires ON cache_entry(expires_at);
```

【必须】缓存表**必须带 `expires_at`**，读取时过期视同未命中，并有**定期清理任务**（见《FastAPI 通用规范》§19）：

```sql
DELETE FROM cache_entry WHERE expires_at < strftime('%Y-%m-%dT%H:%M:%fZ','now');
```

【必须】清理任务不存在的缓存表 = 无上限增长的定时炸弹。

---

## 5. 并发与锁

### 5.1 并发模型

SQLite 的并发模型必须理解清楚，否则所有优化都是盲目的：

| 模式 | 读 | 写 |
|---|---|---|
| **默认（DELETE/rollback journal）** | 读写互斥：写时所有读阻塞 | 单写者 |
| **WAL** | **读不阻塞写，写不阻塞读**（多读并发无上限） | **仍是单写者**：同一时刻只有一个写事务 |

【必须】结论只有一句：**WAL 解决的是读写互斥，不解决写并发。任何时刻只能有一个写事务。**

### 5.2 单写者约束的实践

【必须】应用内**不要自己开多个线程/进程持续写库**（例如「起个后台线程每秒刷状态」）。偶发的并发写会在 `busy_timeout` 窗口内自动排队，但持续高频写会退化成串行等待。

【必须】多进程/多实例部署时，**同一个库文件只能有一个进程负责写**；其余进程只读。做不到就换服务端数据库。

【必须】写操作集中到单一入口（一个 writer 模块 / 一个后台任务），便于排查与限流。

### 5.3 `database is locked` 排查顺序

```
1. 事务是否够短？（有没有在事务里做网络调用、等用户操作、跑大计算）
   → 90% 的情况在这里
2. 是否用了 BEGIN IMMEDIATE？（DEFERRED 的锁升级失败绕过 busy_timeout）
3. busy_timeout 是否设置且足够（≥5000）？
4. 是否有连接泄漏（长期持有未关闭的连接，占住锁）？
5. 是否有多个进程在写同一个库？
6. 是否在 WAL 模式？（默认 DELETE 模式下读也会阻塞写）
7. 库文件是否在网络文件系统上？（NFS/SMB → 立即迁走，锁不可靠）
```

【必须】排查按上述顺序做，**不要一上来就调大 `busy_timeout`**——那只是把「立刻报错」变成「卡 30 秒后报错」，掩盖真正的长事务问题。

### 5.4 WAL 的注意事项

- WAL 文件会增长，在 checkpoint 时收缩。长期持有的读事务会**阻止 checkpoint**，导致 WAL 无限增长——这是「库文件不大但 `-wal` 几个 GB」的原因。
- 【必须】不要长期持有连接不释放（尤其是开着的读事务）。
- 【应当】高写入场景下监控 `-wal` 文件大小；必要时手动 `PRAGMA wal_checkpoint(TRUNCATE)`。
- 【禁止】WAL 模式下把库文件放在网络文件系统上（WAL 依赖共享内存 `-shm`，跨主机不可用）。

---

## 6. 异步应用中的 SQLite

### 6.1 SQLite 是同步的

【必须】认清事实：SQLite 的 C 库是**同步阻塞**的，`aiosqlite` 只是把调用丢到线程池，**并没有真正的异步 IO**。

【必须】在 FastAPI 等异步框架中：
- 用 `aiosqlite` 或 SQLAlchemy 的 `sqlite+aiosqlite` 驱动（内部走线程池，不阻塞事件循环）；
- 或用同步 API + `asyncio.to_thread()` 显式卸载；
- **禁止**在 async 函数里直接调用同步 `sqlite3` 接口——一个慢查询会卡住整个事件循环（连锁后果见《FastAPI 通用规范》§10.1）。

```python
# ✅ 方式一：aiosqlite
async with aiosqlite.connect(settings.sqlite_path) as db:
    await db.execute("PRAGMA journal_mode=WAL")
    async with db.execute("SELECT ... LIMIT 100") as cur:
        rows = await cur.fetchall()

# ✅ 方式二：同步实现 + 线程卸载（复用已有同步代码时更省事）
rows = await asyncio.to_thread(_query_tasks_sync, owner_id)

# ❌ 直接在 async 里同步调用
async def handler():
    conn = sqlite3.connect(path)          # 阻塞事件循环
    return conn.execute("...").fetchall()
```

### 6.2 连接与线程

【必须】`check_same_thread=False` 允许跨线程使用连接，但**同一个连接不得被多个线程并发使用**（SQLite 连接对象不是线程安全的）。安全做法二选一：
- 每个线程/任务用自己的连接（推荐，配合 `NullPool`）；
- 用锁把连接串行化（简单但会成为瓶颈）。

【必须】写操作在异步应用中同样要**串行化**——建议用一个 `asyncio.Lock` 保护写路径，把「单写者」约束显式化，而不是靠 `busy_timeout` 碰运气。

---

## 7. 备份、恢复与维护

### 7.1 备份（唯一正确的方式）

【禁止】直接 `cp` / `rsync` 正在使用的库文件。WAL 模式下 `.db` 与 `-wal` 不同步，拷出来的库**可能损坏或丢数据**。

【必须】使用以下两种在线备份方式之一：

```python
# 方式一：sqlite3 备份 API（在线一致快照，不阻塞写入，支持进度回调）
def backup_database(dst: Path) -> None:
    """在线备份到 dst，不中断正在进行的读写。"""
    with get_conn() as src, sqlite3.connect(dst) as dst_conn:
        src.backup(dst_conn, pages=1000, progress=None, sleep=0.05)
```

```sql
-- 方式二：VACUUM INTO（3.27+），产出一个已整理压缩的副本
VACUUM INTO '/backup/app-20260902.db';
```

【必须】备份策略要明确：**频率、保留份数、存放位置（异地）、恢复演练周期**。没做过恢复演练的备份等于没有备份。
【必须】备份文件与库文件**不放同一块磁盘**。
【应当】备份后校验：`PRAGMA integrity_check` 返回 `ok` 才算成功。

### 7.2 恢复

【必须】恢复顺序固定：**停止应用 → 备份当前现场（哪怕它是坏的）→ 替换库文件（含清理 `-wal`/`-shm`）→ 校验完整性 → 启动应用**。

【必须】恢复前**先给当前库做一份现场快照**——恢复本身可能选错备份点，没有现场就无法回头。

### 7.3 维护

| 操作 | 时机 | 说明 |
|---|---|---|
| `PRAGMA integrity_check` | 定期 + 备份后 + 疑似损坏时 | 返回 `ok` 以外的内容即为损坏 |
| `PRAGMA foreign_key_check` | 重建表迁移之后 | 检查悬空引用 |
| `ANALYZE` | 数据量/分布显著变化后 | 更新统计信息，让规划器选对索引 |
| `PRAGMA optimize` | 【建议】每次关闭连接前 | 轻量版 ANALYZE，官方推荐做法 |
| `VACUUM` | 大量删除之后 | 回收空间、消除碎片；**会重写整库并需要等量磁盘空间，且期间锁库** |
| `PRAGMA wal_checkpoint(TRUNCATE)` | `-wal` 异常增长时 | 强制 checkpoint 并截断 WAL |

【必须】`VACUUM` 是**阻塞操作**，只能在维护窗口执行，禁止在请求路径或高峰期触发。
【应当】用 `auto_vacuum=INCREMENTAL` + 定期 `PRAGMA incremental_vacuum` 替代全量 `VACUUM`（需在建库时设置）。

### 7.4 容量监控

【必须】监控三项并设告警阈值：库文件大小、`-wal` 文件大小、单表行数增长速率。
【必须】异常增长的排查顺序：① 缓存表没清理；② 日志/事件表没有保留期；③ 大 BLOB 入库；④ 大量删除后未 `VACUUM`（空间不会自动归还）。

---

## 8. 安全规范

| 面 | 规范 |
|---|---|
| **SQL 注入** | 【必须】全部参数化；表名/列名走白名单（§4.1） |
| **敏感数据** | 【禁止】明文存储密码、token、密钥、身份证、银行卡号；个人信息最小必要 + 展示脱敏 |
| **文件权限** | 【必须】库文件权限 `0600`（仅属主可读写），所在目录 `0700` |
| **数据出域** | 【禁止】把库文件下载/传播到受控范围之外——等同于导出全量数据 |
| **加密** | 需要静态加密时用 SQLCipher 或系统盘加密；【禁止】自己实现字段级加密而不做密钥管理 |
| **备份安全** | 【必须】备份文件与库文件同等保护，异地存储同样受控 |
| **多租户** | 【必须】应用层按租户/用户过滤；SQLite 无行级安全策略，**隔离完全是应用的责任** |
| **注入面** | 【禁止】把用户输入拼进 `PRAGMA`、`ATTACH DATABASE` 等语句 |

---

## 9. 测试中的 SQLite

### 9.1 作为测试替身的价值与陷阱

用 SQLite 替代生产 MySQL/PostgreSQL 跑测试，**能让测试快一到两个数量级**（无网络往返），但必须清楚它测不到什么。

【必须】以下差异**测不出来**，相关逻辑必须有针对真实数据库的测试兜底：

| 差异 | SQLite 行为 | MySQL/PG 行为 | 影响 |
|---|---|---|---|
| 类型严格性 | 非 STRICT 表几乎不校验 | 严格校验并可能截断/报错 | 类型错误在 SQLite 上测不出来 |
| 字符串长度 | `VARCHAR(10)` 不限制 | 超长报错或截断 | 列宽不足类 bug 漏测 |
| 并发/锁 | 单写者 | 行级锁、间隙锁、死锁 | **死锁与锁竞争完全测不到** |
| 大小写敏感 | `LIKE` 对 ASCII 不敏感、`=` 敏感 | 取决于 collation | 匹配行为不同 |
| 日期函数 | `strftime`/`datetime` | `DATE_FORMAT`/`NOW()` | 方言 SQL 直接报错 |
| 自增行为 | rowid 复用（无 AUTOINCREMENT 时） | 单调递增 | 依赖 id 单调的逻辑会误判 |
| `ALTER TABLE` | 能力受限（§3.5） | 完整支持 | **迁移必须做方言分支** |
| 布尔 | 无原生类型 | 有 | 断言写法不同 |
| 并发隔离级别 | 串行化 | 可配置 | 隔离级别相关逻辑测不到 |

【必须】迁移文件中的方言特有 SQL 必须做分支，保证 SQLite 上的往返测试可跑：

```python
if op.get_bind().dialect.name == "mysql":
    op.execute("UPDATE ... SUBSTRING_INDEX(...)")     # 方言函数只在对应数据库执行
```

【必须】以下场景**禁止**只靠 SQLite 测试：并发/锁/死锁、大数据量性能、方言 SQL、字符集与排序规则、真实索引选择（`EXPLAIN` 结果完全不同）。

### 9.2 内存库

```python
@pytest.fixture
def db():
    """每个用例一个干净的内存库；迁移与生产走同一套代码。"""
    conn = sqlite3.connect(":memory:")
    for name, value in _PRAGMAS:
        if name != "journal_mode":      # 内存库不支持 WAL，跳过
            conn.execute(f"PRAGMA {name}={value}")
    run_migrations(conn)                # 关键：测试与生产共用同一份迁移
    yield conn
    conn.close()
```

【必须】测试库的结构**必须由同一套迁移建立**，禁止在 `conftest.py` 里手写建表 SQL——手写的那份必然与迁移漂移，测试通过而线上炸掉。
【必须】内存库不支持 WAL，PRAGMA 设置要跳过 `journal_mode`。
【应当】需要多连接共享内存库时用 `file:memdb?mode=memory&cache=shared&uri=true`。

---

## 10. 何时该换成服务端数据库

出现以下任一信号，说明已到 SQLite 边界，**评估迁移到 PostgreSQL / MySQL**，不要硬扛：

- [ ] 已确认事务都很短，仍频繁 `database is locked`（真实写并发超限）
- [ ] 需要多实例/多副本部署（横向扩展）
- [ ] 需要多个进程或后台任务**持续写入**
- [ ] 库容量在合理增长下仍将超出可接受范围（一般 > 数十 GB 就该考虑）
- [ ] 需要行级权限、复杂视图、物化视图、分区
- [ ] 需要跨服务共享同一份数据
- [ ] 需要真正的高可用（主从、故障转移）
- [ ] 需要复杂分析查询（窗口函数虽支持，但性能与并发不足）

【必须】迁移前把**方言差异**盘一遍（§9.1 的表），迁移不是换个连接串那么简单。
【建议】**先用 SQLite 起步通常是正确的**——绝大多数内部工具与中低流量应用一辈子到不了这个边界；过早上 PostgreSQL 带来的运维成本往往大于收益。

---

## 附录 A：建表模板

```sql
-- 0002_create_task.sql
-- 任务表：记录用户提交的异步任务及其执行状态
CREATE TABLE IF NOT EXISTS task (
  id           INTEGER PRIMARY KEY,                    -- 任务自增主键（rowid 别名）
  owner_id     TEXT    NOT NULL,                       -- 归属用户标识，所有查询按此过滤
  title        TEXT    NOT NULL,                       -- 任务标题
  status       TEXT    NOT NULL DEFAULT 'pending'      -- 状态：pending=待执行/running=执行中/done=成功/failed=失败
               CHECK (status IN ('pending','running','done','failed')),
  priority     INTEGER NOT NULL DEFAULT 0              -- 优先级 0~9，越大越优先
               CHECK (priority BETWEEN 0 AND 9),
  amount_cent  INTEGER NOT NULL DEFAULT 0              -- 金额，单位：分（禁止用 REAL 存金额）
               CHECK (amount_cent >= 0),
  is_archived  INTEGER NOT NULL DEFAULT 0              -- 是否归档：0=否 1=是
               CHECK (is_archived IN (0,1)),
  payload      TEXT    NOT NULL DEFAULT '{}'           -- 扩展参数 JSON
               CHECK (json_valid(payload)),
  created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),   -- 创建时间，ISO-8601 UTC
  updated_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),   -- 更新时间，由应用层维护
  deleted_at   TEXT,                                   -- 软删除时间；非空即已删除

  UNIQUE (owner_id, title)
) STRICT;

-- 专供「我的任务列表」：WHERE owner_id=? AND status=? ORDER BY created_at DESC
CREATE INDEX IF NOT EXISTS idx_task_owner_status_created ON task(owner_id, status, created_at DESC);

-- 部分索引：待执行队列扫描只关心 pending，索引体积仅为全量索引的几十分之一
CREATE INDEX IF NOT EXISTS idx_task_pending ON task(priority DESC, created_at) WHERE status = 'pending';
```

---

## 附录 B：发布前检查清单

**路径与初始化**
- [ ] 库文件路径来自配置，绝对路径，位于持久化目录
- [ ] 代码中无硬编码相对路径的 `connect()`
- [ ] `.gitignore` 排除 `*.db` / `*.sqlite*` / `*-wal` / `*-shm`，仓库中无库文件
- [ ] 库文件不在网络文件系统上
- [ ] 每个连接都设置了 PRAGMA 基线（WAL / foreign_keys / busy_timeout / synchronous）
- [ ] 初始化幂等，新库与老库走同一条代码路径

**数据结构**
- [ ] 建表带 `STRICT`（3.37+）；否则有 CHECK 兜底
- [ ] 无 `VARCHAR(n)` / `DECIMAL` / `DATETIME` 等无效类型名
- [ ] 金额用 INTEGER 最小单位，无 REAL 金额
- [ ] 时间统一 ISO-8601 UTC，无 `localtime` 默认值
- [ ] 枚举列有 CHECK 约束
- [ ] 每列显式 NOT NULL 或明确可空；表与关键列有中文注释
- [ ] 高频查询有对应索引，且 `EXPLAIN QUERY PLAN` 确认走到

**迁移**
- [ ] 应用代码里无 `CREATE/ALTER/DROP`
- [ ] 全部结构变更在 `migrations/`，按序号命名
- [ ] 已发布迁移未被修改（checksum 校验开启）
- [ ] 每个迁移在事务内执行；数据回填幂等
- [ ] 重建表类迁移：外键开关在事务外、索引触发器已重建、跑了 `foreign_key_check`
- [ ] 迁移有测试（空库应用 / 幂等 / 数据保留 / 索引重建）

**读写与并发**
- [ ] 全部 SQL 参数化；排序字段走白名单
- [ ] 写事务用 `BEGIN IMMEDIATE`；事务内无网络调用与用户等待
- [ ] 批量写用 `executemany` + 单事务，超大批量分批
- [ ] 列表查询有 LIMIT 与显式 ORDER BY（含唯一列兜底）
- [ ] 只有一个写入者；无自建的后台写线程
- [ ] 异步应用中未在 async 函数里直接调同步 sqlite3

**运维**
- [ ] 缓存/日志类表有 `expires_at` 与清理任务
- [ ] 备份走 backup API 或 `VACUUM INTO`，不 cp 活动库
- [ ] 备份异地存放，做过恢复演练
- [ ] 监控库大小、`-wal` 大小、表增长
- [ ] 库文件权限 0600
- [ ] 无敏感明文入库

---

## 附录 C：反模式清单

| # | 反模式 | 后果 | 正确做法 |
|---|---|---|---|
| 1 | 相对路径 / 代码目录 / `/tmp` 存库 | 换目录启动即换库；发布后数据清零 | 路径来自配置的绝对持久路径 |
| 2 | 库文件放 NFS/SMB | 锁不可靠，**静默数据损坏** | 本地磁盘 |
| 3 | 不开 `foreign_keys=ON` | 外键声明**完全不生效** | 每连接设置 PRAGMA |
| 4 | 不用 WAL | 读写互斥，一个慢查询阻塞全部写 | `journal_mode=WAL` |
| 5 | 默认 `DEFERRED` 事务写 | 锁升级失败绕过 busy_timeout，瞬间 locked | 写事务 `BEGIN IMMEDIATE` |
| 6 | `with sqlite3.connect(...)` 当连接管理 | 只提交不关闭 → 连接泄漏 | 显式 close 的上下文管理器 |
| 7 | 应用代码里 `CREATE TABLE IF NOT EXISTS` | 结构取决于"哪段代码先跑到" | 全部走迁移 |
| 8 | 修改已发布的迁移文件 | 新老环境结构静默分叉 | 新增修正迁移 + checksum 校验 |
| 9 | 新库走 init.sql、老库走迁移 | 两条路径长期不一致 | 库永远从空开始，只由迁移建立 |
| 10 | 重建表时在事务内设 `PRAGMA foreign_keys` | **静默不生效** | 开关必须在事务外 |
| 11 | 重建表后忘记重建索引 | 线上查询突然全表扫描 | `DROP TABLE` 会连带删索引，必须显式重建 |
| 12 | `VARCHAR(50)` / `DECIMAL(18,2)` | 长度精度**完全不生效**，制造虚假安全感 | 用五种存储类 + STRICT + CHECK |
| 13 | `REAL` 存金额 | 浮点误差累积 | INTEGER 最小单位 |
| 14 | `datetime('now','localtime')` 默认值 | 服务器换时区后历史数据无法解释 | ISO-8601 UTC |
| 15 | 混用多种日期格式 | 排序比较**静默出错** | 全库统一一种 |
| 16 | 在 `WHERE` 里 `json_extract` 过滤 | 无法走索引，全表扫描 | 提取成生成列并建索引 |
| 17 | 长事务（含网络调用/等用户） | 阻塞全部写入 → `database is locked` | 事务即开即关 |
| 18 | 循环内逐条 commit | 慢 100 倍（每次 fsync） | executemany + 单事务 |
| 19 | 自开后台线程持续写 | 违反单写者，锁竞争 | 写操作集中到单一入口 |
| 20 | 多进程写同一个库 | 锁竞争、性能崩塌 | 单写者或换服务端数据库 |
| 21 | async 函数里直接调同步 sqlite3 | 阻塞事件循环，连锁故障 | aiosqlite 或 `to_thread` |
| 22 | 长期持有连接不释放 | 阻止 WAL checkpoint，`-wal` 涨到几 GB | 用完即关 |
| 23 | `cp` 活动中的库文件 | 备份损坏或丢数据 | backup API / `VACUUM INTO` |
| 24 | 缓存表无过期无清理 | 无上限增长的定时炸弹 | `expires_at` + 定时清理 |
| 25 | 大文件/大 BLOB 入库 | 库膨胀、备份变慢 | 对象存储，库里存 key |
| 26 | 一上来就调大 `busy_timeout` | 把"立刻报错"变成"卡 30 秒后报错" | 先查长事务（90% 的原因） |
| 27 | conftest 手写建表 SQL | 与迁移漂移，测试绿而线上炸 | 测试库也由迁移建立 |
| 28 | 只靠 SQLite 测并发/方言/性能 | 死锁与方言问题完全测不到 | 关键路径补真实数据库测试 |
| 29 | 把它当任务队列用 | 高频写入 + 轮询打爆单写者 | Redis / MQ |
| 30 | 大量删除后不 `VACUUM` | 空间不归还，文件只涨不落 | 维护窗口执行或用 incremental_vacuum |

---

## 附录 D：故障速查表

| 现象 | 最可能原因 | 处理 |
|---|---|---|
| `database is locked` | 长事务（90%）；或 DEFERRED 锁升级失败 | 按 §5.3 顺序排查，先看事务长度 |
| `database table is locked` | 同一连接内嵌套操作同一张表 | 拆开操作，不要在遍历游标时写同表 |
| `unable to open database file` | 目录不存在 / 权限不足 / 路径错误 | `mkdir -p` + 检查权限与绝对路径 |
| 发布后数据全没了 | 库文件在代码目录或镜像层 | 改到持久卷；历史数据无法找回 |
| 外键约束没生效 | 没开 `PRAGMA foreign_keys=ON` | 每连接设置 |
| 存进去的类型不对 | 非 STRICT 表的动态类型 | 改用 STRICT 表 + CHECK |
| 日期排序错乱 | 混用日期格式 | 统一 ISO-8601 UTC 并回填 |
| `-wal` 文件几个 GB | 长期读事务阻止 checkpoint | 释放长连接；`wal_checkpoint(TRUNCATE)` |
| 删了很多数据但文件没变小 | SQLite 不自动归还空间 | 维护窗口 `VACUUM` 或增量 vacuum |
| 查询突然变慢 | 缺索引 / 统计信息过期 / 重建表漏建索引 | `EXPLAIN QUERY PLAN` + `ANALYZE` |
| `malformed database schema` / 损坏 | 网络文件系统 / 非法拷贝 / 磁盘故障 | `integrity_check` 确认，从备份恢复 |
| 迁移在 SQLite 上失败但 MySQL 正常 | 方言 SQL 或 ALTER 能力差异 | 加方言分支（§9.1） |
| 本地有数据线上没有 | 本地库与线上库本就是两个库 | 初始数据写进迁移的 INSERT |

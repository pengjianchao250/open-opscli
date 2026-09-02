# FastAPI 后端开发通用规范

> **文档性质**：团队级强制规范，适用于所有基于 FastAPI 的后端服务（新项目直接采纳，存量项目增量收敛）。
> **约束等级**：`【必须】` 违反即评审不通过 · `【应当】` 需在 PR 中说明理由才可豁免 · `【建议】` 推荐做法。
> **维护方式**：任何条目的修改需经团队评审；因线上事故新增的条目须在条目后附「事故背景」。

---

## 目录

- [0. 总则](#0-总则)
- [1. 技术栈基线](#1-技术栈基线)
- [2. 工程目录结构](#2-工程目录结构)
- [3. 分层架构与职责边界](#3-分层架构与职责边界)
- [4. 命名规范](#4-命名规范)
- [5. API 设计规范](#5-api-设计规范)
- [6. 数据模型与数据库规范](#6-数据模型与数据库规范)
- [7. 数据表更新规范（迁移）](#7-数据表更新规范迁移)
- [8. 配置与环境变量规范](#8-配置与环境变量规范)
- [9. 依赖管理规范](#9-依赖管理规范)
- [10. 异步与并发规范](#10-异步与并发规范)
- [11. 错误处理与异常体系](#11-错误处理与异常体系)
- [12. 日志与可观测性](#12-日志与可观测性)
- [13. 安全规范](#13-安全规范)
- [14. 性能规范](#14-性能规范)
- [15. 测试规范](#15-测试规范)
- [16. 代码审查与提交规范](#16-代码审查与提交规范)
- [17. 发布与回滚规范](#17-发布与回滚规范)
- [18. 协作与执行纪律](#18-协作与执行纪律)
- [19. 定时任务与调度规范（APScheduler）](#19-定时任务与调度规范apscheduler)
- [附录 A：标准代码模板](#附录-a标准代码模板)
- [附录 B：新功能开发 Checklist](#附录-b新功能开发-checklist)
- [附录 C：反模式清单](#附录-c反模式清单)
- [附录 D：红线速查表](#附录-d红线速查表)

---

## 0. 总则

### 0.1 六条基本原则

1. **单一事实来源**：同一业务口径（枚举、过滤条件、计算规则）在代码中只能有一处定义，其余引用它。
2. **显式优于隐式**：类型标注、响应模型、事务边界、超时时间一律显式声明，不依赖框架默认值。
3. **变更可回滚**：任何数据结构变更、任何新特性上线，都必须有明确的回滚路径（迁移 `downgrade`、功能开关）。
4. **失败可观测**：任何失败路径都必须留下可定位的痕迹（日志 / 指标 / 落库），禁止静默吞异常。
5. **边界不越权**：分层依赖单向、模块只改自己职责内的东西、任务范围不擅自扩大。
6. **验证后再声明完成**：没有跑过测试、没有核对实际产出，不得声称任务完成。

### 0.2 本规范的适用边界

- 适用：HTTP API 服务、内部微服务、任务调度服务、流式（SSE/WebSocket）服务。
- 不适用：一次性脚本、POC 原型（但一旦进入主干代码库即适用）。

---

## 1. 技术栈基线

### 1.1 统一选型

| 层 | 选型 | 说明 |
|----|------|------|
| Web 框架 | **FastAPI** | 统一入口，不混用 Flask/Django |
| ASGI 服务器 | **uvicorn[standard]** | 生产可加 gunicorn worker 管理 |
| 数据校验 | **Pydantic v2** | 禁止 v1 写法（`@validator`、`.dict()`、`Config` 内部类） |
| ORM | **SQLAlchemy 2.0 异步风格** | `Mapped` / `mapped_column` / `select()`，禁止 1.x `Query` API |
| 迁移 | **Alembic** | 唯一 DDL 入口 |
| 配置 | **pydantic-settings** | 唯一配置入口 |
| 测试 | **pytest + pytest-asyncio + httpx.AsyncClient** | `asyncio_mode=auto` |
| 依赖管理 | requirements.txt / pyproject + lock | 二选一，全项目统一 |

### 1.2 版本策略

- 【必须】核心框架（FastAPI、SQLAlchemy、Alembic、Pydantic、uvicorn）**钉死精确版本**。
- 【必须】工具库使用 `>=` 时，若存在已知的上游冲突，必须同时钉上下界并在注释中写明冲突来源：
  ```
  # 须 >=45.0.1 以满足 X 的传递依赖；<46 守住 Y 的上界
  cryptography>=45.0.1,<46
  ```
- 【应当】升级核心框架必须单独一个 PR，附全量回归结果。

### 1.3 Python 版本

- 【必须】统一到团队约定的 Python 版本（建议 3.11+，可用 `X | None`、`dict[str, Any]` 等现代语法）。
- 【必须】所有模块首行 `from __future__ import annotations`（延迟注解求值，避免循环导入与运行时开销）。

### 1.4 框架/SDK 原生能力优先

【必须】任何涉及**技术方案选型或架构调整**的改动，动手前先查阅所依赖框架/SDK 的官方文档与源码，确认是否已原生提供该能力。

【必须】框架已提供官方方案的，**优先采用原生方案**，禁止自行造轮子重复实现。

【必须】确认框架不支持、或原生方案无法满足明确需求时，才允许自定义实现，并在 PR 说明中写明「**已确认 X 不支持**」的查证结论与查证位置（文档链接 / 源码路径 / 版本号）。

常见重复造轮子清单（发现即打回）：

| 想做的事 | 框架原生方案 | 别自己写 |
|---|---|---|
| 请求级依赖（DB session、当前用户） | FastAPI `Depends` | 全局变量、手工传参穿透多层 |
| 请求后台任务 | FastAPI `BackgroundTasks` | 裸 `create_task` |
| 应用启停钩子 | `lifespan` 上下文管理器 | `@app.on_event`（已废弃） |
| 参数校验与类型转换 | Pydantic 校验器 / `Annotated` | 手写 `if not isinstance(...)` |
| 序列化控制 | `model_config` / `field_serializer` | 手工拼 dict |
| 关系预加载 | `selectinload` / `joinedload` | 循环里逐条查 |
| 数据库事件钩子 | SQLAlchemy `event.listens_for` | 在每个 service 里重复调用 |
| 迁移分叉收敛 | `alembic merge` | 手改 `down_revision` |
| 连接池管理 | SQLAlchemy Pool | 自建连接缓存 |
| 限流/重试/熔断 | 成熟中间件或库 | 自研计数器 |

**背景**：自研实现往往只覆盖了 happy path，缺少框架已处理的并发、异常传播、资源释放、取消语义等边界，这类缺陷通常在生产才暴露。


---

## 2. 工程目录结构

### 2.1 标准骨架（中小型服务）

```
project_root/
├── app/                          # 应用包（包名可为业务名，全项目统一）
│   ├── main.py                   # 应用装配：中间件、异常处理器、路由注册、lifespan
│   ├── config.py                 # Settings 单例（唯一配置入口）
│   ├── database.py               # 引擎、sessionmaker、get_db 依赖
│   ├── core/                     # 横切基础设施
│   │   ├── auth.py               #   认证/鉴权依赖
│   │   ├── deps.py               #   依赖注入统一出口
│   │   ├── response.py           #   统一响应信封
│   │   ├── exceptions.py         #   业务异常体系
│   │   ├── logging.py            #   日志配置
│   │   ├── pagination.py         #   分页工具
│   │   └── security.py           #   加解密、脱敏、限流
│   ├── models/                   # ORM 模型：一表一文件
│   │   ├── base.py               #   DeclarativeBase + 公共 Mixin
│   │   ├── __init__.py           #   聚合导出（唯一导出口）
│   │   └── user.py  order.py ...
│   ├── schemas/                  # Pydantic 出入参模型
│   │   └── user.py  order.py ...
│   ├── api/
│   │   ├── v1/                   # 对外接口（/api/v1）
│   │   │   ├── __init__.py       #   本版本 router 汇总
│   │   │   └── users.py  orders.py ...
│   │   └── internal/             # 内部接口（/internal），独立鉴权
│   ├── services/                 # 业务服务层
│   │   └── user_service.py ...
│   ├── repositories/             # 【可选】数据访问层，复杂查询下沉
│   ├── tasks/                    # 后台任务 / 定时任务
│   └── clients/                  # 外部系统客户端（HTTP/MQ/第三方 SDK）
├── migrations/                   # Alembic
│   ├── env.py
│   └── versions/
├── tests/
│   ├── conftest.py
│   ├── unit/
│   └── integration/
├── scripts/                      # 运维脚本、数据修复脚本
├── docs/                         # 文档（含 API 契约产物）
├── alembic.ini  pytest.ini  pyproject.toml
├── .env  .env.example
└── README.md
```

### 2.2 大型服务：按领域切分

单个 `services/` 或 `models/` 超过 **30 个文件**时，【应当】升级为领域包：

```
app/
├── domains/
│   ├── order/
│   │   ├── models.py|models/    # 领域内可再拆
│   │   ├── schemas.py
│   │   ├── service.py
│   │   ├── repository.py
│   │   └── router.py
│   └── payment/ ...
└── core/                         # 跨领域共享
```

【必须】两种风格**不得在同一项目内混用**。

### 2.3 文件放置决策表

| 要写的东西 | 放哪里 | 禁止 |
|---|---|---|
| 一张新表的 ORM | `models/<单数蛇形>.py` + `__init__.py` 导出 | 建 `models.py` 聚合文件、往已有模型文件里塞第二个表 |
| 接口出入参 | `schemas/<资源>.py` | 在路由文件里内联定义对外 Schema |
| 对外 HTTP 路由 | `api/v1/<资源复数>.py` | 内部接口混进 v1 |
| 内部服务间接口 | `api/internal/<模块>.py` | 走 `/api/v1` 且不加内部鉴权 |
| 可复用业务逻辑 | `services/<领域>.py` | 200 行业务逻辑写在路由函数里 |
| 复杂查询组装 | `repositories/` 或 service 内私有函数 | 在路由里手写多表 join |
| 鉴权/信封/加解密 | `core/` | 在多个路由各拷一份 |
| 外部系统调用 | `clients/` | 在 service 里直接 `httpx.get(...)` |
| 一次性数据修复 | `scripts/` | 写成迁移里的 DML |
| DDL 变更 | `migrations/versions/` | 手工执行 SQL |

### 2.4 单文件体量红线

| 对象 | 建议上限 | 超出处理 |
|---|---|---|
| 路由文件 | 500 行 | 按子资源拆分（`orders.py` → `orders.py` + `order_items.py`） |
| 服务文件 | 800 行 | 升级为包，按用例拆模块 |
| 单个函数 | 80 行 | 抽私有辅助函数 |
| 路由函数体 | 40 行 | 逻辑下沉到 service |

---

## 3. 分层架构与职责边界

### 3.1 依赖方向（严格单向）

```
        api/          →  schemas/
         ↓
      services/       →  core/   （横切，任意层可依赖）
         ↓
   repositories/
         ↓
       models/
```

【必须】遵守：
- `services/` **不得** import `api/`；
- `models/` **不得** import `services/`；
- `core/` **不得** import 任何业务层（`services`/`api`/`repositories`）；
- 跨领域调用只能通过 service 的公开函数，不得直接操作对方的 model。

### 3.2 各层职责

| 层 | 只做 | 绝不做 |
|---|---|---|
| **api/** | 参数校验、鉴权、归属校验、调 service、组装响应、控制事务提交 | 写业务规则、拼复杂 SQL、直接操作 ORM 关系 |
| **schemas/** | 出入参结构、字段校验、序列化规则 | 含业务逻辑、访问数据库 |
| **services/** | 业务规则、编排多个 repository/client、领域校验 | 感知 HTTP（`Request`/`HTTPException`/状态码）、自行 commit |
| **repositories/** | 查询组装、批量读写 | 业务判断 |
| **models/** | 表结构、字段约束、领域常量、简单派生属性 | 查询逻辑、跨表编排 |
| **core/** | 鉴权、信封、异常、日志、限流、加解密 | 业务规则 |

### 3.3 事务边界（最易出错，必须统一）

【必须】**服务层只 `flush` 不 `commit`，事务边界由调用方（API handler / 任务入口）持有。**

```python
# services/order_service.py —— 正确
async def create_order(db: AsyncSession, payload: OrderCreate) -> Order:
    """创建订单。

    事务约定：本模块只 flush 不 commit，事务边界由调用方负责。
    """
    order = Order(...)
    db.add(order)
    await db.flush()          # 拿自增 id，不提交
    await _create_items(db, order.id, payload.items)
    return order


# api/v1/orders.py —— 由 handler 收口
@router.post("", response_model=OrderOut, status_code=201)
async def create_order_api(payload: OrderCreate, db: AsyncSession = Depends(get_db), ...):
    """创建订单。"""
    order = await create_order(db, payload)
    await db.commit()         # 唯一提交点
    return _to_out(order)
```

【必须】每个新增服务函数在 docstring 中声明事务约定。
【必须】一个请求内的写操作**只有一个提交点**；出现多次 `commit()` 必须在注释中说明为何不能合并（如需要中间可见性）。
【禁止】在 service 内 `try/except` 后自行 `rollback()` 再吞掉异常 —— 事务状态归调用方。

### 3.4 ORM 会话与惰性加载（高频 500 来源）

**背景（真实事故）**：`expire_on_commit=False` + 异步会话下，序列化阶段第一次触碰未预加载的关系，会抛 `MissingGreenlet` 直接 500。

【必须】响应体需要关系数据时，**查询阶段就显式预加载**：
```python
stmt = select(Order).options(selectinload(Order.items)).where(Order.id == oid)
```
【必须】写操作后若要返回关系集合，**重新查询**，不要读旧对象的关系属性（`expire_on_commit=False` 下集合不会刷新，会返回旧数据）。
【禁止】依赖 `response_model` 序列化阶段触发惰性加载。

### 3.5 单一事实来源

【必须】任何被两处以上引用的业务口径，提升为模块级常量，禁止散写字面量。

```python
# models/order.py
ORDER_STATUS_PENDING = "pending"
ORDER_STATUS_PAID = "paid"
ORDER_STATUS_CANCELLED = "cancelled"
ORDER_STATUSES = (ORDER_STATUS_PENDING, ORDER_STATUS_PAID, ORDER_STATUS_CANCELLED)

# 读侧统一过滤口径（全项目共用，避免散写字符串导致口径漂移）
ORDER_VISIBLE = Order.status != ORDER_STATUS_DELETED

# 字段中文注释与迁移共用同一份文案，避免两处漂移
ORDER_STATUS_COMMENT = "订单状态：pending=待支付 / paid=已支付 / cancelled=已取消"
```

**事故背景**：某接口硬编码了状态白名单元组，后续扩枚举时漏改，导致过滤条件失效**静默返回全量数据**，无任何报错。

【必须】不同语义的口径**分开定义**，禁止「顺手复用」——「可见性过滤」和「统计计数口径」即使当前条件相同，也必须是两个常量。

---

## 4. 命名规范

### 4.1 文件与模块

| 对象 | 规则 | 示例 |
|---|---|---|
| 模型文件 | 蛇形**单数** | `order.py`、`order_item.py` |
| Schema 文件 | 蛇形单数，与资源同名 | `order.py` |
| 路由文件 | 蛇形**复数** | `orders.py`、`order_items.py` |
| 服务文件 | 蛇形，领域名或动宾 | `order_service.py`、`payment_notifier.py` |
| 测试文件 | `test_<被测对象>.py` | `test_order_service.py` |
| 迁移文件 | `<revision_id>_<简述>.py` | `a1b2c3_add_order_status.py` |

### 4.2 代码符号

| 对象 | 规则 | 示例 |
|---|---|---|
| 类 | `PascalCase` | `OrderService`、`OrderOut` |
| 函数/变量 | `snake_case` | `create_order`、`total_amount` |
| 私有辅助 | 前缀 `_` | `_to_out`、`_get_owned_order` |
| 常量 | `UPPER_SNAKE` | `ORDER_STATUSES` |
| 模块级单例 | 小写实例名 | `redis_client`、`order_repo` |
| 布尔字段 | `is_/has_/allow_/enabled` 前缀 | `is_default`、`has_children` |
| 时间字段 | `_at` 后缀 | `created_at`、`deleted_at` |
| 数量字段 | `_count` 后缀 | `retry_count` |

### 4.3 Schema 命名约定

| 用途 | 后缀 | 示例 |
|---|---|---|
| 创建请求体 | `Create` | `OrderCreate` |
| 全量更新 | `Update` | `OrderUpdate` |
| 局部更新 | `Patch` | `OrderPatch` |
| 单条输出 | `Out` | `OrderOut` |
| 列表输出 | `List` | `OrderList` |
| 内部传递 | `DTO` | `OrderCalcDTO` |

【禁止】一个 Schema 同时当入参和出参用（字段可见性、必填性天然不同）。

### 4.4 数据表命名

- 表名：**蛇形复数**，可加业务前缀统一（如 `biz_orders`）；全项目前缀策略一致。
- 主键：`id`；外键：`<单数表名>_id`。
- 索引：`idx_<表简称>_<列组合>`；唯一约束：`uq_<表简称>_<语义>`；外键：`fk_<表>_<列>`。

### 4.5 注释语言

- 【必须】团队统一注释语言（本规范默认**中文**），**不得中英混杂**。
- 【必须】每个类、每个公开函数都有 docstring，说明**做什么 + 关键约定**（事务、幂等、副作用）。
- 【必须】关键行注释解释**「为什么这样做」**，而非复述代码在做什么。
- 【应当】踩坑修复处注释写明 **日期 + 现象 + 根因**：
  ```python
  # 2026-08-24 生产定位：事件循环被大对象序列化卡住数秒时，5s 建连预算被停顿吃光，
  # 产生假性建连超时（DB 本身健康）。放宽到 15s 属止血，根治须把同步重活挪出事件循环。
  ```

---

## 5. API 设计规范

### 5.1 路径与版本

- 【必须】对外接口统一前缀 `/api/v{n}`；内部接口统一前缀 `/internal`。
- 【必须】路径用**名词复数**表示资源，动作用 HTTP 方法表达：
  ```
  GET    /api/v1/orders               列表
  POST   /api/v1/orders               创建
  GET    /api/v1/orders/{order_id}    详情
  PUT    /api/v1/orders/{order_id}    全量更新
  PATCH  /api/v1/orders/{order_id}    局部更新
  DELETE /api/v1/orders/{order_id}    删除
  GET    /api/v1/orders/{order_id}/items   子资源
  ```
- 【应当】确实无法用资源表达的动作，用 `POST /orders/{id}:cancel` 或 `POST /orders/{id}/cancel`，全项目统一一种。
- 【禁止】路径中出现动词化的 CRUD（`/getOrderList`、`/order/delete`）。
- 【必须】破坏性变更（删字段、改语义、改必填性）**必须升版本**，不得原地改 v1。

### 5.2 路由声明模板

```python
router = APIRouter(prefix="/orders", tags=["订单"])


@router.get("", response_model=OrderList, summary="订单列表")
async def list_orders(
    status: str | None = Query(default=None, description="订单状态过滤，取值见 ORDER_STATUSES"),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数，上限 100"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrderList:
    """订单列表（按创建时间倒序），仅返回当前用户可见的订单。"""
```

【必须】：
1. **显式声明 `response_model`**。非 JSON 响应（SSE、文件下载、指标）用 `responses={...}` 标注媒体类型与语义。
2. **显式声明返回类型标注**。
3. **挂鉴权依赖**：对外 `get_current_user`，管理端 `get_current_admin_user`，内部 `verify_internal`。
4. 每个 `Query`/`Path`/`Body` 字段带 `description`（直接作为前端契约）。
5. 路由函数只做：校验 → 鉴权/归属 → 调 service → 提交事务 → 组装响应。

【禁止】：
- 路由函数里出现超过 3 行的业务判断；
- 用 `dict` / `Any` 作为 `response_model`；
- 在路由里直接写多表 join。

### 5.3 统一响应信封

【必须】全项目采用统一信封（二选一，不得混用）：

**方案 A（推荐，前端友好）**：
```json
{ "code": 200, "msg": "success", "data": { ... } }
```
- 成功 `code=200`；失败 `code` 为业务错误码（可与 HTTP 状态码一致，也可自定义业务码，全项目统一）。
- 通过中间件统一包裹，业务代码只 `return response_model`。

**方案 B（标准 HTTP 语义）**：直接返回资源体，错误用 RFC 7807 `application/problem+json`。

采用方案 A 时【必须】处理四类跳过包裹的响应：
1. `/openapi.json`、`/docs`、`/redoc`；
2. `304 Not Modified`；
3. **带 `Content-Disposition: attachment|inline` 的文件流**（包裹会改写字节，使 size / 校验和失效）；
4. 非 `application/json` 的响应（SSE、二进制）。

【必须】中间件对**已是信封形状的响应幂等放行**，避免重复包裹。
【必须】同步更新 OpenAPI schema，让文档展示真实的信封结构（否则前端按文档对不上）。

### 5.4 分页 / 排序 / 过滤

【必须】列表接口统一契约：

```python
class Page(BaseModel):
    """通用分页信封。"""
    items: list[Any]
    total: int
    page: int
    page_size: int
```

- 分页参数固定 `page`（从 1 开始）+ `page_size`（带 `le` 上限，建议 100）。
- 【应当】大数据量场景提供游标分页（`cursor` + `next_cursor`），深翻页禁止用 `OFFSET`。
- 排序参数固定 `sort_by` + `order`（`asc|desc`），**排序字段必须白名单校验**，禁止把用户输入直接拼进 `order_by`。
- 【必须】**显式 `ORDER BY`**，不依赖存储引擎默认返回顺序（否则分页会出现重复/遗漏行）。
- 过滤参数一律可选且有默认值；多值过滤用 `list[str] = Query(default=[])`。

### 5.5 HTTP 状态码

| 场景 | 状态码 |
|---|---|
| 查询/更新成功 | 200 |
| 创建成功 | 201（带 `Location` 或返回资源体） |
| 异步接受 | 202 |
| 删除成功且无返回体 | 204 |
| 参数校验失败 | 422（FastAPI 默认）或 400，全项目统一 |
| 未认证 | 401 |
| 已认证但无权限 | 403 |
| 资源不存在 | 404 |
| 状态冲突（重复创建、并发修改） | 409 |
| 限流 | 429 |
| 服务端异常 | 500 |
| 依赖不可用 | 503 |

【必须】**「无权限访问他人资源」与「资源不存在」对外统一返回 404**，不区分——否则 id 可被用于探测资源存在性。

### 5.6 归属与权限校验

【必须】所有涉及用户资源的接口，都要做归属校验，且统一收口成一个私有函数：

```python
async def _get_owned_order(db: AsyncSession, user: User, order_id: int) -> Order:
    """按 id + 归属取订单（软删除的不返回），不存在或不属于当前用户统一 404。"""
    row = (await db.execute(
        select(Order).where(
            Order.id == order_id,
            Order.user_id == user.id,
            ORDER_VISIBLE,
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    return row
```

【必须】**访问控制永远由归属字段（`user_id`/`tenant_id`）兜底**，不得依赖「id 不可猜」。
【禁止】用客户端可控字段（来源标识、来路参数）作为判权依据——这是典型提权漏洞。

### 5.7 对外 ID 暴露

【应当】对外**不直接暴露自增主键**（防枚举遍历、防泄漏业务体量）。三种方案任选其一，全项目统一：

| 方案 | 做法 | 适用 |
|---|---|---|
| UUID 主键 | 直接用 UUIDv7 作主键 | 新项目首选 |
| 业务编号 | 另建 `<资源>_no` 唯一列对外 | 需人工可读（订单号） |
| 可逆加密 | 出参加密、入参解密（确定性算法） | 存量自增主键改造 |

采用**可逆加密**方案时【必须】：
- 出入参统一用 Pydantic `Annotated` 类型自动加解密，禁止在每个接口里手工调用；
- **非 Pydantic 响应（裸 dict）必须手动加密回填**（最容易漏的点）；
- 流式事件、回调、外链中的同一标识也必须用密文；
- **解密失败降级为一个永不命中的哨兵值**（如 `-1`），让归属校验自然返回 404，**不得抛 422 泄漏 id 合法性**；
- 密钥独立配置，**禁止在 `.env` 中重复定义同名变量**（后值覆盖前值会导致密钥漂移，历史密文全部失效）。

### 5.8 幂等性

【必须】以下接口必须幂等：支付、扣款、发消息、创建外部订单、任何有外部副作用的 POST。

实现方式（二选一）：
- 客户端传 `Idempotency-Key` 请求头，服务端建唯一索引去重，重复请求返回首次结果；
- 服务端用业务唯一键（`user_id + biz_no`）建唯一约束，捕获 `IntegrityError` 返回已有记录。

【应当】非幂等接口在短时间窗口内做内容防抖（如 10s 内相同内容视为重复提交）。

### 5.9 API 文档同步

【必须】任何路由 / 请求体 / 响应体 / 状态码 / 参数变更，**在同一次提交中重新生成 OpenAPI 契约文件**：

```bash
python - <<'PY'
import json
from pathlib import Path
from app.main import app
Path("docs/openapi.json").write_text(
    json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
```

【禁止】手工编辑生成的 OpenAPI 文件。
【应当】CI 中加校验：重新生成后 `git diff --exit-code`，不一致即失败。

### 5.10 流式与长连接接口

- 【必须】SSE 用 `StreamingResponse(media_type="text/event-stream")`，并在 `responses={...}` 中标注。
- 【必须】设置 `Cache-Control: no-cache`、`X-Accel-Buffering: no`（避免网关缓冲导致「不流」）。
- 【必须】有**心跳帧**（如每 15s 一个注释帧），防止中间设备按空闲超时断连。
- 【必须】客户端断开时能感知并释放资源（检查 `await request.is_disconnected()` 或捕获 `ClientDisconnect`）。
- 【必须】评估网关缓冲区上限（常见 4KB/16KB），单帧过大会被截断。
- 【禁止】在流式响应中持有数据库会话跨越整个流生命周期。

---

## 6. 数据模型与数据库规范

> 本章面向服务端数据库（MySQL / PostgreSQL）。使用 **SQLite** 时（本地应用、边缘部署、测试替身）另见《SQLite 数据库使用通用规范》——它的类型系统、`ALTER TABLE` 能力、并发模型与本章差异很大，直接套用本章会踩坑。

### 6.1 声明基类与公共 Mixin

```python
# models/base.py
class Base(DeclarativeBase):
    """所有业务表的 ORM 基类；Alembic 仅对此 metadata 生成 DDL。"""


class TimestampMixin:
    """创建/更新时间通用列。"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, comment="记录创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False,
        comment="记录最后更新时间")
```

【必须】多库场景为每个库建独立基类，并在 Alembic 中只对**本服务拥有写权限的那个 metadata** 生成 DDL。

### 6.2 模型写法

```python
class Order(Base, TimestampMixin):
    """订单表。user_id 引用用户中心（跨库无 FK，业务层保证引用完整性）。"""

    __tablename__ = "orders"
    __table_args__ = (
        # 复合索引：专供「我的订单列表」WHERE user_id=? AND status=? ORDER BY created_at DESC 走索引
        Index("idx_orders_user_status_created", "user_id", "status", "created_at"),
        UniqueConstraint("user_id", "biz_no", name="uq_orders_user_biz_no"),
        {"comment": "订单主表"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="订单自增主键")
    user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="下单用户ID（引用用户中心，跨库无FK）")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False,
        default=ORDER_STATUS_PENDING,          # ORM 侧新建对象兜底
        server_default=ORDER_STATUS_PENDING,   # 存量行补值，使 NOT NULL 列可加到有数据的表
        index=True,
        comment=ORDER_STATUS_COMMENT,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, comment="订单金额，单位元，保留4位小数")
    extra: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, comment="扩展元数据JSON")
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="软删除时间；非空即已删除")
```

【必须】清单：

| # | 规则 |
|---|---|
| 1 | **一表一文件，一文件一模型类**；聚合导出只在 `models/__init__.py` |
| 2 | **每个字段必须有中文 `comment`**，说明含义 + 取值范围 / 枚举值；禁止英文或空串敷衍 |
| 3 | 枚举列的 comment 必须**列全所有取值及语义** |
| 4 | 新增 NOT NULL 列必须同时给 `default`（ORM 侧）与 `server_default`（存量行），缺一即失败 |
| 5 | **金额一律 `Numeric/DECIMAL`**，禁止 `Float`；单位在 comment 中写明 |
| 6 | 时间列统一 `DateTime`；**存储统一 UTC**，时区转换在展示层；跨时区业务显式用 `DateTime(timezone=True)` |
| 7 | 字符串列必须给明确长度，且长度与枚举/业务最长值核对（枚举扩值前先确认列宽够） |
| 8 | 布尔用 `Boolean`（或 `TINYINT`），不用 `String("Y"/"N")` |
| 9 | JSON 列用于**非查询条件**的扩展字段；需要过滤/排序的字段必须独立成列 |
| 10 | 跨库 / 跨服务引用**不加 FK**，在 comment 中写明「弱关联不加 FK，业务层保证完整性」 |
| 11 | 同库强关联可加 FK；加 FK 时必须明确 `ondelete` 行为并与 ORM `cascade` 保持一致 |
| 12 | 表级也要 `comment`（`__table_args__` 中 `{"comment": "..."}`） |

### 6.3 索引规范

- 【必须】所有外键列、所有高频过滤列建索引。
- 【必须】高频「过滤 + 排序」组合建**复合索引**，列顺序按「等值列 → 范围列 → 排序列」。
- 【必须】在 `__table_args__` 中用注释写明**该索引专供哪个查询**，否则后人不敢删。
- 【应当】上线前用 `EXPLAIN` 确认实际走了预期索引。
- **注意优化器陷阱**：MySQL 优化器可能选择 `index_merge` 而放弃复合索引，导致排序内存溢出或锁面放大（真实事故：`Out of sort memory` 与死锁均由此引发）。定位性能/锁问题时必须看**实际执行计划**，而非「我建了索引所以应该走索引」。
- 【禁止】为「可能有用」建索引；每个索引都有写放大成本。

### 6.4 软删除

- 【必须】全项目统一一种软删除表示：`deleted_at` 时间戳（推荐）或 `status='deleted'`，**不得混用**。
- 【必须】读侧统一用常量化的过滤条件（`ORDER_VISIBLE`），不散写。
- 【必须】软删除必须同步清理**运行时状态**（待处理队列项、定时任务、缓存），否则会留下「数据已删但后台仍在处理」的幽灵任务（真实事故）。
- 【必须】唯一约束需考虑软删除：`UNIQUE(user_id, biz_no)` 在软删后无法重建同名资源，需改为 `UNIQUE(user_id, biz_no, deleted_at)` 或物理清理策略。

### 6.5 连接池与超时

```python
engine = create_async_engine(
    settings.db_url,
    pool_size=20,            # 常驻连接数
    max_overflow=10,         # 溢出连接（用完即弃，复用需重建连）
    pool_recycle=3600,       # 小于 DB 的 wait_timeout
    pool_timeout=10,         # 等待空闲槽位上限，超时抛错而非无限挂起
    pool_pre_ping=True,      # 驱动兼容时开启；不兼容需注释说明原因
    connect_args={"connect_timeout": 15},
)
```

【必须】每个参数都要有注释说明取值依据；改动连接池参数需附压测或线上指标依据。
【必须】`pool_recycle` < 数据库侧 `wait_timeout`。
**背景**：`connect_timeout` 过小时，事件循环被同步重活卡顿会产生**假性建连超时**（数据库本身健康），排查方向会被完全带偏。

### 6.6 绝对禁止

- 【禁止】在生产/共享库上直接执行 `UPDATE` / `DELETE` / `DROP` 等破坏性 SQL 作为变更手段。
- 【禁止】手工 DDL 作为正式变更方案。
- 【禁止】`SELECT *` 进入 ORM 之外的裸 SQL；裸 SQL 必须参数化，禁止字符串拼接。
- 【禁止】在循环里执行数据库查询（N+1）。

---

## 7. 数据表更新规范（迁移）

### 7.1 唯一入口

【必须】**所有 DDL 变更只能通过 Alembic 迁移**，且迁移文件与对应的模型改动、测试在**同一个提交**中。

### 7.2 关于 `--autogenerate`

| 场景 | 规定 |
|---|---|
| **服务独占数据库** | 【应当】可用 `--autogenerate`，但**必须逐行审查**生成结果后再执行 |
| **多服务共享数据库** | 【禁止】使用 `--autogenerate` |

**为什么禁止**：autogenerate 对整库做 diff，会把不属于本服务 ORM 的表生成 `op.drop_table()`，一旦执行就是不可逆数据丢失；同时会产出大量无关的 `alter_column` 历史漂移。

共享库正确做法：
```bash
alembic revision -m "订单表新增状态列"    # 生成空白迁移，手写变更
```

即使独占库，也【必须】在 `env.py` 配置 `include_object` 过滤器，只处理本服务 metadata 管理的表：

```python
MANAGED_TABLES = set(target_metadata.tables.keys())

def include_object(object, name, type_, reflected, compare_to):
    """过滤 autogenerate 对比范围，只处理本服务管理的表。"""
    if type_ == "table":
        return name in MANAGED_TABLES
    return True
```

### 7.3 迁移文件规范

```python
"""订单表新增状态列与复合索引。

Revision ID: a1b2c3d4
Revises: 9f8e7d6c
Create Date: 2026-09-01
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4"
down_revision = "9f8e7d6c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """新增订单状态列并回填存量行，同时补建列表查询专用复合索引。"""
    op.add_column(
        "orders",
        sa.Column("status", sa.String(length=32), nullable=False,
                  server_default="pending",
                  comment="订单状态：pending=待支付 / paid=已支付 / cancelled=已取消"),
    )
    op.create_index("idx_orders_user_status_created", "orders",
                    ["user_id", "status", "created_at"])

    # 存量行回填：幂等守卫保证重复执行安全；方言分支保证 SQLite 往返测试可跑
    if op.get_bind().dialect.name == "mysql":
        op.execute("UPDATE orders SET status = 'paid' WHERE paid_at IS NOT NULL AND status = 'pending'")


def downgrade() -> None:
    """回滚复合索引与状态列。"""
    op.drop_index("idx_orders_user_status_created", table_name="orders")
    op.drop_column("orders", "status")
```

【必须】清单：

| # | 规则 |
|---|---|
| 1 | `upgrade()` 与 `downgrade()` **都必须实现且对称**，均带 docstring |
| 2 | 每个 `sa.Column` **必须带中文 comment**；建表时表级也加 comment |
| 3 | 模型与迁移的 comment **共用同一个常量**，避免两处漂移 |
| 4 | `down_revision` 必须接**目标主干分支当前的 head** |
| 5 | 数据回填 DML 必须**幂等**（带 `WHERE ... IS NULL` 等守卫），并注释说明回填口径与不回填时的兜底行为 |
| 6 | 含方言特有 SQL 时做方言分支（`op.get_bind().dialect.name`），保证 SQLite 往返测试可跑 |
| 7 | 一个迁移只做一件事；不要把「加列 + 改索引 + 迁数据 + 删表」塞进一个迁移 |
| 8 | 迁移中**不得 import 应用的 ORM 模型**（模型会随代码演进，历史迁移会因此失效）；需要操作数据时用 `sa.table()/sa.column()` 就地声明 |

### 7.4 大表在线变更

【必须】对行数超过百万的表做 DDL 前：
1. 评估是否可 `ALGORITHM=INPLACE, LOCK=NONE` 在线完成，并在迁移注释中记录实测结论；
2. 不可在线的（如缩短列宽、改字符集）改用**双写迁移**：新增列 → 双写 → 回填 → 切读 → 删旧列，分多次上线；
3. 大批量回填必须**分批**（每批 1000~5000 行 + sleep），禁止一条 `UPDATE` 扫全表。

### 7.5 迁移上线顺序（共享库最高频事故点）

```
功能分支开发与自测（本地库 / 独立 schema）
        ↓
   合入主干（release/main）
        ↓
在主干上执行 alembic upgrade head → 写共享库
        ↓
核对 alembic current + 实际字段/索引
        ↓
      共享环境 E2E
```

【禁止】从**尚未合入主干**的分支把迁移应用到共享/生产库。
**后果**：共享库 `alembic_version` 一旦记录了主干上不存在的 revision，主干上的**任何** alembic 命令都会硬失败（`Can't locate revision identified by ...`），`current`/`history`/`upgrade`/新增迁移全部阻断，直到那个分支合入为止。

【禁止】删除 `alembic_version` 中的「孤儿行」来消错——那会丢失「该迁移已在本环境执行」的事实，分支合入后再 upgrade 会重复执行已生效的 DDL。

**多 head 分叉**（两个分支从同一父节点各自派生迁移后先后合入）：
```bash
alembic merge --rev-id <merge_id> <head1> <head2>   # 官方 merge revision，零 DDL 零数据变更
```
【禁止】改某一支的 `down_revision` 做「线性化」——两支 DDL 都已执行、`alembic_version` 是两行并列记录，线性化会让该表退化成「祖先与后代同时在册」的不一致状态。

### 7.6 环境口径必须诚实

在本地库 / 结构镜像 / 独立 schema 上完成的验证，**只能**表述为「本地隔离验证通过」「合入前预验收通过」，**不得**表述为「测试环境验收通过」，更不得据此宣称目标环境已具备发布条件。

### 7.7 迁移必须配套测试

【应当】每个迁移配一个**纯桩测试**（不连库，可进快速档）：

```python
def _load_migration():
    """从文件路径加载迁移模块（迁移不是包内模块，需按路径加载）。"""
    spec = importlib.util.spec_from_file_location("m", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeOp:
    """记录迁移 DDL 调用序列，用于断言。"""
    def __init__(self): self.calls = []
    def add_column(self, table, col): self.calls.append(("add_column", table, col.name))
    def create_index(self, name, table, cols): self.calls.append(("create_index", name))
    def get_bind(self): return _FakeBind("mysql")
```

断言点：DDL 调用序列、`downgrade` 与 `upgrade` 对称、幂等守卫存在、方言分支正确。
【应当】结构性迁移另用 `sqlite+aiosqlite` 内存库做 `upgrade → downgrade → upgrade` 往返验证。

---

## 8. 配置与环境变量规范

### 8.1 唯一配置入口

【必须】所有配置集中在 `config.py` 的 `Settings`（pydantic-settings），全项目通过 `from app.config import settings` 访问。
【禁止】业务代码中出现 `os.getenv(...)`。

```python
class Settings(BaseSettings):
    """应用配置。敏感项无默认值，强制由环境提供。"""

    # 敏感项：禁止在源码中提供默认值
    db_password: str = Field(..., description="数据库密码")
    jwt_secret: str = Field(..., min_length=32, description="JWT 签名密钥，≥32字符")

    # 非敏感项：默认值仅供本地开发，生产必须通过环境覆盖
    db_pool_size: int = Field(default=20, ge=1, le=200, description="数据库连接池常驻连接数")

    # 功能开关：新特性默认关闭，灰度后再翻默认值
    new_pricing_enabled: bool = Field(default=False, description="新计价引擎开关；关闭时行为与上线前完全一致")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def db_url(self) -> str:
        """由字段拼装数据库连接串（密码经 quote 处理特殊字符）。"""
        return f"mysql+asyncmy://{self.db_user}:{quote(self.db_password)}@{self.db_host}:{self.db_port}/{self.db_name}"
```

【必须】：
- 敏感项用 `Field(...)` **强制必填，源码中无默认值**；
- 数值项带 `ge`/`le` 约束；
- 所有字段带中文 `description`；
- **连接串不直接配置**，由拆分字段动态拼装，密码经 `urllib.parse.quote` 处理特殊字符（含 `@`、`?` 的密码是经典踩坑点）；
- 密钥类配置**启动时校验强度**并告警（长度、是否为已知弱值）。

### 8.2 三处同步（强制）

新增 / 删除 / 重命名任何配置项，【必须】在**同一次提交**中同步：

| 文件 | 内容 |
|---|---|
| `config.py` | 字段定义 + 类型 + 约束 + 中文 description |
| `.env` | 实际值（不入库） |
| `.env.example` | 脱敏示例值 + **中文注释说明用途、取值范围、默认行为** |

`.env.example` 按功能分组，新项归入对应分组：
```
# ============ 数据库 ============
# 连接池常驻连接数（溢出连接用完即弃，调大常驻区可减少高并发下的频繁新建）
DB_POOL_SIZE=20
```

【禁止】`.env` 中同名变量重复定义（后值静默覆盖前值，是密钥漂移类事故的常见根因）。上线前用脚本校验重复键。

### 8.3 功能开关

【必须】新特性、有风险的性能优化、行为变更**一律带开关**：
- 布尔开关 `xxx_enabled: bool = False`，默认关，灰度后再翻默认值；
- 数值上限型开关用 `0` 表示完全关闭（如 `xxx_max_chars=0`）；
- **开关关闭时行为必须与上线前完全一致**，并在注释中写明这一承诺；
- 开关**不是永久的**：稳定 2 个迭代后应清理掉开关与旧分支代码。

### 8.4 环境隔离

【必须】本地开发若连接的是**共享**测试环境数据库，启动前必须通过环境变量**关闭所有后台任务**（定时调度、数据清扫、失败恢复、自动评审），否则本机进程会替共享环境跑定时任务、改共享数据。
【应当】为此提供一个 `.env.local` 模板，默认把这些开关全部置 false。

---

## 9. 依赖管理规范

- 【必须】代码中 import 的每个第三方包**必须显式声明**在依赖清单中，包括原本靠传递依赖引入的包（防上游移除后静默炸掉）。
- 【必须】声明时写明**为什么需要**及版本约束理由：
  ```
  # JWT 解签（HS256），认证中间件依赖
  PyJWT>=2.8.0
  # 须 >=45.0.1 满足 X 的传递依赖；<46 守住 Y 的上界
  cryptography>=45.0.1,<46
  ```
- 【必须】开发依赖与运行依赖分离（`requirements-dev.txt` 或 `[project.optional-dependencies]`）。
- 【必须】使用 lock 文件（`uv.lock` / `poetry.lock` / `pip-tools` 产物）保证可复现构建。
- 【应当】引入新依赖前评估：是否可用标准库实现、维护活跃度、许可证、传递依赖体积。
- 【禁止】直接依赖 git 分支或未发布版本进入生产。

---

## 10. 异步与并发规范

### 10.1 async 正确性

- 【必须】异步路由中**不得调用阻塞 IO**（`requests`、`time.sleep`、同步 DB 驱动、阻塞文件读写）。
- 【必须】不得不用同步库时，卸载到线程：
  ```python
  result = await asyncio.to_thread(blocking_call, arg)
  ```
- 【必须】纯 CPU 密集操作（大文本处理、加解密、序列化大对象）同样要卸载，并**带开关**保留回退路径。
- 【建议】完全同步的端点直接用 `def`（FastAPI 会自动放线程池），不要写成 `async def` 再在里面阻塞。

**背景（真实事故）**：单进程事件循环被同步重活卡住数秒，连锁导致**数据库假性建连超时**、SSE 心跳中断、健康检查失败——表象与根因相距极远，排查成本极高。

### 10.2 后台任务必须持有引用

【必须】fire-and-forget 任务用集合持有引用：

```python
_background_tasks: set[asyncio.Task] = set()

task = asyncio.create_task(coro())
_background_tasks.add(task)
task.add_done_callback(_background_tasks.discard)
```

**原因**：CPython 的事件循环只持有 Task 的弱引用，GC 可能在协程真正执行前回收它，导致任务**静默丢失、不报错不打日志**。
【禁止】裸调 `asyncio.create_task(coro())` / `asyncio.ensure_future(coro())` 而不保存返回值。
【必须】给后台任务加 `try/except` 兜底并记录日志，异常不会自动冒泡到任何地方。

### 10.3 超时与重试

- 【必须】所有外部调用（HTTP、DB、缓存、MQ）**显式设置超时**，禁止依赖默认值（很多客户端默认无限等待）。
- 【必须】定义**超时预算**：入口超时 > 各下游超时之和，避免下游超时后上游还在等。
- 【必须】重试**只对幂等操作**开启；重试必须有次数上限 + 指数退避 + 抖动。
- 【禁止】盲目重试：报错后先根据错误类型判断是否可重试，不可重试的错误（4xx、参数错误）立即失败。

### 10.4 定时任务与后台调度

> 调度器选型、Job 注册、幂等、可观测的完整规范见 **§19**；本节只讲通用的活性判定与并发约束。

- 【必须】任务活性判定基于**真实活性信号**（心跳、租约、状态转移记录），**不得仅按记录年龄**判定失败。
  **背景（真实事故）**：按年龄的 sweep 把仍在执行的长任务标记为 failed，而任务完成时又无条件覆写回 succeeded，状态机彻底失真。
- 【必须】任务状态机的每次状态变更都要**记录来源**（谁改的、为什么改），终态覆写要有守卫。
- 【必须】队列消费防「死队首」：终态项不得永久占据队首阻塞后续派发。
- 【必须】多实例（含本地开发实例）连同一队列时，消费必须按 `owner`/`instance` 过滤，否则会互相抢任务。
- 【必须】分布式任务用锁或唯一约束保证单次执行，不能靠「只部署一个实例」的假设。

### 10.5 并发写与锁

- 【必须】并发更新同一行用**乐观锁**（version 列）或 `SELECT ... FOR UPDATE`，禁止「先读后写」不加保护。
- 【必须】多表加锁**顺序全局一致**，避免死锁。
- 【应当】事务尽量短，禁止在事务中做网络调用。

---

## 11. 错误处理与异常体系

### 11.1 业务异常体系

```python
# core/exceptions.py
class AppError(Exception):
    """业务异常基类。

    code：稳定的业务错误码（前端按此分支，禁止按 message 文本判断）；
    message：面向用户的可读文案；
    status_code：映射到的 HTTP 状态码。
    """
    code: str = "INTERNAL_ERROR"
    message: str = "服务异常"
    status_code: int = 500

    def __init__(self, message: str | None = None, **extra):
        self.message = message or self.message
        self.extra = extra


class NotFoundError(AppError):
    """资源不存在（含无权限访问他人资源）。"""
    code, status_code, message = "NOT_FOUND", 404, "资源不存在"


class ConflictError(AppError):
    """状态冲突：重复创建、并发修改、状态机不允许的流转。"""
    code, status_code, message = "CONFLICT", 409, "操作冲突，请刷新后重试"
```

【必须】在 `main.py` 注册统一异常处理器，把 `AppError` 映射为标准响应；未捕获异常统一转 500 并**记录完整堆栈 + 请求上下文**。
【必须】前端可依赖的**业务错误码字符串保持稳定**，文案可改、码不可改。

### 11.2 错误处理纪律

- 【禁止】`except Exception: pass` —— 静默吞异常是最严重的可观测性破坏。
  必要的兜底至少要 `logger.warning(..., exc_info=True)`。
- 【禁止】把异常信息整体 redact 成「系统错误」返回给调用方而不留日志——会造成「失败零反馈」的黑箱（真实事故：故障持续多日无人能定位）。
- 【必须】捕获异常时**尽量窄**：捕获具体异常类型，而不是 `Exception`。
- 【必须】重新抛出时保留原始异常链：`raise AppError(...) from e`。
- 【必须】错误响应中**不得包含**堆栈、SQL、内部路径、连接串；这些只进日志。
- 【应当】外部依赖失败与自身逻辑失败在日志中用不同级别/标记区分，便于告警分流。

---

## 12. 日志与可观测性

### 12.1 日志规范

- 【必须】使用标准 `logging`，`logger = logging.getLogger(__name__)`；禁止 `print`。
- 【必须】应用启动时显式给业务 logger 挂 handler —— uvicorn 只配置 `uvicorn.*` logger，业务 logger 的 INFO/DEBUG 会被静默吞掉。
- 【必须】日志携带**请求追踪 ID**（中间件生成 `X-Request-ID` 并注入 contextvar），可跨服务串联。
- 【必须】日志级别使用规范：

| 级别 | 用于 |
|---|---|
| DEBUG | 开发排查细节，生产默认关闭 |
| INFO | 关键业务节点（创建订单、任务开始/结束、外部调用结果） |
| WARNING | 降级、重试、非预期但可继续（配置回退到默认值） |
| ERROR | 需要人介入的失败，必须带 `exc_info=True` |
| CRITICAL | 服务级不可用 |

- 【必须】日志**不得输出敏感信息**：密码、token、身份证、手机号、完整卡号、密钥。统一走脱敏函数。
- 【应当】关键路径用结构化日志（JSON），便于检索与聚合。

### 12.2 指标与告警

- 【应当】暴露 Prometheus 指标端点（需鉴权），至少包含：QPS、延迟分位、错误率、DB 连接池使用率、队列积压、后台任务成功/失败数。
- 【必须】新增的失败路径要有**可观测出口**：指标计数器 或 落库 或 告警，三选一，**不得只有日志**。
- 【必须】告警要去重收口（同类错误在时间窗口内合并），避免告警风暴淹没真实问题。
- 【应当】关键业务动作留审计记录（谁、何时、对什么资源、做了什么、结果）。

### 12.3 健康检查

```python
@app.get("/health", include_in_schema=False)
async def health():
    """存活探针：不查任何外部依赖，只表示进程存活。"""
    return {"status": "ok"}


@app.get("/ready", include_in_schema=False)
async def ready():
    """就绪探针：检查 DB / 缓存等关键依赖，任一不可用返回 503。"""
```

【必须】区分存活（liveness）与就绪（readiness）：存活探针**不查外部依赖**，否则数据库抖动会导致 K8s 反复重启进程，把小故障放大成大故障。

---

## 13. 安全规范

| 面 | 规范 |
|---|---|
| **认证** | 【必须】统一认证依赖，禁止各接口自行解析 token；token 校验失败统一 401 |
| **鉴权** | 【必须】按归属字段（`user_id`/`tenant_id`）兜底；【禁止】用客户端可控字段判权 |
| **密钥比对** | 【必须】用 `secrets.compare_digest`，防时序攻击 |
| **密钥管理** | 【必须】密钥来自环境/密钥管理服务；【禁止】提交到代码库；【必须】≥32 字符并在启动时校验；【应当】支持轮换 |
| **SQL 注入** | 【必须】全部参数化；裸 SQL 禁止字符串拼接；排序/字段名走白名单 |
| **限流** | 【必须】对外接口有限流（按用户 + 按 IP）；登录、发码等敏感接口单独更严的限流 |
| **CORS** | 【必须】显式白名单来源；【禁止】`allow_origins=["*"]` 与 `allow_credentials=True` 同时使用 |
| **上传** | 【必须】校验类型（按内容而非扩展名）、大小上限、存储路径隔离；【禁止】用户可控文件名直接落盘 |
| **越权遍历** | 【应当】对外不暴露自增主键（见 5.7） |
| **敏感数据** | 【必须】响应与日志脱敏；【必须】敏感字段加密存储；【禁止】在 URL/query 中传敏感信息（会进访问日志） |
| **依赖安全** | 【应当】CI 中跑依赖漏洞扫描 |
| **调试接口** | 【必须】生产环境关闭 `/docs`、`/redoc` 或加鉴权；【禁止】保留任何调试后门 |
| **内部接口** | 【必须】独立密钥鉴权；【必须】网络层同时限制来源；【禁止】暴露到公网 |

---

## 14. 性能规范

### 14.1 查询

- 【禁止】N+1 查询。列表接口需要关联数据时：`selectinload`（一次额外查询）或一次 `GROUP BY` 聚合后在内存分流。
  **背景**：百级主记录 × 万级关联行的场景下，相关子查询会把同一张表重复扫 N 遍。
- 【必须】只取需要的列：`select(A.id, A.name)` 优于 `select(A)`。
- 【必须】列表接口有分页上限，禁止无上限全量返回。
- 【必须】批量操作用批量语句（`insert().values([...])`、`bulk_update_mappings`），禁止循环单条写。
- 【应当】跨表统计走预聚合表或缓存，不在请求路径上实时算。

### 14.2 缓存

- 【应当】高频只读数据加缓存，必须显式设置 TTL。
- 【必须】明确缓存失效策略（写时失效 / 定时过期），并处理缓存击穿（互斥重建）与穿透（空值缓存）。
- 【必须】缓存 key 带版本前缀，便于整体失效。
- 【禁止】把缓存当数据库用（缓存丢失必须能从源重建）。

### 14.3 响应体积

- 【必须】大响应分页或流式返回；单响应体建议 < 1MB。
- 【应当】开启 gzip 中间件（注意与 SSE 不兼容，需排除流式路径）。

---

## 15. 测试规范

### 15.1 测试分层

| 层 | 特征 | 占比 | 执行 |
|---|---|---|---|
| **单元测试** | 不连任何外部依赖，纯函数/服务逻辑，毫秒级 | ≥70% | 每次改动 |
| **集成测试** | 连内存库（SQLite）或容器化的真实依赖 | ~25% | 每次改动 |
| **端到端测试** | 连共享环境，慢且不可并发 | ≤5% | 提交前 / CI |

【必须】连接**共享/真实**外部依赖的测试打标记，与快速档隔离：

```python
# pytest.ini
markers =
    db: 该测试会真实连接共享数据库。慢、依赖网络、并发执行会互相污染。

# 测试文件顶部
pytestmark = pytest.mark.db
```

```bash
pytest -m "not db"                    # 快速档：日常回归
pytest -m "not db" -k "order"         # 快速档 + 相关面收窄（最常用）
pytest -m db                          # 真实依赖档（不可并发）
pytest                                # 全量
```

**背景数据**：某服务全量 3355 用例耗时 323s，其中 581 个真实库用例占 293s（91%），其余纯单测平均 0.051s/个。分层后日常反馈从 5 分钟降到 35 秒。

【建议】不要给 `pytest.ini` 加 `addopts = -m "not db"` —— 默认全量可以防止有人跑完 `pytest` 看到绿色就以为通过了全量验证。

### 15.2 相关面回归（日常默认档）

【必须】开发/优化功能时，**默认只跑与本次改动相关的测试**，圈定方法（按序做，不凭感觉）：

1. 列出改动文件：`git diff --name-only`
2. 用改动的**模块名 / 类名 / 函数名 / 路由路径**在测试目录反查引用：
   ```bash
   grep -rl "OrderService\|/api/v1/orders" tests/
   ```
3. 按改动类型追加：
   - 改路由 / schema → 该路由测试 + OpenAPI 生成校验
   - 改 ORM / 加迁移 → 该表模型测试 + 迁移测试
   - 改公共工具 → 其全部调用方的测试
4. **相关集为空 = 该改动没有测试覆盖，必须补测试**，不得拿"跑了全量"当替代验证。

【必须】跑全量的三种情形（只有这三种）：
1. 改动触及**公共基础设施**（`core/`、`config.py`、`conftest.py`、`models/__init__.py`、`main.py`、框架/依赖升级）——这类改动的「相关面」实为全仓，反查会失真；
2. **合入主干前 / push 前**（入库门禁）；
3. **CI**。

### 15.3 测试写法

- 【必须】`conftest.py` 提供公共 fixture：mock 用户、`AsyncClient`、依赖覆盖。
  ```python
  app.dependency_overrides[get_current_user] = lambda: mock_user
  app.dependency_overrides[get_db] = lambda: fake_session
  ```
- 【必须】测试后清理依赖覆盖（`app.dependency_overrides.clear()`）。
- 【必须】有全局副作用的测试用 `autouse` fixture 隔离并**复原**（否则会污染共享环境的统计数据）。
- 【必须】新测试**优先不连真实库**：能用依赖覆盖或 `sqlite+aiosqlite` 内存库解决的，一律不连共享库。
  ⚠️ 用 SQLite 当测试替身存在**方言与并发行为差异**（类型严格性、字符串长度不生效、锁与死锁、日期函数、`ALTER TABLE` 能力受限）；并发、方言 SQL、性能相关的逻辑必须另有真实数据库测试兜底——差异清单见《SQLite 数据库使用通用规范》§9.1。
  真实库测试有两个固有缺陷：① 断言被历史噪声逼成 `>= N` 的弱形式；② 多人并行执行互相污染（**禁止对这批用例开 `pytest-xdist`**）。
- 【必须】测试命名说明**测的是什么行为**：`test_create_order_rejects_duplicate_biz_no`，而非 `test_create_order_2`。
- 【必须】断言具体值，不要只断言「不为空」。

### 15.4 覆盖要求

【必须】以下必须有测试：
- 每个对外接口的**成功路径 + 至少一个失败路径**（无权限 / 参数非法 / 资源不存在）；
- 每个状态机流转（含非法流转被拒绝）；
- 每个迁移（DDL 序列 + 对称性）；
- 每个幂等实现（重复请求返回相同结果）；
- 每次修复 bug **必须补一个能复现该 bug 的回归测试**。

### 15.5 验收纪律

- 【禁止】只看「流程跑通了 / 没报错」就判定通过。必须核对**最终产出的实际内容**——降级文案、兜底结果、护栏拦截都发生在「无报错」的执行里。
  **背景（真实事故）**：某轮验收只看流式 `done` 事件与错误计数，判定通过；实际最终落库内容是一段拦截文案，用户什么也没拿到。
- 【禁止】核对产出时做任何形式的截断（SQL `LEFT/RIGHT`、日志切片）——被截掉的尾部往往正是问题所在。
- 【必须】除了 error 事件，还要检查**不以 error 形态出现的异常信号**（降级、重试、兜底、回退分支）。
- 【必须】故意制造失败的验收数据要**显式标注**（标题带「故障注入」），避免在共享环境遗留误导性数据。

### 15.6 汇报口径

【必须】写清**跑了哪些测试、通过多少条、筛选条件是什么**：
- ✅ 「相关面回归 182 条通过（筛选：`pytest -m "not db" -k "order"`）」
- ❌ 「测试通过」/「回归通过」/ 未跑全量却写「全量通过」

---

## 16. 代码审查与提交规范

### 16.1 提交粒度

- 【必须】**一个模块 / 一个关注点 = 一个 commit**，且提交时该模块已「功能验证通过 + 已知 bug 全部修完」。未验证完成的中间状态留在工作区。
- 【禁止】把调试试错过程逐条提交（一串针对自己刚写代码的 `fix: 修复上一个 commit 的 xx`）。已提交但未合并未推送的，用 `git commit --amend` / `rebase -i` 压进原 commit。
- 【必须】拆分维度只能是**模块 / 关注点**，不能是**时间 / 试错轮次**。
- 一个功能的完整 commit 应包含：代码 + 迁移 + 测试 + 文档 + API 契约产物。
- 顺带修的存量问题单独 commit，并在 message 中注明与本功能无关。

### 16.2 Commit Message

【必须】遵循 Conventional Commits，**描述部分用团队统一语言**（本规范默认中文）：

```
<type>(<scope>): <描述>

[可选正文：为什么改，而不是改了什么]
```

| type | 用于 |
|---|---|
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `refactor` | 重构（不改行为） |
| `perf` | 性能优化 |
| `test` | 只动测试 |
| `docs` | 只动文档 |
| `chore` | 构建/依赖/工具 |
| `revert` | 回滚 |

示例：
```
feat(orders): 订单列表支持按状态过滤并返回聚合计数
fix(orders): 修 PUT /orders/{id} 未预加载关系导致的 500
```

【禁止】`update`、`fix bug`、`修改`、`123` 这类无信息量的 message。

### 16.3 分支与合并

- 分支命名：`feat/<简述>`、`fix/<简述>`、`hotfix/<简述>`。
- 【必须】合入主干前跑一次全量测试。
- 【必须】主干分支保护：禁止直接 push，必须经 PR + 至少 1 人 review。
- 【必须】**push 到远端需明确决策**（涉及迁移、共享资源、外部契约的改动尤其如此）。

### 16.4 变更记录

【应当】维护 `docs/CHANGELOG.md` 或待发布变更记录，与代码在**同一次提交**入库。每条记录包含：

```
## YYYY-MM-DD 一句话标题
- 为什么改：（背景、根因、不改的后果）
- 改了什么：（文件/模块/类/方法）
- 怎么验证：（测试文件、条数、筛选条件、验证结果）
- 影响范围：（接口/数据/性能/兼容性）
- 回滚方式：（开关 / revert / downgrade）
```

【禁止】代码已入库而变更记录游离在工作区，或事后单独补提交。

### 16.5 Code Review 检查清单

审查者【必须】逐项确认：

- [ ] 分层依赖方向正确，业务逻辑没写在路由里
- [ ] 事务边界清晰，service 层没有自行 commit
- [ ] 关系数据已预加载，不会在序列化阶段触发惰性加载
- [ ] 有 `response_model`、有鉴权依赖、有归属校验
- [ ] 新表/新列有中文 comment；NOT NULL 列配齐 default + server_default
- [ ] 迁移的 upgrade/downgrade 对称，DML 幂等，未 import ORM 模型
- [ ] 新配置项三处同步；新依赖已声明并注明理由
- [ ] 无裸 `create_task`、无阻塞调用、无 `except: pass`
- [ ] 无散写的业务口径字面量
- [ ] 有对应测试（含失败路径），且给出了实际执行结果
- [ ] 日志无敏感信息；错误响应无内部细节
- [ ] OpenAPI 契约已重新生成

### 16.6 静态检查

【必须】CI 强制通过：格式化（ruff format / black）、Lint（ruff）、类型检查（mypy / pyright，至少 `models`/`schemas`/`services` 目录）。
【应当】配置 pre-commit hook 本地拦截。

---

## 17. 发布与回滚规范

### 17.1 发布顺序

```
代码合入主干 → 全量测试通过 → 应用数据库迁移 → 部署应用 → 灰度验证 → 全量放开
```

【必须】**迁移先行且向后兼容**：新代码部署前，旧代码必须能在新表结构上正常运行（加列可以，删列/改语义不行）。
【必须】删列/改语义走**两阶段发布**：
1. 第一次发布：代码停止使用该列（读写都不碰），上线稳定；
2. 第二次发布：迁移删除该列。

### 17.2 回滚路径

【必须】每次发布前明确回滚方式：

| 变更类型 | 回滚方式 |
|---|---|
| 纯代码 | 回滚镜像/版本 |
| 新增列/表 | 代码回滚即可（新列无人写，可后续清理） |
| 有数据回填 | 需评估回填是否可逆，不可逆的必须先备份 |
| 新特性 | **关掉功能开关**（最快，优先） |

【必须】不可回滚的变更（删列、改语义、数据不可逆迁移）需**单独评审并提前备份**。

### 17.3 上线后验证

【必须】发布后核对：健康检查、关键接口冒烟、错误率/延迟指标、日志无新增异常类型、后台任务正常调度。
【必须】发布记录写明：版本、变更内容、迁移 revision、验证结果、回滚方式。

---

## 18. 协作与执行纪律

> 本章约束的是**人与 AI 助手的工作方式**，而非代码本身。多数条目源自真实的返工与事故：
> 越权改动、盲目猜测、试错流水账提交、隔离环境配置不全，造成的损失不亚于代码缺陷。

### 18.1 分析先行（改代码前的强制流程）

【必须】修改任何非平凡代码前，按序完成四步，**禁止直接动手改代码**：

1. **理解问题** —— 完整读完相关代码，弄清现有逻辑与上下文，不看代码就改等于猜；
2. **定位根因** —— 找到根本原因，而非表面现象。改掉症状而根因仍在，等于埋雷；
3. **列出方案** —— 给出至少一个具体方案，写明改动点、理由、影响面、备选方案与取舍；
4. **等待确认** —— 把分析结论告知需求方，**得到确认后再动手**。

**禁止行为**：
- 未读代码就改；
- 未分析根因就凭猜测改；
- 未说明方案就擅自改动；
- 对方只是**描述现象**、并未要求修改时就直接改代码。

**例外**：对方明确说「直接改」「帮我修复」时可跳过第 4 步确认，但**前三步不可省略**。

【必须】排查报错时**先检索既有经验/历史记录再重试**，禁止盲目重试同一操作。

### 18.2 任务范围控制

【必须】需求方明确指定操作某个文件/模块时，**只操作该文件/模块**。

【禁止】以「需要改别处才能达成目标」为由自行扩大改动范围。确需扩大时，**先说明原因并取得确认再动手**。

【必须】发现范围外的问题时，记录下来单独反馈，不顺手改掉——顺手改会让本次变更的影响面失控、回滚粒度失效。

【必须】完成范围内**全部**工作；若某部分被阻塞，把其余部分做完，并**明确说明哪部分未做、为什么**。缩小交付范围是需求方的决定，不是执行者的决定。

### 18.3 不确定性确认与独立判断

【必须】遇到任何不确定或有歧义的点，**禁止自作主张猜测**：
- 不确定意图 → 直接询问；
- 不确定技术方案 → 列出选项及取舍，让对方选；
- 不确定需求细节 → 追问明确后再执行。

【必须】保持**基于事实和技术逻辑的独立判断**，不迎合：
- 对方说的不一定对，以代码与数据为准；
- 不合理的要求要指出并说明原因；
- 提供专业意见，而非顺着临时想法执行。

【必须】提出质疑后若对方重申原方案，**视为其决策**，说明已知风险后按完整要求执行。

### 18.4 隔离环境（worktree）开发规范

#### 环境准备

【应当】代码、迁移、测试与配套文档的开发在**独立 Git worktree** 中进行，不污染主工作区。

【必须】创建 worktree 后，**把所有不入库的本地配置文件一并复制过去**（`.env`、各类 `*.ini`、本地证书、`config.local.*`）。

**背景（真实事故）**：只复制了 `.env` 而漏了另一个配置文件，导致客户端回落到打包的**生产默认配置**，用测试凭证打了生产后端，出现难以理解的权限错误，排查耗时数小时。

【应当】提供一条 `make worktree` / 脚本命令把这套复制动作固化，避免依赖人的记忆。

#### 提交粒度

【必须】同一模块「功能验证通过 + 已知缺陷全部修完」之后才提交；未验证完成的中间状态留在工作区（必要时 `git stash`）。

【禁止】把调试试错过程逐条提交，不允许出现一串针对自己刚写代码的 `fix: 修复上一个 commit 的 xx`。已提交但**未合并未推送**的，用 `git commit --amend` / `git rebase -i` 压进原 commit。

【必须】拆分维度只能是**模块 / 关注点**，不能是**时间 / 试错轮次**：
- 单模块功能 → 原则上 1 个 commit（代码 + 迁移 + 测试 + 文档 + 变更记录）；
- 多模块功能 → 按模块数拆，每个模块仍遵守「验证完成后一次提交」；
- 顺带修的存量问题 → 单独 1 个 commit，并注明与本功能无关。

【必须】一个功能分支的 commit 总数**不超过其涉及的模块数**；超出说明提交时机过早，须在收尾汇报中说明原因。

#### 收尾处置

| 改动类型 | 合并回原分支 | 删除 worktree + 临时分支 | 决策方 |
|---|---|---|---|
| **fix（修复类）** | 自动执行 | 自动执行 | 执行者自行完成 |
| **feat（新功能类）** | **由需求方决定** | **由需求方决定** | 必须先汇报再询问 |

- **fix 收尾**：验证通过 → 提交 → 合并回创建 worktree 时所在分支 → `git worktree remove` + 删临时分支。仅当存在合并冲突需决策、或对方要求保留时才暂缓，并说明原因。
- **feat 收尾**：【禁止】擅自合并、擅自删除。必须汇报：worktree 路径、分支名、commit 清单与说明、验证结果、目标合并分支、预估冲突范围；然后**分开询问**「是否合并回 X 分支」与「是否删除 worktree 与临时分支」，**不得用一个问题捆绑代答**。未拿到明确指令前原样保留。

### 18.5 跨系统共享契约

当一组接口或一批数据表被**两个及以上系统共同读写**（迁移期双跑、多端共用、对外开放 API）时：

【必须】任何一侧修改请求参数、响应体、业务码、数据权限语义，**必须在同一改动周期内同步另一侧的代码与两份契约文档**，禁止单侧演进。

【必须】把共享契约的**可观测行为**逐条写入文档并视为强约束，包括那些看起来「不合理」的历史行为（状态码恒定、错误体形状、缺省参数的语义、未命中路由的输出形状）。**这些不是 bug，不得单侧"修正"**——另一侧的调用方已依赖它们。

【必须】共享数据表的结构变更**须双端评审**，两侧的模型映射同步更新；共享的对象存储桶与 key 模板禁止单侧变更。

【应当】建立**契约一致性校验**（定期跑双端 diff 或契约测试），把「漂移」从人工纪律变成自动检测。

### 18.6 他方资产不可擅改

【禁止】为了修正自己系统的行为，去修改**由他方提供、他方拥有**的资产：用户上传的内容、业务方编写的配置/脚本/文档、第三方仓库的代码、其他团队维护的模块。**即使本地存在其副本，也不得直接编辑。**

【必须】把问题收敛在**自己这一侧**解决：调整自身的处理逻辑、约束、提示、路由策略、兜底。

【必须】确有必要调整他方资产时，**告知其所有者由其自行修改**，不代劳。

**原因**：他方资产是所有者意图的一手表达，擅自改写等于替对方改需求；且本地副本改了不等于线上生效（线上走对方的发布链路），只会造成本地与线上不一致的假象。

### 18.7 环境操作红线

| # | 红线 | 说明 |
|---|---|---|
| 1 | **禁止主动 `git push`** | 本地 commit 可自主，推送远端须明确指令 |
| 2 | **禁止直接对数据库执行破坏性 SQL** | UPDATE/DELETE/DROP 不作为变更手段；结构走迁移，数据修复先确认影响范围并留备份 |
| 3 | **禁止擅自用容器启动业务服务** | 未明确要求时按本地环境（虚拟环境）启动；数据库等基础设施除外 |
| 4 | **禁止清空容器旧数据与卷** | 任何时候都不得 `docker system prune`、删卷、删他人容器 |
| 5 | **必须在虚拟环境中开发测试** | 禁止污染系统 Python |
| 6 | **禁止在共享环境跑并发的真实依赖测试** | 会互相污染，且阻塞他人 |
| 7 | **本地连共享环境时必须关闭全部后台任务** | 否则本机进程会替共享环境跑定时任务、改共享数据 |
| 8 | **禁止提交任何密钥/凭证到代码库** | 包括测试环境的 |

### 18.8 完成的定义（DoD）

【必须】同时满足以下全部条件才可声称「完成」：

- [ ] 功能按需求实现，范围内工作**全部**做完（未做的部分已明确说明）
- [ ] 已完成**变更自审**（对照 §16.5 检查清单）
- [ ] 已跑**相关面测试并通过**，且能给出：跑了哪些、多少条、筛选条件
- [ ] 已核对**实际产出内容**，而非仅「流程没报错」
- [ ] 文档同步：API 契约、配置示例、变更记录
- [ ] 明确的**回滚方式**

【禁止】以下汇报方式：
- 「测试通过」（没有条数与筛选条件）；
- 「应该没问题」「理论上可以」（没有实际验证）；
- 未跑全量却写「全量通过」；
- 在隔离环境验证却写成「测试环境验收通过」（环境口径必须诚实，见 §7.6）。

---

## 19. 定时任务与调度规范（APScheduler）

> 本章覆盖进程内定时任务的选型、注册、执行、观测与测试。
> 通用的并发/活性判定约束见 §10.4，二者配合使用。

### 19.1 选型与边界

| 场景 | 方案 | 说明 |
|---|---|---|
| 应用自身的周期性维护（清扫、对账、聚合、缓存预热） | **APScheduler `AsyncIOScheduler`** | 与应用同进程、同事件循环，可直接复用 DB 连接池与 service 层 |
| 用户可配置的定时任务（业务侧建的「每天 8 点跑报表」） | **DB 驱动 + tick 轮询**（见 §19.7） | 任务定义存库，调度器只做到期判定 |
| 秒级/毫秒级高频触发 | 消息队列 / 事件驱动 | 定时器不是队列 |
| 跨服务编排、需要重试与依赖图 | 外部调度平台（Airflow / DolphinScheduler / K8s CronJob） | 不要在应用里造调度平台 |
| 需要严格「恰好一次」且跨实例 | 外部调度 或 **分布式锁 + 幂等** | 见 §19.5 |

【必须】APScheduler 只用于**应用自身**的周期维护与到期判定，**不承担**跨服务编排、复杂依赖、失败重试策略等调度平台职责。

【必须】使用 `AsyncIOScheduler`（挂在应用事件循环上），**不用** `BackgroundScheduler`——后者跑在独立线程，异步 ORM 会话与事件循环资源无法安全跨线程使用。

### 19.2 调度器生命周期

【必须】调度器由应用 `lifespan` 统一启停，模块内单例，禁止散点创建：

```python
# app/scheduler/runtime.py
_scheduler: AsyncIOScheduler | None = None


async def start_scheduler() -> None:
    """启动调度器并注册全部任务（幂等：重复调用直接返回）。"""
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.scheduler_timezone))
    _scheduler.start()
    register_all_jobs(_scheduler)


async def stop_scheduler() -> None:
    """停止调度器；wait=False 避免长任务阻塞进程退出（在途任务由幂等与清扫兜底）。"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
```

```python
# app/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动调度器，退出时停止。"""
    if settings.scheduler_enabled:
        await start_scheduler()
    yield
    await stop_scheduler()
```

【必须】`start_scheduler()` **幂等**（重复调用不重复注册）——热重载、测试、多次初始化都可能触发。
【必须】停机时 `shutdown(wait=False)`，并依赖任务自身的幂等 + 启动清扫兜底在途任务；`wait=True` 会让长任务阻塞进程退出、拖垮滚动发布。
【应当】提供**排空（drain）接口**：返回当前进程内在途任务数，发版前轮询归零再重启。

### 19.3 声明式任务注册表（推荐）

【必须】**禁止把 Job 定义散落成一长串 `if settings.xxx_enabled: scheduler.add_job(...)`**。这种写法的问题在真实项目中会迅速暴露：

- 十几个任务 = 几百行重复的 `if` + `add_job` + `logger.info`，参数各写各的、默认值漂移；
- 「当前有哪些定时任务、各自什么频率、谁负责」**没有任何一处能一眼看全**；
- 无法程序化枚举，做不了健康检查、管理端展示、契约测试；
- 新增任务靠复制粘贴，漏掉 `max_instances=1` 之类的关键参数不会有任何提示。

【必须】改用**声明式注册表**：一处集中声明所有任务的元数据，一个统一函数负责注册。

```python
# app/scheduler/registry.py
"""定时任务声明式注册表：全部定时任务的单一事实来源。

新增任务只需在 SCHEDULED_JOBS 里加一条声明，注册逻辑（开关、触发器、
互斥、错过策略、日志、埋点）由 register_all_jobs 统一处理。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class ScheduledJob:
    """一个定时任务的完整声明。

    id：全局唯一的 Job 标识，同时用于日志、指标标签与管理端展示，一经确定不得更改。
    func：任务入口，必须是 async def（AsyncIOScheduler 只在事件循环内 await 协程）。
    schedule：调度表达式，支持 "cron:*/5 * * * *" / "interval:300" / "daily:03:20"。
    enabled：读取配置开关的函数，返回 False 时跳过注册（不是删掉声明）。
    """

    id: str
    func: Callable[[], Awaitable[None]]
    schedule: str
    description: str
    category: Literal["maintenance", "sync", "report", "monitor", "backup"] = "maintenance"
    owner: str = ""                      # 责任人/团队，出问题时找谁
    enabled: Callable[[], bool] = lambda: True
    timeout_seconds: int = 300           # 单轮执行超时，超时即取消并告警
    misfire_grace_seconds: int = 60      # 错过触发的宽限期，超过则跳过该轮
    max_instances: int = 1               # 上一轮未结束时不并发（默认必须为 1）
    coalesce: bool = True                # 堆积的多次触发合并为一次，不补偿
    single_flight: bool = True           # 多实例部署时是否抢分布式锁（见 §19.5）
    environments: tuple[str, ...] = ()   # 空 = 全环境；否则仅在列出的环境注册
    tags: tuple[str, ...] = field(default_factory=tuple)


SCHEDULED_JOBS: tuple[ScheduledJob, ...] = (
    ScheduledJob(
        id="sweep_stale_runs",
        func=sweep_stale_runs,
        schedule="cron:*/5 * * * *",
        description="收敛进程崩溃遗留的 running 记录，防止状态永久悬挂",
        category="maintenance",
        owner="platform",
        enabled=lambda: settings.run_sweep_enabled,
        timeout_seconds=120,
    ),
    ScheduledJob(
        id="daily_report",
        func=generate_daily_report,
        schedule="daily:02:00",
        description="每日报表生成",
        category="report",
        owner="data",
        enabled=lambda: settings.daily_report_enabled,
        timeout_seconds=600,
        misfire_grace_seconds=3600,      # 凌晨任务错过后当天内补跑仍有意义
        environments=("production",),
    ),
    ScheduledJob(
        id="asset_reconcile",
        func=reconcile_assets,
        schedule="interval:86400",
        description="资产清单与对象存储对账",
        category="maintenance",
        owner="platform",
        enabled=lambda: settings.asset_reconcile_enabled,
        timeout_seconds=1800,
    ),
)
```

统一注册器：

```python
# app/scheduler/register.py
def build_trigger(schedule: str, tz: ZoneInfo):
    """把声明式 schedule 字符串解析成 APScheduler 触发器。

    支持三种形态，覆盖绝大多数场景且可读性优于裸触发器构造：
      cron:<5段表达式>  → CronTrigger.from_crontab
      interval:<秒>     → IntervalTrigger
      daily:<HH:MM>     → CronTrigger(hour, minute)
    """
    kind, _, expr = schedule.partition(":")
    if kind == "cron":
        return CronTrigger.from_crontab(expr, timezone=tz)
    if kind == "interval":
        return IntervalTrigger(seconds=int(expr), timezone=tz)
    if kind == "daily":
        hour, minute = expr.split(":")
        return CronTrigger(hour=int(hour), minute=int(minute), timezone=tz)
    raise ValueError(f"无法识别的 schedule 声明: {schedule}")


def register_all_jobs(scheduler: AsyncIOScheduler) -> list[str]:
    """按注册表注册全部任务，返回实际注册的 Job id 列表（供健康检查与日志）。"""
    tz = ZoneInfo(settings.scheduler_timezone)
    registered: list[str] = []
    for job in SCHEDULED_JOBS:
        if job.environments and settings.environment not in job.environments:
            logger.info("跳过定时任务 %s：环境 %s 不在 %s 内", job.id, settings.environment, job.environments)
            continue
        if not job.enabled():
            logger.info("跳过定时任务 %s：开关未开启", job.id)
            continue
        scheduler.add_job(
            _wrap(job),                       # 统一包裹：超时、锁、日志、指标、异常兜底
            trigger=build_trigger(job.schedule, tz),
            id=job.id,
            max_instances=job.max_instances,
            coalesce=job.coalesce,
            misfire_grace_time=job.misfire_grace_seconds,
            replace_existing=True,
        )
        registered.append(job.id)
        logger.info("已注册定时任务 %s（%s，%s）", job.id, job.description, job.schedule)
    return registered
```

统一包裹层（**所有横切关注点只写一次**）：

```python
def _wrap(job: ScheduledJob):
    """给任务函数套上统一的超时、单飞锁、日志、指标与异常兜底。

    为什么统一包裹而不是让每个任务自己写：横切逻辑一旦分散，必然出现
    「有的任务记了指标、有的没记」「有的加了锁、有的忘了」的参差，
    而这类缺失只有在故障时才会被发现。
    """
    async def _runner() -> None:
        started = time.monotonic()
        logger.info("定时任务开始 job=%s", job.id)
        JOB_RUNS.labels(job.id).inc()
        try:
            if job.single_flight and not await try_acquire_lock(job.id, job.timeout_seconds):
                logger.info("定时任务 %s 已被其他实例持有，本轮跳过", job.id)
                JOB_SKIPPED.labels(job.id).inc()
                return
            async with asyncio.timeout(job.timeout_seconds):
                await job.func()
        except TimeoutError:
            JOB_FAILURES.labels(job.id, "timeout").inc()
            logger.error("定时任务超时 job=%s timeout=%ds", job.id, job.timeout_seconds)
            await alert(f"定时任务 {job.id} 执行超时")
        except Exception:
            # 必须兜底：APScheduler 里未捕获的异常不会冒泡到任何地方，
            # 不兜底就等于任务静默失败（§11 禁止静默吞异常的具体落地）
            JOB_FAILURES.labels(job.id, "exception").inc()
            logger.exception("定时任务异常 job=%s", job.id)
            await alert(f"定时任务 {job.id} 执行异常")
        finally:
            elapsed = time.monotonic() - started
            JOB_DURATION.labels(job.id).observe(elapsed)
            logger.info("定时任务结束 job=%s 耗时=%.2fs", job.id, elapsed)
            if job.single_flight:
                await release_lock(job.id)

    return _runner
```

**收益**：新增任务从「复制 20 行 + 祈祷没漏参数」变成「加一条 8 行声明」；全部任务可被程序化枚举（健康检查、管理端、契约测试）；横切逻辑只有一份实现。

### 19.4 Job 参数强制约定

【必须】每个 `add_job` 都显式给出以下参数，**禁止依赖默认值**：

| 参数 | 强制取值 | 原因 |
|---|---|---|
| `id` | 显式、全局唯一、语义化 | 无 id 无法排查、无法 `replace_existing`、日志里只有一串 UUID |
| `max_instances` | **默认必须为 1** | 上一轮没跑完又启动一轮 = 并发重复处理；需要并发必须写明理由 |
| `coalesce` | **默认 `True`** | 停机堆积的 N 次触发合并成 1 次；`False` 会在恢复瞬间打出 N 倍负载 |
| `misfire_grace_time` | 显式设置 | 不设时错过即永久跳过；数值按业务语义定（见下） |
| `replace_existing` | `True` | 重复注册直接替换，避免残留旧 Job |
| `timezone` | 调度器级统一设置 | 见 §19.6 |

**`misfire_grace_time` 取值原则**：
- 高频维护任务（每 5 分钟）→ 60s 左右，错过一轮无所谓，下轮就补；
- 每日任务（凌晨报表/清理）→ 数小时，当天内补跑仍有意义；
- 强时效任务（整点推送）→ 短（如 60s），过期补发反而是骚扰。

### 19.5 幂等与多实例

【必须】**每个定时任务都必须幂等**：同一时间窗内被执行两次，结果与执行一次相同。理由：重复触发在真实环境中一定会发生（多实例、错过补偿、手动触发、发布重叠）。

实现幂等的三种手段（按优先级）：
1. **状态机守卫**：`UPDATE ... WHERE status = 'pending'` 拿到影响行数才处理（数据库层天然互斥）；
2. **唯一约束**：结果落库带唯一键，重复写入捕获 `IntegrityError` 忽略；
3. **分布式锁**：Redis `SET key val NX PX <ttl>` 抢占执行权。

多实例部署时【必须】二选一：
- **方案 A（推荐）**：所有实例都注册任务，靠**分布式锁 + 幂等**保证只有一个真正执行；
- **方案 B**：只在一个实例开启调度（配置开关或 leader 选举），其余实例 `scheduler_enabled=false`。
  【必须】采用方案 B 时把「单实例开启」写进部署文档与配置注释，否则扩容时会静默变成多实例并发。

【必须】分布式锁的 TTL **必须大于任务最长执行时间**，且**执行结束主动释放**；只靠 TTL 过期会在长任务场景下出现「锁提前失效 → 两个实例同时跑」。

【禁止】用「反正只部署一个实例」当作幂等的替代——这个假设会在第一次扩容、第一次滚动发布（新旧 Pod 并存）时破产。

### 19.6 任务函数编写规范

```python
async def sweep_stale_runs() -> None:
    """收敛进程崩溃遗留的 running 记录。

    幂等性：按 status='running' AND updated_at < cutoff 条件更新，重复执行无副作用。
    活性判定：以 heartbeat_at 为准，不按记录年龄（见 §10.4）。
    """
    async with SessionLocal() as db:          # 自持会话，不复用请求级 session
        cutoff = datetime.now(UTC) - timedelta(seconds=settings.stale_threshold_seconds)
        result = await db.execute(
            update(Run)
            .where(Run.status == "running", Run.heartbeat_at < cutoff)
            .values(status="failed", failed_reason="心跳超时，判定为进程崩溃遗留")
        )
        await db.commit()
        if result.rowcount:
            logger.warning("收敛残留 running 记录 %d 条", result.rowcount)
```

【必须】：
1. **必须是 `async def`** —— `AsyncIOScheduler` 只在事件循环内 `await` 协程；普通同步函数会被丢进线程池，导致 `asyncio.create_task()` 找不到 running loop 而失败。
2. **自持数据库会话**（`async with SessionLocal()`），不复用请求级 session；用完即关。
3. **自己收口事务**（定时任务就是调用方，见 §3.3）。
4. **可空跑**：没有待处理数据时安静返回，不刷日志。
5. **有产出才记 WARNING/INFO 带数量**，便于从日志判断「跑了但什么也没做」还是「跑了并处理了 N 条」。
6. **单轮处理量有上限**（`LIMIT`/分批），禁止一轮扫全表——数据积压时会把一次维护变成一次事故。
7. **长任务分片可续**：单轮处理不完的，下一轮从断点继续，而不是每轮从头重扫。

【必须】时区统一在**调度器级**设置（`AsyncIOScheduler(timezone=...)`），任务内部一律用 UTC 计算，**只在展示层转换**。跨时区业务的 cron 必须显式带 timezone，且在配置注释中写明基准时区。

【禁止】在任务函数里 `while True` 自循环——那是常驻协程，不是定时任务；两种模型混用会导致停机时无法收敛。

### 19.7 数据库驱动的动态任务

用户可在界面上创建的定时任务（「每天 8 点跑我的报表」）**不要逐条注册成 APScheduler Job**。

| 方案 | 做法 | 问题 |
|---|---|---|
| **逐任务注册**（不推荐） | 启动时把 N 个任务全部 `add_job`，增删改同步内存 Job | 启动 O(N) 且每条都要回写 `next_run_at`；内存与 DB 双份状态易漂移；多实例下每个实例都注册一遍；进程重启期间的变更全丢 |
| **tick 轮询**（推荐） | 只注册**一个** tick Job（如每 5~30 秒），每轮查 DB 里 `next_run_at <= now` 的任务并原子认领 | 启动 O(1)；DB 是唯一事实来源；增删改只改 DB 不碰调度器；多实例天然靠认领事务互斥 |

【必须】采用 tick 方案时：
- 认领必须是**原子操作**：`UPDATE tasks SET claimed_by=?, next_run_at=<下次> WHERE id=? AND next_run_at<=now()`，按 `rowcount` 判断是否抢到；
- `next_run_at` 是**调度的唯一事实来源**：暂停任务置 `NULL`（tick 永不认领），恢复时重算；
- tick 间隔决定**调度精度下限**，需在文档中写明（如 30 秒 tick = 最坏晚 30 秒触发）；
- tick Job 本身同样遵守 §19.4 的参数约定（`max_instances=1` 尤其重要）。

【必须】任务被删除/停用时，**同步清理其待处理队列项与在途状态**，否则会留下「任务已删但后台还在跑」的幽灵执行（§6.4）。

### 19.8 配置与开关

【必须】每个定时任务有**独立的启停开关**，且默认值遵循 §8.3（新任务默认关闭，灰度后再开）：

```python
# config.py
scheduler_enabled: bool = Field(default=False, description="调度器总开关；关闭时不注册任何定时任务")
scheduler_timezone: str = Field(default="Asia/Shanghai", description="调度器基准时区")
run_sweep_enabled: bool = Field(default=True, description="残留 running 记录清扫任务开关")
run_sweep_interval_minutes: int = Field(default=5, ge=1, le=1440, description="清扫任务执行间隔（分钟）")
```

【必须】总开关 + 单任务开关**两级**：总开关关闭时不注册任何任务（本地开发默认状态）。
【必须】间隔类配置带 `ge`/`le` 约束，防止配成 0 或过小把数据库打爆。
【必须】三处同步（§8.2），`.env.example` 中写明**该任务做什么、多久跑一次、关掉会怎样**。
【必须】本地连共享环境时总开关必须关闭（§18.7 第 7 条）。

### 19.9 可观测与告警

【必须】每个任务至少产出：

| 观测项 | 形式 |
|---|---|
| 开始 / 结束 / 耗时 | INFO 日志，带 `job=<id>` 标签 |
| 处理数量 | 有产出时 INFO，异常量级时 WARNING |
| 失败 | ERROR + `exc_info=True` + **告警** |
| 执行次数 / 失败次数 / 耗时分布 | 指标（`job_runs_total`、`job_failures_total{reason}`、`job_duration_seconds`） |
| 上次成功时间 | 指标或落库，用于**「任务静默停跑」告警** |

【必须】**告警要覆盖「没跑」而不只是「跑失败」**。最危险的定时任务故障不是报错，而是**悄悄不再执行**（注册被跳过、调度器没启动、进程假死）——只监控失败率永远发现不了。做法：对每个任务监控 `now - last_success_at > 预期间隔 × 2` 并告警。

【应当】暴露一个只读接口列出当前注册的全部 Job（id、下次触发时间、上次执行结果），用于发布后自检与管理端展示。声明式注册表让这件事变成几行代码。

### 19.10 测试规范

【必须】**任务函数与调度注册分开测**：

```python
# 1. 任务函数：直接 await，不启动调度器（快、可进快速档）
async def test_sweep_stale_runs_marks_only_expired(db_session):
    """只收敛心跳超时的记录，正常心跳的不受影响。"""
    ...
    await sweep_stale_runs()
    ...

# 2. 幂等性：连跑两次，结果一致
async def test_sweep_is_idempotent(db_session):
    """重复执行不产生额外副作用（重复触发在真实环境必然发生）。"""
    await sweep_stale_runs()
    first = await _snapshot(db_session)
    await sweep_stale_runs()
    assert await _snapshot(db_session) == first

# 3. 注册表：纯数据断言，不启动调度器
def test_registry_contract():
    """全部任务声明满足强制约定。"""
    ids = [j.id for j in SCHEDULED_JOBS]
    assert len(ids) == len(set(ids)), "Job id 必须全局唯一"
    for j in SCHEDULED_JOBS:
        assert j.max_instances == 1 or j.id in _CONCURRENT_ALLOWLIST, f"{j.id} 并发需白名单"
        assert j.description and j.owner, f"{j.id} 必须有描述与责任人"
        assert j.timeout_seconds > 0
        build_trigger(j.schedule, ZoneInfo("UTC"))   # schedule 表达式必须可解析

# 4. 触发器解析：表驱动
@pytest.mark.parametrize("schedule,expected_next", [...])
def test_build_trigger(schedule, expected_next):
    """schedule 声明解析出的下次触发时刻符合预期。"""
```

【禁止】在测试里真启动调度器 + `sleep` 等待触发——慢、不稳定、时序依赖。要验证「到点会触发」，直接断言**触发器算出的下次触发时刻**。

【必须】修改任何调度参数（间隔、cron、misfire）都要更新对应的注册表契约测试。

### 19.12 任务的手动执行入口（CLI）

#### 核心原则：任务只写一次，调度与 CLI 共用同一入口

【必须】每个定时任务**同时可被手动执行**，且两条路径**共用同一份任务函数、同一个包裹层、同一套参数校验**。

```
                    ┌─ 调度器（到点自动触发，用默认参数）
任务函数 + 包裹层 ──┤
                    └─ CLI（人工触发，可覆盖参数）
```

**为什么必须支持手动执行**（这不是「顺便加的便利功能」）：
- **故障恢复**：任务失败/漏跑后要立刻补跑一次，不能干等下一个周期；
- **数据修复**：需要对指定日期、指定 ID 范围重跑；
- **发布验证**：上线后立刻验证任务能跑通，而不是等到凌晨才发现炸了；
- **本地调试**：调度器在本地是关闭的，没有 CLI 就无法调试任务逻辑；
- **可测试性**：能被 CLI 调用的任务，天然是「入口清晰、参数显式」的。

【禁止】为手动执行**另写一份脚本**。两份实现必然漂移，且漂移只有在故障需要补跑时才被发现——那是最不能出错的时刻。

#### 注册表扩展：参数模型

在 §19.3 的 `ScheduledJob` 上增加参数声明，CLI 与调度器共用：

```python
class JobParams(BaseModel):
    """任务参数基类：CLI 入参与调度默认值共用同一套校验。"""
    dry_run: bool = Field(default=False, description="只输出将要做什么，不实际写入")


class ReconcileParams(JobParams):
    """资产对账任务参数。"""
    since: date | None = Field(default=None, description="只对账该日期之后的数据，默认全量")
    limit: int = Field(default=1000, ge=1, le=100000, description="单轮处理上限")


@dataclass(frozen=True)
class ScheduledJob:
    ...
    # 参数模型：调度器用 params_model() 的默认值构造，CLI 用命令行入参构造。
    # 一套 Pydantic 模型同时承担「校验 + 默认值 + CLI 帮助文本」三个职责。
    params_model: type[JobParams] = JobParams
    manual_only: bool = False        # True = 只能手动执行，不注册进调度器（一次性运维任务）


SCHEDULED_JOBS = (
    ScheduledJob(
        id="asset_reconcile",
        func=reconcile_assets,                # async def reconcile_assets(p: ReconcileParams) -> JobResult
        schedule="interval:86400",
        description="资产清单与对象存储对账",
        owner="platform",
        params_model=ReconcileParams,
        timeout_seconds=1800,
    ),
    ScheduledJob(
        id="backfill_order_status",
        func=backfill_order_status,
        schedule="",                          # 无调度表达式
        description="订单状态历史回填（一次性运维任务）",
        owner="platform",
        manual_only=True,                     # 只出现在 CLI，不进调度器
        params_model=BackfillParams,
    ),
)
```

任务函数签名统一为 `async def f(params: XxxParams) -> JobResult`：

```python
@dataclass
class JobResult:
    """任务执行结果：CLI 打印摘要、调度器记指标、测试断言，三处共用。"""
    processed: int = 0          # 处理条数
    skipped: int = 0
    message: str = ""           # 人类可读摘要


async def reconcile_assets(p: ReconcileParams) -> JobResult:
    """资产清单与对象存储对账。

    幂等性：按主键 upsert，重复执行结果一致。
    dry_run=True 时只统计差异不写库，供人工确认后再实跑。
    """
    async with SessionLocal() as db:
        diffs = await _scan_diffs(db, since=p.since, limit=p.limit)
        if p.dry_run:
            return JobResult(processed=0, skipped=len(diffs),
                             message=f"[dry-run] 发现 {len(diffs)} 处差异，未写入")
        await _apply(db, diffs)
        await db.commit()
        return JobResult(processed=len(diffs), message=f"已修复 {len(diffs)} 处差异")
```

#### CLI 实现：从注册表自动生成命令

【必须】CLI 命令**由注册表自动生成**，不逐个手写——否则新增任务又要在两处登记，回到「两份实现」的老问题。

```python
# app/cli.py
"""任务命令行入口（仓库根目录 cli.py，与 ASGI 应用模块分离）。

  python cli.py jobs list                                   列出全部任务
  python cli.py jobs describe asset_reconcile               查看某任务的参数、调度与开关状态
  python cli.py jobs run asset_reconcile                    手动执行（用默认参数）
  python cli.py jobs run asset_reconcile --since=2026-09-01 --limit=500
  python cli.py jobs run asset_reconcile --dry-run          只看会做什么，不写入
  python cli.py jobs run asset_reconcile --force            跳过分布式锁强制执行
"""
from __future__ import annotations

import asyncio
import click

from app.scheduler.registry import SCHEDULED_JOBS


@click.group()
def cli() -> None:
    """应用管理命令。"""


@cli.group()
def jobs() -> None:
    """定时任务管理：列出 / 查看 / 手动执行。"""


@jobs.command(name="list")
def jobs_list() -> None:
    """列出全部任务及其调度、开关状态、责任人。"""
    for j in SCHEDULED_JOBS:
        state = "手动" if j.manual_only else ("启用" if j.enabled() else "关闭")
        click.echo(f"{j.id:<32} {state:<4} {j.schedule or '-':<24} {j.owner:<10} {j.description}")


def _build_options(job):
    """把 Pydantic 参数模型的字段自动转成 click 选项（含类型、默认值、帮助文本）。

    为什么自动生成而不是手写 @click.option：参数一旦有两处定义（模型 + CLI），
    改了模型忘了改 CLI 就会出现「传了参数不生效」这种最难排查的问题。
    """
    def decorator(f):
        for name, field in reversed(job.params_model.model_fields.items()):
            f = click.option(
                f"--{name.replace('_', '-')}",
                default=None,                       # None = 用模型默认值，区分「没传」与「传了默认值」
                help=field.description or name,
            )(f)
        return f
    return decorator


for _job in SCHEDULED_JOBS:
    @jobs.command(name=_job.id, help=_job.description)
    @_build_options(_job)
    @click.option("--force", is_flag=True, help="跳过分布式锁强制执行（确认无并发时使用）")
    @click.pass_context
    def _run(ctx, _job=_job, force: bool = False, **kwargs) -> None:
        """手动执行该任务。"""
        # 只把显式传入的参数交给模型，其余走模型默认值
        raw = {k: v for k, v in kwargs.items() if v is not None}
        params = _job.params_model(**raw)          # Pydantic 负责类型转换与校验，非法入参直接报错
        result = asyncio.run(run_job(_job, params, trigger_source="manual", force=force))
        click.echo(result.message or f"完成：处理 {result.processed} 条，跳过 {result.skipped} 条")
        ctx.exit(0)


if __name__ == "__main__":
    cli()
```

#### 入口约定

【必须】**CLI 入口是仓库根目录的 `cli.py`，与 ASGI 应用模块 `main.py` 分离**：

```
python cli.py <命令组> <命令> [--参数=值 ...]
```

```
项目根/
├── cli.py           ← 唯一 CLI 入口：click group，聚合各命令组（jobs / migrate / ...）
├── app/
│   ├── main.py      ← ASGI 应用（uvicorn app.main:app），不含 CLI 逻辑
│   └── cli/         ← 命令实现按组分文件
│       ├── jobs.py      定时任务：list / describe / run
│       ├── migrate.py   数据库迁移
│       └── ops.py       一次性运维命令
```

```python
# cli.py（根目录，保持极薄：只做聚合，不写业务）
"""应用管理命令行入口。

  python cli.py jobs list
  python cli.py jobs run <job_id> [--参数=值 ...]
  python cli.py migrate upgrade
"""
import click

from app.cli.jobs import jobs
from app.cli.migrate import migrate


@click.group()
def cli() -> None:
    """应用管理工具。"""


cli.add_command(jobs)
cli.add_command(migrate)

if __name__ == "__main__":
    cli()
```

【必须】遵守的入口约束：

- **`main.py` 不承载 CLI 逻辑**——导入应用模块时不应有副作用；`python cli.py --help` 必须在不连数据库、不启服务的前提下秒回。
- **`cli.py` 保持极薄**：只做命令聚合，业务实现放 `app/cli/<组>.py`，任务逻辑放 service 层。
- **命令组按领域划分**（`jobs` / `migrate` / `ops`），不要把几十个命令平铺在顶层。
- **CLI 是独立进程**：自持配置与数据库会话，不依赖 Web 进程存活。
- 若团队已约定统一入口为 `python main.py`，可在 `main.py` 末尾加 `if __name__ == "__main__": from cli import cli; cli()` 委托，但**实现仍在 `cli.py`**，不得反过来把逻辑写进 `main.py`。

#### 手动执行与调度执行的差异

【必须】两条路径共用包裹层 `run_job()`，仅以下几点按 `trigger_source` 区分：

| 维度 | 调度触发 | 手动触发 |
|---|---|---|
| 参数 | 模型默认值 | CLI 入参覆盖 |
| 分布式锁 | 抢锁，抢不到跳过 | **同样抢锁**（防与定时轮撞车）；`--force` 可跳过，需在日志中标记 |
| 幂等要求 | 必须 | **必须**（手动补跑与自动轮重叠是常态） |
| 审计 | INFO 日志 + 指标 | **额外记录操作者与命令行**（谁在什么时候跑了什么参数） |
| 失败处理 | 记指标 + 告警 | 记指标 + **非零退出码**，不重复告警（人就在现场） |
| 指标标签 | `trigger="schedule"` | `trigger="manual"` |
| 输出 | 日志 | 日志 + **stdout 可读摘要** |

```python
async def run_job(job, params, *, trigger_source: str = "schedule", force: bool = False) -> JobResult:
    """统一执行入口：调度器与 CLI 都走这里，保证行为完全一致。"""
    logger.info("任务开始 job=%s trigger=%s params=%s", job.id, trigger_source, params.model_dump())
    JOB_RUNS.labels(job.id, trigger_source).inc()
    if job.single_flight and not force and not await try_acquire_lock(job.id, job.timeout_seconds):
        return JobResult(message=f"任务 {job.id} 正被其他执行占用，本次跳过")
    try:
        async with asyncio.timeout(job.timeout_seconds):
            return await job.func(params)
    finally:
        ...
```

#### 强制约定

| # | 规则 | 原因 |
|---|---|---|
| 1 | **每个任务都必须支持 `--dry-run`** | 手动执行常发生在故障现场，先看清会做什么再实跑；写操作任务尤其必须 |
| 2 | **退出码必须规范**：0=成功、1=业务失败、2=参数错误 | 运维脚本与 CI 依赖退出码判断；恒返回 0 会让编排系统误判成功 |
| 3 | **参数校验只写一处**（Pydantic 模型），CLI 选项自动生成 | 两处定义必然漂移，症状是「传了参数不生效」 |
| 4 | **CLI 必须能列出全部任务**（`jobs list`） | 「有哪些任务可跑」要能自查，不靠翻代码 |
| 5 | **手动执行必须留审计**（操作者 + 参数 + 结果） | 事后要能回答「这批数据是谁什么时候补跑改的」 |
| 6 | **一次性运维任务也进注册表**（`manual_only=True`） | 否则又散落成一堆 `scripts/fix_xxx.py`，没有统一的锁/超时/审计 |
| 7 | **CLI 自持配置与会话**，不依赖 Web 进程 | CLI 是独立进程，必须能单独跑通 |
| 8 | **危险任务需二次确认**（`--yes` 或交互确认） | 删除、批量改写类任务防误触 |
| 9 | **CLI 入口不得有 import 副作用** | 导入即启动服务/连库会让 `--help` 都跑不动 |
| 10 | **CLI 路径同样计入测试** | 至少一个用例走 `CliRunner` 验证参数解析与退出码 |

#### 测试

```python
# CliRunner 直接调用 cli.py 暴露的 group，无需真的起子进程
def test_cli_lists_all_registered_jobs():
    """jobs list 必须覆盖注册表全部任务（防新增任务漏挂 CLI）。"""
    result = CliRunner().invoke(cli, ["jobs", "list"])
    assert result.exit_code == 0
    for job in SCHEDULED_JOBS:
        assert job.id in result.output


def test_cli_rejects_invalid_param():
    """非法参数必须以退出码 2 失败，而不是带着错误值继续跑。"""
    result = CliRunner().invoke(cli, ["jobs", "asset_reconcile", "--limit=0"])
    assert result.exit_code != 0


def test_dry_run_writes_nothing(db_session):
    """dry_run=True 时不得产生任何写入。"""
    before = await _snapshot(db_session)
    await reconcile_assets(ReconcileParams(dry_run=True))
    assert await _snapshot(db_session) == before
```

### 19.11 反模式

| # | 反模式 | 后果 | 正确做法 |
|---|---|---|---|
| 1 | 一长串 `if enabled: add_job(...)` | 无法枚举、参数漂移、复制粘贴漏参 | 声明式注册表（§19.3） |
| 2 | 不设 `max_instances=1` | 上轮未完又启一轮，并发重复处理 | 默认 1，并发需写明理由 |
| 3 | 不设 `coalesce=True` | 停机恢复瞬间打出 N 倍负载 | 默认 True |
| 4 | 不设 `misfire_grace_time` | 错过即永久跳过，静默漏跑 | 按业务语义显式设置 |
| 5 | 任务函数不兜底异常 | APScheduler 中未捕获异常不冒泡，**静默失败** | 统一包裹层兜底 + 告警 |
| 6 | 任务无超时 | 一次卡死占住 `max_instances=1` 名额，之后**永不再执行** | `asyncio.timeout` + 告警 |
| 7 | 用 `BackgroundScheduler` | 独立线程，异步会话跨线程不安全 | `AsyncIOScheduler` |
| 8 | 任务写成同步 `def` | 被丢进线程池，找不到 running loop | 一律 `async def` |
| 9 | 一轮扫全表 | 数据积压时把维护变成事故 | 单轮上限 + 分批 + 断点续 |
| 10 | 靠「只部署一个实例」保证不重复 | 扩容/滚动发布时假设破产 | 分布式锁 + 幂等 |
| 11 | 锁 TTL < 任务耗时 | 锁提前失效，两实例同时跑 | TTL > 最长耗时且主动释放 |
| 12 | 用户任务逐条注册成 Job | 启动 O(N)、双份状态漂移、重启丢变更 | tick 轮询（§19.7） |
| 13 | 只监控失败率 | **任务静默停跑**永远发现不了 | 监控 `last_success_at` 陈旧度 |
| 14 | 任务里 `while True` 自循环 | 停机无法收敛 | 常驻协程与定时任务不要混用 |
| 15 | 测试里启调度器 + sleep 等触发 | 慢、不稳定、时序 flaky | 断言触发器算出的下次时刻 |
| 16 | 为手动执行另写一份脚本 | 两份实现必然漂移，且在最需要补跑的故障时刻才暴露 | 调度与 CLI 共用同一任务函数（§19.12） |
| 17 | CLI 选项与参数模型各写一份 | 改了模型忘改 CLI，症状是「传了参数不生效」 | 由参数模型自动生成 CLI 选项 |
| 18 | 任务不支持 `--dry-run` | 故障现场只能闭眼实跑 | 写操作任务必须支持 |
| 19 | CLI 恒返回退出码 0 | 编排系统/CI 误判成功 | 0=成功 / 1=业务失败 / 2=参数错误 |
| 20 | 一次性运维任务散落成独立脚本 | 无锁、无超时、无审计、无人知道存在 | 进注册表并标 `manual_only=True` |

---

## 附录 A：标准代码模板

### A.1 模型

```python
"""订单模型。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Index, JSON, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

# ── 状态枚举：单一事实来源，全项目引用此处，禁止散写字面量 ──
ORDER_STATUS_PENDING = "pending"
ORDER_STATUS_PAID = "paid"
ORDER_STATUS_CANCELLED = "cancelled"
ORDER_STATUSES = (ORDER_STATUS_PENDING, ORDER_STATUS_PAID, ORDER_STATUS_CANCELLED)
# 模型与迁移共用同一份 comment 文案，避免两处漂移
ORDER_STATUS_COMMENT = "订单状态：pending=待支付 / paid=已支付 / cancelled=已取消"


class Order(Base):
    """订单主表。user_id 引用用户中心（跨库无 FK，业务层保证引用完整性）。"""

    __tablename__ = "orders"
    __table_args__ = (
        # 专供「我的订单列表」：WHERE user_id=? AND status=? ORDER BY created_at DESC
        Index("idx_orders_user_status_created", "user_id", "status", "created_at"),
        UniqueConstraint("user_id", "biz_no", name="uq_orders_user_biz_no"),
        {"comment": "订单主表"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="订单自增主键")
    user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="下单用户ID（引用用户中心，跨库无FK）")
    biz_no: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="业务订单号，对外展示与幂等去重使用")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False,
        default=ORDER_STATUS_PENDING, server_default=ORDER_STATUS_PENDING,
        index=True, comment=ORDER_STATUS_COMMENT)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, comment="订单金额，单位元，保留4位小数")
    extra: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, comment="扩展元数据JSON")
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="软删除时间；非空即已删除，数据永久保留")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, comment="记录创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False,
        comment="记录最后更新时间")

    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan")


# 读侧统一可见性口径：软删订单对外一律不可见（当 404 处理）
ORDER_VISIBLE = Order.deleted_at.is_(None)
```

### A.2 Schema

```python
"""订单 API Schema。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OrderCreate(BaseModel):
    """创建订单请求体。"""
    biz_no: str = Field(min_length=1, max_length=64, description="业务订单号，同一用户下唯一")
    amount: Decimal = Field(gt=0, description="订单金额，单位元，必须大于 0")


class OrderOut(BaseModel):
    """订单输出。"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    biz_no: str
    status: str = Field(description=f"订单状态，取值：{'/'.join(ORDER_STATUSES)}")
    amount: Decimal
    created_at: datetime


class OrderList(BaseModel):
    """订单分页列表。"""
    items: list[OrderOut]
    total: int
    page: int
    page_size: int
```

### A.3 服务层

```python
"""订单服务层：API 与后台任务共用的单一事实来源。

事务约定：本模块只 flush 不 commit，事务边界由调用方负责。
"""
from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.models.order import Order, ORDER_STATUS_PENDING

logger = logging.getLogger(__name__)


async def create_order(db: AsyncSession, user_id: int, biz_no: str, amount) -> Order:
    """创建订单（按 user_id + biz_no 幂等）。

    幂等实现：依赖 uq_orders_user_biz_no 唯一约束，重复提交捕获 IntegrityError
    后返回已有记录，避免并发下的双写（先查后插在并发下不可靠）。
    """
    order = Order(user_id=user_id, biz_no=biz_no, amount=amount, status=ORDER_STATUS_PENDING)
    db.add(order)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await _get_by_biz_no(db, user_id, biz_no)
        if existing is None:
            raise ConflictError("订单创建冲突，请重试")
        logger.info("订单重复提交，返回已有记录 biz_no=%s user_id=%s", biz_no, user_id)
        return existing
    return order
```

### A.4 路由

```python
"""订单 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.database import get_db
from app.models.order import Order, ORDER_STATUSES, ORDER_VISIBLE
from app.models.user import User
from app.schemas.order import OrderCreate, OrderList, OrderOut
from app.services.order_service import create_order

router = APIRouter(prefix="/orders", tags=["订单"])


async def _get_owned_order(db: AsyncSession, user: User, order_id: int) -> Order:
    """按 id + 归属取订单（软删除的不返回），不存在或非本人统一 404。"""
    row = (await db.execute(
        select(Order).where(Order.id == order_id, Order.user_id == user.id, ORDER_VISIBLE)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    return row


@router.get("", response_model=OrderList, summary="订单列表")
async def list_orders(
    status: str | None = Query(default=None, description=f"状态过滤，取值：{'/'.join(ORDER_STATUSES)}"),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数，上限 100"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrderList:
    """当前用户的订单列表，按创建时间倒序。"""
    conditions = [Order.user_id == user.id, ORDER_VISIBLE]
    if status is not None:
        if status not in ORDER_STATUSES:      # 枚举白名单校验，防非法值静默返回空集
            raise HTTPException(status_code=422, detail="非法的订单状态")
        conditions.append(Order.status == status)

    total = (await db.execute(
        select(func.count()).select_from(Order).where(*conditions)
    )).scalar_one()
    rows = (await db.execute(
        select(Order).where(*conditions)
        .order_by(Order.created_at.desc(), Order.id.desc())   # 显式排序，含 id 兜底保证分页稳定
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    return OrderList(
        items=[OrderOut.model_validate(r) for r in rows],
        total=total, page=page, page_size=page_size,
    )


@router.post("", response_model=OrderOut, status_code=201, summary="创建订单")
async def create_order_api(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrderOut:
    """创建订单（按 biz_no 幂等）。"""
    order = await create_order(db, user.id, payload.biz_no, payload.amount)
    await db.commit()          # 唯一提交点
    return OrderOut.model_validate(order)
```

---

## 附录 B：新功能开发 Checklist

开发一个「新表 + 新接口」的功能，按序完成：

- [ ] **1. 分析先行**：读相关代码 → 定位边界/根因 → 列方案 → 确认后再动手
- [ ] **2. 建模**：`models/<实体>.py` 一表一文件；字段全带中文 comment；枚举提升为常量；NOT NULL 配齐 default + server_default；`__init__.py` 导出
- [ ] **3. 迁移**：手写 upgrade/downgrade；对称、幂等、方言分支；`down_revision` 接主干 head；不 import ORM 模型
- [ ] **4. Schema**：`schemas/<资源>.py`；Create/Update/Out 分开；字段带 description 与约束
- [ ] **5. 服务层**：`services/<领域>.py`；只 flush 不 commit 并在 docstring 声明；幂等实现
- [ ] **6. 路由**：显式 `response_model` + 鉴权依赖 + 归属校验 + 预加载关系 + 显式排序 + 分页上限
- [ ] **7. 注册**：`main.py` 挂载 router
- [ ] **8. 配置**：新配置项同步 `config.py` + `.env` + `.env.example`；新特性带默认关闭开关
- [ ] **9. 依赖**：新 import 的三方包写入依赖清单并注明用途/版本理由
- [ ] **10. 错误处理**：业务失败用业务异常；无 `except: pass`；错误响应不含内部细节
- [ ] **11. 日志与指标**：关键节点 INFO；失败路径有可观测出口；无敏感信息
- [ ] **12. 测试**：成功路径 + 失败路径 + 幂等 + 迁移；优先不连真实库；连库的打 `db` 标记
- [ ] **13. API 契约**：重新生成 OpenAPI 文件
- [ ] **14. 回归**：`git diff --name-only` → grep 反查 → 跑相关面；触及公共基础设施或准备合主干时补全量
- [ ] **15. 自审**：对照 16.5 检查清单逐项过一遍
- [ ] **16. 变更记录**：写入 CHANGELOG，与代码同 commit
- [ ] **17. 提交**：Conventional Commits + 统一语言；一个模块一次 commit
- [ ] **18. 发布**：迁移先行且向后兼容 → 部署 → 灰度 → 验证；明确回滚方式
- [ ] **19. 汇报**：写明跑了哪些测试、多少条、筛选条件、环境口径

---

## 附录 C：反模式清单

以下写法**评审直接打回**：

| # | 反模式 | 正确做法 |
|---|---|---|
| 1 | `except Exception: pass` | 至少 `logger.warning(..., exc_info=True)`，并捕获具体异常类型 |
| 2 | `asyncio.create_task(coro())` 不保存引用 | 用模块级 set 持有 + `done_callback` 移除 |
| 3 | 路由函数里写 100 行业务逻辑 | 下沉到 service |
| 4 | service 里 `raise HTTPException` | 抛业务异常，由 core 统一映射 |
| 5 | service 里自行 `commit()` | 只 flush，事务边界交调用方 |
| 6 | 业务口径字面量散写在多处 | 提升为模块级常量 |
| 7 | 没有 `response_model` / 用 `dict` 当响应 | 显式声明 Pydantic 模型 |
| 8 | 靠「id 不可猜」当权限控制 | 归属字段校验兜底 |
| 9 | 用客户端可控字段判权 | 用服务端权威数据判权 |
| 10 | 共享库上跑 `alembic --autogenerate` | 手写空白迁移 |
| 11 | 删 `alembic_version` 孤儿行消错 | 合入对应分支或用 merge revision |
| 12 | 改 `down_revision` 做线性化 | `alembic merge` |
| 13 | 未合主干就把迁移应用到共享库 | 先合主干再 upgrade |
| 14 | 迁移里 import ORM 模型 | 用 `sa.table()/sa.column()` 就地声明 |
| 15 | 新增 NOT NULL 列不给 `server_default` | 两个 default 都要给 |
| 16 | 字段无 comment / 英文敷衍 | 中文说明含义与取值 |
| 17 | 金额用 `Float` | `Numeric/DECIMAL` |
| 18 | 循环里查数据库（N+1） | 预加载或批量聚合 |
| 19 | 列表接口不分页 / 无上限 | 分页 + `le` 上限 |
| 20 | 分页不写 `ORDER BY` | 显式排序，含唯一列兜底 |
| 21 | 用户输入直接拼进 `order_by` | 白名单校验 |
| 22 | 异步路由里调阻塞库 | `asyncio.to_thread` 卸载 |
| 23 | 外部调用不设超时 | 显式超时 + 超时预算 |
| 24 | 报错后盲目重试 | 按错误类型判断可重试性 + 退避 |
| 25 | 按记录年龄判定任务失败 | 基于心跳/租约等真实活性信号 |
| 26 | `os.getenv` 散落在业务代码 | 统一走 Settings |
| 27 | `.env` 中同名变量重复定义 | 上线前校验重复键 |
| 28 | 敏感信息进日志/URL | 脱敏；敏感项走 body/header |
| 29 | 存活探针里查数据库 | 存活不查依赖，就绪才查 |
| 30 | 改了接口不更新 OpenAPI | 同提交重新生成 + CI 校验 |
| 31 | 只看「没报错」就判定验收通过 | 核对最终产出的完整实际内容 |
| 32 | 汇报写「测试通过」不给数据 | 写明条数与筛选条件 |

---

## 附录 D：红线速查表

> 21 条不可协商的红线。违反其中任一条，评审直接打回；已合入的须回滚。
> 这一页可单独打印贴在工位 / 放进 PR 模板。

| # | 红线 | 触犯后果 | 详见 |
|---|---|---|---|
| 1 | **改代码前必须先分析**：理解代码 → 定位根因 → 列方案 → 等确认 | 改错方向、埋雷、大规模返工 | §18.1 |
| 2 | **只改指定范围**，扩大范围须先取得确认 | 影响面失控、回滚粒度失效 | §18.2 |
| 3 | **不确定就问，不猜**；有异议要说，被重申则执行 | 做出不是对方要的东西 | §18.3 |
| 4 | **每个 ORM 模型一个文件**，聚合导出只在 `__init__.py` | 循环导入、合并冲突地狱 | §2.3 §6.2 |
| 5 | **DDL 只走迁移**，禁止手工 SQL 作为变更手段 | 环境间结构漂移、无法回滚 | §7.1 |
| 6 | **共享库禁用 `--autogenerate`** | 生成 `drop_table` 删掉别人的表，不可逆 | §7.2 |
| 7 | **迁移未合主干，禁止应用到共享/生产库** | 主干上所有 alembic 命令全阻断 | §7.5 |
| 8 | **禁止删 `alembic_version` 孤儿行、禁止改 `down_revision` 线性化** | 丢失执行事实、重复执行已生效 DDL | §7.5 |
| 9 | **每个表字段必须有中文 comment**；NOT NULL 列配齐 `default` + `server_default` | 后人无法理解、加列直接失败 | §6.2 |
| 10 | **完成实现后必须自审 + 跑相关测试**，并给出条数与筛选条件 | 「说完成了其实没验证」 | §15.2 §18.8 |
| 11 | **所有方法必须有中文 docstring**，关键行注释写「为什么」 | 三个月后没人敢动 | §4.5 |
| 12 | **新依赖必须写进依赖清单**并注明理由 | 换机器/CI 直接起不来 | §9 |
| 13 | **新配置项必须三处同步**：`config.py` + `.env` + `.env.example`（带中文注释） | 部署缺配置、他人不知道怎么配 | §8.2 |
| 14 | **fire-and-forget 任务必须用 set 持有引用** | GC 回收，任务静默丢失不报错 | §10.2 |
| 15 | **API 变更必须同提交重新生成 OpenAPI 契约** | 前后端对不上，联调返工 | §5.9 |
| 16 | **技术方案先查框架/SDK 是否原生支持**，不造轮子 | 自研缺边界处理，生产才炸 | §1.4 |
| 17 | **禁止直接对数据库执行破坏性 SQL**（UPDATE/DELETE/DROP） | 不可逆数据丢失 | §18.7 |
| 18 | **对外 ID 与权限**：归属字段兜底判权，无权限与不存在统一 404 | 越权访问、资源枚举 | §5.6 |
| 19 | **共享契约变更必须双向同步**，既有可观测行为不得单侧"修正" | 另一侧线上直接崩 | §18.5 |
| 20 | **他方资产不得擅改**；**禁止主动 push**；**禁止清空容器数据** | 越权、覆盖他人工作、数据丢失 | §18.6 §18.7 |
| 21 | **定时任务必须幂等 + `max_instances=1` + 异常兜底 + 有超时** | 并发重复处理；异常静默失败；卡死后永不再执行 | §19.4 §19.5 |

### 落地方式建议

| 红线 | 可自动化的强制手段 |
|---|---|
| 4 / 9 / 11 | 自定义 lint 规则或 CI 脚本扫描（模型文件数、`comment=` 缺失、docstring 缺失） |
| 6 / 8 | CI 检查迁移文件不含 `drop_table`（除非带豁免注释）；检查 head 数量 == 1 |
| 12 / 13 | CI 对比 `import` 与依赖清单；对比 `Settings` 字段与 `.env.example` 键 |
| 14 | ruff 自定义规则 / grep `create_task(` 后未接赋值 |
| 15 | CI 重新生成 OpenAPI 后 `git diff --exit-code` |
| 17 / 20 | 生产库账号只读化；分支保护禁止直接 push |

**原则**：能自动化的红线一律自动化，靠人记的红线迟早会破。

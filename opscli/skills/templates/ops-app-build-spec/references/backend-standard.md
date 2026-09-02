# 后端项目规范

自动初始化和改造范围限定为 FastAPI + SQLite。发现其他后端框架或任何非 SQLite 数据库时停止并联系 IT，不做自动框架或数据库转换。

本文是 `docs/开发指南/FastAPI后端开发通用规范.md` 的执行摘要。本文只给结论和不可协商的规则；需要完整论述、代码模板或反模式清单时读全文。两者冲突时以全文为准。SQLite 专项规则见 `sqlite-standard.md`，调用 opscli 的规则见 `opscli-integration-standard.md`，红线总表见 `backend-redlines.md`。

## 技术栈

| 层 | 选型 |
| --- | --- |
| Web 框架 | FastAPI |
| ASGI 服务器 | uvicorn[standard] |
| 数据校验 | Pydantic v2（禁止 `@validator`、`.dict()`、内部 `Config` 类） |
| ORM | SQLAlchemy 2.0 异步风格（`Mapped` / `mapped_column` / `select()`，禁止 1.x `Query` API） |
| 数据库 | SQLite，驱动 `aiosqlite` |
| 迁移 | Alembic，唯一 DDL 入口 |
| 配置 | pydantic-settings |
| 日志 | 标准库 `logging`，禁止 `print`，不引入第三方日志库 |
| 定时任务 | APScheduler `AsyncIOScheduler` |
| CLI | click，根目录 `cli.py` |
| 测试 | pytest + pytest-asyncio（`asyncio_mode=auto`）+ httpx.AsyncClient |
| 依赖管理 | uv + `pyproject.toml` + `uv.lock` |
| Python | 3.12，所有模块首行 `from __future__ import annotations` |

核心框架（FastAPI、SQLAlchemy、Alembic、Pydantic、uvicorn）在 `pyproject.toml` 中钉死精确版本；工具库可用 `>=`。每条依赖上方用中文注释写用途；有上下界时写明冲突来源。开发依赖放 `[project.optional-dependencies].dev`。代码 import 的每个第三方包都必须显式声明，包括原本靠传递依赖引入的。禁止依赖 git 分支或未发布版本。

## 目录

```text
backend/
├── cli.py                    # 唯一 CLI 入口：click group，只做命令聚合
├── app/
│   ├── main.py               # 应用装配：中间件、异常处理器、路由注册、lifespan
│   ├── config.py             # Settings 单例，唯一配置入口
│   ├── database.py           # 引擎、sessionmaker、get_db 依赖
│   ├── core/                 # 横切：鉴权、信封、异常、日志、分页、加解密
│   ├── models/               # ORM，一表一文件；聚合导出只在 __init__.py
│   ├── schemas/              # Pydantic 出入参
│   ├── api/v1/               # 对外接口 /api/v1
│   ├── api/internal/         # 内部接口 /internal，独立鉴权
│   ├── services/             # 业务逻辑，API 与后台任务共用
│   ├── scheduler/            # 声明式注册表 + 统一注册器 + 包裹层
│   └── cli/                  # CLI 命令实现，按组分文件（jobs / migrate / ops）
├── migrations/versions/      # Alembic 迁移，唯一 DDL 入口
├── tests/
├── scripts/
├── docs/
│   ├── 开发指南/             # 从 Skill assets/backend/docs/开发指南 复制的全文规范
│   ├── API规范/openapi.json  # 由应用生成，禁止手工编辑
│   └── CHANGELOG.md
├── AGENTS.md                 # 从 Skill assets/backend/AGENTS.md 复制
├── CLAUDE.md                 # 从 Skill assets/backend/CLAUDE.md 复制并填写
├── pyproject.toml
├── uv.lock
└── .env.example
```

`repositories/`、`tasks/`、`clients/` 按需创建，不创建空目录。单个 `services/` 或 `models/` 超过 30 个文件时升级为 `app/domains/<领域>/` 结构，两种风格不得混用。单文件体量：路由文件 500 行、服务文件 800 行、函数 80 行、路由函数体 40 行，超出即拆分。

## 分层与事务

依赖方向严格单向：`api/ → services/ → repositories/ → models/`，`schemas/` 只被 `api/` 依赖，`core/` 可被任意层依赖但不得反向 import 业务层。`services/` 不得 import `api/`；`models/` 不得 import `services/`；跨领域只调用对方 service 的公开函数。

- 路由只做：参数校验、鉴权、归属校验、调 service、提交事务、组装响应。禁止在路由写业务规则、拼多表 join、直接操作 ORM 关系。
- service 只 `flush` 不 `commit`，提交由 API handler 或任务入口收口，一个请求只有一个提交点。禁止 service 内 `rollback()` 后吞异常。
- 响应需要的关系在查询阶段 `selectinload` 预加载；写后要返回关系集合必须重新查询。禁止依赖序列化阶段触发惰性加载。
- 被两处以上引用的口径（枚举、可见性过滤、计数规则）提升为模型层常量。

## API

- 对外路径 `/api/v1/<名词复数>`，内部路径 `/internal`，破坏性变更升 `/api/v2`。Nginx 只代理 `/api/` 前缀，`/api/v1` 天然包含在内。
- 存活探针 `/health` 不查任何外部依赖；就绪探针 `/ready` 检查数据库，任一不可用返回 503。两者 `include_in_schema=False`。Compose `healthcheck` 使用 `/ready`。
- 每个路由必须：显式 `response_model`、返回类型标注、鉴权依赖、每个 `Query`/`Path`/`Body` 带中文 `description`。禁止 `dict` / `Any` 当 `response_model`。
- 列表接口固定 `page` / `page_size`（带 `le` 上限），显式 `ORDER BY` 且含唯一列兜底；排序字段和枚举过滤值走白名单。
- 无权限访问他人资源与资源不存在统一返回 404；访问控制由归属字段兜底，禁止用客户端可控字段判权。对外不直接暴露自增主键。
- 有外部副作用的 POST 必须幂等（唯一约束或 `Idempotency-Key`）。
- 统一响应信封全项目二选一，不得混用。默认方案 A：`{"code": 200, "msg": "success", "data": {...}}`，失败时 `code` 为稳定业务错误码。包裹层必须跳过 `/openapi.json`、`/docs`、`/redoc`、`304`、带 `Content-Disposition` 的文件流和非 JSON 响应，并对已是信封形状的响应幂等放行。OpenAPI 必须展示真实信封结构。
- 任何路由、请求体、响应体、状态码、参数变化后，同一次改动中从当前 app 重新生成 `docs/API规范/openapi.json`；禁止手工编辑。
- 生产环境关闭 `/docs`、`/redoc` 或加鉴权。CORS 显式白名单，禁止 `allow_origins=["*"]` 与 `allow_credentials=True` 同时使用。
- SSE 使用 `StreamingResponse(media_type="text/event-stream")`，设置 `Cache-Control: no-cache`、`X-Accel-Buffering: no`，带心跳帧，感知客户端断开；禁止在流中持有数据库会话跨越整个流生命周期。

## 异常与日志

- `core/exceptions.py` 定义 `AppError(code, message, status_code)` 基类及 `NotFoundError(404)`、`ConflictError(409)` 等子类。业务失败抛业务异常，service 层不抛 `HTTPException`。
- `main.py` 注册统一处理器：`AppError` 映射为信封；`RequestValidationError` 映射为 422；未捕获异常转 500 并记录完整堆栈与请求上下文。错误码字符串保持稳定，文案可改、码不可改。
- 错误响应不含堆栈、SQL、内部路径、连接串；日志不含密码、token、session、身份证、完整卡号。
- 禁止 `except Exception: pass`；捕获尽量窄，`raise AppError(...) from e` 保留异常链。新增失败路径必须有可观测出口（指标、落库或告警），不得只有日志。
- `logger = logging.getLogger(__name__)`；启动时显式给业务 logger 挂 handler，否则 uvicorn 只配置 `uvicorn.*` 会静默吞掉业务日志。中间件生成 `X-Request-ID` 注入 contextvar，日志携带请求追踪 ID。ERROR 级必须 `exc_info=True`。

## 配置

- 配置统一走 `app/config.py` 的 `Settings(BaseSettings)`；禁止业务代码 `os.getenv`。敏感项无默认值，`Field(..., description="...")`；非敏感项默认值仅供本地开发。
- 新配置项三处同步：`config.py` 字段与中文 `description`、`.env` 实际值、`.env.example` 脱敏示例与中文注释。删除或重命名同样三处同步。`.env` 禁止同名变量重复定义。
- 新特性带默认关闭的功能开关，关闭时行为与上线前完全一致。
- 仓库只提交 `.env.example`。密钥、Token、真实账号和生产地址不得进入源码、镜像、Compose 或文档。

## 异步与后台任务

- 异步路由禁止阻塞 IO；必要时 `asyncio.to_thread`。所有外部调用显式超时；重试只对幂等操作开启，带次数上限与指数退避。
- fire-and-forget 任务必须用集合持有引用并 `add_done_callback` 移除；禁止裸 `asyncio.create_task(coro())`。
- 定时任务四件套：声明式注册表 `SCHEDULED_JOBS`（`app/scheduler/registry.py`，禁止散写 `if enabled: add_job(...)`）；每个 Job 显式 `id`、`max_instances=1`、`coalesce=True`、`misfire_grace_time`、`replace_existing=True`，调度器级 `timezone`；任务函数 `async def`、自持会话、幂等、单轮处理量有上限；统一包裹层负责超时、异常兜底、指标与告警。调度器由 lifespan 启停，`start_scheduler()` 幂等，停机 `shutdown(wait=False)`。
- 告警必须覆盖"没跑"：监控 `now - last_success_at > 预期间隔 × 2`。多实例靠分布式锁 + 幂等，禁止拿"只部署一个实例"当保证。
- 每个任务同时可手动执行，与调度共用同一任务函数、同一包裹层、同一 Pydantic 参数模型：`python cli.py jobs list`、`python cli.py jobs run <job_id> --参数=值`、`python cli.py jobs run <job_id> --dry-run`。禁止为手动执行另写脚本。一次性运维任务也进注册表（`manual_only=True`）。退出码 0 成功、1 业务失败、2 参数错误。

## 数据库与迁移

- 一表一文件；每个字段带中文 `comment`（含义 + 取值范围）；新增 NOT NULL 列同时给 `default` 与 `server_default`；表名蛇形复数；金额、时间等类型规则按 `sqlite-standard.md`。
- 所有 DDL 只走 Alembic；模型改动、迁移文件、测试同一次提交。`upgrade` / `downgrade` 对称；DML 回填幂等；一个迁移只做一件事；迁移中不得 import ORM 模型。
- SQLite 是应用独占库，允许 `--autogenerate`，但 `env.py` 必须配置 `include_object` 只放行本项目 `Base.metadata` 的表，并开启 `render_as_batch=True`；生成后逐行审查。若数据库改为与其他系统共享，立即禁用 `--autogenerate`。
- 禁止手工 DDL、破坏性 SQL、删 `alembic_version` 孤儿行、改 `down_revision` 做线性化（多 head 只能 `alembic merge`）。
- 已有数据的库禁止通过删除数据库重新初始化。

## 测试

- 分层：单元测试不连任何外部依赖 ≥70%；集成测试连内存 SQLite ~25%；端到端 ≤5%。
- 真实连库或外部依赖的测试文件顶部 `pytestmark = pytest.mark.db`；禁止对这批用例开 `pytest-xdist`。`pyproject.toml` 声明 `db` marker。
- 默认只跑相关面：`git diff --name-only` → 用改动的模块、类、函数、路由名 grep 反查 `tests/` → 按改动类型追加。相关集为空即必须补测试。必须跑全量的三种情形：改动触及 `core/`、`config.py`、`conftest.py`、`models/__init__.py`、`main.py` 或框架升级；合入主干前；CI。
- 每个接口成功路径 + 至少一个失败路径；每个状态机流转；每个迁移；每个幂等实现；每次修 bug 补回归测试。测试库结构必须由同一套迁移建立，禁止 conftest 手写建表 SQL。
- 测试通过 `app.dependency_overrides` 替换 `get_db` 与 `get_current_user`，测试后 `clear()`。
- 汇报口径必须写明跑了哪些测试、通过多少条、筛选条件、在什么环境。

## 容器运行

- 基于官方 Python 镜像构建，锁定明确的 Python 主次版本。
- 先精确复制 `pyproject.toml`、`uv.lock`，执行 `uv sync --locked --no-install-project --no-dev`，再精确复制 `backend/` 源码完成安装。禁止无边界的 `COPY . .`。
- 使用 BuildKit cache mount 缓存 `/root/.cache/uv`。
- exec 形式启动命令，绑定 `0.0.0.0`，容器内端口固定 `8000`。
- 以非 root 用户运行；镜像中不包含开发缓存、测试产物、数据库文件或 `.env`。
- SQLite 路径从环境变量读取，容器默认 `/data/app.db`，卷由 Compose 管理。

## 验收

- `uv sync --locked`、`ruff format --check`、`ruff check`、`mypy app/` 和测试通过。
- `/health`、`/ready`、核心 API、校验错误和异常响应通过测试。
- `docs/API规范/openapi.json` 与当前 app 一致（重新生成后 `git diff --exit-code`）。
- 容器重启后 SQLite 数据仍存在。
- 前端经 Compose 网络可以访问 API，浏览器请求不受错误 CORS 配置阻断。
- 日志中不出现密钥、完整鉴权头或敏感请求体。

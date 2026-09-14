# 后端红线总表

本表合并 `docs/开发指南/` 下的 AI 通用规则、`FastAPI后端开发通用规范.md` 附录 D 的红线和 `SQLite数据库使用通用规范.md` 的硬性规则，去重后统一编号。违反任一条评审直接打回，已合入的须回滚。

本文件是普通后端开发、前后端合同变更和后端评审的强制入口。

当前 AppHub 基线以 `backend/app.py`、`docs/apphub-contract.md`、实际路由、Pydantic Schema 和生成的 OpenAPI 为准。路由只做鉴权、参数校验、协议转换和事务收口；单个 FastAPI 进程托管 API 和前端构建产物；依赖沿用目标项目现有依赖清单；AppHub SQLite 应用保持单写实例。OPS 只使用模板已有的 viewer、session 或 local 网关。用户未授权时不得安装依赖、启动服务、写数据库、提交、推送或部署。

效力层级：项目 `backend/CLAUDE.md` 是唯一入口，写红线与项目特化信息；通用条款冲突时以根目录 `docs/开发指南/` 下的全文为准；`AGENTS.md` 只做引用指向。

## 一、执行纪律

| # | 红线 | 全文出处 |
| --- | --- | --- |
| 1 | 改代码前先分析：理解代码 → 定位根因 → 列方案 → 等待确认。对方只描述现象未要求修改时不得直接改。 | FastAPI §18.1 |
| 2 | 只改指定范围；扩大范围须先说明原因并取得确认；范围内工作全部做完，阻塞部分明确说明。 | FastAPI §18.2 |
| 3 | 不确定就问，不猜；保持独立判断，不合理的要求要指出；被重申后视为对方决策并说明风险。 | FastAPI §18.3 |
| 4 | 技术方案先查框架或 SDK 原生能力，有官方方案禁止造轮子；确认不支持须写明查证结论与位置。 | FastAPI §1.4 |
| 5 | 完成实现后必须自审并跑相关面测试，汇报写明测试数量、筛选条件与环境；没有审查和测试不得说完成。 | FastAPI §15.2 §18.8 |
| 6 | 相关面回归是默认动作，全量只在三种情形：触及公共基础设施、合入主干前、CI。相关集为空必须补测试。 | FastAPI §15.2 |
| 7 | 他方资产不得擅改：用户上传内容、业务方配置脚本、第三方仓库、他团队模块，即使本地有副本。 | FastAPI §18.6 |
| 8 | 跨系统共享契约双向同步；既有可观测行为不得单侧修正。 | FastAPI §18.5 |
| 9 | 禁止主动 `git push`；未明确要求不得用容器启动业务服务；任何时候不得清空容器数据与卷；开发测试必须在虚拟环境。 | FastAPI §18.7 |
| 10 | 禁止提交任何密钥或凭证，包括测试环境的。 | FastAPI §13 |
| 11 | commit 前更新变更记录并与代码同一次 commit；commit message 遵循 Conventional Commits 且描述中文；禁止试错流水账提交。 | FastAPI §16 |

## 二、代码与架构

| # | 红线 | 全文出处 |
| --- | --- | --- |
| 12 | 分层依赖严格单向；路由不写业务逻辑；service 只 `flush` 不 `commit`，一个请求只有一个提交点。 | FastAPI §3.1 §3.3 |
| 13 | 每个 ORM 模型独立文件，聚合导出只在 `models/__init__.py`；禁止 `models.py` 式聚合文件。 | FastAPI §2.3 §6.2 |
| 14 | 所有方法必须有中文 docstring，关键行注释写"为什么"；踩坑修复处注明日期、现象、根因。 | FastAPI §4.5 |
| 15 | 响应需要的关系在查询阶段预加载；禁止依赖序列化阶段触发惰性加载。 | FastAPI §3.4 |
| 16 | 被两处以上引用的业务口径提升为模型层常量，禁止散写字面量。 | FastAPI §3.5 |
| 17 | 每个路由显式 `response_model`、返回类型、鉴权依赖、参数中文 `description`；禁止 `dict` / `Any` 当 `response_model`。 | FastAPI §5.2 |
| 18 | 访问控制由归属字段兜底，禁止客户端可控字段判权；无权限与不存在统一 404；对外不直接暴露自增主键。 | FastAPI §5.6 §5.7 |
| 19 | 列表接口必须分页且显式 `ORDER BY` 含唯一列兜底；排序字段与枚举过滤值走白名单。 | FastAPI §5.4 |
| 20 | 有外部副作用的 POST 必须幂等。 | FastAPI §5.8 |
| 21 | API 变更同一次改动中从当前 app 重新生成 OpenAPI 契约；禁止手工编辑契约文件。 | FastAPI §5.9 |
| 22 | 统一响应信封全项目二选一不得混用；包裹层跳过文档、304、文件流、非 JSON 响应并幂等放行。 | FastAPI §5.3 |
| 23 | 禁止 `except Exception: pass` 与静默降级；业务失败抛带稳定错误码的业务异常，service 不抛 `HTTPException`。 | FastAPI §11 |
| 24 | 错误响应不含堆栈、SQL、内部路径、连接串；日志不含密码、token、session、身份证、完整卡号。 | FastAPI §11 §12 |
| 25 | 新增失败路径必须有可观测出口（指标、落库或告警），不得只有日志。 | FastAPI §12.2 |
| 26 | 日志只用标准库 `logging`，禁止 `print`；启动时显式挂 handler；ERROR 必须 `exc_info=True`。 | FastAPI §12.1 |
| 27 | 异步路由禁止阻塞 IO；所有外部调用显式超时；重试只对幂等操作开启并带上限与退避。 | FastAPI §10.1 §10.3 |
| 28 | fire-and-forget 任务必须用集合持有引用；禁止裸 `create_task`。 | FastAPI §10.2 |
| 29 | 后台任务失败判定基于真实活性信号，不得仅按记录年龄。 | FastAPI §10.3 |
| 30 | 配置统一走 Settings，禁止业务代码 `os.getenv`；新配置项三处同步；`.env` 禁止同名变量重复定义；新特性带默认关闭的开关。 | FastAPI §8 |
| 31 | 代码 import 的三方包必须写进目标项目现有依赖清单并注明用途与版本约束理由；核心框架钉死精确版本；禁止依赖 git 分支。 | FastAPI §1.2 §9 |
| 32 | 生产关闭 `/docs`、`/redoc` 或加鉴权；CORS 显式白名单，禁止 `*` 与 `allow_credentials=True` 同时使用；内部接口独立密钥鉴权且不暴露公网。 | FastAPI §13 |

## 三、定时任务

| # | 红线 | 全文出处 |
| --- | --- | --- |
| 33 | 任务声明集中在声明式注册表 `SCHEDULED_JOBS`，禁止散写 `if enabled: add_job(...)`。 | FastAPI §19.3 |
| 34 | 每个 Job 显式 `id`、`max_instances=1`、`coalesce=True`、`misfire_grace_time`、`replace_existing=True`，调度器级 `timezone`；禁止依赖默认值。 | FastAPI §19.4 |
| 35 | 任务函数 `async def`、自持会话、幂等、单轮处理量有上限；禁止任务里 `while True`。 | FastAPI §19.6 |
| 36 | 统一包裹层负责超时、异常兜底、指标与告警；告警覆盖"没跑"而不只是"跑失败"。 | FastAPI §19.9 |
| 37 | 多实例靠分布式锁加幂等，禁止拿"只部署一个实例"当保证。 | FastAPI §19.5 |
| 38 | 每个任务同时可 `python cli.py jobs run <id>` 手动执行，与调度共用同一函数、包裹层、参数模型；禁止另写脚本；写操作任务支持 `--dry-run`；退出码 0/1/2。 | FastAPI §19.12 |

## 四、数据库与迁移

| # | 红线 | 全文出处 |
| --- | --- | --- |
| 39 | 所有 DDL 只走 Alembic；禁止手工 DDL；模型改动、迁移、测试同一次提交。 | FastAPI §7.1 |
| 40 | 共享库禁用 `--autogenerate`；独占库使用时必须配置 `include_object` 并逐行审查。 | FastAPI §7.2 |
| 41 | 迁移先合主干再应用到共享或生产库；禁止删 `alembic_version` 孤儿行；禁止改 `down_revision` 做线性化。 | FastAPI §7.5 |
| 42 | `upgrade` / `downgrade` 对称且带 docstring；每列中文 comment；DML 幂等；一个迁移一件事；迁移中不得 import ORM 模型。 | FastAPI §7.3 |
| 43 | 字段必须带中文 comment（含义 + 取值范围）；新增 NOT NULL 列同时给 `default` 与 `server_default`。 | FastAPI §6.2 |
| 44 | 禁止对生产或共享库直接执行 UPDATE、DELETE、DROP 作为变更手段；数据修复先确认影响范围、留备份、经确认。 | FastAPI §18.7 |
| 45 | 禁止 N+1、循环内单条写、裸 SQL 字符串拼接；SQL 全部参数化，表名列名白名单。 | FastAPI §6.6 |
| 46 | 环境口径必须诚实：本地库或隔离环境的验证不得说成"测试环境验收通过"。 | FastAPI §7.6 |

## 五、SQLite 专项

| # | 红线 | 全文出处 |
| --- | --- | --- |
| 47 | 库文件路径只来自配置且是绝对路径；落在持久卷；禁止镜像层、代码目录、`/tmp`、网络文件系统。 | SQLite §1.1 |
| 48 | 每个连接注入 PRAGMA 基线（WAL、`foreign_keys=ON`、`busy_timeout`），SQLAlchemy 下挂 `connect` 事件。 | SQLite §1.2 §1.5 |
| 49 | 写事务以 `BEGIN IMMEDIATE` 开始；事务要短；禁止事务内网络调用。 | SQLite §1.3 §4.2 |
| 50 | 任何时刻只能有一个写者；AppHub SQLite 应用保持单写实例；禁止多实例同时写同一库。 | SQLite §5 |
| 51 | 禁止 `async def` 中直接调同步 `sqlite3`；写路径串行化。 | SQLite §6 |
| 52 | 金额用 `INTEGER` 最小单位，禁止 `REAL`；时间统一 UTC 且只用一种表示；禁止 `VARCHAR(n)`、`DECIMAL`、`DATETIME`、`BOOLEAN` 类型名。 | SQLite §2.2 §2.3 |
| 53 | 禁止应用代码 `CREATE TABLE IF NOT EXISTS`；`init_database()` 只做建目录、连通性校验、执行迁移。 | SQLite §1.4 §3.1 |
| 54 | Alembic 必须 `render_as_batch=True`；重建表迁移显式重建索引触发器并跑 `foreign_key_check`。 | SQLite §3.5 §3.6 |
| 55 | 禁止 `cp` 活动库文件；备份只用 `Connection.backup()` 或 `VACUUM INTO`；恢复前先备份现场。 | SQLite §7 |
| 56 | 库文件 0600、目录 0700；禁止用户输入拼进 `PRAGMA` 或 `ATTACH DATABASE`。 | SQLite §8 |
| 57 | 测试库结构由同一套迁移建立，禁止 conftest 手写建表 SQL；禁止只靠 SQLite 验证并发、性能、方言。 | SQLite §9 |

## 六、opscli 接入

| # | 红线 | 全文出处 |
| --- | --- | --- |
| 58 | OPS 业务通过模板已有的 viewer、session 或 local 网关按请求注入；禁止自行构造 Manager、模块级凭证单例或缓存 `ExplicitCredentials`。 | OPSCLI_SDK调用规范 §1.1 §3.2 §4.2 |
| 59 | 禁止手拼 `Authorization` 头、直接读取 `credentials.bin` 或 Keychain、硬编码 token、用环境变量偷传 JWT。 | OPSCLI_SDK调用规范 §1.3 §4.2 |
| 60 | 凭证不落盘、不写日志、不进异常文本；定位时只用前 6 位摘要。 | OPSCLI_SDK调用规范 §7.2 |
| 61 | 按 `AuthError` / `QueryError` 等模块基类捕获并保留 code；`NotAuthenticatedError` 只提示登录或改为显式传参，禁止自动重试登录。 | OPSCLI_SDK调用规范 §7.2 |
| 62 | 调用 opscli REST 必须检查 `success` 字段；401 永不重试；查询 payload 禁止手写 `userEmail`、`from.table`、`from.permission`。 | OPSCLI_API调用规范 §3 §4 |

## 七、AppHub 第三方取数

| # | 红线 | 全文出处 |
| --- | --- | --- |
| 63 | Keepa、SellerSprite 只使用请求级 `ThirdPartyApiClient`，通过 `Depends(get_query_credentials)` 复用模板已校验的 `QueryCredentials`；禁止重写模板鉴权或缓存跨请求凭证。 | data-access-standard §4 |
| 64 | `viewer` 只发送 `X-Ops-Token` 与可信 `X-User-*`，`session` 只发送 `X-Session-Id` 与已有可选 Bearer JWT，`local` 只通过 `AuthClient` 标准方法转换为 Session/JWT Header；禁止盲目透传 Header、Cookie、请求体凭证和模式回退。 | data-access-standard §4 |
| 65 | OPS viewer、Keepa 和 SellerSprite 只读取 `OPSCLI_MCP_REST_API_BASE_URL`，生产与预发布由部署环境显式注入；只调用 `/api/v1/*` REST，禁止默认环境、共享 API Key、provider 专属 Base URL 和旧变量回退。 | data-access-standard §5 |
| 66 | `third_party_source_snapshot` 与 `third_party_async_job` 的读写、索引、UPSERT 和 pending 复用必须包含 `owner_user_id`，唯一键固定为 `UNIQUE(owner_user_id, provider, request_hash)`。 | data-access-standard §5 |
| 67 | SellerSprite HTTP 202 只表示受理；`queued/running` 继续轮询，`succeeded` 读取 JSON，`failed/cancelled` 停止；Listing Analysis 禁止提交到普通 jobs。 | data-access-standard §5 |

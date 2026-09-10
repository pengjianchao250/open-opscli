# OPS App 建站取数指引需求定稿

> 日期：2026-09-08  
> 状态：已确认，进入实现  
> 主 Skill：`ops-app-data-builder`；路由 Skill：`ops-app-build-spec`

## 1. 背景与目标

标准 AppHub 页面需要把业务需求转换为可持续运行的数据产品、站点 API、加工逻辑、存储边界和测试合同。`OPS数据集查询与应用资料包` 补充了查询模式、固定同步、跨数据集组合和结果验收经验，但其中包含 2026-08-02 的静态目录和查询 Skill 副本，不能整体复制为新的事实源。

本次目标：

1. 为标准 AppHub 应用页面提供统一取数模式判定和数据产品设计指引。
2. 明确单次查询、引导查询、访问者实时查询和经过批准的系统同步边界。
3. 由 `ops-app-data-builder` 把已验证合同落入 `data-spec.md`、FastAPI、QueryGateway、SQLite、前端 API 和测试。
4. 保持在线元数据、`ops-dataset-query` 和 `ops-query-wizard` 为查询事实源。

## 2. 非目标

- 不修改或复制 `ops-dataset-query`、`ops-query-wizard` 的规则与实现。
- 不复制字段目录、授权目录、Excel、真实结果或历史技术别名。
- 不新增 OPS 无人值守同步任务、系统账号、调度器或后台 worker。
- 不允许复用访问者 `X-Ops-Token` 建立站点共享数据集。
- 不接管已绑定 Dashboard 页面；该场景继续使用 `ops-dashboard-*` Skill。

## 3. 职责分层

- `ops-app-build-spec`：识别数据需求并路由，不猜数据集、字段、聚合和筛选。
- `ops-app-data-builder`：判断取数模式、拆数据产品、组织合同验证并生成数据层。
- `ops-dataset-query`：需求清晰时负责在线选表、字段校验、口径和少量样本。
- `ops-query-wizard`：需求缺参、歧义或结果疑似错误时负责澄清和纠错。

## 4. 取数模式

| 模式 | 场景 | 处理 |
| --- | --- | --- |
| `one-off-query` | 临时核数、分析或导出 | 退出本 Skill，交给查询 Skill |
| `guided-query` | 合同仍有歧义 | 先使用 `ops-query-wizard` |
| `viewer-live` | 页面按访问者权限实时查询 | 使用标准 `ViewerQueryGateway` |
| `viewer-private-persisted` | 保存当前用户历史或加工结果 | 按可信 `owner_user_id` 隔离 |
| `approved-system-sync` | 页面/API/数据库需要固定同步 | 仅有批准的系统适配器时允许 |
| `reference-only` | 静态资料用于发现 | 只形成候选，必须在线验证 |

标准模板当前不自动提供无人值守系统身份。缺少批准适配器时，`approved-system-sync` 必须标记为 `blocked`。

## 5. 合同与输出

每个数据产品必须记录用途、消费者、取数模式、来源状态、字段、筛选、时间、粒度、自然键、快照、新鲜度、分页、身份、存储、站点 API、测试和阻塞项。来源状态为：

- `candidate`：依据业务域或静态资料发现，尚未在线验证。
- `verified`：已由当前身份在线元数据和少量真实查询确认。
- `blocked`：无权限、字段不完整、适配器缺失或合同无法确认。

静态资料不能将状态提升为 `verified`。快照不跨日累计，比率不能直接求和，币种不能混加，`0`、`null`、空字符串和零行分别处理。查询组件只用于枚举和筛选，不作为业务结果。

`docs/ops-app/data-spec.md` 必须记录页面与数据产品、取数模式、候选和验证证据、合同状态、身份与运行时路径、`app.yaml.opscli.datasets`、分页和新鲜度、API、加工、存储、测试和阻塞项。

## 6. 实施与验收

新增 `ops-app-data-builder/references/ops-dataset-application-guide.md`，并更新 Data Builder、Build Spec 路由、版本、manifest、eval 和契约测试。

验收要求：能区分六种模式；单次查询和 Dashboard 页面不误触发；只有在线验证后才能标记 `verified`；OPS 默认保持 `ViewerQueryGateway` 和 `owner_user_id` 隔离；缺少批准适配器时固定同步必须阻塞；查询 Skills 文件保持不变。

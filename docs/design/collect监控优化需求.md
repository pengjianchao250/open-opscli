# collect 监控优化 PRD

> 状态：分期方案；当前交付覆盖共享路径、Bundle 启动隔离、同步手动探测，以及默认关闭的固定关键词反查场景测试。服务级事故、feedback、趋势与恢复动作仍为后续范围。
> 依赖：[collect 监控优化调研](../analysis/collect监控优化调研.md)

## 1. 背景

SellerSprite collect 调用在队列数据库无法打开时直接失败，任务没有进入队列。现有 Collector Monitor 已能观察入队后的积压、停滞、孤儿任务和 worker 容量，但生产尚未启用，且无法对入队前数据库故障告警。

本期目标是让“服务能否接单、队列是否可写、调度器是否消费、任务是否推进、用户是否集中反馈”形成一条可观测链路。

## 2. 产品目标

1. 队列数据库不可打开后 60 秒内在 Monitor 中形成明确事故。
2. Collector 整体不可达、Bundle 不可接单、队列不可读写能被区分。
3. 运维可以在页面或 CLI 发起一次安全的即时探测并看到结果。
4. 生产部署能提前发现 HOME、路径、权限和挂载错误。
5. 反馈数据只以脱敏聚合信号辅助排查，不泄露用户或请求内容。

## 3. 非目标

- 不提供任意 MCP Tool、任意场景、已有任务重新提交、取消或强制重排。
- 不把 Monitor 变成浏览器/账号控制台。
- 不读取或展示 `request_json`、用户邮箱、账号、凭据、绝对结果路径。
- 不以 feedback 代替真实健康探测。
- 不在本期引入 Prometheus、Grafana 或 Sentry 服务依赖。

## 4. 用户与场景

### 4.1 值班运维

- 服务告警后快速判断是 Collector 不在线、数据库不可用、调度器无容量还是单任务卡住。
- 修复权限或挂载后点击“立即探测”，确认恢复，无需提交真实业务任务。

### 4.2 开发人员

- 查看事故时间线、稳定错误码、版本、最后成功时间和相关 feedback 数量。
- 区分根因事故与派生任务异常，避免重复排查。

### 4.3 业务支持

- 只查看服务影响范围和恢复状态，不接触敏感任务参数。

## 5. 功能需求

### FR-1 统一队列路径合同（P0）

- 增加显式队列数据库路径配置。
- Collector 写端与 Monitor 读端必须调用同一解析/规范化逻辑。
- 启动摘要只展示路径指纹或逻辑存储 ID，不回显绝对路径到远端 UI。
- 部署检查必须验证两端 path identity 一致。

当前切片已完成前两项，并通过冲突配置拒绝路径漂移；路径指纹和独立部署校验命令随生产启用门禁后续交付，不视为本次已实现能力。

### FR-2 Collector 启动与就绪分层（P0）

- Collector transport 存活与 SellerSprite Bundle ready 分开。
- Bundle 初始化失败时，业务工具拒绝接单并返回稳定错误码；健康工具仍可用。
- startup check 至少包含父目录、数据库连接、schema、WAL/SHM 写能力、调度器心跳初始化。
- systemd 仍可按策略重启，但不能只依赖重启循环表达健康。

### FR-3 新增服务级事故（P0）

新增规则：

| 规则 | 严重度 | 触发 |
|---|---|---|
| `queue_database_unavailable` | critical | Collector 自报队列写失败或 Monitor 只读打开失败 |
| `collector_unavailable` | critical | 外部探测连续失败 |
| `collector_not_ready` | high | 服务可达但关键 Bundle 不可接单 |
| `monitor_state_unavailable` | critical | Monitor 私有状态库不可写 |
| `feedback_failure_spike` | medium/high | 同签名反馈在窗口内超过阈值，仅辅助告警 |

- 服务级事故必须有连续失败阈值，默认 2 次。
- 恢复默认要求连续成功 2 次。
- `queue_database_unavailable` 活动时抑制同根因的 queue/worker/task 通知，但保留受影响计数。

### FR-4 立即探测（P0）

- UI 增加“立即探测”命令按钮。
- CLI 增加等价 probe 命令。
- 探测只执行健康读与安全预检，不提交真实业务任务、不写任务表。
- 首期同步返回：目标、探测时间、状态、稳定错误码和错误类；不持久化探测历史。
- 同一目标最短间隔 10 秒，最多 1 个并发探测。
- UI 明确展示 running/succeeded/failed/timeout 状态，并允许再次探测。
- Collector UI 可接受 MCP API Key；默认仅用于下一次请求并在发送后清空，用户也可主动选择以明文保存到当前浏览器 `localStorage`，取消选择立即删除。两种模式均不写服务端配置、日志、缓存或状态库，`401/403` 映射为 `COLLECTOR_AUTH_FAILED`。

### FR-4.1 关键词反查场景测试（P0）

- 新增独立“场景测试”Tab，仅允许 `keyword-reverse`（关键词反查）。
- 默认关闭；仅在 `OPSCLI_COLLECTOR_MONITOR_SCENARIO_TEST_ENABLED=true` 且 Collector MCP 地址已配置时可用。
- ASIN 必填；站点、周期和 `page_size` 可修改，服务端固定 `export_format=json`。
- 提交前必须确认会创建真实任务并消耗额度；同一时间只允许一个提交，完成后冷却 10 秒。
- 必须提供页面 API Key，并通过 `Authorization: Bearer` 调用；Key 必须具有 `seller_sprite_run` 权限。真实场景不得回退借用 Monitor 的受保护 Key 文件，该文件只用于 Collector 探测。
- Collector 地址必须使用 HTTPS；仅同机回环地址允许 HTTP。ASIN 使用 10 位 ASCII 字母数字，站点限制为卖家精灵支持列表。
- Monitor 页面地址同样只允许 HTTPS 或明确回环 HTTP，避免浏览器到 Monitor 之间明文传输 Key。
- 成功仅返回 `job_id`、`state`、固定场景和提交时间，随后可在任务 Tab 跟踪。
- 不自动重试。等待超时必须报告 `scenario_outcome_unknown`，提示先查任务列表，禁止引导重复提交。

### FR-5 队列监督增强（P0/P1）

- 保留现有六种任务健康分类。
- 增加排队总量、最老排队年龄、running 数、可用容量、领取速率和完成速率。
- 增加最近 15 分钟趋势，先使用 Monitor 私有库的有界聚合点。
- 不保存业务请求内容。

### FR-6 feedback 关联（P1）

- `ops-feedback-query` companion 定时生成脱敏快照，Monitor 不持有查询密钥。
- Monitor 展示最近窗口内的反馈总量、失败调用量、Top 错误签名和趋势。
- incident 详情显示 `related_feedback_count`、`last_feedback_at`、`max_feedback_severity`。
- 默认不展示反馈 UUID；完整详情仍通过内部 feedback 工具按权限查询。
- 快照过期或读取失败不得影响 Collector/队列健康判定。

### FR-7 通知与静默（P1）

- 服务级事故与任务级事故使用同一状态机。
- 支持按规则和时间窗口静默，静默必须记录创建人、原因和过期时间。
- 维护静默只停止通知，不伪造健康状态。
- 通知显示根因、影响范围、首次时间、持续时间和 Monitor 链接，不显示敏感字段。

### FR-8 生产启用与自检（P0）

- 提供可重复执行的安装/校验流程。
- 部署前校验 Collector/Monitor 路径一致、服务账号权限、状态库写权限、端口和 API Key 文件权限。
- 上线顺序：无通知观察、阈值校准、通知 dry-run、正式通知。
- 回滚只停止 Monitor，不修改业务队列。

## 6. “重试”产品边界

| 动作 | 首期 | 原因 |
|---|---|---|
| 重新探测服务 | 支持 | 幂等、低风险、不创建业务任务 |
| 重新读取队列快照 | 支持 | 只读、可限频 |
| 重新初始化 Bundle | P2 | 需要运维权限、审计、并发保护 |
| 重启 Collector 进程 | P2/外部运维 | 应由 systemd/部署平台控制 |
| requeue 已存在且租约过期任务 | P2 | 需幂等与代际 CAS |
| 重试未入队请求 | 不支持 | 原请求未持久化，Monitor 不应持有敏感参数 |
| 发起固定关键词反查测试任务 | 显式开关后支持 | 用已确认的测试参数验证鉴权、入队和调度链路，不等同于重试原请求 |

## 7. 成功指标

- 数据库不可打开事故发现时间 P95 <= 60 秒。
- Monitor 首月关键事故漏报为 0。
- 同一根因通知压缩率 >= 80%。
- 手工探测 P95 <= 5 秒，超时有明确结果。
- 生产路径漂移在发布前检查中被阻止。
- Monitor API/UI 敏感字段泄露测试持续为 0。

## 8. 验收标准

1. 队列路径指向目录、不可写目录、只读文件系统、schema 损坏均有稳定错误码测试。
2. Collector Bundle 初始化失败时，健康接口仍能报告 `not_ready`，业务调用不能入队。
3. 独立 Monitor 在 Collector 整体下线时产生并恢复 `collector_unavailable`。
4. 数据源错误和 Collector 错误会形成事故并通知，不只停留在页面摘要。
5. “立即探测”不会增加任务表、MCP run 表或业务输出目录内容。
6. feedback 快照断开时 Monitor 仍可正常扫描队列。
7. 根因抑制、连续失败、连续恢复与静默均有状态机回归测试。
8. 安装校验在当前文档错误路径场景下必须失败并给出修复建议。
9. 场景测试默认关闭，不能调用任意工具；401、403、冷却和结果未知均返回稳定错误码且不泄露 Key。

# MCP 场景调用统计设计

## 目标

所有通过 `InstrumentedMcpProxy` 注册的 MCP Tool 统一记录低敏场景维度，支持按服务、场景、接口、结果和调用方统计次数。该统计描述逻辑 Tool 调用，不等同于供应商 HTTP 请求次数或计费单位。

## 事件维度合同

MCP 遥测事件的 `dimensions` 使用以下固定结构：

```json
{
  "schema_version": 1,
  "service": "seller_sprite",
  "operation": "seller_sprite_run",
  "endpoint": "/v1/keyword-reverse",
  "runtime_role": "executor",
  "scenario": "keyword-reverse",
  "site": "US",
  "period": "30d"
}
```

必有字段：

- `schema_version`：维度合同版本。
- `service`：注册清单中的准确模块名。
- `operation`：MCP Tool 名。
- `runtime_role`：`executor` 为真实执行入口，`gateway_proxy` 为网关代理入口。

可选字段：

- `scenario`：场景标识。从 Tool 调用参数的 `scenario`、`feature`、`function`、`target` 提取。
- `endpoint`：实际上游接口的短名称或规范路径，由服务注册的低敏解析器从调用参数解析；不记录完整 URL、凭证或请求参数。
- `site/domain/geo`：站点或地域。
- `period`：周期。
- `provider`：数据提供方。
- `target`：场景目标类型。

遥测不记录 JWT、Session、ASIN、关键词、请求参数对象、输出路径等内容。

## 计数口径

场景调用次数只统计：

```text
event_type = mcp_tool
runtime_role = executor
```

`gateway_proxy` 用于排查网关链路，不进入实际场景调用总数。公共遥测和 MySQL 表只记录调用事实，`status` 固定为 `called`；公共层不读取 Tool 返回值，也不判断成功、失败、无数据或额度不足。上述业务状态由各服务自己的业务记录维护，不从公共调用表推导。

## MySQL 查询示例

统一 MCP 服务可将事件旁路写入当前采集库的 `mcp_call_events` 表。该表已经把用户、服务、场景和接口拆成列，查询不再依赖 JSON 路径。计数只统计 `runtime_role = 'executor'`，并按 UTC 时间过滤（北京时间本周边界请先换算为 UTC）：

启用配置：

```text
OPSCLI_MCP_TELEMETRY_MYSQL_ENABLED=true
OPSCLI_COLLECTION_MYSQL_HOST=<host>
OPSCLI_COLLECTION_MYSQL_DATABASE=polaris_ops_mcp
OPSCLI_COLLECTION_MYSQL_USER=<writer>
OPSCLI_COLLECTION_MYSQL_PASSWORD=<secret>
```

首次部署可临时使用 `OPSCLI_MCP_TELEMETRY_MYSQL_AUTO_CREATE_SCHEMA=true` 自动创建表；生产环境建议由迁移账号执行 DDL 后关闭该开关。

已按旧版本建表的数据库无需删表或重建；写入器会将兼容字段 `status` 固定写为 `called`，不写入业务成功/失败状态。

已按更早版本建表且未启用自动建表时，部署迁移账号可执行以下幂等前置迁移（字段/索引已存在时忽略对应错误）：

```sql
ALTER TABLE mcp_call_events ADD COLUMN endpoint VARCHAR(128) NULL;
ALTER TABLE mcp_call_events
    ADD KEY ix_mcp_call_events_service_endpoint_time (service, endpoint, occurred_at);
```

按用户、服务、场景、Tool 和上游接口统计：

```sql
SELECT
    COALESCE(user_email, '(unknown)') AS user_email,
    service,
    COALESCE(scenario, '(未归类)') AS scenario,
    operation,
    COALESCE(endpoint, '(未解析)') AS endpoint,
    COUNT(*) AS calls
FROM mcp_call_events
WHERE event_type = 'mcp_tool'
  AND runtime_role = 'executor'
  AND occurred_at >= :week_start_utc
  AND occurred_at < :next_week_start_utc
GROUP BY user_email, service, scenario, operation, endpoint
ORDER BY service, user_email, calls DESC;
```

全服务总计（查看 Keepa、卖家精灵、Google Trends、鹰眼等服务是否都有记录）：

```sql
SELECT service, COUNT(*) AS calls
FROM mcp_call_events
WHERE runtime_role = 'executor'
  AND occurred_at >= :start_utc
  AND occurred_at < :end_utc
GROUP BY service
ORDER BY calls DESC;
```

第三方上游工具的 `service` 为 `external_<server_id>`，例如鹰眼配置的 `server_id=pnd` 时为 `external_pnd`。

### Keepa 按用户和场景统计

```sql
SELECT
    COALESCE(user_email, '(unknown)') AS user_email,
    COALESCE(scenario, '(未归类)') AS scenario,
    COUNT(*) AS calls
FROM mcp_call_events
WHERE event_type = 'mcp_tool'
  AND service = 'keepa'
  AND runtime_role = 'executor'
  AND occurred_at >= :start_utc
  AND occurred_at < :end_utc
GROUP BY user_email, scenario
ORDER BY calls DESC, user_email, scenario;
```

邮箱来自已经验证的 MCP 请求上下文；本地 stdio 模式会从当前凭证恢复。确实无法识别邮箱的调用保留为 `NULL`，查询中显示为 `(unknown)`，不得与其他用户合并为某个真实邮箱。

## 边界

- 遥测当前为非阻塞发送，网络异常会丢弃，因此适合产品使用分析和容量趋势，不作为财务结算唯一依据。
- 一个场景可能产生多次供应商 HTTP 请求；真实上游请求次数应在各 HTTP Client seam 另记请求事件。
- 一个场景可能消耗多个供应商计费单位；计费单位应由额度结算层单独记录，不能从场景调用次数推算。

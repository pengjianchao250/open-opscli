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

- `scenario`：场景标识。依次从规范化结果和调用参数的 `scenario`、`feature`、`function`、`target` 提取。
- `site/domain/geo`：站点或地域。
- `period`：周期。
- `provider`：数据提供方。
- `target`：场景目标类型。

遥测不记录 JWT、Session、ASIN、关键词、请求参数对象、输出路径等内容。

## 计数口径

场景调用次数只统计：

```text
event_type = mcp_tool
dimensions.runtime_role = executor
```

`gateway_proxy` 用于排查网关链路，不进入实际场景调用总数。`status=error` 同时覆盖 Tool 抛出的异常和统一响应中的 `success=false`。

## MySQL 查询示例

当前遥测接收端会把完整事件保存到 `opscli_telemetry.raw_payload` JSON。以下查询按北京时间自然周统计执行端场景调用：

```sql
SELECT
    user_email,
    JSON_UNQUOTE(JSON_EXTRACT(raw_payload, '$.dimensions.service')) AS service,
    JSON_UNQUOTE(JSON_EXTRACT(raw_payload, '$.dimensions.scenario')) AS scenario,
    JSON_UNQUOTE(JSON_EXTRACT(raw_payload, '$.dimensions.operation')) AS operation,
    COUNT(*) AS calls,
    SUM(status = 'success') AS successes,
    SUM(status = 'error') AS failures,
    ROUND(AVG(duration_ms)) AS avg_duration_ms
FROM opscli_telemetry
WHERE event_type = 'mcp_tool'
  AND JSON_UNQUOTE(
      JSON_EXTRACT(raw_payload, '$.dimensions.runtime_role')
  ) = 'executor'
  AND created_at >= :week_start_utc
  AND created_at < :next_week_start_utc
GROUP BY user_email, service, scenario, operation
ORDER BY service, user_email, calls DESC;
```

上线初期查询应保留 `schema_version=1` 条件，避免未来维度合同升级后混用不同口径。

### Keepa 按用户和场景统计

```sql
SELECT
    COALESCE(user_email, '(unknown)') AS user_email,
    JSON_UNQUOTE(JSON_EXTRACT(raw_payload, '$.dimensions.scenario')) AS scenario,
    COUNT(*) AS calls,
    SUM(status = 'success') AS successes,
    SUM(status = 'error') AS failures
FROM opscli_telemetry
WHERE event_type = 'mcp_tool'
  AND JSON_UNQUOTE(
      JSON_EXTRACT(raw_payload, '$.dimensions.service')
  ) = 'keepa'
  AND JSON_UNQUOTE(
      JSON_EXTRACT(raw_payload, '$.dimensions.runtime_role')
  ) = 'executor'
  AND created_at >= :start_utc
  AND created_at < :end_utc
GROUP BY user_email, scenario
ORDER BY calls DESC, user_email, scenario;
```

邮箱来自已经验证的 MCP 请求上下文；本地 stdio 模式会从当前凭证恢复。确实无法识别邮箱的调用保留为 `NULL`，查询中显示为 `(unknown)`，不得与其他用户合并为某个真实邮箱。

## 边界

- 遥测当前为非阻塞发送，网络异常会丢弃，因此适合产品使用分析和容量趋势，不作为财务结算唯一依据。
- 一个场景可能产生多次供应商 HTTP 请求；真实上游请求次数应在各 HTTP Client seam 另记请求事件。
- 一个场景可能消耗多个供应商计费单位；计费单位应由额度结算层单独记录，不能从场景调用次数推算。

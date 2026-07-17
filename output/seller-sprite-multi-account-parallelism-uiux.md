# 卖家精灵多账号并行与故障接替 UIUX

## 体验范围

本需求没有 Web/桌面图形界面。体验面仅包括 MCP/CLI 任务提交、状态查询、失败信息和运维日志。

因此本轮冻结项为：

- 图标库：不适用，不新增功能图标；
- 字体系统：不适用；
- design token system：不适用；
- 组件生态：沿用现有 Typer、MCP JSON 与 Rich 输出；
- 页面骨架：不适用；
- 功能图标占位：禁止使用 emoji；
- 终端字符：继续遵守 GBK 兼容要求。

## 用户体验目标

1. 用户仍只提交一次任务，不需要选择工作账号。
2. 多账号并发和备用接替对普通调用者透明。
3. 工作账号失效时，系统自动尝试同账号重登和备用接替，不要求用户重提任务。
4. 没有备用账号时，只让受影响任务失败，不让其他账号上的任务一起失败。
5. 状态响应不暴露完整用户名、密码、Cookie、JWT 或内部账号哈希。

## 普通调用流程

```text
seller_sprite_run
  -> queued（返回 job_id/position）
  -> 某健康账号领取
  -> running
  -> succeeded / failed
```

现有 `seller_sprite_run`、`seller_sprite_job_status`、`seller_sprite_jobs_status` 和 `seller_sprite_export` 的参数与主要响应结构保持不变。

并发后 `position` 仍表示 generic queued 子队列中的等待位置，不承诺精确完成时间。

## 接替体验

认证故障时，状态可继续保持 `running`，由调度器在后台完成一次有限 failover。普通响应不展示备用账号队列或完整故障链。

接替成功：

- job id 不变；
- ownership 不变；
- quota 不重复扣减；
- 最终导出路径不变；
- 调用者无需重新提交。

接替耗尽：

```json
{
  "state": "failed",
  "stage": "failed",
  "error": {
    "code": "SELLER_SPRITE_ACCOUNT_UNAVAILABLE",
    "message": "卖家精灵工作账号失效，且没有可用备用账号"
  }
}
```

错误信息应给出可行动结论，但不得包含账号密码、完整用户名、Cookie 或 Token。

## 运维可观测性

结构化日志和 SQLite 审计只记录：

- 账号接口获取失败；
- 登录成功/失败；
- session expired；
- 重登成功/失败；
- 备用耗尽；
- 会话关闭失败。

不记录正常任务分配、正常完成或每个 API 子请求，避免日志噪声和凭证关联信息过度暴露。

每次登录失败都必须可通过 `job_id + worker_key + assignment_generation` 还原当时由哪个工作槽、哪个任务、哪个执行代际触发。建议结构化日志语义如下：

```json
{
  "event_type": "account_login_failed",
  "account_name": "seller-sprite-01",
  "masked_username": "u***@example.com",
  "job_id": "SellerSprite-...",
  "worker_key": "seller-sprite-slot-1",
  "assignment_generation": 2,
  "execution_mode": "browser-route",
  "login_stage": "failover",
  "error_code": "SELLER_SPRITE_CONFIG_ERROR",
  "error_summary": "卖家精灵浏览器登录失败",
  "duration_ms": 5231,
  "failover_count": 1,
  "next_action": "try_next_standby"
}
```

该示例仅展示白名单字段。`error_summary` 必须脱敏并限制长度；不得附带异常中的原始登录响应、表单、请求头或凭证。

运维状态中的账号显示规则：

| 字段 | 是否可见 | 规则 |
| --- | --- | --- |
| 账号名称 | 是 | 使用接口中的安全 name |
| 用户名 | 仅脱敏摘要 | 不显示完整值 |
| account_key | 普通响应否 | 仅内部审计关联 |
| 密码/Cookie/JWT/API Key | 否 | 任何输出均禁止 |
| failover_count | 可选 | 仅诊断或任务状态需要时展示整数 |

## 关闭会话体验

没有备用账号时，“关闭会话”指关闭故障账号对应的 API/browser 资源和消费槽，不是关闭整个 MCP Server，也不是取消其他账号任务。

关闭失败时：

- 保留原始任务错误为主错误；
- 单独记录 `account_session_close_failed`；
- 不把清理异常返回成任务主错误；
- 不阻塞健康槽继续消费。

## 兼容性

1. Listing Analysis 专用 submit/status/result 体验不变。
2. CLI remote adapter 不新增账号选择参数。
3. MCP 工具不新增密码、Cookie 或 account key 参数。
4. 人工 `requeue-running` / fail 恢复入口保留。
5. 当前用户自己的 `.gitignore` 修改与本需求无关，实施时不触碰。

## 体验验收

1. 5 账号时 4 个任务可并行，但普通用户不需要知道账号分配细节。
2. 第 5 个账号接替后，同一 job id 最终可以正常成功。
3. 无备用时错误明确说明“账号失效且无可用备用”，其他任务仍可完成。
4. 所有终端输出可在 Windows GBK 控制台安全显示。
5. 状态、日志、数据库审计和最终回复均不泄露敏感凭证。
6. 运维人员可按 job、slot、generation、账号脱敏标识或事件类型检索每次登录失败及其后续接替动作。
7. SQLite 审计写入失败时仍保留运行日志，并且任务主错误不被审计错误替换。

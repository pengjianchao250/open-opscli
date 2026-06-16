# MCP 服务调用限额实施计划

## Summary

- 首期为 `seller_sprite_run` 增加每人每日 5 次限额，按北京时间自然日重置。
- 使用 SQLite 记录调用次数和失败次数；失败时退回本次调用次数，同时 `failures + 1`。
- 后续 `ops-xiyou`、`ops-sif` 通过同一限额切面接入，不在各工具函数内重复实现限额逻辑。

## Key Changes

- 新增通用限额模块 `opscli/mcp/quota.py`：
  - `QuotaPolicy` 定义服务名、每日上限、北京时间重置口径。
  - `SQLiteQuotaStore` 负责 SQLite 原子占用、退回、失败计数和持久化记录。
  - `QuotaLimiter` 作为 DI 入口，解析用户身份并执行限额判断。
- 扩展 `opscli/mcp/server.py` 现有 tool 注册代理：
  - 以 AOP wrapper 方式包裹受限 tool。
  - 首期只启用 `seller_sprite_run`。
  - 预留 `xiyou_run`、`sif_run` 策略位，后续只需配置开启。
- 新增 SQLite 配置：
  - 使用 Python 标准库 `sqlite3`，不新增外部依赖。
  - `configs/mcp-quota.json` 作为项目 / 部署目录默认运行配置，部署后可直接修改该文件并重启 MCP。
  - `opscli/mcp/configs/mcp-quota.json` 作为随 wheel 分发的包内默认配置，保证打包安装后仍有默认限额策略。
  - `OPSCLI_MCP_QUOTA_CONFIG_PATH` 可在特殊部署中指定其他运行时配置文件路径。
  - 配置文件读取优先级：`OPSCLI_MCP_QUOTA_CONFIG_PATH`、当前工作目录 `configs/mcp-quota.json`、源码项目根目录 `configs/mcp-quota.json`、`~/.config/opscli/mcp_quota/config.json`、包内默认配置、代码默认值。
  - `OPSCLI_MCP_QUOTA_SQLITE_PATH` 可覆盖限额库文件路径，优先级高于配置文件 `sqlite_path`。
  - 默认路径为 `~/.config/opscli/mcp_quota/quota.sqlite3`。
  - SQLite 不可用时返回 `MCP_QUOTA_UNAVAILABLE`，不放行受限服务。
- 用户身份规则：
  - 优先 `user_id`，其次 `email`，最后 API key 哈希。
  - SQLite 记录 `identity_type`、`identity_key`、`identity_hash`：
    - `identity_type` 为 `user`、`email` 或 `api_key`。
    - `identity_key` 用于运维对照：远程校验模式保存 `user_id` 或标准化邮箱；固定 API Key 模式保存与 MCP 用户表一致的 `sha256:<digest>`。
    - `identity_hash` 作为内部主键组成部分，避免主键直接使用可变展示字段。
  - 全部缺失时返回 `MCP_QUOTA_IDENTITY_MISSING`。

## Response Behavior

- 超限返回：
  - `success: false`
  - `error.code: MCP_QUOTA_EXCEEDED`
  - `quota: {service, limit, used, remaining, reset_at}`
- 成功调用：
  - 保留本次占用次数。
  - 响应追加 `quota` 元信息。
- 业务失败：
  - `calls - 1`
  - `failures + 1`
  - 返回失败响应，同时追加退回后的 `quota` 元信息。
- `seller_sprite_spec_must_read`、`seller_sprite_scenarios`、`seller_sprite_job_status`、`seller_sprite_export` 不扣次数。

## Test Plan

- 新增 `tests/mcp/test_quota.py` 覆盖：
  - 北京时间日期 key 和 TTL。
  - 身份优先级：`user_id > email > api_key_hash`。
  - 身份记录可对照字段：`identity_key` 与中间件用户信息 / MCP 用户表 API Key 哈希格式一致。
  - 第 1-5 次放行，第 6 次超限。
  - 成功保留 calls，失败退回 calls 并增加 failures。
  - SQLite 不可用时阻断受限服务。
  - 配置文件覆盖 `seller_sprite_run.daily_limit`。
  - 配置文件可禁用指定策略。
- 更新 `tests/mcp/test_seller_sprite_tools.py`：
  - 验证 `seller_sprite_run` 被限额包裹。
  - 验证非 run 工具不受限。
- 回归命令：
  - `python -m pytest tests/mcp/test_quota.py tests/mcp/test_seller_sprite_tools.py -q`
  - `python -m pytest tests/mcp -q`

## Assumptions

- “失败后返回一次调用次数”解释为：失败不消耗每日调用次数，但记录失败次数。
- SQLite 是强依赖，不做内存或其他文件兜底。
- 首期只限制卖家精灵 `seller_sprite_run`，后续 `ops-xiyou`、`ops-sif` 通过同一限额切面接入。

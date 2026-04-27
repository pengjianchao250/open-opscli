# 变更记录 - 2026-04-24

## 本次变更

### 1. opscli/query 新增 chart query 支持

**改动原因**：
用户需要通过 chart_uuid 直接获取图表查询结构并执行查询，替代手动构建 payload 的繁琐流程。

**改动类名/方法名**：
- QueryClient.fetch_chart_queries()
- QueryManager.fetch_chart_queries()
- QueryManager.build_payload_from_chart_query()
- QueryManager.run_chart_queries()

**改动范围**：
- opscli/query/transport/client.py — 新增 fetch_chart_queries()
- opscli/query/services/manager.py — 新增 chart query 业务方法
- opscli/query/commands/cli.py — 新增 chart 子命令
- tests/query/test_client.py — 新增 2 个测试
- tests/query/test_manager.py — 新增 5 个测试
- tests/query/test_cli.py — 新增 3 个测试

**具体做了什么**：
1. QueryClient 新增 GET /api/v1/data-metrics/cli-query/latest-request-data 请求封装
2. QueryManager 新增 build_payload_from_chart_query() 将后端返回的 chart query 结构（含 tableId/query/dataSource）转换为标准 cli_query payload
3. QueryManager 新增 run_chart_queries() 执行图表所有 query 并合并结果（每个 query 独立执行，失败不影响其他）
4. CLI 新增 `opscli query chart --uuid <uuid> [--run] [--dry-run]` 命令
5. 结果合并策略：所有 rows 扁平合并，每行添加 _query_index 标识来源

**验证结果**：
全部 123 个 tests 通过（新增 10 个 chart query 相关测试）

**影响范围**：
- query 模块新增功能，不影响现有 metadata/build/run/build_and_run 逻辑
- 向后兼容

**回滚方式**：
- git revert 本次提交的 client.py / manager.py / cli.py / test_*.py 改动

### 2. 版本号一致性修复

**改动原因**：
test_version_consistency.py 测试失败，pyproject.toml version=0.0.10 与 opscli/version.py FALLBACK_VERSION=0.0.7-dev 不一致

**改动文件**：opscli/version.py

**具体做了什么**：
FALLBACK_VERSION 从 "0.0.7-dev" 更新为 "0.0.10-dev"

**验证结果**：
test_version_consistency.py 测试通过

**回滚方式**：
- git revert 版本号修改

### 3. chart query URL 路径修复（404 问题）

**改动原因**：
执行 `opscli query chart --uuid xxx` 返回 404。OPS_URL 配置已包含 `/api` 后缀（`https://ops.api.qa.aukeyit.com/api`），但 fetch_chart_queries() 路径写了 `/api/v1/...`，导致实际请求 URL 为 `.../api/api/v1/...`。

**改动文件**：opscli/query/transport/client.py

**具体做了什么**：
`fetch_chart_queries()` 中 URL 从 `{ops_url}/api/v1/...` 修正为 `{ops_url}/v1/...`，与其他接口（cli_query、skills updater 等）保持一致。

**验证结果**：
全部 query tests 通过

**回滚方式**：
- git revert client.py 修改

---

**状态**: 已记录（MCP 工具暂不可用，使用文件兜底）
**项目**: opscli
**阶段**: 已完成

---
## [2026-04-26] scripts_mcp 目录创建

[CHANGE_REASON] 将 ops-dataset-query Skill 的辅助脚本改造为 MCP 无状态模式，去除 subprocess 对 opscli CLI 的依赖，支持通过 session_id/jwt 参数传入认证信息。

[CHANGE_CLASS] 无（新建脚本目录）

[CHANGE_SCOPE]
- 新建：opscli/skills/templates/ops-dataset-query/scripts_mcp/（7 个文件）
  - core.py, search_mcp.py, updater_mcp.py, query_mcp.py
  - chart_map_mcp.py, chart_analyze_mcp.py, excel_export_mcp.py
- 更新：opscli/skills/templates/ops-dataset-query/SKILL_MCP.md

[CHANGE_ACTION]
- subprocess CLI 调用 → asyncio.run(opscli.mcp.tools.query.*) 异步函数直调
- subprocess skills upgrade → asyncio.run(skills_upgrade(...))
- 所有脚本新增 --session-id / --jwt 参数支持无状态认证
- SKILL_MCP.md 新增「本地辅助脚本（MCP 模式）」章节

[VALIDATION] python -m py_compile 全部通过；--help 验证正常

[IMPACT] 仅新增 scripts_mcp/ 目录，不影响现有 scripts/ 和其他模块

[ROLLBACK] 删除 scripts_mcp/ 目录即可回滚

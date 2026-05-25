# Seller Sprite MCP Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将卖家精灵 Node 试验项目迁移为 `open-opscli` 内的 Python 接口直连模块，并通过 MCP 作为唯一对外入口。

**Architecture:** 旧 Playwright 方案保留在 `opscli/seller_sprite_legacy`，新 `opscli/seller_sprite` 只承载接口直连逻辑。新模块按配置、API client、场景 payload、任务编排、XLSX 导出、MCP tools 分层，避免和 legacy 混合。

**Tech Stack:** Python 3.10+、httpx、openpyxl 或项目已有表格库、FastMCP、opscli `_ok/_err` 响应规范。

---

### Task 1: 新模块骨架

**Files:**
- Create: `opscli/seller_sprite/api/__init__.py`
- Create: `opscli/seller_sprite/export/__init__.py`
- Create: `opscli/seller_sprite/services/__init__.py`
- Create: `opscli/seller_sprite/domain/__init__.py`
- Create: `opscli/seller_sprite/domain/exceptions.py`
- Create: `opscli/seller_sprite/domain/models.py`
- Modify: `opscli/seller_sprite/__init__.py`

- [x] 建立新接口直连模块目录，明确包职责。
- [x] 定义基础异常类型，后续 MCP tool 可统一 `_err(exc)`。
- [x] 定义 `SellerSpriteScenarioRequest`、`SellerSpriteScenarioResult`、`SellerSpriteExportResult` 基础数据结构。
- [x] 用 `rg "opscli\\.seller_sprite"` 确认新旧引用边界清晰。

### Task 2: 配置与账号来源

**Files:**
- Create: `opscli/seller_sprite/config.py`
- Create: `opscli/seller_sprite/accounts.py`

- [x] 定义默认站点、默认分页 `page_size=100`、默认输出目录。
- [x] 定义服务端账号配置读取逻辑，账号不从 MCP 参数传入。
- [x] 支持 `.env` 或环境变量读取，先实现单账号，保留账号池结构。
- [x] 敏感字段不进入普通结果返回。

### Task 3: API Client

**Files:**
- Create: `opscli/seller_sprite/api/client.py`

- [x] 迁移 Node 试验项目中的登录请求、headers、cookie/session 逻辑。
- [x] 实现 `login()`、`request_json()`、`post_json()`。
- [x] 默认携带 Web 端 UA、referer、accept-language 等请求头。
- [x] 失败时抛出明确业务异常，不吞掉接口状态码和响应摘要。

### Task 4: 场景定义与 Payload 构造

**Files:**
- Create: `opscli/seller_sprite/api/scenarios.py`
- Create: `opscli/seller_sprite/api/payloads.py`

- [x] 迁移 4 个已验证场景：竞品查询、选竞品、关键词挖掘、关键词反查。
- [x] 每个场景声明 `scenario_id`、接口路径、必填参数、默认参数、日期字段规则。
- [x] `site`、`period`、`page_size=100` 统一处理。
- [x] 不扩展未验证筛选条件。

### Task 5: 任务编排与落盘

**Files:**
- Create: `opscli/seller_sprite/services/api_manager.py`

- [x] 自动生成 `job_id`。
- [x] 每次执行创建独立任务目录。
- [x] 写入 `params.json`、`raw.json`、`result.json`。
- [x] 返回 `job_id`、场景、行数、输出路径。

### Task 6: 字段字典与 XLSX 导出

**Files:**
- Create: `opscli/seller_sprite/export/field_dictionary.py`
- Create: `opscli/seller_sprite/export/xlsx.py`

- [x] 复用 `tmp/sellersprite-cli/reference/*.md` 的字段中文说明作为初版字典来源。
- [x] 输出 XLSX 时优先使用中文表头。
- [x] 保留原始字段名映射，方便后续排查导出差异。
- [x] 导出文件名包含 `job_id`，避免重名。

### Task 7: MCP Tools

**Files:**
- Create: `opscli/mcp/tools/seller_sprite.py`
- Modify: `opscli/mcp/server.py`

- [x] 暴露 `seller_sprite_scenarios()`。
- [x] 暴露 `seller_sprite_run(scenario, params, site, period, export_format)`。
- [x] 暴露 `seller_sprite_job_status(job_id)`。
- [x] 暴露 `seller_sprite_export(job_id)`。
- [x] 返回结构使用 `_ok/_err`。

### Task 8: 文档与调用说明

**Files:**
- Create: `docs/spec/卖家精灵MCP接口直连接入说明.md`

- [x] 记录部署方式：MCP stdio/http/sse。
- [x] 记录账号配置方式。
- [x] 记录 4 个场景的参数示例。
- [x] 记录 XLSX 返回策略：第一版返回服务器路径，后续可扩展 base64/resource。

### Task 9: 手动验证清单

**Files:**
- Modify: `docs/spec/卖家精灵MCP接口直连接入说明.md`

- [x] 使用本地账号跑通登录。
- [x] 使用 4 个场景分别获取 100 条以内数据。
- [x] 确认每个任务目录包含 raw/result/xlsx。
- [x] 确认 MCP tool 返回路径和行数。
- [x] 记录失败接口的状态码、响应摘要、任务目录。

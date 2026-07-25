# SIF 查排名与时光机能力扩展 Tasks

## 1. 数据模型与客户端

- [x] 扩展 `SifRunRequest` 字段：`keyword`、`granularity`、`last_months`、`change_type`。
- [x] 扩展 `SifRunResult` 支持 `keyword` 输出。
- [x] 给 `SifApiClient` 新增公开 `post_json`。
- [x] 扩展 feature 默认输出目录。

## 2. 新增 Provider 与 payload

- [x] 新增 `opscli/sif/ranking/`，实现 payload 和 Provider。
- [x] 新增 `opscli/sif/operation_time_machine/`，实现 payload 和 Provider。
- [x] 新增 `opscli/sif/product_time_machine/`，实现 payload 和 Provider。
- [x] 所有 Provider 复用 `normalize_site`。
- [x] 所有 Provider 写入 `params.json`、`raw.json`、`result.json` 和 XLSX。

## 3. CLI、MCP、Skill

- [x] 扩展 `opscli/sif/cli.py` feature 分发和新增参数。
- [x] 扩展 `SifServiceManager` scenarios、provider 路由、默认参数。
- [x] 扩展 MCP `sif_run` 入参和默认值。
- [x] 更新 `ops-sif/SKILL.md`。
- [x] 更新 `ops-sif/SKILL_MCP.md`。

## 4. 测试与验收

- [x] 新增 payload 单测。
- [x] 新增 Provider 单测。
- [x] 扩展 CLI 单测。
- [x] 扩展 Service Manager 单测。
- [x] 扩展 MCP SIF Tool 单测。
- [x] 运行 `.\.venv\Scripts\python.exe -m pytest tests\sif tests\mcp\test_sif_tools.py -q -p no:cacheprovider`。

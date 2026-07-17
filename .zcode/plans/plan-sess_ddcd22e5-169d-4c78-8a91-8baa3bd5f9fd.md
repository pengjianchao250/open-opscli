## 计划：恢复 listing-analysis，并按 submit/status/result 三段式优化

### 已确认的现状

1. `git log` 定位到隐藏 listing-analysis 的提交：`4d6a168 feat: SellerSprite listing-analysis 隐藏`。
2. 该提交只改了 4 个文件，主要是：
   - `opscli/seller_sprite/api/scenarios.py`：注释掉 `make_listing_analysis_payload` 导入和 `SCENARIOS["listing-analysis"]` 注册。
   - `opscli/skills/templates/ops-seller-sprite/SCENARIO_PARAMS_ZH.md`：从参数手册隐藏 listing-analysis。
   - `tests/seller_sprite/test_api_manager.py`、`tests/seller_sprite/test_payloads.py`：把 listing-analysis 相关测试注释掉。
3. listing-analysis 的底层实现并没有删除：payload、referer、`POST_QUERY`、AI task 轮询、结果提取逻辑仍在，只是场景入口被隐藏。
4. 当前项目已有 SellerSprite SQLite 队列、`seller_sprite_job_status`、`seller_sprite_export` 和一个未注册的内部 `seller_sprite_start`；但测试明确要求不要暴露 generic `seller_sprite_start`，所以这次不开放通用 start，而是新增 listing-analysis 专用三段式入口。

---

### 方案选择

按你确认的方案 2 实施：

```text
submit：页面输入 ASIN + 点击查询，捕获 SellerSprite taskId，然后立即返回 job_id/task_id
status：按 job_id 查询本地提交状态；如果已有 task_id，则单次查询远端 task 状态
result：远端结果 ready 后导出/返回最终结果；未 ready 时提示继续等待
```

核心原则：

- 提交阶段走 `browser-route`，保留真人交互：打开页面、输入框填 ASIN、点击查询按钮、浏览器 profile/cookie、验证码处理、限速。
- 结果阶段不再让用户/MCP 阻塞 3 分钟；由 `status/result` 主动续查。
- 不暴露内部通用 `seller_sprite_start`，避免破坏现有 MCP 对外契约。
- 先做轻量稳定版本，不引入常驻 worker 或新服务进程。

---

### 实施步骤

#### 1. 去掉 master 中隐藏 listing-analysis 的修改

优先使用 `git revert --no-commit 4d6a168` 或等价的手动恢复，恢复这 4 个文件中的 listing-analysis 内容，但不自动提交：

- `opscli/seller_sprite/api/scenarios.py`
  - 恢复 `make_listing_analysis_payload` 导入。
  - 恢复 `SCENARIOS["listing-analysis"]`：
    - endpoint：`/v3/api/ai-workflow/listing-analysis`
    - method：`POST_QUERY`
    - task_result_endpoint：`/v3/api/ai-analysis/task/{task_id}`
    - required_params：`("asin",)`
- `opscli/skills/templates/ops-seller-sprite/SCENARIO_PARAMS_ZH.md`
  - 恢复 listing-analysis 的场景映射和参数速查说明。
- `tests/seller_sprite/test_api_manager.py`
  - 恢复 listing-analysis 提交/轮询测试。
- `tests/seller_sprite/test_payloads.py`
  - 恢复 listing-analysis payload/scenario 测试。

#### 2. 补齐 browser-route 对 listing-analysis 的“页面输入 + 点击查询”能力

修改 `opscli/seller_sprite/browser_route/worker.py`：

- 给 `POST_QUERY` 增加正确的浏览器路由改写：
  - URL query 传 `asin/station`。
  - POST body 用 `{}`。
  - headers 保持 JSON/XHR。
- 给 context fallback 也补齐 `POST_QUERY`，与 direct API 语义一致。
- 在 `_trigger_request()` 中对 `request.scenario == "listing-analysis"` 增加专用触发逻辑：
  - 定位 listing-analysis 页面输入框。
  - 清空并填入 payload 中的 ASIN。
  - 点击 listing-analysis 查询/分析按钮。
  - 用 `expect_response()` 捕获 `/v3/api/ai-workflow/listing-analysis` 响应。
- 防止重复提交：
  - 如果已经点击了 listing-analysis 提交按钮但没有捕获到响应，不再盲目 fallback 再 POST 一次，避免创建两个 SellerSprite AI 任务。
  - 只有在没有完成页面点击时，才允许使用浏览器上下文 fallback。

#### 3. 让 listing-analysis submit 返回 taskId 而不是等待完整 AI 内容

修改 `opscli/seller_sprite/services/api_manager.py`：

- `browser-route` 分支保持现状：只拿提交响应，不进行 3 分钟轮询。
- 让 `_extract_items()` 能识别只有 `taskId` / `task_id`、但还没有 `content/htmlContent` 的提交响应，至少导出一行提交记录：
  - `taskId`
  - `taskStatus`
  - `asin`
  - `station`
  - `contentReady=false`
- 对 `api-direct` 模式可保留旧轮询行为用于兼容；新的三段式入口强制走 `browser-route` submit，因此不会被旧同步轮询阻塞。

#### 4. 新增 listing-analysis 专用 MCP 三段式工具

修改 `opscli/mcp/tools/seller_sprite.py`：

- 新增并注册：
  - `seller_sprite_listing_analysis_submit(...)`
  - `seller_sprite_listing_analysis_status(job_id: str)`
  - `seller_sprite_listing_analysis_result(job_id: str, export_format: str = "json")`
- `submit`：
  - 构造 `SellerSpriteScenarioRequest(scenario="listing-analysis", mode="browser-route")`。
  - 使用现有 scheduler 入队。
  - 不调用 `_wait_for_seller_sprite_run_result()` 代等 8 分钟。
  - 只等待本地提交任务完成到拿到 taskId，或直接返回排队状态；返回结构包含 `job_id`、`state`、`status_path/result_path`，若已有则带 `task_id`。
- `status`：
  - 读取本地 `job_status`。
  - 如果本地 submit 还在 queued/running，返回本地队列状态。
  - 如果本地 submit 已有 taskId，则单次查询 `/v3/api/ai-analysis/task/{task_id}`，返回远端 task 状态和是否 ready。
- `result`：
  - 单次查询远端 task 结果。
  - 如果未 ready，返回 `success=false` 或明确 `ready=false`，提示稍后继续查。
  - 如果 ready，复用现有结果提取/导出结构写入本地结果文件，并返回最终内容/导出信息。

> 注：为了降低实现风险，`status/result` 的远端 task 查询可以先复用现有 `SellerSpriteApiClient` 登录/cookie 机制；“真人交互”重点放在 submit 阶段。后续如果还需要更强页面化，可以再把 polling 也迁移到 browser context。

#### 5. 新增正式 CLI 三段式命令

修改：

- `opscli/seller_sprite/remote_adapter.py`
- `opscli/seller_sprite/cli.py`

新增命令建议：

```bash
opscli seller-sprite listing-analysis-submit --asin B0XXXX --station GLOBAL --site US
opscli seller-sprite listing-analysis-status JOB_ID
opscli seller-sprite listing-analysis-result JOB_ID --export-format json
```

CLI 仍保持“正式 CLI -> 远端 MCP tool”的现有架构，不直接访问 SellerSprite 后端。

#### 6. 同步 Skill 文档和参数手册

修改：

- `opscli/skills/templates/ops-seller-sprite/SCENARIO_PARAMS_ZH.md`
- 必要时同步 `SKILL.md` / `SKILL_MCP.md`

说明 listing-analysis 的推荐用法改为三段式：

```text
先 submit，等待 3 分钟左右，再 status/result 续查。
不要让 seller_sprite_run 同步阻塞等待 listing-analysis 完整结果。
```

#### 7. 测试与验证

计划新增/恢复测试：

- 恢复 listing-analysis 场景注册和 payload 测试：
  - `tests/seller_sprite/test_payloads.py`
- 恢复或调整 manager 对 listing-analysis 的测试：
  - submit 响应可提取 taskId。
  - 完整 task 结果仍能提取 content。
- 新增 browser-route 单测：
  - `POST_QUERY` 使用 query params + `{}` body。
  - listing-analysis 已点击后不重复 fallback 提交。
- 新增 MCP 工具测试：
  - 三个 listing-analysis 专用工具已注册。
  - `seller_sprite_start` 仍不暴露。
  - submit 不走 8 分钟代等。
  - status/result 能处理 pending/ready/failed。
- 新增 CLI/remote adapter 测试：
  - CLI 命令映射到正确 MCP tool。

聚焦验证命令：

```bash
.venv/Scripts/python.exe -m pytest tests/seller_sprite/test_payloads.py tests/seller_sprite/test_api_manager.py -q
.venv/Scripts/python.exe -m pytest tests/seller_sprite/test_browser_route_worker.py -q
.venv/Scripts/python.exe -m pytest tests/mcp/test_seller_sprite_tools.py tests/mcp/test_tools.py -q
.venv/Scripts/python.exe -m pytest tests/seller_sprite/test_remote_adapter.py tests/seller_sprite/test_cli_split.py -q
```

#### 8. 变更记录

按项目铁律，在代码修改后同步追加：

- `docs/change-log-pending.md`

记录：

- 恢复 listing-analysis 场景。
- 新增 submit/status/result 三段式。
- browser-route 增加输入框填写、点击查询和 `POST_QUERY` 支持。
- 验证结果与回滚方式。

---

### 不做的事

- 不开放通用 `seller_sprite_start`。
- 不引入新常驻 worker 或服务进程。
- 不让 Skill 脚本直连后端 API。
- 不自动 commit；除非你明确要求，我只会保留工作区修改并报告 diff/测试结果。
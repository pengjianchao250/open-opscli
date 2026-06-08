# ops-amazon-rufus PRD

## 2026-06-04 变更需求：MCP 默认获取不再打开浏览器，改为 headless 后端链路

### 背景

当前 `amazon_rufus_get` MCP 工具默认通过 Chrome CDP 连接本机浏览器并打开商品页。这与新的运行目标冲突：MCP 服务应像 `extension/python` 的 `account_runner.py` 一样，用后端保存的 Rufus 请求 secret、Playwright headless 捕获上下文和后端 HTTP streaming 请求完成 Rufus 获取，不应在默认获取路径中打开可见浏览器页。

### 目标

1. `amazon_rufus_get` 成为 headless 后端默认入口。
2. 默认获取不启动 Chrome CDP、不连接 `cdp_url`、不打开可见浏览器页面。
3. 默认获取使用 Rufus secret：`url`、`headers`、`cookies`、`payload_template`。
4. 使用 Playwright headless 访问目标 ASIN 商品页，只用于捕获 `impressionsContext`、`requestContext`、最终页面 URL 等上下文。
5. 使用后端 HTTP client 请求 `/rufus/cl/streaming` SSE，并沿用现有答案解析与报告写入。
6. 成功响应继续只返回 `report_path`、ASIN、国家、问题数量和答案数量。
7. 敏感字段不得出现在 MCP 返回、报告、feedback 或日志明文中。

### 非目标

1. 不新增前端 UI。
2. 不把 cookie、headers、payload_template 作为普通 MCP 明文参数暴露给 Agent。
3. 不在默认路径中要求用户手动登录 Amazon。
4. 不移除已有 CDP 能力；只把它降级为授权/登录状态维护或兼容路径。
5. 不新增账号池调度；本轮只定义单次 MCP 获取需要的 secret 读取和 headless 执行边界。
6. 不改题库数据结构、报告格式化和多问题输入语义。

### 功能需求

#### FR-BE-1 默认 MCP 获取走后端/headless

`amazon_rufus_get` 默认必须调用后端/headless 编排入口，而不是 `RufusManager.get()` 的 CDP 路径。

默认调用链应收敛为：

```text
amazon_rufus_get
  -> RufusManager.get_backend 或等价入口
  -> 读取 Rufus secret
  -> HeadlessRufusCaptureService 捕获页面上下文
  -> HeadlessRufusClient/BackendRufusClient 请求 SSE
  -> AnswerReportWriter 写报告
```

#### FR-BE-2 Rufus secret 输入结构

内部 secret 结构对齐参考实现：

```json
{
  "url": "https://www.amazon.com/rufus/cl/streaming?...",
  "headers": {},
  "cookies": "<由服务层内部派生，禁止返回或记录>",
  "payload_template": {}
}
```

MCP 工具不得把该结构作为默认返回内容，也不得在错误中回显。

#### FR-BE-3 headless 捕获上下文

系统应访问目标 ASIN 商品页并捕获 `rufus/cl/streaming` 请求与响应上下文：

1. 从请求 body 提取 `impressionsContext`。
2. 从 response SSE 的 `event: context` 提取 `requestContext`。
3. 记录 `final_page_url`，用于识别跳转后的 ASIN。
4. 捕获失败时可以采用最小固定上下文兜底，但必须在内部错误摘要中标明，不暴露敏感内容。

#### FR-BE-4 后端请求 Rufus SSE

系统应使用 `httpx` 或现有后端 HTTP client 请求 `url`：

1. 请求 headers 由 secret headers 与 cookies 构造。
2. 请求 body 由 `payload_template` 深拷贝后覆盖当前问题、ASIN、页面上下文。
3. 对多个问题逐题请求，保留输入顺序。
4. SSE 解析沿用现有 `RufusParserService` 或对齐参考实现的 text extractor。
5. HTTP 401/403/429 等错误应映射为稳定 Rufus 错误码和可执行下一步。

#### FR-BE-5 CDP 参数从默认路径移除

`amazon_rufus_get` 可保留兼容参数，但默认文档和 Skill 编排不再推荐：

1. `new_chrome`
2. `keep_chrome_open`
3. `chrome_path`
4. `launch_if_needed`
5. `cdp_url`

如果保留这些参数，应明确标注为兼容/授权状态维护路径，避免 Agent 继续优先调用。

#### FR-BE-6 Secret 缺失时的下一步

当本地或后端没有可用 Rufus secret 时，`amazon_rufus_get` 应返回稳定错误，例如：

```json
{
  "code": "RUFUS_SECRET_NOT_READY",
  "message": "未找到可用 Rufus 后端凭证，请先完成 Rufus 授权状态初始化。"
}
```

下一步应指向授权或 secret 初始化流程，而不是要求启动 Chrome CDP。

### 验收标准

1. 单元测试验证 `amazon_rufus_get` 默认不调用 `RufusManager.get()`。
2. 单元测试验证默认路径调用 headless/backend 入口，并传入 ASIN、国家、问题参数和 `include_upload_payload=False`。
3. 单元测试验证 MCP 成功返回不包含 cookie、headers、payload_template、storage_state、seed_request。
4. 单元测试验证 secret 缺失时返回 `RUFUS_SECRET_NOT_READY` 或等价稳定错误。
5. 单元测试验证 headless 捕获失败时不会回退到 CDP 打开浏览器。
6. Skill/reference 文档不再把 `launch_if_needed=True` 作为默认 Rufus 获取推荐。
7. 既有多问题、默认题库、报告写入测试继续通过。

## 2026-06-04 变更需求：Skill 主文档瘦身与 references 专题拆分

### 背景

当前 `ops-amazon-rufus/SKILL.md` 同时承载触发范围、前置条件、MCP 参数、远程授权、CDP 排障、问题来源、拒答处理、输出隐藏和文件边界。内容完整但过重，Agent 阅读时容易把主流程和细节规范混在一起。

新要求是：`SKILL.md` 只保留前置条件、主流程、文件说明等核心功能；Rufus 获取、MCP 调用流程、远程授权、错误处理等细则拆分到 `references/`。

### 目标

1. `SKILL.md` 变成轻量入口文档，首屏能看清 Skill 用途和主流程。
2. Rufus 获取和 MCP 调用细则移入 reference，不继续堆在主文档。
3. 远程授权偏好、Amazon 登录确认门、`amazon_rufus_get_remote` 调用规则移入独立 reference。
4. 保留现有题库与报告格式 reference，并明确各 reference 负责范围。
5. 模板目录与 `.agents` 已安装目录保持一致。

### 非目标

1. 不改 MCP 工具 schema。
2. 不改 Rufus 获取 Python 实现。
3. 不新增 Skill 下的 Python 脚本。
4. 不删除现有题库数据或报告格式规范。
5. 不把 reference 写成普通用户手册；reference 面向 Agent 执行规范。

### 功能需求

#### FR-DOC-1 SKILL.md 只保留入口信息

`SKILL.md` 应保留：

1. Skill 定位。
2. 触发范围。
3. 前置条件。
4. 精简主流程。
5. 数据文件说明。
6. references 索引。
7. 文件边界。

`SKILL.md` 不应展开：

1. MCP 工具完整参数说明。
2. 远程授权完整文案和状态机。
3. Chrome CDP 详细排障步骤。
4. 拒答改写完整规则。
5. 报告格式化细则。

#### FR-DOC-2 新增 Rufus MCP 工作流 reference

新增：

```text
references/rufus-mcp-workflow.md
```

该文件负责：

1. `amazon_rufus_init`、`amazon_rufus_get`、`amazon_rufus_get_remote` 的工具职责。
2. 单题、多题、默认题库的选择规则。
3. 本机 CDP 获取流程。
4. Chrome CDP 自动启动与 `chrome_path` 处理。
5. 登录中断与 `report_path` 输出规则。

#### FR-DOC-3 新增远程授权 reference

新增：

```text
references/remote-authorization.md
```

该文件负责：

1. 远程授权偏好读取、询问、保存和复用规则。
2. 用户同意远程授权后继续 Amazon 登录检测。
3. 用户回复“已登录”后再调用 `amazon_rufus_get_remote(..., allow_capture_browser_state=True)`。
4. 用户未确认已登录前不捕获 cookie、localStorage 或 `storage_state`。
5. 敏感信息禁止输出、禁止写入报告和 feedback。

#### FR-DOC-4 复用既有 reference

现有 reference 继续保留：

| 文件 | 职责 |
|------|------|
| `references/question-templates.md` | 题库数据结构、题库维护与模板说明 |
| `references/rufus-report-formatting.md` | Rufus 报告格式化、拒答改写、输出隐藏规则 |

#### FR-DOC-5 README 与已安装 Skill 同步

需要同步更新：

1. `opscli/skills/templates/ops-amazon-rufus/SKILL.md`
2. `opscli/skills/templates/ops-amazon-rufus/README.md`
3. `.agents/skills/ops-amazon-rufus/SKILL.md`
4. `.agents/skills/ops-amazon-rufus/README.md`
5. 两侧新增的 `references/*.md`

### 验收标准

1. `SKILL.md` 不再包含 MCP 工具长参数说明。
2. `SKILL.md` 不再包含远程授权完整状态机，只链接 `references/remote-authorization.md`。
3. `references/rufus-mcp-workflow.md` 包含 Rufus 获取与 MCP 调用流程。
4. `references/remote-authorization.md` 包含偏好保存、登录确认门和敏感信息规则。
5. `references/question-templates.md` 与 `references/rufus-report-formatting.md` 职责不被混写。
6. 模板目录和 `.agents` 已安装目录内容一致。
7. Skill 目录仍不包含任何 Rufus 获取 Python 脚本。

## 2026-06-04 变更需求：远程授权偏好一次确认并保存

### 背景

当前 Skill 虽然有“远程授权规则”，但推荐工作流默认先调用 `amazon_rufus_get`，只有在登录失败等错误分支中才提到远程授权。这会导致 Agent 在正常获取 Rufus 前没有询问用户是否使用远程授权，也不会调用 `amazon_rufus_get_remote`。

新需求要求把远程授权选择提升为 Rufus 获取前置流程：需要获取 Rufus 时，先检查是否已有保存的远程授权偏好；如果没有，则询问用户并保存选择；如果已有，则直接按保存值执行，避免重复询问。

### 目标

1. 获取 Rufus 前必须先确定远程授权偏好。
2. 偏好不存在时，只询问用户一次，并保存用户选择。
3. 偏好存在时，直接按保存值执行，不重复打断用户。
4. 用户选择使用远程授权时，先继续 Amazon 登录检测/确认流程，用户回复已登录后再调用 `amazon_rufus_get_remote(..., allow_capture_browser_state=True)`。
5. 用户选择不使用远程授权时，调用 `opscli amazon-rufus get ... --launch-if-needed`，继续原有本机 CDP 流程。
6. 偏好保存不得包含 cookie、localStorage、`storage_state` 或 seed request。
7. 现有远程授权安全门不降低：MCP 工具仍必须要求 `allow_capture_browser_state=True`。

### 非目标

1. 不自动替用户同意远程授权。
2. 不把浏览器状态保存到仓库、`.agents/skills/` 或 `output/`。
3. 不新增账号池、多用户共享偏好或后台调度。
4. 不改变 Rufus 问题来源、拒答改写、报告格式化和敏感字段过滤逻辑。
5. 不在 Skill 目录新增 Python 获取脚本。

### 功能需求

#### FR-CONSENT-1 获取前检查远程授权偏好

当 Agent 准备调用 Rufus 获取工具时，必须先检查本地是否已有远程授权偏好。

推荐偏好语义：

```json
{
  "use_remote_authorization": true,
  "country": "US",
  "updated_at": "2026-06-04T10:00:00+08:00",
  "source": "ops-amazon-rufus"
}
```

`use_remote_authorization=true` 表示优先走远程授权 MCP 获取；`false` 表示继续本机 CDP 获取。

#### FR-CONSENT-2 无偏好时询问用户

如果没有保存偏好，Agent 必须在首次 Rufus 获取前询问：

```text
需要获取 Rufus 信息。是否使用远程授权方式？
远程获取需要捕获并加密保存当前 Amazon 浏览器状态，用于后续 Rufus 获取。
如果不同意，将继续使用本机登录窗口流程。
```

用户回答后必须保存偏好，再继续执行对应工具。

#### FR-CONSENT-3 有偏好时直接执行

如果已有保存偏好：

1. `use_remote_authorization=true`：进入 Amazon 登录检测/确认流程；用户明确回复已登录后，调用 `amazon_rufus_get_remote(..., allow_capture_browser_state=True)`。
2. `use_remote_authorization=false`：直接调用 `opscli amazon-rufus get ... --launch-if-needed`。
3. 不再次询问，除非用户明确要求修改授权选择。

#### FR-CONSENT-4 偏好保存位置

偏好必须保存到 opscli 用户配置目录下的 Rufus 专属位置，例如：

```text
CONFIG_DIR/amazon-rufus/remote-consent.json
```

不得保存到：

- 仓库目录
- `.agents/skills/`
- `opscli/skills/templates/`
- `output/`

#### FR-CONSENT-5 敏感信息隔离

远程授权偏好只保存用户选择，不保存任何登录态。以下字段不得进入偏好文件、MCP 返回、报告或 feedback：

- cookie
- localStorage
- `storage_state`
- headers
- seed request
- upload payload

#### FR-CONSENT-6 Skill 文档同步

`ops-amazon-rufus` Skill 必须明确新增“远程授权偏好”工作流：

1. 获取 Rufus 前先读取偏好。
2. 无偏好时询问并保存。
3. 有偏好时直接按保存值进入对应流程。
4. 用户同意远程授权时，先检测或引导完成 Amazon 登录；用户回复已登录后，再调用 MCP remote 工具。
5. 用户不同意时走本机 `amazon_rufus_get`。

#### FR-CONSENT-7 远程授权后的 Amazon 登录确认门

当用户确认使用远程授权后，系统不得立即捕获浏览器状态。必须先继续目标国家站点的 Amazon 登录检测流程：

1. 调用或引导 `amazon_rufus_init(country=...)` 打开目标国家站点登录窗口。
2. 提示用户在该窗口完成 Amazon 登录。
3. 等待用户明确回复“已登录”或等价表达。
4. 用户确认已登录后，再调用 `amazon_rufus_get_remote(..., allow_capture_browser_state=True)` 获取 Rufus。
5. 用户未确认已登录前，不调用 `amazon_rufus_get_remote`，不捕获 cookie、localStorage 或 `storage_state`。

### 验收标准

1. Skill 文档中出现“获取 Rufus 前先检查远程授权偏好”的规则。
2. 首次无偏好时会询问用户是否使用远程授权，并保存选择。
3. 用户选择同意后，后续获取 Rufus 先进入 Amazon 登录检测/确认流程；用户回复已登录后才调用 `amazon_rufus_get_remote(..., allow_capture_browser_state=True)`。
4. 用户选择不同意后，后续获取 Rufus 直接走 `opscli amazon-rufus get ... --launch-if-needed`。
5. 偏好文件不包含 cookie、localStorage 或 `storage_state`。
6. 现有 `RUFUS_REMOTE_CONSENT_REQUIRED` 安全门仍然有效。
7. 用户未回复已登录前，远程授权路径不会调用 MCP remote 获取工具。
8. 单元测试覆盖偏好不存在、偏好为 true、偏好为 false、用户修改偏好、用户已登录确认五类场景。

## 2026-06-04 变更需求：CDP 未启动时自动发现并启动 Chrome

### 背景

Rufus CLI 依赖 Chrome DevTools Protocol 连接本地 Chrome。当前用户常遇到 `CHROME_CDP_UNAVAILABLE`：Chrome 未以 remote debugging 模式启动，或 `chrome.exe` 不在 PATH 中，导致 `amazon-rufus get` 无法继续。用户希望 Skill 能帮助处理这个问题：先检查 CDP 状态，CDP 不可用时自动搜索本机 Chrome，再通过 Python 启动带 CDP 的 Chrome。

### 目标

1. `opscli amazon-rufus get` 支持“CDP 不可用时自动启动 Chrome”的真实能力。
2. 启动前必须先检查当前 `cdp_url` 是否可用，避免重复启动 Chrome。
3. 未指定 `chrome_path` 时，系统能搜索用户已安装的 Chrome。
4. 启动 Chrome 必须使用 Python 逻辑完成，不依赖用户手写 PowerShell 命令。
5. 启动时必须使用 opscli 专用 `user-data-dir`，避免污染用户默认 Chrome profile，并满足 Chrome 136+ remote debugging 限制。
6. `ops-amazon-rufus` Skill 更新编排规则，让 Agent 在 CDP 未启动时优先使用自动启动路径。

### 非目标

1. 不在 Skill 目录新增 `scripts/get_rufus.py`、`scripts/start_chrome.py` 或任何采集脚本。
2. 不全局安装、更新或卸载 Chrome。
3. 不修改系统环境变量、注册表或默认浏览器设置。
4. 不复用用户默认 Chrome profile 开启 remote debugging。
5. 不新增独立 GUI 或浏览器管理后台。
6. 不改变 Rufus seed 捕获、replay、报告生成和题库解析逻辑。

### 功能需求

#### FR-CDP-1 先检查 CDP 状态

执行自动启动前，系统必须先检查 `cdp_url`：

```text
GET {cdp_url}/json/version
```

只要返回可用的 HTTP 响应并能被 Playwright 连接，就不启动新的 Chrome。

#### FR-CDP-2 自动搜索 Chrome 路径

当 CDP 不可用且需要启动 Chrome 时，系统应按顺序搜索：

1. 用户显式传入的 `--chrome-path`。
2. Windows 注册表 `App Paths\chrome.exe`。
3. Windows 常见安装路径，例如 `Program Files`、`Program Files (x86)`、用户 LocalAppData。
4. PATH 中的 `chrome` / `chrome.exe`。
5. macOS 和 Linux 的常见 Chrome/Chromium 路径作为跨平台兜底。

找不到 Chrome 时返回稳定错误，并提示用户通过 `--chrome-path` 指定。

#### FR-CDP-3 Python 启动 Chrome CDP

启动逻辑必须由 Python 完成，推荐使用 `subprocess.Popen()`，参数列表必须逐项传入，避免拼接 shell 字符串。

启动参数至少包含：

```text
--remote-debugging-port=<port>
--remote-debugging-address=127.0.0.1
--user-data-dir=<opscli 专用 Rufus profile>
--no-first-run
--no-default-browser-check
```

启动后轮询 CDP endpoint，直到可用或超时。

#### FR-CDP-4 CLI 参数落地

现有 CLI 参数必须从“预留”变为可用：

```text
--launch-if-needed
--chrome-path <path>
```

语义：

1. `--launch-if-needed`：先连现有 CDP；失败后搜索并启动 Chrome。
2. `--chrome-path`：指定 Chrome 可执行文件路径，跳过自动搜索或作为最高优先级候选。
3. `--new-chrome`：仍表示无条件先启动一个新调试窗口。

#### FR-CDP-5 MCP 与 Skill 编排

MCP `amazon_rufus_get` 推荐同步支持 `launch_if_needed` 和 `chrome_path`，让 Agent 不必回退 CLI。

Skill 文档应增加规则：

1. 普通获取优先调用 `amazon_rufus_get` 默认后端/headless 链路；用户拒绝保存浏览器状态时，改用 `opscli amazon-rufus get ... --launch-if-needed`。
2. 如果工具返回 `CHROME_CDP_UNAVAILABLE` 且未启用自动启动，重试时应启用自动启动。
3. 如果自动搜索失败，应询问用户 Chrome 安装路径，再传入 `chrome_path`。
4. 不要求用户手动执行 PowerShell 启动命令，除非自动启动也失败。

#### FR-CDP-6 错误与敏感信息

错误信息不得输出 cookie、localStorage、storage_state、seed request 或完整环境变量。允许输出：

1. `cdp_url`
2. 是否尝试自动启动
3. Chrome 路径是否找到
4. 建议的 `--chrome-path` 下一步

### 验收标准

1. CDP 已启动时，`--launch-if-needed` 不重复启动 Chrome。
2. CDP 未启动且能找到 Chrome 时，自动启动 Chrome，并继续连接 `connect_over_cdp()`。
3. 用户传入 `--chrome-path` 时优先使用该路径。
4. 找不到 Chrome 时返回 `CHROME_CDP_UNAVAILABLE`，message 提示指定 `--chrome-path`。
5. `opscli amazon-rufus get --help` 中 `--launch-if-needed` 不再标注“预留”。
6. MCP 工具可传 `launch_if_needed=True` 并透传到 Manager。
7. Skill 文档包含 CDP 未启动的处理分支。
8. 单元测试不启动真实 Chrome，通过 monkeypatch 验证路径发现、启动参数和 CDP 探测顺序。

## 2026-06-04 变更需求：CLI `-q/--question` 支持多临时问题

### 背景

当前 `amazon-rufus get` 已支持 `--question` 单题模式，可以在用户传入明确问题时跳过默认题库。但用户现在需要更进一步：支持类似 `-q` 的短参数，并允许一次输入多个临时问题来提问，而不是读取问题模板。

### 目标

1. `opscli amazon-rufus get` 支持 `-q` 作为 `--question` 的短别名。
2. 同一次 CLI 调用允许多次传入 `-q/--question`，按传入顺序逐题获取答案。
3. 传入任意临时问题时跳过默认题库，不读取 `question_templates.json`。
4. 单题旧用法继续兼容：`--question "问题"` 仍可用。
5. MCP Tool 与 CLI 问题来源语义保持一致，可支持多个临时问题。
6. Skill 文档同步更新，不再描述“临时多问题只能逐条调用”。

### 非目标

1. 不新增 `ask`、`questions` 等新子命令。
2. 不新增问题文件参数、JSON 参数或分隔符语法。
3. 不把临时问题写回默认题库。
4. 不改变 Rufus replay、parser、报告格式化或浏览器捕获主链路。
5. 不改变未传问题时的默认题库模式。

### 功能需求

#### FR-MQ-1 CLI 支持短选项

`amazon-rufus get` 的问题选项必须同时支持：

```text
--question
-q
```

示例：

```powershell
opscli amazon-rufus get B0TEST1234 US -q "这个商品适合送礼吗？"
```

#### FR-MQ-2 CLI 支持多次传入问题

同一次命令允许多次传入 `-q/--question`：

```powershell
opscli amazon-rufus get B0TEST1234 US `
  -q "这个商品适合送礼吗？" `
  -q "差评主要集中在哪些方面？"
```

系统必须按 CLI 输入顺序生成 `questions` 列表，并逐题获取答案。

#### FR-MQ-3 临时问题跳过题库

只要用户传入至少一个有效临时问题，系统必须跳过 `QuestionBankService.load_templates()`，不依赖本地题库文件是否存在或为空。

#### FR-MQ-4 空白问题校验

任何显式传入的空字符串或全空白问题都必须返回稳定错误，不得静默过滤，也不得回退题库模式。

推荐错误：

```json
{
  "code": "INVALID_RUFUS_QUESTION",
  "message": "--question/-q 不能为空"
}
```

#### FR-MQ-5 Service 层兼容单题与多题

`RufusManager` 应支持临时问题列表，同时保留现有单题参数兼容：

1. 新增 `questions: list[str] | None` 内部参数。
2. 保留 `question: str | None`，旧调用继续可用。
3. 当 `questions` 和 `question` 同时存在时，应返回参数冲突错误，避免来源歧义。

#### FR-MQ-6 MCP 支持多题

MCP Tool 推荐新增 `questions: list[str] | None` 参数，保留 `question: str | None` 兼容。调用方传入多个临时问题时，工具一次生成一份报告。

#### FR-MQ-7 Skill 文档同步

`ops-amazon-rufus` Skill 应更新问题来源选择规则：

1. 用户给出单个明确问题时，用单题模式。
2. 用户给出多个明确问题时，用多题临时问题模式。
3. 用户只要求默认报告、完整分析或未给问题时，才使用默认题库。

### 验收标准

1. `opscli amazon-rufus get --help` 展示 `--question` 和 `-q`。
2. 单次 `-q "问题"` 仍生成单题报告。
3. 多次 `-q` 按顺序生成多题报告。
4. 多题模式不读取题库；题库缺失时仍可执行到 Rufus 获取链路。
5. 任一空白问题返回 `INVALID_RUFUS_QUESTION`。
6. MCP Tool 成功处理 `questions=["问题一", "问题二"]` 并返回 `question_count=2`。
7. 现有题库模式、远程授权模式和报告输出测试继续通过。

## 2026-06-03 变更需求：未登录时远程获取授权与 Rufus MCP 链路

### 背景

当前 Rufus CLI 在 Amazon 未登录或未捕获 `/rufus/cl/streaming` 时，会保留浏览器窗口并要求用户完成本机登录后继续。用户现在要求在“未登录 Amazon”场景下新增一个可选远程获取分支：先询问用户是否同意远程获取 Rufus 数据；如果不同意，继续走现有本机流程；如果同意，则登录后提取 cookie 和 localStorage，保存到本地，并调用 Rufus MCP 工具获取 Rufus 信息。

### 目标

1. 在检测到 Amazon 未登录时，向用户明确询问是否同意远程获取 Rufus 数据。
2. 询问文案必须说明：远程获取需要一个干净、未绑定信用卡的 Amazon 账户；该账户仅用户本人使用，不会共享给其他用户。
3. 用户不同意时，继续走现有本机获取流程，并提示本机运行期间可能出现卡顿。
4. 用户同意时，仍打开 Amazon 页面并检查登录；用户完成登录后，捕获该站点 cookie 和 localStorage 并保存到本地。
5. 保存本地状态后，调用 Rufus MCP 工具，传入 cookie/localStorage 获取 Rufus 信息。
6. MCP 获取完成后继续原有 Skill 流程，包括问题来源选择、拒答改写、报告格式化和最终路径输出。

### 非目标

1. 不自动创建、托管或共享 Amazon 账号。
2. 不验证 Amazon 账号是否真的未绑定信用卡；系统只做明确提示与用户确认。
3. 不建立账号池、多用户共享队列或后台调度。
4. 不把 cookie/localStorage 输出到终端、报告、错误详情或 `output/` 目录。
5. 不改变用户拒绝远程获取后的现有本机 Chrome/CDP 流程。
6. 不在文档确认前创建 `.super-dev/changes/*` 或开始编码。

### 功能需求

#### FR-REMOTE-1 未登录时询问远程获取授权

当 `amazon-rufus get` 检测到当前 Amazon 页面未登录，或现有登录态无法获取有效 Rufus 答案时，系统必须暂停并向用户询问是否同意远程获取 Rufus 数据。

询问文案必须包含：

1. 当前 Amazon 未登录或登录态不可用。
2. 是否同意远程获取 Rufus 数据。
3. 远程获取需要一个干净、未绑定信用卡的 Amazon 账户。
4. 该账户仅用户本人使用，不会共享给其他用户。
5. 如果不同意，将继续本机获取流程，运行期间系统可能卡顿。

#### FR-REMOTE-2 用户不同意时保持现有流程

用户选择不同意时：

1. 不读取、不保存 cookie 或 localStorage。
2. 不调用 Rufus MCP 工具。
3. 继续执行当前本机 Chrome/CDP 获取流程。
4. 保留现有 `RUFUS_LOGIN_REQUIRED` 和 `SEED_REQUEST_NOT_CAPTURED` 的中断续跑语义。
5. 提示用户本机获取期间可能出现卡顿。

#### FR-REMOTE-3 用户同意后打开 Amazon 登录页

用户选择同意时：

1. 系统仍按当前国家站点打开 Amazon 页面。
2. 系统检查页面登录状态；未登录时提示用户在新窗口完成登录。
3. 登录完成后再捕获浏览器状态，不得在用户登录前保存空状态。
4. 切换国家站点时，只捕获当前 `country` 对应站点的状态。

#### FR-REMOTE-4 捕获并保存 cookie/localStorage

登录完成后，系统必须捕获当前浏览器上下文中的 cookie 和 localStorage。推荐使用 Playwright `storage_state()` 作为标准结构，因为它包含：

1. `cookies`
2. `origins[].localStorage`

保存要求：

1. 状态必须保存到本地，但不得保存到仓库目录、`.agents/skills/` 或 `output/`。
2. 状态应保存在 `opscli.config.CONFIG_DIR` 下的 Rufus 专属目录，并使用加密文件或等价保护。
3. 不在 stdout、报告、异常 message、日志或 feedback payload 中回显状态内容。
4. 同一国家站点的新状态覆盖旧状态，避免多账号状态混用。

#### FR-REMOTE-5 调用 Rufus MCP 工具

保存状态后，系统调用 Rufus MCP 工具获取数据。工具入参至少包含：

1. `asin`
2. `country`
3. `questions`
4. `storage_state` 或等价的 `cookies + localStorage`
5. `timeout_seconds`

工具返回结构必须与当前 `RufusManager.get()` 结果兼容，至少包含：

1. `asin`
2. `country`
3. `page_url`
4. `question_count`
5. `questions`
6. `answers`

#### FR-REMOTE-6 继续原有 Skill 流程

Rufus MCP 获取完成后，系统必须复用原有 Skill 输出链路：

1. 若用户提供 `--question`，仍使用单题模式。
2. 未提供问题时，仍使用默认题库模式。
3. 仍执行拒答检测和 180 字内中文改写重试。
4. 仍用 `AnswerReportFormatter` 写入 `output/amazon-rufus/<ASIN>-YYYYMMDD-HHMMSS.md`。
5. 最终只回复报告路径，不输出 cookie、localStorage、seed request、upload payload 或原始 JSON。

#### FR-REMOTE-7 远程获取失败的降级处理

如果用户已同意远程获取，但 Rufus MCP 工具调用失败：

1. 错误信息不得泄漏 cookie/localStorage。
2. 系统应提示可退回本机获取流程。
3. 若用户选择退回本机流程，按 FR-REMOTE-2 继续执行。
4. Rufus MCP 工具本身的异常属于工具失败，应按 ops-feedback 铁律处理；用户主动拒绝或登录中断不属于工具异常。

### 验收标准

1. 未登录 Amazon 时，CLI/Skill 会先询问是否同意远程获取 Rufus 数据。
2. 询问文案包含“干净、未绑定信用卡的账户”“仅你本人使用”“不会共享给其他用户”“不同意则本机获取且可能卡顿”。
3. 用户不同意时，不保存任何 Amazon cookie/localStorage，不调用 Rufus MCP，仍走现有本机流程。
4. 用户同意并完成登录后，本地保存结构包含 cookies 与 localStorage。
5. 保存路径不在仓库目录、`.agents/skills/` 或 `output/` 下。
6. Rufus MCP 工具收到 `asin/country/questions/storage_state/timeout_seconds` 并返回兼容数据。
7. MCP 返回成功后，报告格式、路径和 Skill 最终回复与现有流程一致。
8. stdout、报告和错误 JSON 不包含 cookie、localStorage 或完整 storage_state。
9. 现有本机 Rufus 获取测试继续通过。

## 2026-06-03 变更需求：Python 端 headless 获取 Rufus 数据调用方法

### 背景

当前 Rufus CLI 主要依赖用户可见 Chrome 登录态：先 `amazon-rufus init` 打开窗口，再 `amazon-rufus get` 连接 CDP 捕获 seed request。用户现在要求补充 Python 端获取 Rufus 数据能力，并参考 `E:/code/work/extension/python` 的 headless browser 实现。

### 目标

1. 提供一个明确的 Python 调用入口，允许业务代码直接获取 Rufus 答案数据。
2. 使用 Playwright headless browser 捕获 Amazon Rufus 动态请求上下文。
3. 支持传入 Amazon `cookie`、header、payload_template，并用该 `cookie` 获取 Rufus 数据，避免依赖用户手工打开 Chrome。
4. 输出结构与现有 `RufusManager.get()` 兼容，继续复用报告生成与后续数据处理。
5. 不把 cookie、headers、原始 request body 输出到终端或报告中。

### 非目标

1. 本阶段不直接改代码，不创建 `.super-dev/changes/*`。
2. 不替换现有 CDP attach 模式。
3. 不新增后台账号池、队列调度或持久化能力。
4. 不把敏感 cookie 设计成普通 CLI 明文参数。
5. 不在测试中访问真实 Amazon 或真实浏览器 profile。

### 功能需求

#### FR-HEADLESS-1 Python 调用入口

新增 Python 端调用方法，建议命名为 `RufusManager.get_headless(...)`。调用者传入 ASIN、国家、问题或题库来源，以及 Rufus 请求来源信息。

建议调用形态：

```python
data = RufusManager().get_headless(
    asin="B0TEST1234",
    country="US",
    question="这个商品适合送礼吗？",
    streaming_url="https://www.amazon.com/rufus/cl/streaming?tabId=...",
    headers=headers,
    cookie=amazon_cookie,
    payload_template=payload_template,
    timeout_seconds=180,
)
```

`cookie` 是完整 Amazon Cookie header 字符串，必须作为必填参数传入。实现应参考 `E:/code/work/extension/python` 中 `capture_rufus_payload_context_for_asin(asin, cookie, origin_url)` 的调用语义。

#### FR-HEADLESS-2 Headless 捕获上下文

方法内部必须通过 Playwright headless browser 打开 Amazon 商品页，并捕获首个匹配 `rufus/cl/streaming` 的请求和响应。打开页面前必须将传入的 `cookie` 注入 browser context，确保商品页具备 Amazon 登录态。

捕获结果至少包含：

1. `request_url`
2. `request_headers`
3. `request_body`
4. `impressionsContext`
5. `requestContext`
6. `final_page_url`

#### FR-HEADLESS-3 Rufus 问答请求

获取动态上下文后，系统应基于 `payload_template` 构造每个问题的 payload，并通过 Rufus streaming URL 发起 POST 请求，解析 SSE 响应为现有 `AnswerData` 兼容结构。该 POST 请求同样必须使用传入的 `cookie`，避免捕获上下文与请求登录态不一致。

#### FR-HEADLESS-4 输出兼容

`get_headless()` 返回的数据结构应与 `get()` 保持兼容，至少包含：

1. `asin`
2. `country`
3. `page_url`
4. `question_count`
5. `questions`
6. `answers`
7. `seed_request` 或等价 headless 捕获上下文

#### FR-HEADLESS-5 敏感信息保护

实现和调用示例不得把 cookie、headers、payload_template 明文写入日志、报告、异常详情或终端输出。

### 验收标准

1. Python 层可以用 `RufusManager().get_headless(...)` 完成单题 Rufus 获取。
2. 默认题库模式仍可复用问题解析逻辑。
3. 返回结果能被现有 `AnswerReportFormatter` 消费。
4. 捕获失败时返回稳定业务异常，不泄漏 cookie/header。
5. 单元测试通过 mock Playwright captor 和 httpx streaming client 验证 `cookie` 被传入捕获流程和 Rufus streaming 请求流程。
6. 现有 `amazon-rufus init/get` CDP 模式不回归。

## 2026-05-14 变更需求：拒答检测与 180 字内问题改写

### 背景

用户进一步明确：本轮不是只处理 `--question` 为空的问题，而是需要对 Rufus 返回的答案进行分析。如果答案属于拒绝回答，系统应在保持原有语义的前提下修改问题，并把改写后的问题限制在 180 字以内，然后重新获取答案。

2026-05-14 用户新增约束：拒答后重新生成的问题必须是中文。该约束对单题模式和题库模式都生效。

### 目标

1. 对每个 Rufus 答案执行拒答检测。
2. 当答案被判定为拒答时，自动生成 180 字以内的语义等价问题。
3. 改写后的重试问题必须使用中文。
4. 用改写后的问题最多重试 3 次；加上原问题首次执行，单题最多 4 次尝试，避免无限循环。
5. 单题模式和题库模式都支持拒答重试。
6. 报告和结构化数据中保留拒答改写的审计信息。

### 非目标

1. 不引入外部 LLM 或远端改写 API。
2. 不做无限多轮自动改写。
3. 不把普通超时、空答案或网络失败直接当作拒答。
4. 不修改题库源文件；题库问题被改写只影响本次运行。
5. 不输出 seed request、headers、cookie 或内部原始 JSON。

### 功能需求

#### FR-REFUSAL-1 答案拒答检测

每次 `RufusParserService.parse()` 产出 `AnswerData` 后，系统必须分析回答内容是否拒答。

检测范围：

1. `answer.text`
2. `answer.summaryText`
3. 可转为文本的 `answer.blocks`

拒答特征包括但不限于：

- “我无法回答”
- “不能提供”
- “无法提供”
- “不方便回答”
- “I can't answer”
- “I cannot answer”
- “I'm unable to”
- “not able to assist”

#### FR-REFUSAL-2 拒答后改写问题

当答案被判定为拒答时，系统必须基于原问题生成一个改写问题。

改写约束：

1. 保持原有语义，不改变商品对象、分析维度或用户意图。
2. 改写后问题不超过 180 字。
3. 改写后问题必须使用中文；原问题为英文或中英混合时，应转写为自然中文问句。
4. 使用更中性、面向公开商品信息的表达。
5. 不添加用户没有提出的新分析维度。

#### FR-REFUSAL-3 最多 3 次重试

每个问题最多自动改写并重试 3 次：

1. 第一次使用原问题。
2. 若某次答案拒答，则在保持原语义的前提下生成新的 180 字以内问题并重试。
3. 最多执行 3 次改写重试；加上原问题首次执行，`attemptCount` 最大为 4。
4. 若 3 次改写重试后仍拒答，保留最后一次答案，并标记“已改写 3 次后仍拒答”。

#### FR-REFUSAL-4 结构化输出元信息

当发生拒答检测或改写时，答案结构中必须包含审计字段：

```json
{
  "refusalDetected": true,
  "refusalRetryApplied": true,
  "originalQuestion": "原问题",
  "rewrittenQuestion": "改写后问题",
  "attemptCount": 4
}
```

未发生拒答时可省略这些字段或显式置为 false，但实现必须保持现有 `AnswerData` 基础字段兼容。

#### FR-REFUSAL-5 报告展示

报告默认展示最终答案。若发生拒答改写，应在对应题目前展示简短说明：

```text
已检测到首次回答拒答，已在保持原语义的前提下改写问题并重试。
改写后问题：基于商品页面和公开评价，分析该商品是否适合送礼，并说明理由
```

报告不展示完整首次拒答原文，除非用户明确要求排障。

#### FR-REFUSAL-6 与问题来源兼容

拒答处理必须同时适用于：

1. `--question` 单题模式。
2. 本地题库模式。

题库模式下，改写只影响本次运行，不写回 `.agents/skills/ops-amazon-rufus/data/question_templates.json`。

### 验收标准

1. 构造包含拒答短语的 Rufus answer，系统能识别为拒答。
2. 拒答后生成的改写问题不超过 180 字。
3. 拒答后生成的改写问题必须为中文。
4. 改写问题保留原问题核心语义。
5. 拒答后最多重试 3 次，不发生无限循环。
6. 3 次改写重试后仍拒答时，报告和数据能体现“已改写 3 次后仍拒答”。
7. 题库模式与 `--question` 模式都覆盖拒答重试测试。
8. 空白 `--question` 仍作为输入校验返回 `INVALID_RUFUS_QUESTION`，但不与拒答检测混淆。

## 2026-05-14 变更需求：CLI 传入问题与题库双模式

### 背景

当前 `opscli amazon-rufus get <asin> <country>` 只能读取本地默认题库并逐题获取 Rufus 答案。用户现在希望支持第二种方式：调用 CLI 时直接传入一个问题，让 Rufus 只回答该问题。这样 Agent 在用户已经给出明确问题时，不需要先跑完整题库，也不需要依赖题库是否已同步。

### 目标

1. 保留现有题库模式：未传问题时继续读取 `ops-amazon-rufus/data/question_templates.json`。
2. 新增单题模式：传入 `--question "<问题>"` 时只执行该问题。
3. 单题模式复用现有浏览器、seed request、replay、parser、报告落地和错误结构。
4. Skill 文档同步更新，让 Agent 能按用户意图选择题库模式或单题模式。
5. 不改变 `opscli amazon-rufus get <asin> <country>` 的既有默认行为。

### 非目标

1. 不新增 `ask`、`question` 等新子命令。
2. 不支持一次传入多个临时问题。
3. 不把临时问题写入 `question_templates.json`。
4. 不新增题库保存能力；题库保存仍属于问题模板管理域。
5. 不改变 Rufus replay 参数、SSE 解析或报告格式化规则。

### 功能需求

#### FR-QUESTION-1 新增 `--question` 选项

`amazon-rufus get` 新增可选参数：

```powershell
opscli amazon-rufus get B0TEST1234 US --question "这个商品适合送礼吗？" --new-chrome
```

参数规则：

1. `--question` 为字符串选项。
2. 参数值去除首尾空白后作为唯一问题。
3. 问题文本包含空格或标点时，用户应使用引号包裹。
4. `--question` 不影响 `asin`、`country` 两个位置参数。

#### FR-QUESTION-2 单题模式跳过题库读取

当传入有效 `--question` 时，`RufusManager.get()` 必须直接使用该问题构造问题列表：

```python
questions = [question.strip()]
question_source = "cli"
```

单题模式不得调用 `QuestionBankService.load_templates()`，因此不会因为本地题库缺失或为空而失败。

#### FR-QUESTION-3 默认题库模式保持不变

当未传 `--question` 时，系统必须保持现有行为：

1. 读取本地 `ops-amazon-rufus/data/question_templates.json`。
2. 按模板和 `questions[].position` 生成问题列表。
3. 题库缺失或为空时继续返回 `QUESTION_BANK_NOT_READY`。
4. 输出报告仍按题库问题顺序生成。

#### FR-QUESTION-4 空问题校验

当用户显式传入空问题或全空白问题时，系统必须返回稳定错误，不得静默回退题库模式。

推荐错误：

```json
{
  "code": "INVALID_RUFUS_QUESTION",
  "message": "--question 不能为空"
}
```

#### FR-QUESTION-5 输出数据标识来源

Manager 返回数据中应增加轻量来源字段：

```json
{
  "question_source": "cli"
}
```

取值：

- `cli`：问题来自 `--question`。
- `template`：问题来自本地题库。

现有 `questions` 字段保持为字符串列表，保证 `AnswerReportFormatter` 继续复用。

#### FR-QUESTION-6 Skill 同步修改

`opscli/skills/templates/ops-amazon-rufus/SKILL.md` 和 `README.md` 必须同步描述两种工作流：

1. 有明确问题：优先执行 `--question` 单题模式。
2. 无明确问题或用户要求完整默认分析：执行题库模式。

Skill 文档必须强调：单题模式仍需要 Amazon 登录和 seed request 捕获，但不要求先升级题库。

### 验收标准

1. `opscli amazon-rufus get --help` 展示 `--question`。
2. 传入 `--question "问题"` 时，manager 使用单题列表，且不读取题库。
3. 未传 `--question` 时，现有题库模式测试继续通过。
4. 显式空白 `--question` 返回 `INVALID_RUFUS_QUESTION`。
5. 单题模式生成的报告标题包含用户传入的问题。
6. 单题模式 stdout 仍只输出 `output/amazon-rufus/<ASIN>-YYYYMMDD-HHMMSS.md` 保存路径。
7. `SKILL.md` 和 `README.md` 均包含单题模式示例和题库模式选择规则。

## 2026-05-14 变更需求：问题模板 reference 拆分与保存接口文档

### 背景

当前 `ops-amazon-rufus` 的文档结构把问题模板升级说明、Rufus 回答获取、登录前置、答案格式化混在同一条阅读路径里。用户希望把“问题模板”单独拆成一个 `references` 文档，后续只保留问题模板相关内容，并补充“保存模板”的接口调用说明。

前端真实入口已经表明问题模板是独立管理域：

- `opencalw-management/index.vue` 只负责页面壳和 tab。
- `QuestionTemplatesTab.vue` 负责模板列表、新增、编辑、删除、问题列表管理。
- `QuestionTemplateDescriptionDialog.vue` 负责模板保存。
- `QuestionTemplateQuestionsDialog.vue` 负责问题保存、追加、修改、删除、清空。

### 目标

1. 将问题模板相关说明从 `ops-amazon-rufus` 主使用流中拆出，形成独立 reference。
2. 新 reference 只保留问题模板相关内容，不再混入 `amazon-rufus get` 回答流程。
3. 在 reference 中同时写清楚“获取默认模板”和“保存管理端模板”的接口。
4. 保留当前 `amazon-rufus get` 与答案格式化文档不变的职责边界。
5. 不新增 CLI 运行时功能，只做文档与引用结构调整。

### 非目标

1. 不新增 `amazon-rufus` 新命令。
2. 不修改 Rufus 采集、重放、解析或报告格式化逻辑。
3. 不把管理端模板保存接口接到 `opscli` 运行链路。
4. 不把问题模板 reference 写成答案报告格式化文档。
5. 不要求用户理解前端实现细节，只输出可执行的接口说明。

### 功能需求

#### FR-QT-1 独立 reference 文件

新增一个仅服务问题模板的 reference 文档，建议路径：

`opscli/skills/templates/ops-amazon-rufus/references/question-templates.md`

该文档应只包含：

- 问题模板数据结构
- 获取默认题库接口
- 模板管理接口
- 问题列表保存接口
- 保存工作流
- 本地 `question_templates.json` 与远端接口的关系

#### FR-QT-2 主文档只保留跳转

`README.md` 与 `SKILL.md` 中与题库相关的说明只保留最小入口：

- `opscli skills install ops-amazon-rufus`
- `opscli skills upgrade ops-amazon-rufus`
- 链接到 `references/question-templates.md`

不再把管理端模板接口细节写进回答获取流程。

#### FR-QT-3 获取接口文档

reference 必须说明默认题库来源：

- `GET /opencalw/default-question-templates`

并写清楚本地同步结果落盘到：

- `.agents/skills/ops-amazon-rufus/data/question_templates.json`

#### FR-QT-4 保存接口文档

reference 必须补全保存相关接口：

- `POST /admin/opencalw/question-templates`
- `PATCH /admin/opencalw/question-templates/{templateId}`
- `PUT /admin/opencalw/question-templates/{templateId}/questions`
- `PUT /admin/opencalw/question-templates/{templateId}/questions/append`
- `PUT /admin/opencalw/question-templates/{templateId}/questions/{questionId}`
- `DELETE /admin/opencalw/question-templates/{templateId}`
- `DELETE /admin/opencalw/question-templates/{templateId}/questions/{questionId}`

#### FR-QT-5 保存工作流

reference 需要按前端交互顺序描述：

1. 新增模板只提交 `description`。
2. 修改模板描述只提交 `description`。
3. 新增问题通过 `append` 接口追加。
4. 整体保存问题列表通过 `PUT .../questions` 覆盖写入。
5. 单题修改与删除分别走单题接口。

#### FR-QT-6 数据格式说明

文档必须明确：

1. 前端使用 camelCase 类型名。
2. 实际请求/响应经 `extensionInterceptors` 转换后，wire JSON 与本地 `question_templates.json` 仍按 snake_case 文档化。
3. `question_templates.json` 继续作为 Skill 远端升级结果，不是运行时生成报告。

### 验收标准

1. 能在 `ops-amazon-rufus` 文档树中找到独立的 `question-templates` reference。
2. `README.md` / `SKILL.md` 不再把题库接口和 Rufus 回答流程混在一起。
3. reference 中同时覆盖获取与保存接口。
4. reference 中明确本地题库文件与远端接口的关系。
5. 不改动现有 `amazon-rufus get` 用户流程和答案报告文档。

## 2026-05-07 变更需求：登录前置提示与 streaming 捕获失败指引

### 背景

`ops-amazon-rufus` 依赖浏览器中的 Amazon 登录态。虽然 Skill 文档已经说明需要先登录对应国家站点，但用户在安装 Skill 后仍可能直接执行 `get`，并在没有捕获到 `/rufus/cl/streaming` 时不知道下一步该执行什么命令。

本轮目标是把“需要先登录 Amazon”和“未捕获 streaming 后执行 init”变成 CLI 稳定契约，而不是只存在于文档或经验中。

### 目标

1. 安装 `ops-amazon-rufus` 后，安装结果必须提示使用前需要登录 Amazon。
2. 安装提示必须给出 `opscli amazon-rufus init <country>` 作为登录初始化命令。
3. `amazon-rufus get` 未捕获 `/rufus/cl/streaming` 时，错误信息必须让用户执行 `init` 登录后重试。
4. 保持现有成功 JSON 和错误 JSON 顶层结构稳定。
5. 不新增 Amazon 凭证管理能力，不在 CLI 内保存 Amazon 账号信息。

### 非目标

1. 不自动登录 Amazon。
2. 不自动调用 `amazon-rufus init`。
3. 不检测或展示 Amazon 用户身份。
4. 不改变题库升级、Rufus replay、报告格式化和上传 payload。
5. 不对其他 Skill 增加 Rufus 专属安装提示。
6. 不在非交互安装成功输出中追加 JSON 之外的散文本。

### 功能需求

#### FR-LOGIN-1 安装后登录前置提示

当用户执行以下命令并成功安装 `ops-amazon-rufus`：

```bash
opscli skills install ops-amazon-rufus
```

安装结果的 `data` 必须包含登录前置提示，建议字段：

```json
{
  "requires_amazon_login": true,
  "next_steps": [
    "使用前必须先登录对应国家站点的 Amazon 账户。",
    "请先执行 opscli amazon-rufus init <country>，在新窗口完成登录。",
    "登录后再执行 opscli amazon-rufus get <asin> <country> --new-chrome。"
  ]
}
```

约束：

1. 仅 `ops-amazon-rufus` 安装结果增加这些字段。
2. 其他 Skill 的安装输出保持原有字段。
3. 非交互安装 stdout 仍是单个 JSON payload，避免破坏脚本解析。
4. `--pretty` 只影响 JSON 缩进，不改变字段含义。
5. 安装失败时不输出登录提示，只输出原有错误结构。

#### FR-LOGIN-2 交互安装结果一致

当用户通过交互安装流程安装 `ops-amazon-rufus` 时，最终 JSON 结果中同样必须包含登录提示字段。若交互流程已有 Rich 文本进度输出，最终 payload 仍必须携带机器可读 `requires_amazon_login` 与 `next_steps`。

#### FR-STREAM-1 未捕获 streaming 的错误指引

当 `amazon-rufus get` 在等待期内没有捕获 `/rufus/cl/streaming` 请求时，系统必须返回稳定错误结构：

```json
{
  "success": false,
  "command": "amazon-rufus get",
  "data": null,
  "error": {
    "code": "SEED_REQUEST_NOT_CAPTURED",
    "message": "..."
  }
}
```

`message` 必须包含：

1. 未捕获 `/rufus/cl/streaming`。
2. 请执行 `opscli amazon-rufus init <country>`。
3. 在新窗口登录 Amazon 后重试。
4. 目标站点可能不支持 Rufus。
5. 当前商品页 URL，便于排障。

推荐文案：

```text
未捕获 /rufus/cl/streaming。请先执行 opscli amazon-rufus init US，并在新窗口登录 Amazon 后重试；同时确认目标站点支持 Rufus: https://www.amazon.com/dp/B0TEST1234
```

#### FR-STREAM-2 错误路径不生成报告

未捕获 streaming 属于采集失败，必须保持现有错误路径行为：

1. 退出码为 `1`。
2. 不生成 `output/amazon-rufus/*.md` 报告文件。
3. 不输出 `seed_request`、headers、cookie 或原始 JSON。
4. `--pretty` 只格式化错误 JSON。

### 验收标准

1. `opscli skills install ops-amazon-rufus` 成功输出中包含 `data.requires_amazon_login = true`。
2. `data.next_steps` 至少包含 `opscli amazon-rufus init <country>`。
3. `opscli skills install ops-dataset-query` 输出不包含 `requires_amazon_login`。
4. 交互安装 `ops-amazon-rufus` 的最终 JSON 中包含同样的登录提示字段。
5. `SeedRequestNotCapturedError` 的错误 message 包含 `opscli amazon-rufus init US`。
6. `amazon-rufus get` 未捕获 streaming 时返回 `SEED_REQUEST_NOT_CAPTURED`，退出码为 `1`。
7. 未捕获 streaming 时不生成答案报告文件。
8. 原有 `amazon_rufus` 与 `skills` 测试继续通过。

## 2026-04-30 变更需求：参考前端渲染的答案格式化

### 背景

`amazon-rufus get` 目前成功时只输出 `answers[].text`，但输出文本来自 Rufus 流式内容还原，存在大量空行、项目符号拆行和结构化信息缺失问题。用户要求参考 operation-frontend 中 `asinRufusView` 的渲染方式，用 CLI 输出前拿到的全量数据对结果进行格式化。

### 目标

1. CLI 成功时默认将 Rufus 答案报告写入运行目录下的 `output/amazon-rufus`。
2. 输出格式参考前端 `AsinRufusSectionCard` 与 `AsinRufusAnswerBlocks` 的展示顺序。
3. 优先使用 `answer.blocks`、`productLinks`、`recommendedAsins`、`summaryText` 等结构化字段，而不是只输出 `answer.text`。
4. 格式化过程不得截断、总结、改写 Rufus 原文。
5. stdout 只输出报告保存路径，不再承载完整报告正文。

### 非目标

1. 不修改 Rufus 请求、题库、SSE 解析或上传 payload 结构。
2. 不引入 GUI、Web 页面或默认分页器。
3. 不把原始 `seed_request`、headers、cookie 或 `upload_payload` 输出给最终用户。
4. 不使用 LLM 对答案二次润色，避免改变业务含义。
5. 不新增可配置文件输出参数；本轮固定使用运行目录下的 `output/amazon-rufus`。
6. 不实现分页器、剪贴板中转或交互式查看器。
7. 不尝试把已退化的一列文本强行猜测成表格。

### 功能需求

#### FR-FMT-1 默认报告式输出

`opscli amazon-rufus get <asin> <country>` 成功时，必须生成格式化后的答案报告文件。

文件路径规则：

1. 输出目录：`Path.cwd() / "output" / "amazon-rufus"`。
2. 文件名：`<ASIN>-YYYYMMDD-HHMMSS.md`。
3. `ASIN` 使用 manager 返回的标准化大写 ASIN。
4. 时间使用命令运行时本地时间，精确到秒。
5. stdout 输出保存路径提示，不输出完整报告正文。

每个问题按 section 输出：

1. 标题：`## 第 N 题：<question>`。
2. 相关产品：来自 `answer.productLinks`。
3. 答案正文：来自 `answer.blocks` 或 `answer.text`。
4. 推荐 ASIN：来自 `answer.recommendedAsins`。
5. 总结：来自 `answer.summaryText`。
6. 单题失败且文本为空时，继续输出 `第 N 题未获取到答案`。

#### FR-FMT-2 前端 block 模型对齐

正文渲染必须参考前端 `buildAsinRufusAnswerBlocks()`：

1. 优先消费 `answer.blocks`。
2. 支持 `heading`、`paragraph`、`list_item`、`table_row`。
3. 连续 `list_item` 合并为列表输出。
4. 连续 `table_row` 合并为 Markdown 表格输出，第一行作为表头，后续行作为表体。
5. 缺少 `blocks` 时回退解析 `answer.text`，支持 Markdown 标题、列表和带 delimiter 的 Markdown 表格。
6. 不满足表格条件的管道文本保持普通段落。

#### FR-FMT-3 原文保留

格式化器不得使用会主动丢弃内容的行数限制、字符数限制或摘要逻辑。只要 Rufus 返回了文本，CLI 展示层不得主动删减。

#### FR-FMT-4 输出安全边界

格式化输出不得包含：

1. `seed_request`
2. `upload_payload`
3. 请求头
4. cookie
5. 原始完整 JSON

#### FR-FMT-5 文件落地边界

文件写入必须满足：

1. 自动创建 `output/amazon-rufus` 目录。
2. 使用 UTF-8 编码写入报告，保证中文答案可读。
3. 成功路径不再把完整报告写入 stdout。
4. 如果 formatter 返回空字符串，仍写入空报告文件并输出路径，保持成功链路可追踪。
5. 错误路径维持现有 JSON 错误输出，不生成报告文件。

### 验收标准

1. 用前端 `answerBlocks.test.ts` 的样例构造 Python formatter 测试，验证 heading、paragraph、list、table 输出一致。
2. `answer.blocks` 存在时优先使用结构化 blocks，不直接输出 fallback text。
3. `productLinks`、`recommendedAsins`、`summaryText` 按前端顺序展示。
4. 成功执行后在运行目录的 `output/amazon-rufus` 生成 `<ASIN>-YYYYMMDD-HHMMSS.md`。
5. 现有隐藏 `seed_request` 与 `upload_payload` 的测试继续通过。
6. stdout 只包含保存路径提示，不包含报告正文、`seed_request` 或 `upload_payload`。
7. `tests/amazon_rufus/test_core.py` 新增 CLI 与 formatter 回归测试。

## 2026-04-29 变更需求：新增 init 登录初始化命令

### 背景

`amazon-rufus get` 使用独立 Chrome profile 打开 Amazon 商品页并复用浏览器登录态。首次使用时，用户需要先在该 profile 中登录 Amazon，否则 `get` 可能无法捕获 Rufus 请求或无法获得完整站点能力。

### 用户故事

作为运营或采集执行者，我希望先运行一条初始化命令打开对应国家的 Amazon 站点，并在新窗口中完成登录，从而让后续 `amazon-rufus get` 复用相同浏览器 profile 执行 Rufus 问答。

### 命令定义

```bash
opscli amazon-rufus init <country>
```

参数：

- `country`：国家名，沿用现有 `US/UK/DE/JP` 站点映射。

示例：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; uv run --extra amazon opscli amazon-rufus init US
```

### 功能需求

#### FR-INIT-1 国家站点解析

系统必须复用现有国家站点映射，将 `country` 解析为对应 Amazon 首页：

- `US -> https://www.amazon.com`
- `UK -> https://www.amazon.co.uk`
- `DE -> https://www.amazon.de`
- `JP -> https://www.amazon.co.jp`

不支持的国家必须返回现有稳定错误结构，并提示支持范围。

#### FR-INIT-2 浏览器打开方式

系统必须使用与现有 Rufus 获取流程相同的 Chrome 打开方式：

- 使用固定 remote debugging 端口 `9222`。
- 使用固定独立 profile `E:\chrome-profiles\opscli-rufus`。
- 通过 Playwright CDP 连接该 Chrome。
- 打开解析出的 Amazon 首页。

#### FR-INIT-3 用户提示

页面打开后，命令必须输出：

```text
请在新窗口中登录亚马逊
```

随后命令结束。

#### FR-INIT-4 窗口保留

`init` 命令结束时不得关闭新打开的 Chrome 窗口，以便用户继续完成登录，并让登录态写入固定 profile。

#### FR-INIT-5 职责边界

`init` 命令不得执行以下动作：

- 不读取 Rufus 题库。
- 不访问商品详情页。
- 不捕获 `/rufus/cl/streaming`。
- 不重放 Rufus 请求。
- 不构造上传 payload。

### 验收标准

1. `opscli amazon-rufus init --help` 可见。
2. `opscli amazon-rufus init US` 会打开 `https://www.amazon.com`。
3. `opscli amazon-rufus init DE` 会打开 `https://www.amazon.de`。
4. 成功打开后 CLI 输出 `请在新窗口中登录亚马逊`。
5. 命令结束后 Chrome 窗口保持打开。
6. 不支持的国家返回明确错误，不打开错误站点。

## 2026-04-29 变更需求：Skill 运行 UTF-8 与答案报告输出

### 背景

`ops-amazon-rufus` 面向 AI Agent 和运营同学使用，Rufus 回答包含中文、特殊符号和 Amazon 商品文本。若命令未在 UTF-8 环境下运行，Windows PowerShell 可能出现乱码；同时 Agent 使用场景只需要最终格式化报告，不需要把完整 JSON 暴露给用户。

### 目标

1. Skill 文档中的所有运行示例必须显式使用 UTF-8 环境变量。
2. 命令执行完成后，Skill 面向用户的最终输出返回报告保存路径，完整报告文件按前端渲染规则生成。
3. 原始 JSON 仅作为本地解析中间结果，不作为最终回复直接输出。
4. 不改变 `opscli amazon-rufus get <asin> <country>` 的核心运行链路。

### 非目标

1. 不移除 CLI 内部结构化 JSON 能力，避免破坏脚本与测试兼容性。
2. 不新增上传、批量调度或远端 API 调用能力。
3. 不在 Skill 层直接调用后端接口。

### 功能需求

1. PowerShell 示例必须在同一命令会话中设置 `$env:PYTHONUTF8 = "1"` 与 `$env:PYTHONIOENCODING = "utf-8"`。
2. `amazon-rufus get` 成功时只输出报告保存路径。
3. 当存在多条答案时，报告文件按题库顺序输出每个问题 section。
4. 当某题 `text` 为空但 `isSuccess` 为 `false` 时，报告文件应输出该题失败信息摘要，避免静默丢失。
5. 最终用户回复不得包含 `seed_request`、`upload_payload`、请求头或完整 JSON。

### 验收标准

1. `ops-amazon-rufus` 的 `SKILL.md` 和 `README.md` 均包含 UTF-8 运行示例。
2. 文档明确要求最终只向用户输出报告保存路径。
3. 原有 CLI 全量数据契约在架构文档中被标记为内部解析契约，而不是 Skill 最终展示契约。

## 2026-04-29 变更需求：复刻扩展端 Rufus 请求行为

### 背景

当前 `amazon-rufus` CLI 已能捕获 Rufus seed request 并逐题重放，但请求参数比扩展端 `AsinRufusDialog` 少。为提升回答成功率、上下文准确性和跨站点一致性，需要让 CLI 尽量复刻扩展端的请求构造行为。

### 目标

1. CLI 使用题库问题获取 Rufus 回答时，请求 body 字段与扩展端保持一致。
2. CLI 重放 URL 显式携带扩展端使用的 `tabId/programId/ref` 参数。
3. 保持现有命令入口、输出结构和题库加载方式不变，降低升级风险。
4. 不引入上传、远端 API、GUI 或新命令。

### 非目标

1. 不复制扩展端表单驱动的 `keyword/persona/optimizeAsin` 动态问题生成逻辑。
2. 不把浏览器所有 request headers 无差别注入页面内 fetch。
3. 不改变 `opscli amazon-rufus get <asin> <country>` 的用户交互路径。
4. 不在文档确认前创建 `.super-dev/changes/*` 或开始编码。

### 功能需求

1. Payload 构造必须基于 seed body 深拷贝，避免污染原始记录。
2. 每题必须替换 `queryContext.query`。
3. 每题必须设置 `queryContext.actionType = "SEARCH"`。
4. 每题必须设置 `queryContext.qis = "NileCLTextInput"`。
5. 每题必须设置 `pageContext.originPageType = "DETAIL_PAGE"`。
6. 每题必须确保 `pageContext.targetPageMetadata` 中存在 `{ type: "ASIN", value: <目标 ASIN> }`。
7. 每题必须确保 `pageContext.originPageMetadata` 中存在 `{ type: "ASIN", value: <目标 ASIN> }`。
8. 每题必须设置 `bottomSheetContext.previousTurnsBottomSheetSize = "expanded"`。
9. 每题必须设置 `impressionsContext.FIRST_TIME_USER_MESSAGE_SEEN_STATUS = "SEEN"`。
10. 当沿用上一题 `threadId` 时，`historyThreadContext` 必须包含 `threadId` 与 `threadState`，其中 `threadState` 默认 `THREAD_STATE_UNKNOWN`。
11. 重放 URL 必须保留 seed origin/path，并确保 query 参数包含 `tabId`、`programId=NILE_CLASSIC:desktop-cl`、`ref=nl_cl_dsk_csq`。

### 验收标准

1. 单元测试覆盖 body 补字段、ASIN metadata 覆盖/追加、URL query 参数补齐。
2. 原有 `amazon-rufus` 测试继续通过。
3. CLI 输出结构不破坏既有字段：`asin`、`country`、`page_url`、`question_count`、`answers`、`seed_request`、`upload_payload`。
4. 新实现保持 KISS：请求复刻逻辑集中在 replay/service 层，不分散到 CLI 层。

## 需求概述

新增一套 Amazon Rufus CLI 与 Skill 能力，支持用户基于已登录的本地 Chrome 会话，对指定 ASIN 自动发起题库问题并返回结构化答案。

本期交付目标：

- 新增命令：`opscli amazon-rufus get <asin> <country>`
- 新增 Skill：`ops-amazon-rufus`
- 支持 Skill 远端升级，用于同步题库与运行参数
- 复用 Amazon 商品页真实 Rufus 请求上下文
- 返回结构化答案
- 构造与现有前端一致的上传 payload，但暂不发送上传接口

---

## 用户故事

### 用户故事 1

作为使用 `opscli` 的运营同学或 AI Agent，
我希望输入一个 ASIN 和国家站点，
命令就能自动打开商品页、抓取 seed request、跑题库并返回回答，
这样我就不需要手工逐题在 Amazon 页面里点 Rufus。

### 用户故事 2

作为技能维护者，
我希望默认题库可以通过 `opscli skills upgrade ops-amazon-rufus` 更新，
这样不需要每次改题都发 CLI 代码版本。

### 用户故事 3

作为后续接口开发者，
我希望当前 CLI 输出的 upload payload 与前端既有格式兼容，
这样后面只要接入真实上传接口即可，无需重做数据模型。

---

## 成功标准

满足以下条件视为一期成功：

1. 用户执行 `opscli amazon-rufus get <asin> <country>` 时，能够在本地已登录 Chrome 上跑通完整流程。
2. 命令能捕获一个有效 seed request，并用它重放题库问题。
3. 至少能正确解析出每题的最终回答文本和结构化 answer 数据。
4. CLI 内部全量数据中包含以下解析字段，Skill 最终回复只展示格式化答案报告：
   - 请求上下文摘要
   - 逐题答案
   - 标准上传 payload
5. `opscli skills install ops-amazon-rufus` 与 `opscli skills upgrade ops-amazon-rufus` 能正常工作。

---

## 范围

### In Scope

- 新增 `amazon-rufus` 顶级 CLI 模块
- 新增 `get` 子命令
- Playwright attach 到本地 Chrome CDP 端口
- 基于国家码拼装商品页 URL
- 监听页面 `/rufus/cl/streaming` seed request
- 从本地 Skill 数据读取默认题目模板
- 逐题重放 Rufus
- 解析 SSE 为结构化 answer
- 构造标准上传 payload
- Skill 安装 / 状态 / 升级链路接入

### Out of Scope

- 真正调用上传接口
- 批量多 ASIN 调度
- 自动登录 Amazon
- 自建桌面 UI 或 Web UI
- 宿主 Chrome MCP 作为正式运行依赖

---

## 命令设计

### 主命令

```bash
opscli amazon-rufus get <asin> <country>
```

### 推荐选项

```bash
opscli amazon-rufus get <asin> <country> \
  [--cdp-url http://127.0.0.1:9222] \
  [--new-chrome] \
  [--chrome-path "C:/Program Files/Google/Chrome/Application/chrome.exe"] \
  [--launch-if-needed] \
  [--skills-dir <dir>] \
  [--timeout 180] \
  [--pretty] \
  [--no-upload-payload]
```

### 参数说明

- `asin`
  - 必填，10 位 Amazon ASIN
- `country`
  - 必填，2 位国家码，如 `US`、`UK`、`DE`、`JP`
- `--cdp-url`
  - 可选，Chrome DevTools 地址，默认 `http://127.0.0.1:9222`
- `--new-chrome`
  - 可选，先新开一个 Chrome 调试窗口，再连接默认 CDP 地址
- `--chrome-path`
  - 可选，Chrome 可执行文件路径
- `--launch-if-needed`
  - 可选，当 CDP 不可用时自动尝试启动 Chrome
- `--skills-dir`
  - 可选，指定 `ops-amazon-rufus` Skill 所在目录
- `--timeout`
  - 可选，单题最大等待秒数
- `--pretty`
  - 保留参数但不改变成功输出口径；成功时仍只输出报告保存路径
- `--no-upload-payload`
  - 可选，仅返回答案，不输出上传 payload

---

## 功能需求

### FR-1 题库读取

命令执行时必须先读取本地 `ops-amazon-rufus` Skill 数据，包括：

- 默认模板列表
- 模板内嵌问题列表

国家站点映射直接固定在代码中，不再作为 Skill 数据下发。

若本地数据缺失，应提示用户先执行：

```bash
opscli skills install ops-amazon-rufus
opscli skills upgrade ops-amazon-rufus
```

### FR-2 国家站点映射

系统必须根据 `country` 解析目标商品页 origin，例如：

- `US -> https://www.amazon.com`
- `UK -> https://www.amazon.co.uk`
- `DE -> https://www.amazon.de`
- `JP -> https://www.amazon.co.jp`

映射数据不写死在业务代码，走 Skill 数据文件。

### FR-3 Chrome attach

系统必须优先 attach 到用户本地已启动 Chrome。

新增 `--new-chrome` 参数后，系统必须先启动一个独立 Chrome 调试窗口，再连接 CDP。默认 Windows 启动命令固定为：

```powershell
Start-Process chrome.exe -ArgumentList '--remote-debugging-port=9222 --user-data-dir="E:\chrome-profiles\opscli-rufus" --no-first-run --no-default-browser-check'
```

该模式使用独立 `user-data-dir`，避免污染用户默认 Chrome profile，并确保 remote debugging 端口可被当前命令连接。

若 attach 失败：

- `--launch-if-needed` 未开启：直接报错，并提示用户手动以 remote debugging 模式启动 Chrome
- `--launch-if-needed` 开启且 `--chrome-path` 可用：尝试自动启动 Chrome
- `--new-chrome` 已开启：先执行固定启动命令，短暂等待 CDP 可用后再 attach；若仍失败，返回启动命令与 `--cdp-url` 排障提示

### FR-4 seed request 捕获

系统必须在进入商品页前注册监听器，尽早捕获 `/rufus/cl/streaming` request。

seed request 至少需要提取：

- `requestUrl`
- `requestBody`
- `requestHeaders`
- `tabId`
- `asin`
- `pageUrl`
- `country`

若未捕获到 seed request，应返回明确失败原因。

### FR-5 题库执行

系统必须按题库顺序逐题执行。

每题执行逻辑：

1. 基于 seed request 构造新的 payload
2. 替换问题文本
3. 必要时带回 `historyThreadContext`
4. 发送 Rufus 请求
5. 解析回答

### FR-6 回答解析

系统必须输出结构化 answer，字段与现有前端兼容：

- `text`
- `html`
- `summaryText`
- `productLinks`
- `recommendedAsins`
- `blocks`
- `isSuccess`

### FR-7 上传 payload 构造

系统必须构造两类 payload，本期默认不真正发 HTTP：

1. record collect payload
2. per-question answer update payload

要求：

- 外层结构与现有前端 `collectInterceptRecordsApi + updateRecordAnswerApi` 兼容
- `businessType` 使用新业务类型，例如 `asin_rufus_cli`
- `requestBody` 允许使用 CLI 自己的业务字段，只要求外层 record 结构一致
- 真实上传请求代码需要在实现中存在，但默认以注释状态保留，不参与一期运行

### FR-8 命令输出与 Skill 展示

CLI 命令成功时只输出格式化答案报告保存路径。内部数据结构仍至少包含：

- `asin`
- `country`
- `page_url`
- `seed_record`
- `questions`
- `answers`
- `upload_payload`
- `captured_at`

Skill/Agent 面向最终用户展示时，必须输出报告文件路径；完整报告基于上述全量数据生成，并且不得输出内部 JSON。

---

## 非功能需求

### NFR-1 运行稳定性

- 单题超时可配置
- 某一题失败时应保留失败信息，不影响前面已成功的题
- 最终返回中要区分成功题与失败题

### NFR-2 可审计性

- 输出要包含 seed request 摘要
- 输出要包含题库版本与模板 ID
- 输出要包含运行时间戳

### NFR-3 可扩展性

- 未来接真实上传接口时，不需要重写核心数据模型
- 未来可扩展到 batch 命令

### NFR-4 规范一致性

- Python 代码全中文注释
- Skill 不直接调用业务后端
- 远端数据同步统一收口到 `opscli skills upgrade ops-amazon-rufus`

---

## Skill 需求

### Skill 名称

- `ops-amazon-rufus`

### Skill 类型

- 远端升级型 Skill

### Skill 最小目录

```text
ops-amazon-rufus/
├── SKILL.md
└── data/
    ├── VERSION.json
    └── question_templates.json
```

`question_templates.json` 使用 `default-question-templates` 接口结构，模板与题目列表合并在同一个文件内：

```json
{
  "items": [
    {
      "id": 56,
      "description": "测试",
      "preferred_version_index": 0,
      "questions": [
        {
          "id": 3172,
          "text": "问题1",
          "position": 1
        }
      ],
      "created_at": "2026-04-28T09:25:05",
      "updated_at": "2026-04-28T09:25:12"
    }
  ]
}
```

`runner_config.json`、`marketplaces.json` 与 `questions/<template_id>.json` 不再作为一期 Skill 数据文件；国家站点映射固定在代码中，并按 `US` 等国家名选择。

### Skill 文档要求

`SKILL.md` 必须描述：

- 前置条件：Amazon 登录、Skill 升级、MCP Rufus 工具可用
- 登录前置条件必须明确到国家站点维度：不同国家站点 Amazon 账户登录态可能独立，调用 `amazon_rufus_get` 前必须确认该 `country` 对应站点已登录
- 初始化登录入口：`amazon_rufus_init(country)`，并说明工具会打开对应国家站点登录窗口
- 获取入口：`amazon_rufus_get`；用户同意保存 cookie / browser state 后使用 `amazon_rufus_get_remote`
- 常见错误排查
- 典型 MCP 工作流

---

## 2026-06-03 PRD 增量：Rufus MCP Tool 化与 Skill 去实现细节化

### 背景

本节为最新约束，后续 Spec 和实现以本节为准；旧章节中出现的 `opscli amazon-rufus get` Skill 工作流只保留历史背景，不再作为 Skill 交互入口。

此前 `ops-amazon-rufus` 同时承担两类职责：

1. 作为 Skill 数据包，提供默认题库。
2. 作为 Agent 使用指南，描述 `opscli amazon-rufus get`、`--remote-rufus`、Python/headless 获取等执行流程。

用户本轮明确要求：MCP 应包含之前创建的 Python 获取 Rufus 功能，该功能不应该在 Skill 中以 Python/CLI 实现流程或 `.py` 脚本文件出现。同时 Skill 应保持当用户同意保存 cookie / browser state 时，走 MCP 的方式获取。因此产品边界需要调整为“MCP 执行，Skill 做数据与授权编排规则”。

### 产品目标

1. MCP Server 暴露 Rufus 获取工具，Agent 通过 MCP Tool 调用 Rufus 能力，不再依赖 Skill 文档里的命令流程。
2. `opscli/amazon_rufus` 继续作为 Python 核心实现，MCP Tool 直接复用现有服务层。
3. `ops-amazon-rufus` Skill 保留题库文件说明、升级说明和 Agent 授权编排规则。
4. Rufus 获取 `.py` 文件归属 MCP 工具层，例如 `opscli/mcp/tools/amazon_rufus.py`，不得放入 Skill 目录。
5. 敏感登录态不出现在 Skill、stdout、报告、feedback、telemetry 原始参数中。

### 非目标

本轮不做以下事项：

- 不重写 Rufus 获取核心逻辑。
- 不新增独立 MCP Server。
- 不把 cookie、storage_state 明文作为用户文档中的推荐用法。
- 不把 Skill 改造成执行脚本集合。
- 不在 `ops-amazon-rufus` Skill 下新增 `scripts/get_rufus.py`、`scripts/rufus.py` 等获取脚本。
- 不支持批量 ASIN 的新能力。
- 不新增 UI 页面。

### 用户故事

#### US-1：Agent 通过 MCP 获取单个 ASIN 的 Rufus 回答

作为 Agent，我希望调用 `amazon_rufus_get` 并传入 ASIN、国家和可选问题，从而获得报告路径和结构化摘要，而不是拼装 `opscli amazon-rufus get` 命令。

验收：

- 支持单题 `question`。
- 未传 `question` 时使用本地题库。
- 返回 `success/data/error` 统一结构。
- 成功时写入 `output/amazon-rufus/<ASIN>-YYYYMMDD-HHMMSS.md`。

#### US-2：Agent 初始化 Amazon 登录窗口

作为 Agent，我希望调用 `amazon_rufus_init` 打开对应国家站点登录窗口，提示用户完成登录。

验收：

- 输入 `country`。
- 返回国家、站点 URL、下一步提示。
- 不读取题库，不触发 Rufus 请求。

#### US-3：Agent 在用户明确授权后按 Skill 规则使用 MCP 远程/headless 获取

作为 Agent，我希望 Skill 明确告诉我：当用户同意保存 cookie / browser state 后，应调用 `amazon_rufus_get_remote`，由 MCP 工具捕获并加密保存浏览器状态，再获取 Rufus 答案。

验收：

- 工具参数必须包含显式授权布尔值。
- 未授权时返回稳定错误，不执行捕获。
- 成功后不返回 cookie、localStorage 或 storage_state。
- Skill 不提供 `opscli --remote-rufus` 或 Python headless 示例，只提供 MCP 工具调用规则。

#### US-4：Skill 不再包含 Rufus 获取实现细节

作为维护者，我希望 `ops-amazon-rufus` Skill 说明题库数据、升级方式和授权后调用 MCP 的规则，不再出现 `opscli amazon-rufus get`、`--remote-rufus`、Python headless 调用等实现流程。

验收：

- `opscli/skills/templates/ops-amazon-rufus/SKILL.md` 删除获取流程文案。
- `.agents/skills/ops-amazon-rufus/SKILL.md` 同步删除获取流程文案。
- Skill 描述调整为“Rufus 默认题库数据包与 MCP 编排规则”。
- 用户同意保存 cookie / browser state 时，Skill 指导 Agent 调用 `amazon_rufus_get_remote(..., allow_capture_browser_state=True)`。
- Skill 目录不得包含获取 Rufus 的 `.py` 脚本文件。

### 功能需求

#### FR-1 MCP 工具注册

新增 `opscli/mcp/tools/amazon_rufus.py`，并在 `opscli/mcp/server.py` 中条件注册。
该文件就是 MCP 拥有 Rufus 获取能力的 Python 工具文件。

推荐工具：

| 工具 | 职责 |
|------|------|
| `amazon_rufus_init` | 打开国家站点登录窗口 |
| `amazon_rufus_get` | 本机 Chrome/CDP 获取 Rufus 回答并写报告 |
| `amazon_rufus_get_remote` | 用户授权后捕获 storage state 并走 headless 获取 |
| `amazon_rufus_get_headless` | 可选，供自动化场景传入已准备好的 storage state 或 cookie，不作为默认 Agent 流程 |

#### FR-2 报告输出

MCP 工具成功时返回：

```json
{
  "report_path": "output/amazon-rufus/B0TEST1234-20260603-120000.md",
  "asin": "B0TEST1234",
  "country": "US",
  "question_count": 1,
  "questions": ["这个商品适合送礼吗？"],
  "answer_count": 1
}
```

默认不返回：

- `seed_request`
- `upload_payload`
- headers
- cookie
- localStorage
- storage_state

#### FR-3 登录中断

当服务层抛出 `RUFUS_LOGIN_REQUIRED` 或 `SEED_REQUEST_NOT_CAPTURED`：

- MCP 返回 `success=false`。
- `error.code` 保留原业务错误码。
- `data.next_action` 提示调用 `amazon_rufus_init` 或等待用户登录后重试。
- 不生成 feedback 草案。

#### FR-4 Skill 去实现细节化

Skill 应保留：

- `data/question_templates.json` 说明。
- `data/VERSION.json` 说明。
- `opscli skills upgrade ops-amazon-rufus` 用于同步题库。
- “执行 Rufus 获取请使用 MCP Tool”的简短说明。
- 用户同意保存 cookie / browser state 后调用 `amazon_rufus_get_remote` 的规则。
- 用户不同意保存 cookie / browser state 时，不调用远程捕获工具的规则。

Skill 应移除：

- `opscli amazon-rufus get` 完整流程。
- PowerShell 运行前缀。
- `--remote-rufus` 用户授权流程。
- Python headless 调用方式。
- 手动 Chrome 启动命令。
- 报告格式化执行要求。
- 任何获取 Rufus 的 `.py` 脚本文件，例如 `scripts/get_rufus.py`、`scripts/rufus_headless.py`。

#### FR-5 Skill 目录文件约束

`opscli/skills/templates/ops-amazon-rufus/` 允许包含：

- `SKILL.md`
- `README.md`
- `data/VERSION.json`
- `data/question_templates.json`
- `references/*.md`

不允许包含：

- `scripts/get_rufus.py`
- `scripts/rufus.py`
- `scripts/headless_rufus.py`
- 任何直接获取 Rufus、捕获 cookie、请求 Amazon Rufus 的 Python 脚本。

### 非功能需求

#### NFR-1 安全

- 任何 MCP 返回和报告中不得包含 cookie、localStorage、storage_state。
- 远程/headless 捕获必须要求显式授权参数。
- telemetry 不记录敏感入参。

#### NFR-2 一致性

- 复用 `opscli.mcp.tools.helpers._ok/_err` 响应结构。
- 复用 `RufusManager`，不 shell 调 CLI。
- 代码注释使用中文。

#### NFR-3 可测试性

- MCP 工具函数必须是模块级函数，可被单元测试直接导入。
- 测试不访问真实 Amazon，不启动真实 Chrome。
- 通过 monkeypatch 注入 fake manager。

### 一期验收口径

1. `opscli-mcp` 的工具列表包含 `amazon_rufus_init` 和 `amazon_rufus_get`。
2. `amazon_rufus_get` 调用 `RufusManager.get()` 并生成报告路径。
3. 登录中断返回不带 feedback 草案。
4. 成功返回不包含敏感字段。
5. `ops-amazon-rufus` Skill 文档不再描述 Python/CLI 获取流程，但保留用户同意保存 cookie 后调用 MCP 的规则。
6. `ops-amazon-rufus` Skill 目录不包含获取 Rufus 的 `.py` 脚本文件。
7. `tests/mcp` 新增 Rufus 工具测试并通过。

## 一期验收口径

满足以下验收项即可进入实现：

1. `opscli amazon-rufus --help` 与 `opscli amazon-rufus get --help` 可见。
2. `opscli skills install ops-amazon-rufus` 可安装模板。
3. `opscli skills upgrade ops-amazon-rufus` 能把题库同步到本地。
4. `opscli amazon-rufus get <asin> <country>` 能返回答案与 upload payload。
5. 上传请求代码存在于实现中，但默认注释掉，不会进行真实上传。

## 2026-06-04 变更需求：远程获取缺失 Playwright 浏览器时默认自动修复一次

### 背景

远程 Rufus 获取链路会调用 Playwright 启动 headless Chromium。当前用户看到的错误是：

```text
RUFUS_HEADLESS_CAPTURE_ERROR: 无法启动 headless Chromium
```

本地复现显示底层真实原因是当前 Playwright 版本需要的 `chromium_headless_shell-1217` 未安装。Playwright 官方文档要求每个版本安装对应浏览器二进制。

### 目标

1. 缺失 Playwright 浏览器二进制时，系统默认自动安装当前环境匹配的 Chromium。
2. 自动安装完成后，系统默认重试一次 headless Chromium 启动。
3. 不新增 CLI/MCP 参数，不要求用户显式传入自动修复开关。
4. 自动修复失败时，错误信息给出可执行下一步。
5. MCP 错误码保持 `RUFUS_HEADLESS_CAPTURE_ERROR`，不破坏现有分支处理。
6. 不泄露 cookie、storage state、headers、seed request 或本地敏感状态。

### 非目标

1. 不新增 `auto_install_browser`、`install_browser_if_needed` 等公开参数。
2. 不改远程授权、登录确认、storage_state 保存流程。
3. 不改 Rufus 请求构造、SSE 解析和报告格式。
4. 不把 Playwright 安装逻辑放到 Skill 目录。
5. 不对所有 Chromium 启动失败都自动安装；只处理 Playwright 明确提示浏览器二进制缺失的场景。

### 功能需求

#### FR-HC-1 保留稳定错误码

`playwright.chromium.launch(headless=True)` 失败时，仍返回：

```json
{
  "code": "RUFUS_HEADLESS_CAPTURE_ERROR"
}
```

#### FR-HC-2 缺失浏览器时默认自动安装

当底层异常包含 Playwright 浏览器缺失提示时，系统应默认执行一次安装：

```text
<当前 Python 解释器> -m playwright install chromium
```

实现必须使用当前进程的 `sys.executable`，避免安装到错误 Python 环境。

#### FR-HC-3 安装后只重试一次

自动安装成功后，系统只重试一次 `playwright.chromium.launch(headless=True)`。若仍失败，不得继续循环安装或无限重试。

#### FR-HC-4 自动修复失败时返回可执行错误

自动安装失败或重试仍失败时，message 应包含：

1. 无法启动 headless Chromium。
2. 已尝试自动安装 Playwright Chromium。
3. 建议手动执行 `python -m playwright install chromium` 或当前项目等价命令。

#### FR-HC-5 不返回敏感信息

错误响应不得包含：

- cookie
- localStorage
- `storage_state`
- headers
- seed request
- upload payload

#### FR-HC-6 文档和排障提示对齐

`ops-amazon-rufus` 相关 reference 应把该错误列为环境依赖问题，而不是登录态问题或 CDP 问题。

### 验收标准

1. 缺失 Playwright Chromium 时，系统默认执行一次 `python -m playwright install chromium`。
2. 自动安装后只重试一次 headless Chromium 启动。
3. 不新增 CLI/MCP 参数。
4. 自动修复失败时，错误码仍为 `RUFUS_HEADLESS_CAPTURE_ERROR`，并提示手动安装命令。
5. 单元测试覆盖自动安装成功、安装失败、重试失败三类场景。
6. 现有 MCP 和 Rufus 单元测试继续通过。

## 2026-06-05 变更需求：RUFUS_HEADLESS_CAPTURE_ERROR 时重新打开 Amazon 页面重试

### 背景

Rufus MCP 默认 headless 获取链路会打开 Amazon 商品页并捕获 `/rufus/cl/streaming` seed request。当前页面捕获只有一次尝试，若首轮商品页未触发 Rufus 请求或页面临时导航失败，会直接返回：

```text
RUFUS_HEADLESS_CAPTURE_ERROR
```

用户希望工具内部自动重新打开 Amazon 页面，最多重试 3 次。

### 目标

1. 对 headless 页面打开和 seed request 捕获增加有限重试。
2. 首次失败后最多重试 3 次重新打开 Amazon 商品页。
3. 重试成功后继续原有 Rufus 请求、答案解析和报告写入。
4. 最终失败时错误码仍保持 `RUFUS_HEADLESS_CAPTURE_ERROR`。
5. 不新增 MCP/CLI 参数，不要求 Agent 手动重试工具。
6. 不泄露 cookie、storage_state、headers、seed request 或 upload payload。

### 非目标

1. 不对空 cookie、无效 storage_state、secret 缺失做页面重试。
2. 不把 headless 失败回退到 Chrome CDP 或可见浏览器路径。
3. 不重启 Playwright browser；本轮只重新打开 Amazon 商品页。
4. 不修改 Rufus payload 构造、SSE 解析、题库或报告格式。
5. 不增加可配置重试次数，避免扩大 MCP 工具输入面。

### 功能需求

#### FR-HCR-1 页面捕获失败后自动重开

`HeadlessRufusCaptureService.capture_seed_request()` 在已成功启动 browser 并创建 context 后，如果单次页面捕获失败，应关闭当前 page 并重新创建 page，再次打开同一个 `page_url`。

#### FR-HCR-2 最多重试 3 次

首次尝试不计入重试次数。首次失败后最多额外重试 3 次，总页面打开尝试最多 4 次。

#### FR-HCR-3 保持授权状态复用

重试必须复用同一个 browser context 中已注入的 cookie 或 storage_state，避免重复读写敏感登录态。

#### FR-HCR-4 不放大总捕获预算

`timeout_seconds` 继续表示 headless 捕获总预算。重试应使用剩余预算；如果预算耗尽，应停止重试并返回稳定错误。

#### FR-HCR-5 错误信息可执行且脱敏

最终失败时，message 应说明：

1. 未捕获 `/rufus/cl/streaming` 或 headless 捕获失败。
2. 已重新打开 Amazon 商品页并最多重试 3 次。
3. 下一步仍是确认 cookie/storage_state 是否有效、目标站点是否支持 Rufus 或重新完成授权。

错误中不得包含 cookie、localStorage、storage_state、headers、seed request 原文或 upload payload。

### 验收标准

1. 单元测试模拟前 3 次页面未捕获、最后一次捕获成功，断言返回 seed request。
2. 单元测试模拟 4 次页面均未捕获，断言最终错误码仍为 `RUFUS_HEADLESS_CAPTURE_ERROR`。
3. 单元测试断言最多只额外重试 3 次，不出现无限循环。
4. 单元测试断言 retry 期间不会重复启动 Chromium，不会调用 CDP。
5. 既有 Playwright 浏览器缺失自动安装测试继续通过。
6. 既有 MCP `amazon_rufus_get` 和 `amazon_rufus_get_remote` 测试继续通过。

## 2026-06-05 变更需求：移除 MCP CDP 链路和 amazon_rufus_get_remote

### 背景

Rufus MCP 默认获取已经收敛到 `amazon_rufus_get -> RufusManager.get_backend -> headless capture -> HeadlessRufusClient`。但 MCP 仍暴露 `amazon_rufus_init` 和 `amazon_rufus_get_remote`，并在 `amazon_rufus_get` 中保留 CDP 兼容参数，导致 Agent 仍可能进入 CDP/remote 授权状态捕获流程。

### 目标

1. MCP 工具列表只保留纯后端/headless 获取入口 `amazon_rufus_get`。
2. MCP 不再暴露 `amazon_rufus_init`。
3. MCP 不再暴露 `amazon_rufus_get_remote`。
4. `amazon_rufus_get` 不再暴露 `new_chrome`、`keep_chrome_open`、`chrome_path`、`launch_if_needed`、`cdp_url` 等 CDP 兼容参数。
5. 登录恢复或授权缺失的错误提示不再指向 CDP 或 remote 工具。
6. 成功响应仍只返回 `report_path`、ASIN、国家、问题数量和答案数量。

### 非目标

1. 本轮不删除 `opscli amazon-rufus` CLI 的旧 CDP 兼容实现。
2. 本轮不删除 `BrowserAttachService` 或 `RufusBrowserStateStore` 文件。
3. 本轮不重新设计后端 Rufus secret 获取来源。
4. 本轮不改变题库、报告格式和 headless streaming 请求逻辑。

### 功能需求

#### FR-MCP-CDP-1 工具注册只保留 get

`opscli/mcp/tools/amazon_rufus.py` 的 `_ALL_TOOLS` 应只包含：

```python
amazon_rufus_get
```

MCP 工具列表不应再包含：

```text
amazon_rufus_init
amazon_rufus_get_remote
```

#### FR-MCP-CDP-2 get 参数去 CDP 化

`amazon_rufus_get` 只保留业务必要参数：

```text
asin
country
question
questions
skills_dir
timeout_seconds
```

不再保留 CDP 兼容参数：

```text
new_chrome
keep_chrome_open
chrome_path
launch_if_needed
cdp_url
```

#### FR-MCP-CDP-3 错误恢复文案去 remote/CDP 化

当捕获到 `RUFUS_LOGIN_REQUIRED` 或 `SEED_REQUEST_NOT_CAPTURED` 时，MCP `next_action` 不再提示调用 `amazon_rufus_init`。推荐文案：

```text
当前 Rufus 后端授权状态不可用或已失效，请刷新 Rufus 后端授权状态后重新调用 amazon_rufus_get。
```

#### FR-MCP-CDP-4 答案登录恢复判断保留但重命名语义

短期保留 `_answers_require_login_resume()` 逻辑，避免扩大行为变更。文档必须说明它不是严格登录检测，而是空答案兜底：

1. `answers` 为空。
2. 所有答案都没有 `text`、`html`、`summary_text`、`blocks`。

后续可单独改名为 `_answers_have_no_displayable_content()` 或映射成更准确错误码。

#### FR-MCP-CDP-5 Skill 文档去 remote/CDP 化

`ops-amazon-rufus` Skill 主文档和 references 不再要求 Agent 调用：

```text
amazon_rufus_init
amazon_rufus_get_remote
opscli amazon-rufus init
opscli amazon-rufus get --launch-if-needed
```

默认流程应只描述：

```text
amazon_rufus_get -> report_path
```

### 验收标准

1. MCP 工具列表测试断言只暴露 `amazon_rufus_get`。
2. MCP 测试删除 `amazon_rufus_init` 和 `amazon_rufus_get_remote` 调用分支。
3. `amazon_rufus_get` 参数 schema 不包含 CDP 兼容参数。
4. `RUFUS_LOGIN_REQUIRED` 的 `next_action` 不再出现 `amazon_rufus_init` 或 `amazon_rufus_get_remote`。
5. Skill 文档不再出现 remote/CDP 默认恢复流程。
6. 既有 `amazon_rufus_get` 单题、多题、默认题库和敏感字段过滤测试继续通过。

## 2026-06-05 变更需求：宿主未暴露 Rufus MCP 工具时提供本机兼容入口

### 背景

当前 Skill 前置条件要求 MCP Server 可用，并能看到 `amazon_rufus_*` 工具。该要求适合 MCP 已接入的宿主，但在部分 Codex/Agent 运行环境中，Rufus MCP 工具可能未暴露给当前会话。此时 Skill 不能停在“确认 MCP Server 可用”，也不能把“工具不可见”误判为 Rufus 后端授权缺失。

仓库已有正式 CLI 兼容入口 `opscli amazon-rufus get`，可通过本机 Chrome CDP 获取 Rufus 回答，并支持 `--launch-if-needed` 自动启动调试 Chrome。因此 Skill 需要补充清晰分流：MCP 工具可见时走默认后端/headless；MCP 工具不可见时走 opscli 正式 CLI 的本机 CDP 兼容链路。

### 目标

1. Skill 明确区分“当前宿主未暴露 MCP 工具”和“MCP 工具返回业务错误”。
2. MCP 工具可见时，默认继续调用 `amazon_rufus_get`。
3. MCP 工具不可见时，指导 Agent 使用 `opscli amazon-rufus get` 触发本机 CDP 兼容获取。
4. CLI 兼容路径保留问题来源语义：单题、多题、默认题库。
5. CLI 兼容路径仍不允许在 Skill 目录新增或执行 Rufus 获取脚本。
6. 成功输出继续只展示报告路径。

### 非目标

1. 不新增 MCP 工具。
2. 不修改 `amazon_rufus_get` 的默认 headless 后端语义。
3. 不把 CDP 重新提升为 MCP 默认获取路径。
4. 不在 Skill 目录新增 `scripts/get_rufus.py` 或同类脚本。
5. 不自动安装 Chrome、不修改系统环境变量。

### 功能需求

#### FR-MCP-FB-1 宿主能力检查

Agent 使用 Skill 后，应先判断当前宿主是否可调用以下工具：

```text
amazon_rufus_init
amazon_rufus_get
amazon_rufus_get_remote
```

只要 `amazon_rufus_get` 可见，就优先按 MCP 工作流执行。

#### FR-MCP-FB-2 MCP 工具不可见时使用 CLI 兼容入口

当当前宿主未暴露 `amazon_rufus_*` 工具时，Agent 应改用正式 CLI：

```powershell
opscli amazon-rufus get <ASIN> <COUNTRY> --skills-dir ".agents/skills" --launch-if-needed
```

如果用户提供临时问题，应使用 `-q/--question`：

```powershell
opscli amazon-rufus get <ASIN> <COUNTRY> --skills-dir ".agents/skills" --launch-if-needed -q "问题一" -q "问题二"
```

#### FR-MCP-FB-3 登录初始化

CLI 兼容路径需要登录时，应使用：

```powershell
opscli amazon-rufus init <COUNTRY>
```

用户完成目标国家站点 Amazon 登录后，再按原 ASIN、国家和问题来源重试 `get`。

#### FR-MCP-FB-4 CDP 可恢复错误

如果 CLI 兼容路径返回 CDP 不可用：

1. 未启用 `--launch-if-needed` 时，重试并启用。
2. 自动搜索 Chrome 失败时，询问用户 Chrome 可执行文件路径，再传 `--chrome-path`。
3. 不要求用户手写 Chrome remote debugging 命令，除非自动启动和显式路径都失败。

#### FR-MCP-FB-5 输出与敏感信息

CLI 兼容路径成功时，Agent 只提取并展示报告路径。不得展示：

- cookie
- localStorage
- `storage_state`
- headers
- seed request
- upload payload
- 完整原始 JSON

### 验收标准

1. `SKILL.md` 不再把 MCP 工具可见写成唯一硬前置。
2. `references/rufus-mcp-workflow.md` 包含“MCP 工具不可见时的兼容入口”。
3. 文档明确：MCP 工具不可见走 CLI；MCP 返回授权缺失走远程授权 reference。
4. 文档明确 CLI 兼容入口仍不在 Skill 目录执行 Python 脚本。
5. 模板目录与 `.agents` 已安装目录的 Skill 文档保持一致。

## 2026-06-05 变更需求：RUFUS_HEADLESS_CAPTURE_ERROR 后走 CDP 登录并重试

### 背景

MCP 默认 headless 链路可能返回 `RUFUS_HEADLESS_CAPTURE_ERROR`。该错误不等同于 MCP 工具不可见，也不等同于 Chrome CDP 端点不可用。它通常表示 headless 阶段未能获取商品页 Rufus 上下文，或已保存的 Amazon 浏览器状态不可用。

用户要求在该错误出现时，Skill 应指导 Agent 先走 CDP 登录流程刷新目标国家站点登录态；用户登录完成后，再按原有流程重新走 MCP 或 CDP 获取 Rufus。

### 目标

1. Skill 明确 `RUFUS_HEADLESS_CAPTURE_ERROR` 的恢复路径。
2. 恢复前保留原 ASIN、国家和问题来源。
3. MCP 工具可见时，先调用 `amazon_rufus_init(country=...)` 打开 CDP 登录窗口。
4. 用户确认已登录后，调用 `amazon_rufus_get_remote(..., allow_capture_browser_state=True)` 捕获或刷新浏览器状态，并继续获取 Rufus。
5. MCP 工具不可见或用户已处于 CLI 兼容路径时，使用 `opscli amazon-rufus init <COUNTRY>` 登录，再重新执行原 `opscli amazon-rufus get ...`。
6. 错误和报告不得输出敏感登录态。

### 非目标

1. 不新增 MCP 工具或参数。
2. 不改变 `amazon_rufus_get` 默认 headless 后端入口。
3. 不把 `RUFUS_HEADLESS_CAPTURE_ERROR` 简化为 `CHROME_CDP_UNAVAILABLE`。
4. 不在 Skill 目录新增 Python 获取脚本。
5. 不在用户未确认登录前调用 `amazon_rufus_get_remote`。

### 功能需求

#### FR-HCF-1 MCP headless 捕获失败进入 CDP 登录恢复

当 `amazon_rufus_get` 或 `amazon_rufus_get_remote` 返回 `RUFUS_HEADLESS_CAPTURE_ERROR` 时，Agent 应进入 headless 捕获失败恢复分支，而不是进入 MCP 工具不可见分支。

#### FR-HCF-2 MCP 可见时的恢复步骤

当前宿主可调用 MCP 工具时：

1. 记录原始 `asin`、`country`、`question` 或 `questions`、`skills_dir`。
2. 调用 `amazon_rufus_init(country=...)` 打开目标国家站点 Amazon 登录窗口。
3. 请用户在该窗口完成登录，并等待用户明确回复“已登录”。
4. 用户确认后调用 `amazon_rufus_get_remote(..., allow_capture_browser_state=True)`，按原问题来源获取 Rufus。
5. 成功后只展示 `report_path`。

#### FR-HCF-3 CLI 兼容路径的恢复步骤

当前宿主未暴露 MCP 工具，或原始入口已经是 CLI 兼容路径时：

1. 执行 `opscli amazon-rufus init <COUNTRY>`。
2. 等待用户完成目标国家站点 Amazon 登录。
3. 按原问题来源重新执行 `opscli amazon-rufus get ... --launch-if-needed`。
4. 如果自动 Chrome 搜索失败，再询问 `--chrome-path`。

#### FR-HCF-4 二次失败处理

如果刷新登录态后仍返回 `RUFUS_HEADLESS_CAPTURE_ERROR`：

1. 不继续无限重试。
2. 提示用户可确认目标商品页是否支持 Rufus，或明确要求改走本机 CDP 兼容路径。
3. 不输出 cookie、localStorage、`storage_state`、headers、seed request 或 upload payload。

### 验收标准

1. `references/rufus-mcp-workflow.md` 包含 `RUFUS_HEADLESS_CAPTURE_ERROR` 的独立恢复分支。
2. 恢复分支明确先 `amazon_rufus_init`，用户确认已登录后再 `amazon_rufus_get_remote(..., allow_capture_browser_state=True)`。
3. CLI 兼容路径明确使用 `opscli amazon-rufus init` 后重试原 `get`。
4. 文档仍区分 `RUFUS_SECRET_NOT_READY`、`RUFUS_HEADLESS_CAPTURE_ERROR`、`CHROME_CDP_UNAVAILABLE`。
5. 模板目录与 `.agents` 已安装目录保持一致。

## 2026-06-05 PRD 修正：彻底删除 Rufus CDP 与 remote 链路

### 背景

用户已明确要求彻底删除 CDP，并去掉 `if not answers` 判断。此前 PRD 中关于 CLI CDP 兼容入口、`amazon_rufus_init` 登录窗口、`amazon_rufus_get_remote` 授权刷新、`CHROME_CDP_UNAVAILABLE` 恢复的需求不再作为后续实现依据。

### 目标

1. Rufus MCP 只暴露 `amazon_rufus_get`。
2. Rufus CLI 只保留 `opscli amazon-rufus get` 的后端/headless 获取入口。
3. 删除所有 Rufus CDP 参数、CDP 登录初始化命令和 remote browser state 捕获链路。
4. 空 `answers` 正常生成报告并返回成功结果，不触发登录恢复。
5. Skill 文档不再引导用户处理 CDP、调试端口、Chrome 路径或远程授权。

### 非目标

1. 不保留本机 CDP 兜底路径。
2. 不保留 `amazon_rufus_get_remote` 或等价 remote 工具。
3. 不通过空答案、空正文或空 blocks 推断用户需要登录。
4. 不新增替代登录窗口工具。
5. 不在 Skill 目录保存 cookie、`storage_state` 或临时脚本。

### 功能需求

#### FR-CDP-RM-1 MCP 工具收敛

MCP Rufus 工具列表必须只包含：

```text
amazon_rufus_get
```

不得再注册或导出：

```text
amazon_rufus_init
amazon_rufus_get_remote
```

#### FR-CDP-RM-2 `amazon_rufus_get` 参数收敛

`amazon_rufus_get` 只接受业务参数：

```text
asin
country
question
questions
skills_dir
timeout_seconds
```

不得继续接受或透传：

```text
cdp_url
new_chrome
keep_chrome_open
chrome_path
launch_if_needed
allow_capture_browser_state
```

#### FR-CDP-RM-3 CLI CDP 删除

CLI 删除 `init` 子命令，并从 `get` 删除 CDP/remote 选项。`opscli amazon-rufus get` 应直接调用后端/headless 获取链路。

#### FR-CDP-RM-4 空答案正常返回

当 Rufus 后端返回空 `answers` 时，系统应继续执行报告写入与结果返回。验收重点：

1. 不抛 `RUFUS_LOGIN_REQUIRED`。
2. `answer_count` 为 `0`。
3. `report_path` 存在。
4. MCP 返回仍过滤敏感字段。

#### FR-CDP-RM-5 文档清理

模板 Skill 与 `.agents` 已安装 Skill 中不得再出现 CDP/remote 操作指引。历史变更记录可以保留，但当前流程文档必须以“无 CDP”作为唯一可执行路径。

### 验收标准

1. 工具注册测试确认只暴露 `amazon_rufus_get`。
2. CLI help 测试确认没有 `init`、`--cdp-url`、`--new-chrome`、`--keep-chrome-open`、`--chrome-path`、`--launch-if-needed`、`--remote-rufus`。
3. Manager 测试确认空 `answers` 成功生成报告。
4. Skill 契约测试确认不再引导 `amazon_rufus_init`、`amazon_rufus_get_remote` 或 CDP 兼容入口。
5. 变更同步更新 `docs/change-log-pending.md`。

## 2026-06-05 PRD 修正：三类 MCP 错误统一进入单次 CDP 登录恢复

### 覆盖声明

本节覆盖前文“Skill 文档不得再出现 CDP/remote 操作指引”的结论。新的产品要求是：默认 MCP 获取仍保持后端/headless，但当 MCP 返回指定错误时，Skill 必须统一进入一次 CDP 登录恢复流程。

### 背景

`amazon_rufus_get` 可能返回 `success=false`，并在 `error.code` 中给出稳定错误码。当前三类错误对用户来说都指向同一类可恢复动作：目标国家站点 Amazon 登录态、授权材料或页面上下文不可用。用户希望 Skill 不再把这些错误分散成多个提示，而是先引导一次 CDP 登录，然后按原问题继续获取。

### 目标

1. `amazon_rufus_get` 仍是默认首选入口。
2. 以下 MCP 错误统一进入 CDP 登录恢复：
   - `RUFUS_HEADLESS_REQUEST_ERROR`
   - `RUFUS_HEADLESS_CAPTURE_ERROR`
   - `RUFUS_SECRET_NOT_READY`
3. 每次 Skill 调用最多触发一次 CDP 登录。
4. 登录恢复后保留原 ASIN、国家、单题/多题/默认题库来源。
5. 登录后重试使用 opscli 正式 CLI CDP 入口，不在 Skill 目录新增脚本。
6. 登录后仍失败时，不再重复登录，直接返回可执行错误。
7. 成功输出仍只展示报告路径。

### 非目标

1. 不把 CDP 重新变成 MCP 默认获取路径。
2. 不要求 MCP 重新暴露 `cdp_url`、`chrome_path` 或 `launch_if_needed` 参数。
3. 不新增 `ops-amazon-rufus/scripts/*` 采集脚本。
4. 不持久保存“已登录一次”的普通状态文件。
5. 不在报告、MCP 返回或 feedback 中输出 cookie、localStorage、`storage_state`、headers、seed request 或 upload payload。

### 功能需求

#### FR-LOGIN-RECOVERY-1 统一错误触发条件

当 `amazon_rufus_get` 返回以下结构时，Agent 必须进入登录恢复分支：

```json
{
  "success": false,
  "error": {
    "code": "RUFUS_HEADLESS_REQUEST_ERROR"
  }
}
```

触发错误集合为：

```text
RUFUS_HEADLESS_REQUEST_ERROR
RUFUS_HEADLESS_CAPTURE_ERROR
RUFUS_SECRET_NOT_READY
```

#### FR-LOGIN-RECOVERY-2 单次登录护栏

每次 Skill 调用开始时建立运行态：

```text
login_recovery_attempted = false
```

首次命中触发错误时，将其设置为 `true` 并进入 CDP 登录流程。若后续再次命中触发错误，或用户已经完成一次登录恢复但仍失败，必须停止，不得再次调用 `init`。

#### FR-LOGIN-RECOVERY-3 CDP 登录流程

登录流程使用 opscli 正式入口：

```powershell
opscli amazon-rufus init <COUNTRY>
```

Agent 必须等待用户明确回复“已登录”或等价表达后，才能执行恢复后的获取命令。

#### FR-LOGIN-RECOVERY-4 保留原问题来源重试

登录后根据原始问题来源执行：

默认题库：

```powershell
opscli amazon-rufus get <ASIN> <COUNTRY> --skills-dir ".agents/skills" --launch-if-needed
```

单题：

```powershell
opscli amazon-rufus get <ASIN> <COUNTRY> --skills-dir ".agents/skills" --launch-if-needed -q "<QUESTION>"
```

多题：

```powershell
opscli amazon-rufus get <ASIN> <COUNTRY> --skills-dir ".agents/skills" --launch-if-needed -q "<Q1>" -q "<Q2>"
```

#### FR-LOGIN-RECOVERY-5 二次失败处理

如果登录恢复后的 CLI 获取仍失败，Agent 必须报告：

```text
本次 Skill 调用已触发过一次 CDP 登录恢复，仍未成功；不再重复打开登录窗口。
```

同时保留原始错误码和简短 message，不输出敏感字段。

#### FR-LOGIN-RECOVERY-6 Skill 文档同步

需要同步更新：

1. `opscli/skills/templates/ops-amazon-rufus/SKILL.md`
2. `opscli/skills/templates/ops-amazon-rufus/references/rufus-mcp-workflow.md`
3. `.agents/skills/ops-amazon-rufus/SKILL.md`
4. `.agents/skills/ops-amazon-rufus/references/rufus-mcp-workflow.md`

`SKILL.md` 保持轻量，详细流程写入 reference。

### 验收标准

1. `SKILL.md` 明确列出三类错误会进入一次性 CDP 登录恢复。
2. `references/rufus-mcp-workflow.md` 包含完整错误分流、登录护栏和重试命令。
3. 文档明确每次 Skill 调用最多触发一次登录。
4. 文档明确登录后仍失败不再重复登录。
5. 文档仍禁止在 Skill 目录新增 Rufus 获取脚本。
6. 文档仍禁止输出 cookie、localStorage、`storage_state`、headers、seed request 和 upload payload。
7. 模板目录与 `.agents` 已安装目录保持一致。

## 2026-06-05 PRD 修正：登录态捕获保存后重试 MCP

### 覆盖声明

本节覆盖前文“登录后重新执行 `opscli amazon-rufus get`”的恢复方式。最新目标是：未登录或登录态不可用时，完成登录、捕获 cookie/localStorage、保存到本地加密状态，然后重新调用 MCP `amazon_rufus_get`，由 MCP 内部读取并使用 cookie。

### 用户确认范围

#### 本轮处理

1. 闭环登录态保存：未登录或状态不可用时，引导用户登录后捕获 `storage_state`。
2. 补齐生产入口：新增或明确 `opscli amazon-rufus save-state <COUNTRY>`，调用 `RufusBrowserStateStore.save()`。
3. 统一指引：安装后提示、Skill 文档和 reference 统一使用 `init -> save-state -> amazon_rufus_get`。
4. 让 MCP 获取复用本地状态：`amazon_rufus_get` 不接收明文 cookie 参数，而是在服务层读取本地加密状态并派生 Cookie header。

#### 本轮不处理

1. 默认题库为空继续报错，不新增兜底题库。
2. `answer_count=0` 或空报告不处理。
3. Rufus 题库升级接口环境切换不处理，只记录当前没有读取 `.env` 或 `OPS_URL`。
4. 发布配置中 `ops-amazon-rufus` 未进入公开产物不处理。

### 功能需求

#### FR-STATE-LOOP-1 登录态不可用判定

当 `amazon_rufus_get` 因以下原因失败时，Agent 进入登录态刷新流程：

```text
RUFUS_SECRET_NOT_READY
RUFUS_HEADLESS_CAPTURE_ERROR
RUFUS_HEADLESS_REQUEST_ERROR
```

其中 `RUFUS_SECRET_NOT_READY` 表示本地没有可用授权状态；`RUFUS_HEADLESS_CAPTURE_ERROR` 和 `RUFUS_HEADLESS_REQUEST_ERROR` 可能表示本地 cookie/storage_state 已失效或页面上下文不可用。本轮只触发一次刷新，避免无限循环。

#### FR-STATE-LOOP-2 打开目标国家站点登录

Agent 调用：

```powershell
opscli amazon-rufus init <COUNTRY> --launch-if-needed
```

如果 Chrome 自动发现失败，允许用户补充路径并使用：

```powershell
opscli amazon-rufus init <COUNTRY> --launch-if-needed --chrome-path "<CHROME_PATH>"
```

`init` 只负责打开目标国家站点 Amazon 登录窗口，不保存状态，不请求 Rufus。

#### FR-STATE-LOOP-3 用户确认后保存浏览器状态

用户回复“已登录”后，Agent 调用：

```powershell
opscli amazon-rufus save-state <COUNTRY>
```

该命令连接同一 CDP profile，读取 Playwright `storage_state()`，校验其中包含 `cookies` 与 `origins`，然后加密保存到 `CONFIG_DIR/amazon-rufus/browser-state-<COUNTRY>.bin`。

命令输出不得展示 cookie、localStorage、`storage_state` 原文或 seed request。

#### FR-STATE-LOOP-4 重试 MCP 获取

状态保存成功后，Agent 按原始 ASIN、国家和问题来源重新调用：

```text
amazon_rufus_get(...)
```

MCP 工具内部通过 `RufusBackendSecretProvider.load(country)` 读取本地加密状态，由 `RufusBrowserStateStore.build_cookie_header()` 派生 Cookie header，再传给 headless capture 和 HTTP streaming client。

MCP 调用参数仍只包含 ASIN、国家、临时问题或 `skills_dir`，不新增明文 cookie 参数。

#### FR-STATE-LOOP-5 单次恢复护栏

每次 Skill 调用最多执行一次：

```text
init -> 用户登录 -> save-state -> amazon_rufus_get
```

如果保存状态后 MCP 仍失败，本轮直接返回错误，不再次打开登录窗口。

#### FR-STATE-LOOP-6 CLI 指引统一

安装后指引和 Skill reference 不再推荐 `--new-chrome` 作为默认路径。`--new-chrome` 可保留为调试兼容参数，但用户主路径统一为：

```text
opscli amazon-rufus init <COUNTRY> --launch-if-needed
用户完成登录
opscli amazon-rufus save-state <COUNTRY>
amazon_rufus_get(...)
```

### 验收标准

1. `RufusBrowserStateStore.save()` 有生产调用链，不再只被测试使用。
2. `opscli amazon-rufus save-state <COUNTRY>` 能保存当前国家站点的 Playwright `storage_state`。
3. `amazon_rufus_get` 在本地状态存在时能从服务层派生 Cookie header，并完成 headless capture 与 streaming 请求。
4. MCP 返回和报告不包含 cookie、localStorage、`storage_state`、headers、seed request 或 upload payload。
5. 安装后 next_steps、Skill `SKILL.md`、reference 文档不再把 `--new-chrome` 作为推荐步骤。
6. `opscli amazon-rufus init` 暴露 `--chrome-path`，解决 Chrome 自动发现失败时无法初始化的问题。
7. `QUESTION_BANK_NOT_READY`、空答案报告、题库接口环境切换、发布配置问题不进入本轮验收。

## 2026-06-06 变更需求：Rufus Skill 与 CLI 职责重构

### 背景

当前 Rufus 能力已经具备 MCP 默认后端获取、CLI 登录态初始化、CLI `save-state` 加密保存状态和 CLI 本机 CDP 兼容获取。但历史文档多次在“彻底去 CDP”和“错误后 CDP 登录恢复”之间切换，导致 Skill 与 CLI 的推荐入口容易漂移。

本轮目标是收敛职责边界，而不是扩大功能：让 Agent 和用户清楚知道默认调用什么、什么时候打开登录窗口、什么时候保存本地登录态、什么时候才使用 CLI `get` 兜底。

### 目标

1. `amazon_rufus_get` 继续作为默认 Rufus 获取入口。
2. `ops-amazon-rufus/SKILL.md` 保持轻量，只承载触发范围、前置条件、主流程和 reference 索引。
3. `references/rufus-mcp-workflow.md` 成为 Rufus Skill 执行规则的主 reference。
4. 登录态相关错误统一走一次性恢复：`init -> 用户确认已登录 -> save-state -> amazon_rufus_get`。
5. `opscli amazon-rufus get` 明确定位为“宿主没有 MCP 工具时的本机兼容入口”和“开发排障入口”，不作为普通默认推荐路径。
6. CLI、Skill、README、安装后 next_steps 的推荐命令保持一致。
7. 任何路径都不得向 Agent、报告、feedback 或终端输出 cookie、localStorage、`storage_state`、headers、seed request 或 upload payload 原文。

### 非目标

1. 不在本轮删除 `BrowserAttachService`、`RufusManager.get()` 或 CLI `get`。
2. 不重新暴露 `amazon_rufus_init` 或 `amazon_rufus_get_remote` MCP 工具。
3. 不给 `amazon_rufus_get` 新增明文 cookie、headers、`storage_state` 或 CDP 参数。
4. 不改默认题库接口环境和发布配置。
5. 不新增 Skill 目录下的 Python 获取脚本。
6. 不新增图形界面。

### 功能需求

#### FR-RFC-1 Skill 主文档职责收敛

`opscli/skills/templates/ops-amazon-rufus/SKILL.md` 与 `.agents/skills/ops-amazon-rufus/SKILL.md` 必须保持一致，并只保留：

1. Skill 定位与触发范围。
2. 前置条件。
3. 默认调用 `amazon_rufus_get` 的精简主流程。
4. 三类错误进入一次登录态刷新。
5. 最终只展示 `report_path`。
6. reference 索引与文件边界。

不得在主文档展开 CDP 参数表、完整命令状态机或敏感字段细节。

#### FR-RFC-2 Reference 执行规则唯一化

`references/rufus-mcp-workflow.md` 必须完整表达：

1. 问题来源优先级：`questions` > `question` > 默认题库。
2. 默认 MCP 调用参数。
3. 登录态刷新触发错误：`RUFUS_SECRET_NOT_READY`、`RUFUS_HEADLESS_CAPTURE_ERROR`、`RUFUS_HEADLESS_REQUEST_ERROR`。
4. 单次恢复护栏：每次 Skill 调用最多一次。
5. 恢复命令：`opscli amazon-rufus init <COUNTRY> --launch-if-needed` 与 `opscli amazon-rufus save-state <COUNTRY>`。
6. 保存后重新调用 `amazon_rufus_get`，不把 cookie 传入 MCP 参数。
7. 当前宿主未暴露 MCP 工具时，才使用 `opscli amazon-rufus get ... --launch-if-needed` 兜底。

#### FR-RFC-3 CLI 命令定位

CLI 文案和 help 应形成清晰定位：

1. `init`：打开目标国家站点登录窗口，准备 CDP profile。
2. `save-state`：捕获并加密保存当前国家站点浏览器状态，不执行 Rufus 问答。
3. `get`：本机兼容获取入口，保留 `-q/--question` 多问题能力；普通 Agent 主路径不优先推荐它。

#### FR-RFC-4 安装后指引统一

安装 `ops-amazon-rufus` 后的 `next_steps` 和 README 只推荐主路径：

```text
opscli amazon-rufus init <country> --launch-if-needed
用户完成目标国家站点登录
opscli amazon-rufus save-state <country>
amazon_rufus_get(...)
```

不得把 `--new-chrome` 或 `opscli amazon-rufus get ... --launch-if-needed` 写成默认主路径。

#### FR-RFC-5 CDP profile 后续收敛

如果进入实现阶段，优先评估是否把 CDP profile 目录从用户 home 下的 `.opscli/chrome-profiles` 收敛到 `CONFIG_DIR/amazon-rufus/chrome-profile-<port>`，并补齐 `--remote-debugging-address=127.0.0.1`。

该项属于后续 Spec/tasks 里的实现候选，不在文档确认前编码。

### 验收标准

1. 模板 Skill 与 `.agents` 已安装 Skill 的 `SKILL.md`、README 和 reference 内容一致。
2. `SKILL.md` 不包含完整 CDP 参数表，不把 CLI `get` 写成默认主路径。
3. `rufus-mcp-workflow.md` 包含 `init -> save-state -> amazon_rufus_get` 的完整登录态刷新闭环。
4. 安装后 next_steps 不包含 `--new-chrome`。
5. MCP 工具 schema 仍只暴露 `amazon_rufus_get` 的业务参数。
6. CLI `get` 仍支持多次 `-q/--question`，但文档定位为兼容入口。
7. 相关测试覆盖文档同步、CLI help、next_steps、MCP schema 和敏感字段过滤。

## 2026-06-06 变更需求：手动登录态导入撤出 Skill/MCP 暴露面

### 背景

当前 Rufus 默认获取已经收敛到 `amazon_rufus_get -> RufusManager.get_backend`，MCP 参数面也已经排除了 CDP 与 remote 工具。后续临时验证中曾引入手动登录态导入路径，但用户已明确要求清理相关能力，不能出现在 MCP 或 Skill 中。

### 目标

1. MCP 仍只保留 `amazon_rufus_get`，能力边界是后端/headless 获取 Rufus 并写报告。
2. Skill 只编排用户确认、`watch-login` 登录恢复和 MCP 重试。
3. Skill 模板、已安装 Skill、README、workflow reference 和安装后 next_steps 不出现手动登录态导入流程。
4. CLI、MCP、Skill 都不得在输出、报告、feedback 或测试快照中暴露原始 cookie、headers、payload、完整请求或本地状态。
5. CLI 底层调试能力是否继续存在不影响 Skill/MCP 暴露面；如后续要删除 CLI 子命令，应另立变更并补充回归。

### 非目标

1. 不在 `amazon_rufus_get` MCP 参数中新增 `cookie`、`headers`、`storage_state` 或 CDP 参数。
2. 不新增 MCP `save_cookie`、`read_cookie`、`init` 或 remote 工具。
3. 不把 cookie 写入仓库、`.agents/skills/`、`opscli/skills/templates/` 或 `output/`。
4. 不实现真实后端账号池、远端 cookie 同步、自动续期或多账号轮转。
5. 不要求用户把 cookie 作为命令行参数明文传入。

### 功能需求

#### FR-RUFUS-STATE-1 MCP 获取只读本地状态

`amazon_rufus_get` 不改变调用参数。MCP 仍通过：

```text
RufusBackendSecretProvider.load(country)
  -> RufusBrowserStateStore.load(country)
  -> RufusBrowserStateStore.build_cookie_header(...)
```

读取本地加密状态并进入 headless 获取。

#### FR-RUFUS-STATE-2 Skill 流程收敛

Skill 文档与 installed Skill 只描述编排规则：

1. 默认调用 `amazon_rufus_get`。
2. 若状态缺失或捕获失败，触发一次 `watch-login`。
3. `watch-login` 成功后重新调用 `amazon_rufus_get`。
4. 如果 `amazon_rufus_get` 仍失败，本次 Skill 调用不重复恢复，直接返回结构化错误。

#### FR-RUFUS-STATE-3 敏感信息保护

以下位置必须保持脱敏或不出现 cookie：

1. CLI stdout/stderr。
2. MCP 返回。
3. `output/amazon-rufus/*.md`。
4. `docs/change-log-pending.md`。
5. feedback payload。
6. 单测断言快照。

### 验收标准

1. `amazon_rufus_get` MCP schema 仍只包含业务参数，不包含 cookie、headers、storage_state、CDP 参数或手动状态导入能力。
2. Skill 模板与 `.agents` 已安装 Skill 均不包含要求用户复制 cookie、headers、payload 或浏览器请求的指引。
3. 安装后 next_steps 只包含 `watch-login` 和 `amazon_rufus_get` 主路径。
4. 单元测试覆盖 MCP schema、Skill 文档同步、安装提示和敏感字段过滤。
5. 真实链路测试在代码实现和 Skill 校验完成后执行：先安装 Skill，再用子 agent 提示词 `$ops-amazon-rufus 帮我分析美国站，B0B1MLVMY5 这个商品的信息，要问 1. 这是什么商品 2. 这个商品评价如何？` 完整跑通。

## 2026-06-06 变更需求：CLI 监听登录页并捕获 Rufus streaming seed

### 背景

Cookie mock 可以验证 CLI 状态保存和 provider 读取，但真实 Amazon 页面仍可能显示未登录，导致 headless 商品页不触发 `/rufus/cl/streaming`。需要 CLI 连接可见 CDP Chrome，实时监听用户登录页，在用户完成登录后自动捕获目标 ASIN 商品页的 streaming 请求材料。

### 功能需求

1. 新增 `opscli amazon-rufus watch-login <ASIN> <COUNTRY> --launch-if-needed`。
2. 命令阻塞监听 Amazon 页面，自动检测目标国家站点登录完成。
3. 登录完成后自动打开目标 ASIN 商品页，监听并捕获首个 `/rufus/cl/streaming` request。
4. 捕获后加密保存 Playwright `storage_state` 和 normalized `curl_data`：`url`、脱敏 `headers`、`cookies`、`payload_template`。
5. `amazon_rufus_get` 后端获取时，若本地保存的 seed 与本次 ASIN/国家一致，可直接复用 `curl_data` 请求 Rufus；不一致时继续走 headless 捕获。
6. CLI/MCP/报告/feedback 不输出 cookie、headers、payload template、request body、完整 curl 或 storage_state。

### 验收标准

1. `watch-login --help` 可见并包含 ASIN、country、CDP、timeout、Chrome path 和 launch-if-needed 参数。
2. `watch-login` 成功输出只包含脱敏摘要：国家、ASIN、保存状态、登录检测状态、cookie/origin 数量、streaming request 是否保存。
3. Skill 登录恢复主路径为 `watch-login -> amazon_rufus_get`，不再要求 Agent 等用户回复“已登录”后手动 `save-state`。
4. 单测覆盖状态加密保存 `curl_data`、provider 优先读取、manager 复用同 ASIN seed、CLI 脱敏输出和 fake Playwright request 监听。

## 2026-06-06 变更需求：浏览器复制请求导入撤出 Skill/MCP

浏览器 Network 面板复制请求曾用于验证 Rufus 后端请求复用，但该路径不应出现在 MCP 或 Skill 中。后续默认恢复路径统一为 CLI 监听登录页并捕获 streaming seed，MCP 继续只读取本地加密状态。

### 用户价值

1. 用户不需要复制 cookie、headers、payload 或浏览器请求材料给 Agent。
2. Skill/MCP 暴露面更小，敏感数据只存在于服务层内部加密状态。
3. 登录恢复路径保持可解释：`watch-login` 捕获真实页面请求，`amazon_rufus_get` 读取状态并获取答案。

### 范围

不新增 MCP 保存工具；不改变 `amazon_rufus_get` schema；不在 Skill 模板、已安装 Skill、README、workflow reference 或安装后 next_steps 中出现浏览器请求复制路径。CLI 底层调试入口是否保留，单独由后续 CLI 清理变更决定。

### 验收标准

1. `amazon_rufus_get` MCP schema 不包含 curl、cookie、headers、payload、`storage_state` 或 CDP 参数。
2. Skill 模板、已安装 Skill 和安装后 next_steps 不包含手动导入或浏览器复制请求路径。
3. `RufusBackendSecretProvider` 可以继续读取本地加密 `curl_data`，但该字段不成为 MCP/Skill 输入。
4. 工作区和报告敏感片段扫描无命中。

## 2026-06-06 变更需求：Rufus 默认题库与上传接口配置化

### 背景

默认题库接口曾硬编码到本地开发地址，Rufus 上传接口只返回 disabled hint。为支持本地、测试和生产环境切换，需要把两个 endpoint 纳入 opscli 统一配置模型。

### 功能需求

1. `opscli skills upgrade ops-amazon-rufus` 的默认题库 path 固定为 `/opencalw/default-question-templates`。
2. 默认题库请求按 `OPS_URL + 固定 path` 执行，本地调试只通过覆盖 `ops_url` / `OPSCLI_OPS_URL` 切换 base URL。
3. Rufus 上传 path 固定为 `/v1/rufus/upload`，按 `OPS_URL + 固定 path` 请求。
4. CLI 只有显式传入 `--submit-upload` 时才发送上传请求；未传时只构造内部 payload，不发送。
5. MCP `amazon_rufus_get` 不新增上传参数，不默认上传，不返回 upload payload。

### 验收标准

1. `.env` 和 `~/.config/opscli/config.ini [systems]` 均可覆盖 `OPSCLI_OPS_URL` / `ops_url`，但不能覆盖 Rufus 接口 path。
2. 默认题库请求会附带 ops 认证。
3. Rufus 上传请求会附带 ops 认证和 MCP API Key 透传。
4. 旧的 Rufus endpoint 配置 key 不再生效，避免误配接口 path。
5. 相关 auth、Rufus transport、Rufus manager、CLI、MCP 和 Skill 回归测试通过。

## 2026-06-08 变更需求：报告新鲜度约束

### 背景

同一个 ASIN 可以在 `output/amazon-rufus/` 下存在多份历史 Markdown 报告。用户要求 Skill 不允许返回历史 ASIN 报告，必须使用最新报告。当前 `amazon_rufus_get` 成功响应会返回本次写入的 `report_path`，因此流程必须绑定本次返回路径，避免 Agent 后续按 ASIN 扫目录时误读旧文件。

### 目标

1. 每次 Rufus Skill 调用成功后，只允许把本次工具返回的 `report_path` 作为最终报告路径。
2. 需要读取报告正文时，只读取本次 `report_path`，不读取同 ASIN 历史报告。
3. 登录恢复后重新调用 `amazon_rufus_get` 时，必须用重试成功后的最新 `report_path` 覆盖旧状态。
4. 宿主无 MCP、走 CLI 兼容入口时，优先从本次 CLI 输出中提取报告路径；不能用历史路径替代本次输出。
5. 无法确认最新报告时直接报错，不用旧报告兜底。

### 非目标

1. 不删除 `output/amazon-rufus/` 下已有历史报告。
2. 不改变报告文件名结构。
3. 不把历史报告自动归档或清理。
4. 不要求用户手动选择报告文件。
5. 不把报告正文直接塞进 MCP 成功响应。

### 功能需求

#### FR-REPORT-FRESH-1 绑定本次 MCP report_path

`amazon_rufus_get` 成功后，Agent 必须记录本次响应里的：

```text
data.report_path
```

该路径是本次 Skill 调用唯一有效的报告路径。最终回复和后续正文读取都以该路径为准。

#### FR-REPORT-FRESH-2 禁止按 ASIN 读取任意历史报告

Agent 不得使用以下方式替代本次 `report_path`：

```text
output/amazon-rufus/<ASIN>-*.md
```

尤其不能读取第一个匹配文件、IDE 当前打开文件或上一次对话遗留路径。

#### FR-REPORT-FRESH-3 登录恢复后刷新报告路径

如果首次 `amazon_rufus_get` 失败后触发 `watch-login`，恢复成功后重新调用 `amazon_rufus_get`。最终报告路径必须来自重试成功后的响应，而不是恢复前、历史运行或旧缓存。

#### FR-REPORT-FRESH-4 CLI 兼容入口的最新路径解析

仅当当前宿主没有暴露 `amazon_rufus_get`、必须使用 CLI 兼容入口时，Agent 才能从本次 CLI stdout 解析报告路径。

如果 CLI stdout 没有报告路径，才允许按以下顺序解析最新 ASIN 报告：

1. 文件名中的 `YYYYMMDD-HHMMSS` 时间戳降序。
2. 时间戳相同或缺失时按文件 mtime 降序。
3. 若仍无法唯一确定，返回错误，不读取历史报告。

#### FR-REPORT-FRESH-5 Skill 文档同步

`SKILL.md`、`README.md` 与 `references/rufus-mcp-workflow.md` 必须明确：最终输出只展示本次工具返回的 `report_path`；如需正文，只读取该路径；禁止返回历史 ASIN Markdown 报告。

### 验收标准

1. `references/rufus-mcp-workflow.md` 包含“报告新鲜度约束”。
2. `SKILL.md` 最终输出步骤包含“本次工具返回的 report_path”。
3. `README.md` 常用路径包含“不得返回历史 ASIN 报告”。
4. 文档或测试明确禁止按 ASIN glob 读取任意历史报告。
5. 如实现最新报告解析 helper，单测创建同 ASIN 两个报告，断言只返回时间戳或 mtime 最新文件。

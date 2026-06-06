# ops-amazon-rufus UIUX

## 2026-06-04 体验增量：MCP 默认获取不再打开浏览器

### 体验目标

用户调用 Rufus MCP 获取时，不应看到或感知 Chrome CDP、调试端口、可见浏览器窗口、`launch_if_needed` 或 `chrome_path`。默认体验应是：Agent 调用 `amazon_rufus_get`，MCP 在后端完成 headless 捕获和 Rufus streaming 请求，最终返回报告路径。

### 默认用户路径

推荐 Agent/MCP 使用路径：

```text
amazon_rufus_get(
  asin="B0TEST1234",
  country="US",
  questions=["这个商品适合送礼吗？", "差评主要集中在哪些方面？"]
)
```

成功返回保持简洁：

```json
{
  "report_path": "output/amazon-rufus/B0TEST1234-20260604-120000.md",
  "asin": "B0TEST1234",
  "country": "US",
  "question_count": 2,
  "answer_count": 2,
  "next_action": "已生成 Rufus 报告，请读取 report_path 查看完整答案。"
}
```

### 用户心智

新的默认心智：

1. Rufus 获取由 MCP 后端完成。
2. headless browser 是后端短暂捕获上下文的实现细节。
3. 用户不需要在默认获取时打开浏览器页。
4. 用户不需要知道 CDP、端口、Chrome 路径或 profile。
5. 如果后端 Rufus secret 不可用，系统提示先完成授权/状态初始化。

### 授权/初始化体验

当后端 secret 缺失或失效时，错误应指向“授权状态初始化”，而不是“启动 Chrome CDP”：

```json
{
  "code": "RUFUS_SECRET_NOT_READY",
  "message": "未找到可用 Rufus 后端凭证，请先完成 Rufus 授权状态初始化。"
}
```

如果需要保留 `amazon_rufus_init`，它的体验应定位为辅助动作：

```text
amazon_rufus_init -> 打开登录/授权窗口 -> 保存或刷新后端可用状态
```

它不应被描述为每次获取 Rufus 的前置步骤。

### CDP 文案降级

以下文案不再出现在默认 Skill/MCP 获取流程中：

1. “请启用 `launch_if_needed=True`”。
2. “请提供 Chrome 可执行文件路径”。
3. “请检查 `http://127.0.0.1:9222`”。
4. “请在新窗口中登录后重新调用 `amazon_rufus_get`”。

这些内容只保留在兼容排障文档或授权状态捕获流程中。

### 错误体验

后端/headless 失败应按失败点给下一步：

| 场景 | 用户看到的下一步 |
|------|------------------|
| secret 缺失 | 完成 Rufus 授权状态初始化 |
| secret 过期或 401 | 刷新授权状态 |
| 403/429 | 稍后重试或切换可用账号状态 |
| headless 浏览器缺失 | 系统自动安装一次，失败后提示安装命令 |
| 商品页未捕获 Rufus 上下文 | 检查 ASIN、站点是否支持 Rufus，或刷新 secret |

错误中不得展示 cookie、headers、payload_template、storage_state、seed request 或 upload payload。

### Skill 编排体验

`ops-amazon-rufus` Skill 的默认流程应改为：

1. 读取问题来源：单题、多题或默认题库。
2. 调用 `amazon_rufus_get`。
3. 成功时回复 `report_path`。
4. 若返回 secret/授权缺失，再进入授权初始化流程。
5. 只有用户明确要求本机 CDP 排障时，才读取兼容 CDP reference。

### UI/设计系统

本轮没有图形界面，不新增图标、字体、design token 或组件。体验变更仅限 MCP 工具语义、Skill 默认路径和错误文案。若后续新增授权管理 UI，必须先单独冻结图标库、字体系统、design token、组件生态和页面骨架。

## 2026-06-04 体验增量：SKILL.md 轻量入口与 references 专题阅读

### 体验目标

Agent 打开 `SKILL.md` 时，应先看到“这个 Skill 什么时候用、前置条件是什么、主流程怎么走、细节去哪读”。不应在主文档首屏被 MCP 参数、CDP 排障、远程授权状态机、拒答改写细则淹没。

### 主文档阅读体验

`SKILL.md` 推荐章节：

1. 功能简介。
2. 触发范围。
3. 前置条件。
4. 精简主流程。
5. References 索引。
6. 数据文件。
7. 文件边界。

每个章节应短。主流程只说明“先读偏好、必要时登录、按 reference 调 MCP、最终返回 report_path”，不展开每个 MCP 工具参数。

### References 索引体验

`SKILL.md` 中的 references 索引应直接告诉 Agent 何时读哪个文件：

```text
- references/rufus-mcp-workflow.md：Rufus 获取、MCP 工具调用、问题来源选择。
- references/remote-authorization.md：远程授权偏好、Amazon 登录确认、敏感信息规则。
- references/question-templates.md：默认题库与模板维护。
- references/rufus-report-formatting.md：报告格式、拒答改写和输出隐藏。
```

### Reference 阅读体验

每个 reference 应只解决一个主题：

1. `rufus-mcp-workflow.md` 不写题库维护接口。
2. `remote-authorization.md` 不写报告格式化规则。
3. `question-templates.md` 不写 Rufus 获取流程。
4. `rufus-report-formatting.md` 不写 MCP 调用参数。

这样 Agent 可以按任务只读取必要 reference，降低上下文噪音。

### README 体验

`README.md` 应面向人类维护者，提供目录结构和阅读入口，不复制完整流程。它可以比 `SKILL.md` 更像说明书，但仍不应重复 reference 的长段规则。

### 文案边界

主 `SKILL.md` 可以出现工具名：

- `amazon_rufus_init`
- `amazon_rufus_get`
- `amazon_rufus_get_remote`

但详细参数、错误分支和调用状态机应放入 reference。这样主文档保留导航能力，reference 保留执行精度。

### UI/设计系统

本轮没有图形界面，不新增图标、字体、design token 或组件。体验变更仅限文档信息架构和阅读路径。

## 2026-06-04 体验增量：远程授权偏好一次确认

### 体验目标

用户不应在每次 Rufus 获取时都被重复询问是否使用远程授权；但首次使用远程授权前也不能被系统静默捕获浏览器状态。正确体验是：第一次需要获取 Rufus 时问清楚并保存选择，之后直接按保存值执行。

### 推荐交互

首次没有偏好时，Agent 询问：

```text
需要获取 Rufus 信息。是否使用远程授权方式？
远程获取需要捕获并加密保存当前 Amazon 浏览器状态，用于后续 Rufus 获取。
如果不同意，将继续使用本机登录窗口流程。
```

用户选择：

```text
同意，使用远程授权
不同意，使用本机流程
```

选择后提示：

```text
已保存本次选择，后续获取 Rufus 将直接按该选择执行。如需更改，请明确告诉我重新设置远程授权偏好。
```

如果用户选择远程授权，继续提示：

```text
请在打开的目标国家站点 Amazon 窗口完成登录。登录完成后回复“已登录”，我再调用 MCP 获取 Rufus。
```

### 后续获取体验

保存值为 `true`：

```text
已读取远程授权偏好：使用远程授权。请先确认目标国家站点 Amazon 已登录；登录完成后回复“已登录”，我再调用 amazon_rufus_get_remote 获取 Rufus。
```

保存值为 `false`：

```text
已读取远程授权偏好：使用本机流程。将调用 opscli amazon-rufus get 的 CDP 兼容入口获取 Rufus。
```

这些提示应短，不再重复展示完整授权风险说明。只有用户要求修改偏好时，才重新展示完整授权说明。

### Agent 行为规则

1. 需要获取 Rufus 前，先读取远程授权偏好。
2. 没有偏好时询问用户并保存选择。
3. 有偏好时直接进入对应流程，不重复询问远程授权偏好。
4. 用户同意远程授权时，先调用或引导 `amazon_rufus_init(country=...)` 检测/打开 Amazon 登录窗口，等待用户回复“已登录”。
5. 用户确认已登录后，调用 `amazon_rufus_get_remote(..., allow_capture_browser_state=True)`。
6. 用户不同意远程授权时，调用 `opscli amazon-rufus get ... --launch-if-needed`。
7. 如果用户说“改成远程授权”“以后不用远程授权”等明确意图，覆盖保存偏好。

### 文案边界

可以展示：

- 是否已保存远程授权偏好。
- 当前偏好是远程授权还是本机流程。
- 远程授权路径需要用户登录完成后回复“已登录”。
- 下一步调用哪个 MCP 工具。

不得展示：

- cookie
- localStorage
- `storage_state`
- headers
- seed request
- upload payload
- 偏好文件中的绝对路径，除非用户明确排障。

### 与登录态保存的关系

远程授权偏好不是浏览器登录态。用户选择远程授权后，后续真正捕获并加密保存浏览器状态仍由 `amazon_rufus_get_remote(..., allow_capture_browser_state=True)` 执行。UI 文案不能让用户误以为“保存偏好”已经等于“保存 cookie”。

同样，用户选择远程授权也不等于 Amazon 已登录。必须等用户在目标国家站点完成登录并回复“已登录”后，才进入 MCP 获取流程。

### UI/设计系统

本轮没有图形界面，不新增图标、字体、design token 或组件。体验变更仅限 Agent 询问文案、MCP 工具选择和本地偏好复用规则。

## 2026-06-04 体验增量：CDP 未启动时自动帮助启动 Chrome

### 体验目标

用户不应该因为不知道如何启动 Chrome CDP 而卡在 `CHROME_CDP_UNAVAILABLE`。当 CDP 没有启动时，系统应先自动判断，再尝试搜索本机 Chrome 并启动带 remote debugging 的独立 Chrome profile。只有自动路径失败时，才让用户提供 Chrome 安装路径。

### 推荐用户路径

CLI 用户：

```powershell
opscli amazon-rufus get B0TEST1234 US --launch-if-needed
```

如果用户已知 Chrome 路径：

```powershell
opscli amazon-rufus get B0TEST1234 US `
  --launch-if-needed `
  --chrome-path "C:/Program Files/Google/Chrome/Application/chrome.exe"
```

Agent / MCP 用户：

```text
amazon_rufus_get(
  asin="B0TEST1234",
  country="US",
  launch_if_needed=True
)
```

### 用户心智

规则保持简单：

1. 已有 CDP：直接连接，不新开 Chrome。
2. 没有 CDP：自动找 Chrome 并启动 CDP。
3. 找不到 Chrome：请用户提供 Chrome 路径。
4. 启动后仍要用户登录对应国家站点 Amazon；CDP 启动不等于 Amazon 已登录。

### Skill 编排体验

`ops-amazon-rufus` Skill 应把 CDP 问题当作可恢复前置条件处理：

1. 默认调用 Rufus MCP 获取时，优先使用 `amazon_rufus_get` 后端/headless 链路；用户拒绝保存浏览器状态时，才使用 `opscli amazon-rufus get ... --launch-if-needed`。
2. 如果工具返回 `CHROME_CDP_UNAVAILABLE`，先检查是否已启用自动启动。
3. 若未启用，重试时启用自动启动。
4. 若已启用但仍失败，询问用户 Chrome 安装路径，再传 `chrome_path` 重试。
5. 最后才提示用户手动启动 Chrome CDP。

### 错误文案

CDP 未启动且未启用自动启动：

```text
Chrome CDP 未启动。请启用 --launch-if-needed，系统会自动查找 Chrome 并启动调试窗口。
```

自动搜索失败：

```text
未找到本机 Chrome。请提供 Chrome 可执行文件路径，例如 C:/Program Files/Google/Chrome/Application/chrome.exe。
```

启动后 CDP 仍不可用：

```text
已尝试启动 Chrome 调试窗口，但 CDP 端点仍不可用。请检查端口是否被占用，或改用其他 --cdp-url。
```

文案不应要求用户先理解 `--remote-debugging-port`、profile 目录或 PowerShell 启动语法；这些细节只在排障文档中保留。

### 成功体验

自动启动 Chrome 后，后续体验保持不变：

1. 如果需要登录，打开 Amazon 页面让用户登录。
2. 用户登录完成后继续 `amazon_rufus_get`。
3. 成功时仍只返回报告路径。
4. 不输出 seed request、headers、cookie、localStorage 或 storage_state。

### 体验边界

1. 不在 Skill 目录中放 Python 启动脚本；用户看到的是 MCP/CLI 参数，不是脚本文件。
2. 不自动安装 Chrome。
3. 不复用用户默认 Chrome profile 开启 remote debugging。
4. 不把 CDP 自启动与远程授权混在一起；CDP 只是本机浏览器前置条件，远程授权仍必须单独征得用户同意。

### UI/设计系统

本轮没有图形界面，不新增图标、字体、design token 或组件。体验变更仅限 CLI/MCP 参数、Skill 编排规则和错误文案。

## 2026-06-04 体验增量：`-q/--question` 多临时问题输入

### 体验目标

用户已经有明确问题时，不应被迫跑默认题库。用户有多个明确问题时，也不应重复启动多次 Rufus 获取流程。CLI 应允许用户在同一次命令中多次传入 `-q/--question`，并输出一份按输入顺序排列的多题报告。

### 推荐命令

单题：

```powershell
opscli amazon-rufus get B0TEST1234 US -q "这个商品适合送礼吗？"
```

多题：

```powershell
opscli amazon-rufus get B0TEST1234 US `
  -q "这个商品适合送礼吗？" `
  -q "差评主要集中在哪些方面？" `
  -q "这个商品更适合什么使用场景？"
```

长选项仍可用：

```powershell
opscli amazon-rufus get B0TEST1234 US `
  --question "问题一" `
  --question "问题二"
```

### 用户心智

规则应足够简单：

1. 传了 `-q/--question`：只问这些临时问题，不跑默认题库。
2. 传了多个 `-q/--question`：按输入顺序逐题回答，生成一份报告。
3. 没传问题：使用默认题库。

不引入逗号分隔、换行分隔、JSON 字符串或问题文件，避免用户猜转义规则。

### 报告体验

多题报告沿用现有 section 结构：

```text
## 第 1 题：这个商品适合送礼吗？

### 答案

...

## 第 2 题：差评主要集中在哪些方面？

### 答案

...
```

成功 stdout 仍只输出报告路径，不输出完整 JSON 或内部请求字段。

### 错误体验

任一问题为空时直接失败：

```json
{
  "success": false,
  "command": "amazon-rufus get",
  "data": null,
  "error": {
    "code": "INVALID_RUFUS_QUESTION",
    "message": "--question/-q 不能为空"
  }
}
```

不要自动忽略空白问题。原因是用户可能以为多个问题都已执行，实际报告缺题会造成误判。

### Agent 选择规则

1. 用户给出一个明确 Rufus 问题：调用单题模式。
2. 用户给出多个明确 Rufus 问题：一次性传入多题模式。
3. 用户只给 ASIN 和国家，或说“默认报告”“完整分析”“跑题库”：使用默认题库。
4. 用户同意保存 cookie / browser state 时，MCP 远程工具也应接收同样的问题列表语义。

### UI/设计系统

本轮无图形界面，不新增图标、字体、design token 或组件。体验变更仅限 CLI/MCP 参数和报告结构。

## 2026-06-03 体验增量：未登录时远程获取授权与本机降级

### 体验目标

当系统发现当前 Amazon 未登录时，不应只抛出“请继续告诉我，我会继续执行”的中断信息，而应先给用户一个明确选择：

1. 同意远程获取 Rufus 数据。
2. 拒绝远程获取，继续现有本机流程。

用户只有在看清风险后才会继续。文案必须说明远程获取需要一个干净、未绑定信用卡的 Amazon 账户，并且该账户仅用户本人使用，不会共享给其他用户。若用户拒绝，则继续本机获取流程，并提前告知运行期间可能出现卡顿。

### 交互流程

推荐交互顺序：

1. `amazon-rufus get` 检测当前 Amazon 未登录。
2. CLI 弹出授权确认。
3. 用户选择“同意”或“不同意”。
4. 同意后，系统保持 Amazon 页面打开，等待用户完成登录。
5. 登录完成后，系统捕获 cookie + localStorage 并保存到本地加密状态。
6. 调用 Rufus MCP 工具获取答案。
7. 返回原有答案报告路径。

### 授权文案

建议主文案：

```text
检测到当前 Amazon 未登录。
是否同意使用远程 Rufus 获取方式？
远程获取需要你提供一个干净、未绑定信用卡的 Amazon 账户；该账户仅你本人使用，不会共享给其他用户。
如果不同意，将继续使用本机获取流程，运行期间可能会出现卡顿。
```

推荐按钮/选项：

1. `同意远程获取`
2. `不同意，继续本机获取`

### 同意后的体验

用户选择同意后，界面只保留两件事：

1. 让用户在新窗口完成 Amazon 登录。
2. 登录完成后自动继续，不要求用户再手工复制 cookie 或 localStorage。

建议提示文案：

```text
请在新窗口中完成 Amazon 登录。登录完成后将自动保存当前站点的 cookie 和 localStorage，并调用 Rufus 获取。
```

### 拒绝后的体验

用户选择拒绝后，不再出现与远程获取相关的额外提示。系统直接沿用现有本机流程，并把风险说清楚：

```text
已选择本机获取，将继续使用现有流程。运行期间本机可能会卡顿。
```

### 状态保存体验

保存本地状态是敏感动作，界面上不应展示 cookie、localStorage 明细或文件路径。用户只需要知道：

1. 已登录。
2. 已保存。
3. 已开始获取。

不要在 UI 中出现“复制 cookie”“导出 localStorage”之类的操作入口，也不要展示 JSON 内容。

### 错误体验

如果同意远程获取后，登录态仍然不可用或 MCP 工具失败，错误提示应尽量简短，并指向下一步：

1. 登录态不可用时，提示重新完成登录。
2. MCP 失败时，提示可退回本机流程。
3. 不输出敏感状态详情。

推荐文案：

```text
远程获取失败，请重新完成 Amazon 登录后重试；如需继续，也可以切换回本机获取流程。
```

### 成功输出体验

成功后保持当前体验不变：

1. 仍输出 `Rufus 答案报告已保存：...`
2. 仍将完整报告写入 `output/amazon-rufus`
3. 不输出 cookie、localStorage、seed request 或 upload payload

### 视觉与设计系统

本轮没有新增图形界面，仍是终端交互。若后续要把 consent 做成可视化面板，必须先冻结图标库、字体系统、design token、组件生态和页面骨架，再进入前端实现。本轮只锁定文案、按钮语义和错误反馈，不引入新 UI 组件。

## 2026-06-03 体验增量：Python 端 headless 获取调用方式

### 体验目标

业务代码应能在不打开可见 Chrome 的情况下获取 Rufus 数据；但用户仍能继续使用当前 `amazon-rufus init/get` 的可见浏览器登录流程。两种路径的输出语义保持一致，避免调用者理解两套报告结构。

### Python 调用体验

首选调用方式是 SDK 风格方法：

```python
from opscli.amazon_rufus.services.manager import RufusManager

data = RufusManager().get_headless(
    asin="B0TEST1234",
    country="US",
    question="这个商品适合送礼吗？",
    streaming_url=streaming_url,
    headers=headers,
    cookie=amazon_cookie,
    payload_template=payload_template,
)
```

调用者只需要关心四类输入：

1. 商品与站点：`asin`、`country`
2. 问题来源：`question` 或默认题库
3. Rufus 请求来源：`streaming_url`、`headers`、`cookie`、`payload_template`
4. 超时控制：`timeout_seconds`

其中 `cookie` 是必传项。它不是普通配置项，而是本次 headless 获取 Rufus 数据的 Amazon 登录态来源：系统先用它打开商品页并捕获 `rufus/cl/streaming` 上下文，再用同一份 `cookie` 请求 Rufus 答案。

### CLI 体验边界

当前阶段不建议新增 `--cookie` 这类命令行参数，因为终端历史和进程列表容易泄漏敏感信息。若后续需要 CLI headless 模式，推荐形态是：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run --extra amazon opscli amazon-rufus get B0TEST1234 US --question "这个商品适合送礼吗？" --headless --curl-file ".secrets/rufus-curl.txt"
```

该 CLI 形态必须在 Spec 阶段再确认；本轮只锁定 Python 调用方法。

### 成功输出体验

`get_headless()` 返回结构应与现有 `get()` 一致，因此调用方可以继续写报告：

```python
from opscli.amazon_rufus.services.answer_report_formatter import AnswerReportFormatter

report_text = AnswerReportFormatter().format_data(data)
```

用户看到的报告仍是问题与答案，不展示 cookie、headers、seed request 原文或完整 payload。

### 失败体验

常见失败应给出可执行原因：

1. Cookie 为空：提示调用方先提供 Amazon 登录 cookie。
2. 未捕获 `rufus/cl/streaming`：提示 cookie 可能失效、站点不支持 Rufus 或商品页未触发 Rufus。
3. Rufus 返回 401/403：提示登录态过期。
4. Rufus 返回 429：提示账号被限流，应稍后重试或切换账号。

所有错误都不得回显敏感 header/cookie。

## 2026-05-14 体验增量：拒答后自动改写问题

### 体验目标

用户不应该只得到“Rufus 拒绝回答”的终态结果。系统应先识别拒答，再把原问题改写成更中性、仍保留原语义、且不超过 180 字的问题，并最多自动重试 3 次。

本轮新增体验约束：拒答后自动生成的重试问题必须是中文。即使用户原问题是英文或中英混合，报告中展示的改写后问题也应为中文。

### 用户可感知行为

用户仍执行原命令：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run --extra amazon opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" --new-chrome --question "这个商品适合送礼吗？"
```

若第一次答案拒答，报告中展示：

```text
## 第 1 题：这个商品适合送礼吗？

已检测到首次回答拒答，已在保持原语义的前提下改写问题并重试。
改写后问题：基于商品页面和公开评价，分析该商品是否适合送礼，并说明理由

### 答案

Rufus 最终回答文本。
```

用户不需要手工复制拒答内容再改问法。

### 改写文案体验

改写问题应满足：

1. 不超过 180 字。
2. 保留原问题的核心对象与分析维度。
3. 使用中文表达。
4. 使用中性、可回答的表达。
5. 不新增用户没有要求的维度。

例如：

```text
原问题：这个商品是不是很垃圾，差评是不是说明不能买？
改写后：基于商品页面和公开评价，分析该商品的主要差评风险、购买顾虑和适用场景，并给出客观判断
```

英文原问题也必须转成中文重试问题：

```text
原问题：Is this product safe for kids and worth buying?
改写后：基于商品页面和公开评价，分析该商品是否适合儿童使用、主要风险点和购买价值
```

### 失败体验

如果 3 次改写重试后仍然拒答，报告应明确说明已经达到重试上限：

```text
已检测到首次回答拒答，已改写问题并重试 3 次；重试后仍未获得有效回答。
```

该状态不应继续自动改写第 4 次，避免用户等待不可控的多轮尝试。

### 与空白问题的关系

空白 `--question` 仍是输入错误，应直接返回 `INVALID_RUFUS_QUESTION`。拒答处理发生在 Rufus 已经返回答案之后，用户体验上属于“回答质量补救”，不是“参数校验”。

### Agent 回复规范

Agent 回复用户时只给报告路径和必要摘要。发生拒答改写时，可以说明“已自动改写并重试”，但不要输出 seed request、headers、cookie 或完整 JSON。

## 2026-05-14 体验增量：题库模式与单题模式并存

### 体验目标

用户获取 Rufus 答案时，应能根据意图选择合适路径：

1. 想看默认分析：不传问题，使用题库模式。
2. 已有明确问题：传入 `--question`，只获取该问题答案。

这能减少不必要的题库执行时间，也避免 Agent 在用户已经问得很具体时输出一整份默认报告。

### 推荐命令

单题模式：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run --extra amazon opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" --new-chrome --question "这个商品适合送礼吗？"
```

题库模式：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; $env:SKIP_CYTHON = "1"; uv run --extra amazon opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" --new-chrome
```

### Agent 选择规则

Skill 执行时按以下规则判断：

1. 用户消息中包含明确的 Rufus 问题，例如“这个商品适合送礼吗”“差评风险是什么”，优先使用 `--question`。
2. 用户只提供 ASIN 和国家，或要求“默认报告”“完整分析”“跑题库”，使用题库模式。
3. 用户要求多个问题时，本轮不走多个 `--question`；先提示当前 CLI 单题模式一次只支持一个问题，或按题库模式执行。
4. 单题模式仍需要对应国家站点 Amazon 登录；未登录时仍引导执行 `opscli amazon-rufus init <country>`。

### 成功输出体验

两种模式成功时都只输出报告路径：

```text
Rufus 答案报告已保存：output/amazon-rufus/B0TEST1234-20260514-153000.md
```

单题报告标题直接使用用户传入的问题：

```text
## 第 1 题：这个商品适合送礼吗？

### 答案

Rufus 回答文本。
```

题库报告继续按模板顺序输出多个问题 section。

### 失败体验

显式传入空问题时，不回退到题库模式，而是返回明确错误：

```json
{
  "success": false,
  "command": "amazon-rufus get",
  "data": null,
  "error": {
    "code": "INVALID_RUFUS_QUESTION",
    "message": "--question 不能为空"
  }
}
```

这样可以避免用户以为 CLI 回答了指定问题，实际却跑了默认题库。

### UI/图标/设计系统锁定

本轮没有图形 UI 实现，不涉及图标库、字体系统、design token 或组件生态变更。CLI 文案必须继续保持简洁、明确、可执行。

## 2026-05-14 体验增量：问题模板 reference 独立化

### 体验目标

用户阅读 `ops-amazon-rufus` 文档时，应能清晰区分两类任务：

1. 获取 Rufus 回答：登录 Amazon、同步题库、执行 `amazon-rufus get`、查看报告。
2. 管理问题模板：查看默认题库、创建模板、保存问题、修改或删除模板。

本轮将第二类任务独立到 `references/question-templates.md`，避免用户在执行回答获取时被管理端接口干扰。

### 阅读路径

推荐文档入口：

```text
README.md / SKILL.md
  -> 常用命令与 Rufus 获取流程
  -> references/question-templates.md
     -> 问题模板获取与保存接口
  -> references/rufus-report-formatting.md
     -> 报告格式化规范
```

### 新 reference 体验规范

`references/question-templates.md` 应采用资源文档风格：

1. 先说明适用范围：只处理问题模板，不处理 Rufus 回答。
2. 再给出数据模型：模板、问题、本地题库文件。
3. 再给出接口表：获取、创建、保存、追加、更新、删除。
4. 最后给保存工作流：新增模板、追加问题、整体覆盖、修改单题。

文档不应使用“获取回答”“登录 Amazon”“seed request”“报告”等章节标题。

### 保存接口的用户心智

用户只需要理解两种保存方式：

1. 新增模板：先创建描述，再追加问题。
2. 保存问题：可以整体覆盖，也可以追加或单题修改。

推荐文案：

```text
新增模板只创建模板描述；问题内容通过 questions 接口单独保存。
```

该文案能避免用户误以为 `POST /question-templates` 同时保存问题列表。

### CLI / Skill 主流程不变

普通 Rufus 获取用户仍按以下路径使用：

```powershell
opscli skills upgrade ops-amazon-rufus --skills-dir ".agents/skills"
opscli amazon-rufus init US
opscli amazon-rufus get B0B1MLVMY5 US --skills-dir ".agents/skills" --new-chrome
```

主流程文档中只保留“题库接口详见 reference”的跳转，不展示管理端保存接口。

### UI/图标/设计系统锁定

本轮没有图形 UI 实现，不涉及图标库、字体系统、design token 或组件生态变更。若后续要在 CLI 外新增问题模板管理页面，必须重新更新本文件并冻结对应 UI 方案后再编码。

## 2026-05-07 体验增量：登录前置提示与 init 指引

### 体验目标

用户安装 `ops-amazon-rufus` 后，应立即知道该 Skill 不是纯离线题库工具，而是依赖对应国家站点的 Amazon 浏览器登录态。用户在未登录时执行 `get`，也必须直接看到下一步命令，而不是只看到“未捕获请求”。

### 安装成功体验

命令：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; uv run --extra amazon opscli skills install ops-amazon-rufus --skills-dir ".agents/skills" --pretty
```

成功输出仍是 JSON，推荐形态：

```json
{
  "success": true,
  "command": "skills install",
  "data": {
    "name": "ops-amazon-rufus",
    "version": "v0.0.0",
    "installed_paths": [
      {
        "tool": "custom",
        "path": ".agents/skills/ops-amazon-rufus",
        "replaced": false
      }
    ],
    "requires_amazon_login": true,
    "next_steps": [
      "使用前必须先登录对应国家站点的 Amazon 账户。",
      "请先执行 opscli amazon-rufus init <country>，在新窗口完成登录。",
      "登录后再执行 opscli amazon-rufus get <asin> <country> --new-chrome。"
    ]
  },
  "error": null
}
```

体验约束：

1. 非交互安装不输出 JSON 之外的散文本。
2. 文案必须包含明确命令 `opscli amazon-rufus init <country>`。
3. 文案不展示 Chrome profile、CDP URL 或 cookie 细节。
4. 其他 Skill 的安装输出不出现 Amazon 登录提示。

### 未捕获 streaming 的失败体验

用户未登录、登录到错误国家站点、目标站点不支持 Rufus，或页面没有触发 Rufus 请求时，`get` 可能无法捕获 `/rufus/cl/streaming`。

错误输出仍是稳定 JSON：

```json
{
  "success": false,
  "command": "amazon-rufus get",
  "data": null,
  "error": {
    "code": "SEED_REQUEST_NOT_CAPTURED",
    "message": "未捕获 /rufus/cl/streaming。请先执行 opscli amazon-rufus init US，并在新窗口登录 Amazon 后重试；同时确认目标站点支持 Rufus: https://www.amazon.com/dp/B0TEST1234"
  }
}
```

### 文案规范

错误文案必须按以下顺序组织：

1. 先说明失败点：未捕获 `/rufus/cl/streaming`。
2. 再给下一步：执行 `opscli amazon-rufus init <country>`。
3. 再说明动作：在新窗口登录 Amazon 后重试。
4. 最后保留排障上下文：目标站点可能不支持 Rufus，以及当前商品页 URL。

推荐文案：

```text
未捕获 /rufus/cl/streaming。请先执行 opscli amazon-rufus init US，并在新窗口登录 Amazon 后重试；同时确认目标站点支持 Rufus: https://www.amazon.com/dp/B0TEST1234
```

不推荐文案：

```text
未捕获请求，请确认环境后重试
```

原因：没有说明下一步命令，用户仍需猜测应该启动哪个登录流程。

### 与既有 init 体验的关系

`init` 成功文案仍保持：

```text
请在新窗口中登录亚马逊
```

本轮不是替换 `init`，而是让安装后和失败后都指向它。这样用户路径变成：

1. 安装 Skill 后看到需要登录。
2. 执行 `opscli amazon-rufus init US`。
3. 在新窗口完成 Amazon 登录。
4. 执行 `opscli amazon-rufus get <asin> US --new-chrome`。
5. 成功时只看到报告保存路径。

### 体验边界

1. 不在错误中输出 headers、cookie、seed request 或 upload payload。
2. 不要求用户理解 CDP 和 Chrome profile。
3. 不将 Amazon 登录态抽象为 `opscli auth login`，避免与 opscli 内部认证体系混淆。
4. 不承诺 `init` 后一定能捕获 Rufus；目标站点是否支持 Rufus仍由 Amazon 页面决定。

## 2026-04-30 体验增量：参考前端渲染的格式化答案输出

### 体验目标

`amazon-rufus get` 的成功输出应参考前端 `asinRufusView` 的卡片信息层级，而不是把 Rufus 流式还原后的松散文本原样抛给终端。用户看到的内容应满足：

1. 段落之间最多一个空行。
2. 每个问题是一段独立 section。
3. 相关产品、答案正文、推荐 ASIN、总结按前端顺序展示。
4. 正文优先使用结构化 blocks，支持 heading、list、table。
5. 默认将完整报告写入 `output/amazon-rufus`，避免终端或 Agent 输出窗口截断正文。

### 默认终端体验

命令：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; uv run --extra amazon opscli amazon-rufus get B0B1MLVMY5 US --skills-dir ".agents/skills" --new-chrome
```

stdout 只输出保存路径：

```text
Rufus 答案报告已保存：output/amazon-rufus/B0B1MLVMY5-20260430-101530.md
```

文件内容为参考前端卡片结构的纯文本报告：

```text
## 第 1 题：分析该商品的优势与缺陷

### 答案

#### Aiheal 的劣势与问题（致命缺陷）

- 保温功能残缺：96°C以上无法保温
- 可靠性风险：部分用户反馈突然停止工作、Hold功能失效、按钮故障

| 问题 | 影响 | 严重程度 |
| --- | --- | --- |
| 96°C以上无法保温 | 205°F咖啡按 HOLD 键无反应 | 致命 |

### 推荐 ASIN

- B0ABC12345 - 竞品电热水壶 (AsinFaceoutList)

### 总结

Rufus 总结文本。
```

说明：formatter 只在 `answer.blocks` 或标准 Markdown 表格中输出表格；对于 `output/1.txt` 这种已退化的一列文本，不强行猜测列结构，避免误改 Rufus 原文。

### 文案边界

1. 默认不输出“格式化规则说明”，避免干扰用户阅读答案。
2. 默认不输出内部 JSON。
3. 默认只提示保存路径，不把完整答案报告刷到 stdout。
4. 错误仍使用稳定 JSON 结构，便于脚本排障。

## 2026-04-29 体验增量：init 登录初始化

### 体验目标

`init` 是用户首次使用 Rufus 采集前的准备命令。它应把“打开正确国家站点”和“使用正确 Chrome profile 登录”这两件事合并成一个明确动作，降低后续 `get` 因未登录导致失败的概率。

### 推荐使用路径

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; uv run --extra amazon opscli amazon-rufus init US
```

命令执行后：

```text
请在新窗口中登录亚马逊
```

用户完成登录后，再执行：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; uv run --extra amazon opscli amazon-rufus get B0B1MLVMY5 US --skills-dir ".agents/skills" --new-chrome
```

### 文案规范

成功文案必须短、明确、可执行：

```text
请在新窗口中登录亚马逊
```

不输出浏览器调试参数、profile 路径或内部 CDP 细节，除非发生错误。

### 失败体验

1. 国家不支持：提示支持的国家列表。
2. Chrome 启动失败：复用现有 Chrome 启动失败排障文案。
3. CDP 不可用：提示检查 `http://127.0.0.1:9222` 或重新执行命令。

### 体验边界

`init` 不展示题库信息、不输出 JSON 成功结构、不引导用户输入 ASIN。用户只需要关注一件事：在新开的 Amazon 窗口中完成登录。

## 2026-04-29 体验增量：UTF-8 与答案报告输出

### 体验目标

用户通过 Skill 获取 Rufus 结果时，不需要阅读完整 JSON。CLI 应在 UTF-8 环境运行，并仅把格式化答案报告作为最终答案输出。

### 终端运行体验

推荐 PowerShell 命令：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; uv run --extra amazon opscli amazon-rufus get B0B1MLVMY5 US --skills-dir ".agents/skills" --new-chrome
```

该写法只影响当前命令进程，符合最小侵入原则，不要求用户修改系统环境变量。

### 最终回复体验

最终回复只输出答案报告：

```text
## 第 1 题：问题文本

### 答案

Rufus 回答文本。
```

不应展示：

1. 完整 JSON。
2. `seed_request`。
3. `upload_payload`。
4. request headers、cookie 或调试字段。

### 与内部全量数据的关系

CLI 的全量数据仍是内部机器协议，用于稳定生成格式化答案报告。Skill 使用者和 Agent 不应把内部数据直接作为最终结果回复给用户，除非用户明确要求查看原始结果或排障。

## 2026-04-29 体验增量：参数对齐不改变用户心智

### 体验目标

本轮是底层请求复刻，不应让用户学习新命令。用户仍只需要执行：

```bash
opscli amazon-rufus get B0TEST1234 US
```

### 用户可感知收益

1. Rufus 回答更贴近扩展端结果。
2. 商品详情页上下文更稳定，减少回答偏离目标 ASIN 的概率。
3. 跨站点请求参数更一致，减少因缺少 `programId/ref` 导致的不确定行为。
4. CLI 机器输出结构保持不变，脚本调用方无需适配。

### 文案与输出约束

1. 不新增“复刻模式”文案，避免暴露内部实现细节。
2. 若后续新增 debug 输出，只能在调试字段展示 `replay_url` 与 `payload_fields` 摘要，不输出完整 cookie 或敏感 header。
3. Skill 最终回复只展示格式化答案报告，seed/request 细节仅保留在内部数据中用于排障。

### CLI 使用体验不变项

1. 命令入口不变：`opscli amazon-rufus get <asin> <country>`。
2. Chrome 前置条件不变：复用已登录 Amazon 的本地调试 Chrome。
3. 题库来源不变：`ops-amazon-rufus/data/question_templates.json`。
4. 内部数据字段不变：`asin`、`country`、`page_url`、`answers`、`seed_request`、`upload_payload`。

### UI/图标/设计系统锁定

本需求无图形 UI 实现。若后续需要图形页面，必须先在本文件追加并冻结以下内容后才能编码：

1. 图标库：Lucide、Heroicons 或 Tabler 之一。
2. 字体系统：明确字体族、字号阶梯与行高。
3. design token system：颜色、间距、圆角、阴影。
4. 组件生态：现有前端组件库或明确替代方案。
5. 页面骨架：信息架构与状态流。

## 文档目标

本需求没有新增图形页面，本文件定义的是：

- CLI 交互体验
- Skill 使用体验
- 答案文本的可读性
- 错误提示与排障路径

目标是让使用者在终端里完成一次稳定、可理解、可复用的 Rufus 获取流程。

---

## 体验原则

### 1. 一条命令完成主流程

核心命令必须保持短路径：

```bash
opscli amazon-rufus get <asin> <country>
```

使用者不需要理解内部的：

- CDP attach
- seed request
- history thread context
- SSE 解析

这些都应该被收敛在命令内部。

### 2. 前置条件要显式

因为本命令依赖本地已登录 Chrome，会有比普通 CLI 更强的环境要求。

因此 `SKILL.md` 和错误信息都必须显式强调：

1. Chrome 需开启 remote debugging
2. 用户需先登录目标国家站点的 Amazon 账户
3. 不同国家站点登录态可能独立，切换国家时需重新确认登录状态
4. 需先安装并升级 `ops-amazon-rufus`
5. 推荐通过 `opscli amazon-rufus init <country>` 打开登录窗口

### 3. 输出先给答案，再留上下文

Skill 最终回复的阅读顺序应为：

1. 第一题答案文本
2. 第二题答案文本
3. 后续题目答案文本

低层 request 细节只留在内部数据中，默认不展示给最终用户。

---

## CLI 交互规范

### 命令风格

沿用当前项目风格：

- CLI 成功时输出格式化答案报告保存路径，Skill 最终也只展示该路径
- 成功时不输出内部 JSON，错误时返回稳定结构
- 错误返回稳定结构

### 推荐帮助文案

```text
opscli amazon-rufus get <asin> <country>
  连接本地已登录 Chrome，复用 Rufus 请求上下文，按题库获取指定 ASIN 的回答
```

### 推荐参数设计

```text
opscli amazon-rufus get B0ABC12345 US
opscli amazon-rufus get B0ABC12345 DE --cdp-url http://127.0.0.1:9222
opscli amazon-rufus get B0ABC12345 US --new-chrome
opscli amazon-rufus get B0ABC12345 JP --launch-if-needed --chrome-path "C:/Program Files/Google/Chrome/Application/chrome.exe"
```

`--new-chrome` 面向最常见人工使用场景：命令先新开一个 Chrome 调试窗口，再连接该窗口。默认启动命令为：

```powershell
Start-Process chrome.exe -ArgumentList '--remote-debugging-port=9222 --user-data-dir="E:\chrome-profiles\opscli-rufus" --no-first-run --no-default-browser-check'
```

---

## 成功输出体验

### 格式化报告输出

CLI 默认输出适合人工和 Agent 阅读的格式化报告：

```text
## 第 1 题：问题文本

### 答案

Rufus 回答文本。
```

### Skill 最终输出

Agent 直接复用 CLI stdout 中的格式化报告：

```text
## 第 1 题：问题文本

### 答案

Rufus 回答文本。
```

不得直接展示 `seed_request`、`upload_payload` 或完整 JSON。

### 答案项体验

内部数据中每题至少保留：

- `template_id`
- `question`
- `is_success`
- `answer.text`

详细字段：

- `summaryText`
- `recommendedAsins`
- `productLinks`
- `blocks`

---

## 失败体验

### 错误提示原则

错误提示必须告诉用户：

1. 失败点在哪
2. 可能原因是什么
3. 下一步该做什么

### 关键错误文案

#### 场景 1：CDP 不可用

```text
未连接到 Chrome DevTools：请使用 --new-chrome 自动新开调试窗口，或手动以 remote debugging 模式启动 Chrome 后通过 --cdp-url 指定可用地址
```

#### 场景 2：未捕获 seed request

```text
未采集到 /rufus/cl/streaming 请求。请确认当前 Chrome 已登录 Amazon、目标站点支持 Rufus，并刷新商品页后重试
```

#### 场景 3：题库缺失

```text
本地未找到 ops-amazon-rufus 题库数据，请先执行 opscli skills install ops-amazon-rufus 和 opscli skills upgrade ops-amazon-rufus
```

#### 场景 4：单题超时

```text
第 3 题请求超时（90 秒）。已保留前面题目的结果
```

---

## Skill 使用体验

### Skill 名称

- `ops-amazon-rufus`

### Skill 文档体验目标

`SKILL.md` 要做到：

- 一打开就知道这个 Skill 是干什么的
- 明确依赖 `amazon_rufus_get` MCP Tool
- 明确说明国家站点登录前置条件
- 明确说明 `amazon_rufus_init(country)` 是登录初始化工具
- 给出 MCP 调用工作流
- 给出常见错误排查

### Skill 文档的推荐章节

1. 功能简介
2. 前置要求
3. MCP 工具
4. 典型工作流
5. 常见错误排查
6. 本地数据与升级说明

### Skill 文档的典型工作流

```text
1. 确认 ops-amazon-rufus Skill 已安装并完成题库升级。
2. 如未登录对应国家站点，调用 amazon_rufus_init(country="US")。
3. 用户完成 Amazon 登录后，调用 amazon_rufus_get(asin="B0ABC12345", country="US")。
4. 如果用户同意保存 cookie / browser state，调用 amazon_rufus_get_remote(..., allow_capture_browser_state=True)。
5. 最终回复只展示 MCP 返回的 report_path。
```

---

## 数据输出体验

### 上传 payload 的解析策略

因为本期不真正上传，`upload_payload` 只作为 CLI 内部字段，不作为 Skill 最终回复内容。

建议：

- CLI 默认可继续包含 `upload_payload`
- Agent 最终回复必须隐藏 `upload_payload`
- 用户明确要求排障时，才可提示其查看原始 JSON
- 若后续查看源码，应能看到注释态的上传调用代码，便于对照未来接入点

## 视觉与文案风格

虽然这是 CLI 需求，仍需遵循现有项目的输出风格：

- 文案简洁、明确、可执行
- 不使用情绪化措辞
- 不输出宿主内部概念
- 不把 Chrome MCP 当成正式依赖写进主流程

---

## 2026-06-03 UIUX 增量：MCP Tool 交互体验与 Skill 编排体验

### 体验定位

本节为最新约束，后续 Spec 和实现以本节为准；旧章节中出现的 CLI 命令示例只保留历史背景，不再作为 Skill 交互入口。

本轮没有前端页面，UIUX 的核心是“工具调用体验”：

- MCP 客户端看到的工具名必须直接表达业务动作。
- 工具描述必须让 Agent 知道什么时候需要用户授权。
- 返回值必须可读、可继续，不暴露内部调试字段。
- Skill 文档不再把用户带回终端命令流程，但保留用户授权和 MCP 调用决策。
- Agent 在 Skill 目录中不应看到或调用获取 Rufus 的 `.py` 脚本文件。

### MCP 工具命名

推荐命名：

| 工具名 | 体验意图 |
|--------|----------|
| `amazon_rufus_init` | 打开登录窗口，动作轻量且可恢复 |
| `amazon_rufus_get` | 获取 Rufus 回答，默认入口 |
| `amazon_rufus_get_remote` | 用户明确同意后捕获浏览器状态并远程/headless 获取 |

不推荐：

| 命名 | 问题 |
|------|------|
| `rufus_get` | 缺少 Amazon 领域前缀 |
| `ops_amazon_rufus_get` | 过长，重复项目名前缀 |
| `amazon_rufus_cli_get` | 暗示仍通过 CLI 执行 |
| `amazon_rufus_python_get` | 把实现细节暴露为用户心智 |

### 参数体验

`amazon_rufus_get` 参数按使用频率排序：

1. `asin`
2. `country`
3. `question`
4. `skills_dir`
5. `new_chrome`
6. `keep_chrome_open`
7. `cdp_url`
8. `timeout_seconds`

理由：

- ASIN、国家、问题是业务参数。
- `skills_dir` 是本地题库定位参数。
- Chrome/CDP/timeout 是运行时参数，放在后面降低认知噪音。

远程授权参数命名必须显式：

```text
allow_capture_browser_state
```

不使用 `yes`、`force`、`remote` 这类含糊参数。该参数名直接说明会捕获浏览器状态，有助于 Agent 在调用前向用户确认。

### 返回体验

成功返回应足够短：

```json
{
  "report_path": "output/amazon-rufus/B0TEST1234-20260603-120000.md",
  "asin": "B0TEST1234",
  "country": "US",
  "question_count": 1,
  "answer_count": 1,
  "next_action": "已生成 Rufus 报告，请读取 report_path 查看完整答案。"
}
```

不默认返回完整答案正文，原因：

- Rufus 回答可能较长。
- 报告文件已经是更稳定的阅读载体。
- 减少 MCP 响应体膨胀和终端截断。
- 避免调试字段随完整 data 误返回。

### 错误体验

登录中断文案应明确“下一步做什么”：

```json
{
  "success": false,
  "error": {
    "code": "RUFUS_LOGIN_REQUIRED",
    "message": "未获取到 Rufus 答案，可能 Amazon 未登录。"
  },
  "data": {
    "next_action": "请调用 amazon_rufus_init 打开对应国家站点登录窗口；用户登录完成后重新调用 amazon_rufus_get。"
  }
}
```

远程授权未确认：

```json
{
  "success": false,
  "error": {
    "code": "RUFUS_REMOTE_CONSENT_REQUIRED",
    "message": "调用远程 Rufus 获取前必须明确允许捕获当前 Amazon 浏览器状态。"
  }
}
```

文案不应包含：

- cookie
- localStorage
- storage_state
- headers
- seed request
- upload payload

### Skill 文档体验

`ops-amazon-rufus` Skill 的首屏应变短，定位为“题库数据 + MCP 编排规则”：

```text
ops-amazon-rufus 提供 Amazon Rufus 默认题库数据。
Rufus 获取能力由 MCP Tool 提供：amazon_rufus_get。
当用户同意保存 cookie / browser state 时，调用 amazon_rufus_get_remote。
```

Skill 文档中保留：

- 数据文件列表。
- 题库升级说明。
- MCP 工具名称索引。
- 用户同意保存 cookie / browser state 后，走 `amazon_rufus_get_remote(..., allow_capture_browser_state=True)`。
- 用户不同意保存 cookie / browser state 时，不调用远程捕获工具。
- 登录中断不属于工具异常，不提交 feedback。
- 明确说明获取 Rufus 的 Python 文件在 MCP 工具层：`opscli/mcp/tools/amazon_rufus.py`。

Skill 文档中移除：

- 终端执行大段示例。
- PowerShell 环境变量前缀。
- Chrome 调试窗口命令。
- 远程授权长流程。
- 报告格式化执行规则。
- `scripts/get_rufus.py`、`scripts/rufus.py`、`scripts/headless_rufus.py` 等获取 Rufus 的 Python 脚本文件。

这样可以避免 Agent 同时看到“Skill 要求跑 CLI”和“MCP Tool 可直接调用”两套入口，同时保留用户同意保存 cookie 后走 MCP 获取的关键决策。

### Skill 文件体验

用户或 Agent 打开 `ops-amazon-rufus` Skill 目录时，应看到数据与说明，而不是可执行采集脚本。

推荐目录观感：

```text
ops-amazon-rufus/
├── SKILL.md
├── README.md
├── data/
│   ├── VERSION.json
│   └── question_templates.json
└── references/
    └── question-templates.md
```

不应出现：

```text
ops-amazon-rufus/scripts/get_rufus.py
ops-amazon-rufus/scripts/rufus.py
ops-amazon-rufus/scripts/headless_rufus.py
```

这能让使用者形成稳定心智：Skill 是知识和题库，MCP Python 文件才是执行工具。

### 可访问性和可维护性

虽然本轮没有 UI 组件，仍需满足工具可理解性：

- 工具 docstring 使用中文说明副作用。
- 参数名使用英文 snake_case，描述使用中文。
- 错误码稳定，便于 Agent 做分支处理。
- `next_action` 使用短句，不写多段说明。

### UIUX 结论

MCP 化后的最佳体验不是让用户记住命令，而是让 Agent 看到清晰工具：

```text
amazon_rufus_init -> amazon_rufus_get -> report_path
```

远程/headless 获取只在用户明确授权时出现：

```text
amazon_rufus_get_remote(..., allow_capture_browser_state=True)
```

Skill 则变成数据包和编排规则，不再承载 CLI/Python 获取实现，也不包含获取 Rufus 的 `.py` 脚本文件；该文件由 MCP 层拥有和维护，目标路径为 `opscli/mcp/tools/amazon_rufus.py`。

## UIUX 结论

本需求的一期 UIUX 重点不是“设计界面”，而是：

- 把复杂流程压缩成一条稳定命令
- 让前置依赖足够显式
- 让错误信息足够明确
- 让内部数据适合脚本和排障解析，最终回复适合人工阅读

只要这四点做对，`ops-amazon-rufus` 的首版体验就是合格的。

## 2026-06-04 体验增量：headless 浏览器缺失时默认自动修复一次

### 体验问题

当前用户只看到：

```text
RUFUS_HEADLESS_CAPTURE_ERROR: 无法启动 headless Chromium
```

这句话说明了失败点，但没有说明下一步。实际底层错误是 Playwright 当前版本需要的 headless Chromium 二进制不存在。用户已确认期望默认自动修复一次，不新增参数。

### 推荐体验

当首次启动 headless Chromium 失败，且底层异常明确表示 Playwright 浏览器二进制缺失时，系统应默认执行：

```powershell
python -m playwright install chromium
```

随后自动重试一次 headless Chromium 启动。用户不需要额外传 `auto_install` 参数，也不需要手工执行命令。

### 失败文案

如果自动安装失败或重试仍失败，MCP 返回的 message 推荐为：

```text
无法启动 headless Chromium；已尝试自动安装 Playwright Chromium 并重试一次，但仍未成功。请在 opscli 运行环境执行 python -m playwright install chromium 后重试。
```

如果由项目命令执行，推荐给出等价 PowerShell：

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; uv run --extra amazon python -m playwright install chromium
```

### 用户心智

该错误应被归类为“运行环境缺失”，且系统会先尝试自修复一次。它不是：

1. Amazon 未登录。
2. CDP 没启动。
3. 题库未安装。
4. Rufus 商品页不支持。

### 文案边界

错误中可以展示：

- Playwright 浏览器二进制缺失。
- 已自动安装并重试一次。
- 建议安装命令。
- 简短底层异常摘要。

错误中不得展示：

- cookie
- localStorage
- `storage_state`
- headers
- seed request
- upload payload

### 成功后的体验不变

自动安装并重试成功后，远程获取仍沿用既有体验：

1. 用户明确同意远程授权。
2. 用户完成目标国家站点 Amazon 登录。
3. MCP 捕获并加密保存浏览器状态。
4. headless 获取 Rufus。
5. 成功时只返回 `report_path`。

## 2026-06-05 体验增量：headless 捕获失败时自动重新打开 Amazon 页面

### 体验问题

偶发 `RUFUS_HEADLESS_CAPTURE_ERROR` 对用户来说通常不可操作：用户已经授权或已经有后端 secret，但 Amazon 商品页首轮没有触发 Rufus streaming，工具就直接失败。

### 推荐体验

系统应在用户无感知的情况下自动重新打开 Amazon 商品页：

```text
首次打开商品页
  -> 未捕获 Rufus streaming
  -> 自动重新打开商品页，最多重试 3 次
  -> 捕获成功后继续生成 report_path
```

成功时不需要在最终回复中强调重试细节，保持现有成功输出：

```json
{
  "report_path": "output/amazon-rufus/B0TEST1234-20260605-120000.md",
  "next_action": "已生成 Rufus 报告，请读取 report_path 查看完整答案。"
}
```

### 失败文案

如果 3 次重试后仍失败，推荐错误文案为：

```text
未捕获 /rufus/cl/streaming；已重新打开 Amazon 商品页并重试 3 次。请确认 cookie 或浏览器状态有效，或目标商品页支持 Rufus。
```

该文案把失败归因到“页面捕获仍未成功”，而不是让用户误以为：

1. MCP 没有调用 Python。
2. Chrome CDP 未启动。
3. Playwright Chromium 缺失。
4. 题库缺失。

### 文案边界

允许展示：

- 已重新打开 Amazon 商品页。
- 已重试 3 次。
- 可能需要刷新授权状态或确认站点支持 Rufus。
- 简短底层异常类型。

不得展示：

- cookie
- localStorage
- `storage_state`
- headers
- seed request
- upload payload

### UI/设计系统

本轮没有图形界面，不新增图标、字体、design token 或组件。体验变更仅限 MCP 内部重试和最终错误文案；未来如增加可视化诊断面板，仍需先单独冻结图标库、字体系统、design token、组件生态和页面骨架。

## 2026-06-05 体验增量：MCP 工具去 CDP 与去 remote

### 体验目标

Agent 看到的 Rufus MCP 工具应只有一个默认入口：

```text
amazon_rufus_get
```

用户不再看到或被引导到：

```text
amazon_rufus_init
amazon_rufus_get_remote
CDP
chrome_path
launch_if_needed
allow_capture_browser_state
```

### 默认体验

新默认流程：

```text
用户给 ASIN / 国家 / 可选问题
  -> Agent 调用 amazon_rufus_get
  -> MCP 后端/headless 获取 Rufus
  -> 返回 report_path
```

成功输出保持不变：

```json
{
  "report_path": "output/amazon-rufus/B0TEST1234-20260605-120000.md",
  "next_action": "已生成 Rufus 报告，请读取 report_path 查看完整答案。"
}
```

### 授权失败体验

去掉 CDP/remote 后，授权失败不能再提示“打开登录窗口”或“允许捕获浏览器状态”。推荐文案：

```text
当前 Rufus 后端授权状态不可用或已失效，请刷新 Rufus 后端授权状态后重新调用 amazon_rufus_get。
```

### “答案是否需要登录恢复”的用户解释

该判断不是在检测浏览器是否真的登录，而是在判断 Rufus 结果是否完全没有可展示内容：

1. 没有任何 answer。
2. 所有 answer 都没有正文、HTML、摘要或结构化 blocks。

如果命中，就说明本轮结果无法生成有效报告，系统当前把它归入登录/授权状态恢复。去掉 CDP 后，用户看到的恢复动作应从“打开登录窗口”变成“刷新后端授权状态”。

### 文案边界

Skill 和 MCP 返回中不再出现：

- `amazon_rufus_init`
- `amazon_rufus_get_remote`
- `allow_capture_browser_state=True`
- `opscli amazon-rufus init`
- `--launch-if-needed`
- `chrome_path`

仍然可以出现：

- `amazon_rufus_get`
- `report_path`
- `RUFUS_SECRET_NOT_READY`
- `RUFUS_HEADLESS_CAPTURE_ERROR`
- `RUFUS_LOGIN_REQUIRED`

### UI/设计系统

本轮没有图形界面，不新增图标、字体、design token 或组件。体验变更仅限 MCP 工具面、Skill 文案和错误恢复指引。

## 2026-06-05 体验增量：当前宿主未暴露 Rufus MCP 工具时的提示与兼容路径

### 体验问题

用户使用 Skill 时，可能处在一个没有暴露 `amazon_rufus_*` MCP 工具的宿主环境中。此时如果文档只写“确认 MCP Server 可用”，Agent 容易停在前置条件上，无法继续完成 Rufus 获取。

这类问题不应被描述成 Rufus 后端授权失败，也不应让用户理解成必须手工写 CDP 命令。更好的体验是：说明当前宿主没有可调用的 Rufus MCP 工具，然后切换到 opscli 正式 CLI 兼容入口。

### 推荐提示

当工具列表不可见时，Agent 可提示：

```text
当前宿主未暴露 amazon_rufus_* MCP 工具。我将改用 opscli amazon-rufus 的本机兼容入口获取 Rufus，仍只返回报告路径。
```

不要把宿主工具可见性、MCP 服务状态和 CDP 实现细节压成一句话；这类表述容易让用户误以为授权失败、服务异常和本机兼容链路是同一个问题。

### 推荐命令体验

默认题库：

```powershell
opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" --launch-if-needed
```

临时问题：

```powershell
opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" --launch-if-needed -q "这个商品适合送礼吗？"
```

多临时问题：

```powershell
opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" --launch-if-needed -q "这个商品适合送礼吗？" -q "差评主要集中在哪些方面？"
```

### 输出体验

CLI 成功时会输出报告保存路径。Agent 最终仍只展示路径，不展示完整命令日志、内部 JSON 或请求字段。

如果需要登录，提示用户使用：

```powershell
opscli amazon-rufus init US
```

并在目标国家站点完成 Amazon 登录后重试原 `get` 命令。

### UI/设计系统

本轮没有图形界面，不新增图标、字体、design token 或组件。体验变更仅限 Skill 文案、宿主能力判断和 CLI 兼容入口提示。

## 2026-06-05 体验增量：RUFUS_HEADLESS_CAPTURE_ERROR 后的登录恢复提示

### 体验问题

用户看到 `RUFUS_HEADLESS_CAPTURE_ERROR` 时，很难判断下一步是刷新授权、处理 CDP，还是重试问题。该错误更适合被解释为“headless 获取没有拿到可用页面上下文或登录态”，因此应引导用户完成一次可见 CDP 登录，再按原入口重试。

### 推荐提示

MCP 工具返回该错误时，Agent 可提示：

```text
Rufus headless 获取未捕获到可用页面上下文。请先在目标国家站点完成 Amazon 登录，我会刷新浏览器状态后按原问题继续获取。
```

随后调用：

```text
amazon_rufus_init(country="US")
```

等待用户回复“已登录”后，再调用：

```text
amazon_rufus_get_remote(
  asin="B0TEST1234",
  country="US",
  questions=["原问题一", "原问题二"],
  skills_dir=".agents/skills",
  allow_capture_browser_state=True,
)
```

### CLI 兼容提示

如果当前宿主没有 Rufus MCP 工具，或原入口就是 CLI 兼容路径：

```powershell
opscli amazon-rufus init US
```

用户完成登录后，重试原命令：

```powershell
opscli amazon-rufus get B0TEST1234 US --skills-dir ".agents/skills" --launch-if-needed -q "原问题"
```

### 文案边界

允许展示：

- `RUFUS_HEADLESS_CAPTURE_ERROR`。
- 需要通过 CDP 登录窗口刷新目标国家站点登录态。
- 登录完成后按原问题来源继续获取。

不得展示：

- cookie
- localStorage
- `storage_state`
- headers
- seed request
- upload payload

### UI/设计系统

本轮没有图形界面，不新增图标、字体、design token 或组件。体验变更仅限错误恢复提示和登录后重试路径。

## 2026-06-05 体验修正：无 CDP 的 Rufus 单链路体验

### 覆盖声明

本节覆盖前文所有 CDP 登录窗口、`amazon_rufus_init`、`amazon_rufus_get_remote`、CLI CDP 兼容入口和 `--launch-if-needed` 提示。后续用户体验只围绕 `amazon_rufus_get` 与报告路径展开。

### 用户心智

用户不需要理解或处理：

- Chrome CDP
- remote debugging port
- Chrome profile
- `chrome_path`
- `amazon_rufus_init`
- `amazon_rufus_get_remote`
- `allow_capture_browser_state`

用户只需要提供：

- ASIN
- 国家站点
- 默认题库或临时问题

### 推荐成功提示

```text
Rufus 获取完成，报告已生成：output/amazon-rufus/<asin>-<timestamp>.md
```

即使 `answer_count=0`，也按正常完成提示，不把空答案解释成登录恢复：

```text
Rufus 获取完成，本轮未返回可展示答案，报告已生成：output/amazon-rufus/<asin>-<timestamp>.md
```

### 推荐失败提示

`RUFUS_SECRET_NOT_READY`：

```text
当前 Rufus 后端授权材料不可用，请刷新后端授权状态后重试 amazon_rufus_get。
```

`RUFUS_HEADLESS_CAPTURE_ERROR`：

```text
Rufus headless 页面上下文捕获失败，系统已按内部重试策略重新打开页面；超过重试上限后仍失败。请稍后重试或确认目标商品页是否支持 Rufus。
```

### 禁止提示

当前流程文档和 Agent 回复中不得再提示：

- 调用 `amazon_rufus_init`
- 调用 `amazon_rufus_get_remote`
- 打开 CDP 登录窗口
- 手动启动 Chrome remote debugging
- 传 `--launch-if-needed`
- 传 `--chrome-path`
- 使用 `opscli amazon-rufus init`

### 体验验收

1. 工具可见性提示只围绕 `amazon_rufus_get`。
2. 空答案是“0 答案报告”，不是“登录失败”。
3. 错误恢复不出现 CDP、Chrome 调试端口或 remote browser state。
4. 最终回答只展示报告路径和必要摘要，不输出 cookie、headers、seed request 或 `storage_state`。

## 2026-06-05 体验修正：三类 MCP 错误后的单次登录恢复提示

### 覆盖声明

本节覆盖前文“错误恢复不出现 CDP”的体验结论。新的体验要求是：默认成功路径仍隐藏 CDP；只有 `amazon_rufus_get` 返回指定错误时，才向用户展示一次 CDP 登录恢复。

### 用户心智

用户需要理解的规则只有三条：

1. 先尝试默认 Rufus MCP 获取。
2. 如果 MCP 返回授权/上下文相关错误，系统会打开一次目标国家站点 Amazon 登录窗口。
3. 本次请求只会要求登录一次；登录后仍失败，不会反复弹登录窗口。

### 触发错误提示

当 MCP 返回以下错误时：

```text
RUFUS_HEADLESS_REQUEST_ERROR
RUFUS_HEADLESS_CAPTURE_ERROR
RUFUS_SECRET_NOT_READY
```

推荐提示：

```text
Rufus MCP 获取返回 <ERROR_CODE>。我会触发一次目标国家站点 Amazon 登录恢复，请在打开的窗口完成登录。登录完成后回复“已登录”，我会按原 ASIN、国家和问题继续获取。
```

如果 `RUFUS_HEADLESS_REQUEST_ERROR` 的 message 是 `Rufus 请求失败: 403`，不要把它展示成“服务不可用”。推荐解释为：

```text
Rufus 请求被 Amazon 拒绝，本轮按授权或页面上下文失效处理，进入一次登录恢复。
```

### 登录确认门

调用登录窗口后，Agent 必须等待用户确认：

```text
请在打开的 Amazon 窗口完成目标国家站点登录。完成后回复“已登录”。
```

用户未确认前，不执行恢复后的 `get`。

### 登录后重试提示

用户确认后：

```text
已记录本次 Skill 调用已完成一次登录恢复。现在按原问题来源继续获取 Rufus。
```

成功时：

```text
Rufus 获取完成，报告已生成：output/amazon-rufus/<ASIN>-<timestamp>.md
```

### 二次失败提示

如果登录后仍失败：

```text
本次 Skill 调用已触发过一次 CDP 登录恢复，仍未成功；为避免重复登录循环，不再打开第二次登录窗口。错误：<ERROR_CODE>: <message>
```

该提示要短，直接说明停止原因和错误码。

### 禁止提示和输出

即使进入 CDP 登录恢复，也不得输出或要求用户复制：

- cookie
- localStorage
- `storage_state`
- headers
- seed request
- upload payload
- 完整原始 JSON

不应让用户手工理解或输入 Chrome remote debugging 参数。Skill 可以使用 opscli 正式 CLI 的 `init/get` 入口，但面向用户的提示应聚焦“登录一次并重试原问题”。

### UI/设计系统

本轮没有图形界面，不新增图标、字体、design token 或组件。体验变更仅限 Agent 提示、一次性登录护栏和错误恢复文案。

## 2026-06-05 体验修正：登录态保存闭环与命令指引统一

### 覆盖声明

本节覆盖前文“登录后执行 `opscli amazon-rufus get ... --launch-if-needed`”的体验文案。最新体验目标是：登录恢复后先保存本地浏览器状态，再重新调用 MCP `amazon_rufus_get`。

### 用户可见主流程

用户只需要理解四步：

1. 系统先尝试 Rufus MCP 获取。
2. 如果登录态不可用，系统打开目标国家站点 Amazon 登录窗口。
3. 用户登录完成后，系统保存本地浏览器状态。
4. 系统重新调用 MCP 获取并返回报告路径。

### 推荐提示

MCP 返回登录态相关错误时：

```text
Rufus MCP 获取返回 <ERROR_CODE>，当前国家站点登录态不可用。我会打开一次 Amazon 登录窗口。请在窗口中完成登录，完成后回复“已登录”。
```

打开登录窗口时：

```text
请在打开的目标国家站点 Amazon 窗口完成登录。登录完成后回复“已登录”，我会保存本地登录态并继续 MCP 获取。
```

用户确认后：

```text
已确认登录完成。我会保存当前国家站点的本地浏览器状态，然后按原 ASIN、国家和问题重新调用 Rufus MCP。
```

保存成功后：

```text
本地登录态已保存，正在重新调用 amazon_rufus_get。
```

最终成功：

```text
Rufus 获取完成，报告已生成：output/amazon-rufus/<ASIN>-<timestamp>.md
```

二次失败：

```text
本次 Skill 调用已完成一次登录态刷新，仍未成功；为避免重复登录循环，不再打开第二次登录窗口。错误：<ERROR_CODE>: <message>
```

### 命令展示规则

面向用户和 Agent 的默认命令只展示：

```powershell
opscli amazon-rufus init US --launch-if-needed
opscli amazon-rufus save-state US
```

Chrome 自动发现失败时，再提示：

```powershell
opscli amazon-rufus init US --launch-if-needed --chrome-path "C:/Program Files/Google/Chrome/Application/chrome.exe"
```

不再把以下命令作为推荐主路径：

```powershell
opscli amazon-rufus get B0TEST1234 US --new-chrome
opscli amazon-rufus get B0TEST1234 US --launch-if-needed
```

`get --new-chrome` 可以保留为开发排障能力，但用户文档和安装后引导不主动推荐。

### 不处理项的用户体验

本轮不改变以下体验：

1. 默认题库为空仍返回题库未就绪错误，引导升级题库。
2. `answer_count=0` 或空报告不新增解释。
3. 题库升级接口环境切换不展示给普通用户。
4. 发布配置不进入用户提示。

### 敏感信息规则

任何提示、报告或错误都不得展示：

- cookie
- localStorage
- `storage_state`
- headers
- seed request
- upload payload
- 完整原始 JSON

用户不需要复制 cookie，也不需要理解 `storage_state` 文件路径。系统只告知“本地登录态已保存”。

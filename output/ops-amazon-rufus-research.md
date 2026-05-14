# ops-amazon-rufus Research

## 2026-05-14 Rufus 拒答检测与问题改写研究

### 本轮反馈

用户补充说明：本轮不只是校验空白问题，还要在拿到 Rufus 答案后分析答案是否属于拒绝回答。如果被拒绝回答，需要在保持原有语义的前提下修改问题，并且改写后的问题限制在 180 字以内。

2026-05-14 新增约束：用户进一步要求 `ops-amazon-rufus` Skill 在拒答后重新生成问题时，改写后的问题必须使用中文。该规则应作为 Skill 执行规范中的硬约束，而不是仅作为示例文案。

### 本地链路观察

当前最合适的接入点不是 CLI 参数解析层，而是 Rufus replay 后的答案解析层：

1. `RufusReplayService.replay_with_page()` 已经逐题调用 `page.evaluate()` 并把 SSE 文本交给 `RufusParserService.parse()`。
2. `RufusParserService.parse()` 返回 `AnswerData`，包含 `text`、`summaryText`、`blocks`、`isSuccess` 和 `threadId`。
3. `AnswerReportFormatter` 基于 `answers[]` 和 `questions[]` 输出报告标题和正文。
4. 因此拒答检测应在每次 `AnswerData` 生成后执行：先判断回答是否拒答，再决定是否改写问题并重试。
5. 单题模式与题库模式都应走同一套拒答处理，避免只有 `--question` 才具备重试能力。

### 拒答判断结论

首版采用保守启发式，不引入外部模型依赖：

1. 检测范围包括 `answer.text`、`answer.summaryText` 和可转文本的 `answer.blocks`。
2. 命中明确拒答短语时判定为拒答，例如“我无法回答”“不能提供”“无法提供”“不方便回答”“I can't answer”“I cannot answer”“I'm unable to”“not able to assist”。
3. 不把普通失败、超时、空答案直接等同于拒答；这些仍按现有失败逻辑处理。
4. 检测逻辑应集中在独立服务中，例如 `QuestionRefusalService`，避免把字符串规则散落在 replay 或 formatter 中。

### 问题改写结论

首版改写策略应满足四个约束：

1. 保持原问题的业务语义，不改变目标 ASIN、比较对象、评价维度或用户意图。
2. 改写后问题长度限制在 180 字以内；建议按 Python `len()` 对去空白后的 Unicode 字符串计数。
3. 改写后的问题必须使用中文，即使原问题包含英文，也应在保留商品对象、比较对象和分析维度的前提下转写为中文问句。
4. 每个问题最多自动改写并重试 3 次；加上原问题首次执行，单题最多 4 次尝试，避免 Rufus 连续拒答时陷入无限循环或生成大量不可控请求。

推荐改写原则：

1. 去掉容易触发拒答的命令式或敏感化表达，例如“必须”“保证”“是否违规”等绝对化措辞。
2. 保留核心对象和分析维度，例如“适合送礼”“差评风险”“广告投放价值”。
3. 改成面向商品公开信息的中性问法，例如“基于商品页面和公开评价，分析该商品是否适合送礼，并说明理由”。
4. 如果原问题是英文或中英混合，应将核心意图翻译/转写为自然中文，避免直接生成英文重试问题。
5. 如果改写结果仍超过 180 字，优先压缩修饰语和重复背景，而不是截断核心业务词。

### 2026-05-14 外部资料补充

Amazon 官方资料说明 Rufus/Alexa for Shopping 的核心场景是回答商品问题、基于商品页面、评论、社区问答和目录信息辅助购买决策。该定位支持本轮采用“中文、中性、基于商品页面和公开评价”的改写方向。

官方资料同时显示 Amazon 已在 2026-05-13 将 Rufus 重新命名为 Alexa for Shopping。当前仓库中的 CLI、Skill、模块名仍为 `ops-amazon-rufus`，本轮仅增加拒答后中文改写规则，不做命名迁移，避免扩大影响面。

参考：

- https://www.aboutamazon.com/news/retail/how-to-use-amazon-rufus
- https://www.aboutamazon.com/news/retail/amazon-agentic-ai-gen-ai-shopping/
- https://www.aboutamazon.com/news/retail/alexa-for-shopping-ai-assistant

### 方案判断

采用“拒答检测 + 语义改写 + 最多 3 次重试”的最小方案：

1. 空白 `--question` 仍应提前报错，但这只是输入校验，不是本轮核心。
2. 每个问题先按原文执行一次。
3. 若回答被判定为拒答，则生成 180 字以内的改写问题，并立即用同一 seed/page 上下文重试；最多重试 3 次。
4. 若 3 次改写重试后仍拒答，则保留最后一次结果，并在结构化数据与报告中标记“已改写 3 次后仍拒答”。
5. 输出数据增加拒答与改写元信息，例如 `refusalDetected`、`refusalRetryApplied`、`originalQuestion`、`rewrittenQuestion`、`attemptCount`。
6. 报告中默认展示最终答案；发生改写时补充一行改写说明，不展示完整内部请求或 seed 数据。

该方案符合 KISS/YAGNI：不新增多轮自我优化、不引入外部 LLM、不改变 Chrome/seed/replay 主链路，只在单题执行的结果判定后增加一次可审计的重试。

## 2026-05-14 CLI 传入问题与题库双模式研究

### 本轮需求

用户要求修改 `amazon-rufus` CLI 和 `ops-amazon-rufus` Skill：获取 Rufus 答案需要支持两种方式。

1. 题库模式：继续读取 `ops-amazon-rufus/data/question_templates.json`，按模板问题逐题获取答案。
2. 单题模式：调用 CLI 时直接传入一个问题，只获取该问题对应的 Rufus 答案。

Skill 文档也要同步调整，避免 Agent 在用户已经给出明确问题时仍强制跑完整题库。

### 本地链路观察

当前代码路径：

- `opscli/amazon_rufus/commands/cli.py`
- `opscli/amazon_rufus/services/manager.py`
- `opscli/amazon_rufus/services/question_bank.py`
- `opscli/amazon_rufus/services/replay.py`
- `opscli/skills/templates/ops-amazon-rufus/SKILL.md`
- `opscli/skills/templates/ops-amazon-rufus/README.md`

现状结论：

1. CLI `get` 只有必填位置参数 `asin`、`country`，没有问题参数。
2. `RufusManager.get()` 总是通过 `QuestionBankService.load_templates()` 读取题库，再把模板问题扁平化成 `questions`。
3. 题库文件缺失或为空会抛出 `QuestionBankNotReadyError`，因此当前即使用户只想问一个问题，也必须先安装并升级题库。
4. `RufusReplayService.replay_with_page()` 已经接收 `questions: list[str]`，底层重放链路天然支持传入任意问题列表。
5. `AnswerReportFormatter` 从 `data["questions"]` 或 `upload_payload.records[0].questions` 提取题目标题，因此只要 `data["questions"]` 是单题列表，报告天然可以复用。
6. 现有测试已覆盖 CLI 写报告、manager 编排、replay 请求构造和 formatter 标题提取；本轮应补充单题模式测试，而不是重写底层 replay。

### 外部资料结论

Typer 官方文档说明，可选 CLI argument 会在 help 中显示为带方括号的位置参数；这适合兼容式扩展，但带空格的问题文本必须整体加引号，且会改变 `get <asin> <country>` 后续位置参数语义。参考：https://typer.tiangolo.com/tutorial/arguments/optional/

Typer 官方参数参考说明，CLI option 可以通过 `--name` 这类显式别名接收值，且 options 通常可省略；这更适合新增 `--question`，因为它不会改变既有两个位置参数的心智。参考：https://typer.tiangolo.com/reference/parameters/

Typer 还支持多次传入同一个 option 并获得 `list[str]`，说明后续如果要支持多条临时问题，可以扩展为多个 `--question`，但本轮用户只要求“传入参数问题”这一种直接问答方式，不应提前实现多题参数。参考：https://typer.tiangolo.com/tutorial/multiple-values/multiple-options/

### 方案判断

采用“显式 `--question` 单题模式 + 默认题库模式”的最小方案：

1. CLI 增加 `--question` 选项，而不是新增第三个位置参数。
2. 未传 `--question` 时保持现有题库模式，继续要求本地题库就绪。
3. 传入 `--question` 且去空白后非空时，跳过 `QuestionBankService.load_templates()`，直接使用 `[question]` 作为问题列表。
4. 单题模式仍复用 Chrome attach、seed request 捕获、Rufus replay、答案解析、报告落地和 `upload_payload` 构造。
5. 空字符串或全空白 `--question` 应视为无效输入，返回稳定错误；不应回退到题库模式，避免用户误以为执行了指定问题。
6. `data` 中增加轻量字段标识来源，例如 `question_source: "template" | "cli"`，便于报告与排障理解；现有字段 `questions` 保持不变。
7. Skill 文档同步为：用户提供明确问题时执行 `opscli amazon-rufus get <asin> <country> --question "<问题>" --new-chrome`；用户要求默认 Rufus 分析或未给问题时执行题库模式。

该方案符合 KISS/YAGNI：不新增命令、不新增问题文件、不引入多题临时参数、不改 replay 协议，只在 manager 的问题来源选择处增加一个清晰分支。

## 2026-05-14 问题模板 reference 拆分与保存接口研究

### 本轮需求

用户要求修改 `amazon-rufus` 相关 CLI / Skill 文档结构：

1. 将问题模板的获取拆到独立 `references` 文档中，不再和 Rufus 回答获取流程写在一起。
2. 独立 reference 文件后续只承载问题模板相关内容。
3. 问题模板能力不止获取，还应覆盖保存能力。
4. 保存接口参考 `E:/code/work/workspace-op/operation-frontend/packages/operation-frontend-core/src/pages/tools/index/opencalw-management/index.vue` 间接挂载的管理页调用链。

### 本地链路观察

当前 `ops-amazon-rufus` Skill 目录只有一个报告格式化 reference：

- `opscli/skills/templates/ops-amazon-rufus/README.md`
- `opscli/skills/templates/ops-amazon-rufus/SKILL.md`
- `opscli/skills/templates/ops-amazon-rufus/references/rufus-report-formatting.md`
- `opscli/skills/templates/ops-amazon-rufus/data/question_templates.json`

现状问题：

1. `README.md` 与 `SKILL.md` 主要服务 `amazon-rufus init/get` 使用流程，问题模板升级说明混在回答获取流程里。
2. `references/rufus-report-formatting.md` 已经是答案报告格式化规范，不应承载题库接口。
3. `QuestionBankService` 只读取 `.agents/skills/ops-amazon-rufus/data/question_templates.json`，不负责远端保存。
4. `SkillsUpdater.upgrade_ops_amazon_rufus()` 当前只调用默认题库读取接口，将返回的 `items` 写入本地 `question_templates.json`。
5. 内置模板 `data/question_templates.json` 现在是空 `items`，真实题库依赖 `opscli skills upgrade ops-amazon-rufus` 同步。

前端真实调用链：

1. `opencalw-management/index.vue` 只挂载 `QuestionTemplatesTab` 和 `ConfigTab`，默认激活 `question-templates`。
2. `QuestionTemplatesTab.vue` 负责列表刷新、新增模板、修改描述、配置问题列表、删除模板。
3. `QuestionTemplateDescriptionDialog.vue` 调用创建与更新模板描述 mutation。
4. `QuestionTemplateQuestionsDialog.vue` 调用追加问题、整体保存问题列表、单题更新、单题删除。
5. `project/tools/api/modules/opencalw.ts` 是接口定义源头；`project/tools/services/opencalw.ts` 只是在 Vue Query 层封装缓存失效。

前端接口清单：

| 能力 | 方法 | 路径 | 请求体 |
|---|---|---|---|
| 列出模板 | `GET` | `/admin/opencalw/question-templates` | 无 |
| 获取模板详情 | `GET` | `/admin/opencalw/question-templates/{templateId}` | 无 |
| 新增模板 | `POST` | `/admin/opencalw/question-templates` | `{ "description": "..." }` |
| 修改模板描述 | `PATCH` | `/admin/opencalw/question-templates/{templateId}` | `{ "description": "..." }` |
| 删除模板 | `DELETE` | `/admin/opencalw/question-templates/{templateId}` | 无 |
| 整体保存问题列表 | `PUT` | `/admin/opencalw/question-templates/{templateId}/questions` | `{ "questions": ["..."] }` |
| 追加问题 | `PUT` | `/admin/opencalw/question-templates/{templateId}/questions/append` | `{ "questions": ["..."] }` |
| 修改单题 | `PUT` | `/admin/opencalw/question-templates/{templateId}/questions/{questionId}` | `{ "text": "..." }` |
| 删除单题 | `DELETE` | `/admin/opencalw/question-templates/{templateId}/questions/{questionId}` | 无 |
| 获取默认题库 | `GET` | `/opencalw/default-question-templates` | 无 |

`extensionInterceptors.ts` 会在请求前将 data/params 转为 snake_case，并在响应后将 `data` 转为 camelCase。因此前端类型是 `preferredVersionIndex`、`questionsCount`、`createdAt`、`updatedAt`，但本地题库文件与后端 wire JSON 应继续按 snake_case 文档化，例如 `preferred_version_index`、`questions_count`、`created_at`、`updated_at`。

### 外部资料结论

同类 API 文档有两个可借鉴点：

1. GitHub REST 的 repository contents 文档按资源聚合 get / create-or-update / delete 操作，并为每个操作列出 path、参数、状态码和示例；这适合本轮把“问题模板”作为独立资源 reference 维护。参考：https://docs.github.com/en/rest/repos/contents?apiVersion=2022-11-28
2. OpenAPI / Swagger 支持用 tags 对 operations 分组，Swagger UI 会按 tag 展示操作；这说明“问题模板”应作为独立文档分组，而不是混在 `amazon-rufus get` 回答流程里。参考：https://swagger.io/docs/specification/v3_0/grouping-operations-with-tags/

### 方案判断

采用“新增独立 reference，现有主文档只保留跳转”的最小方案：

1. 新增 `opscli/skills/templates/ops-amazon-rufus/references/question-templates.md`。
2. 新文件只写问题模板数据模型、获取接口、保存接口、保存工作流、本地题库文件关系和注意事项。
3. `README.md` 与 `SKILL.md` 只保留题库升级的简短入口，并链接到 `references/question-templates.md`。
4. 不把 Rufus 回答获取、Chrome 登录、seed request、报告格式化写入新 reference。
5. 不新增 CLI 子命令，不改变 `amazon-rufus get` 运行链路。
6. 不让 Skill 脚本直接调用后端接口；如后续需要命令化保存，应新增正式 `opscli` 命令入口，而不是在 Skill 文档里指导直接 `curl` 生产接口。

该方案符合 KISS/YAGNI：本轮需求是文档结构和接口调用说明，不扩展题库管理运行能力；保存接口先精确文档化，避免把管理端 mutation 误写成回答获取流程的一部分。

## 2026-05-07 登录前置提示与 streaming 捕获失败研究

### 本轮需求

用户要求为 `ops-amazon-rufus` 增加两处登录引导：

1. 安装 `ops-amazon-rufus` 后，提示用户该 Skill 需要先登录 Amazon 才能使用。
2. 获取 Rufus 答案时，如果 Python 采集脚本没有拦截到 `/rufus/cl/streaming` 请求，必须报错，并明确让用户执行 `opscli amazon-rufus init <country>` 去登录 Amazon。

### 本地链路观察

相关路径：

- `opscli/skills/commands/cli.py`
- `opscli/skills/services/manager.py`
- `opscli/skills/domain/models.py`
- `opscli/amazon_rufus/services/browser.py`
- `opscli/amazon_rufus/domain/exceptions.py`
- `.agents/skills/ops-amazon-rufus/SKILL.md`
- `opscli/skills/templates/ops-amazon-rufus/README.md`

当前行为：

1. `opscli skills install <name>` 成功后输出稳定 JSON：`success`、`command`、`data`、`error`。
2. `SkillBatchInstallResult.to_dict()` 只包含 `name`、`version`、`installed_paths`，没有 Skill 专属安装后提示。
3. `ops-amazon-rufus` 的 Skill 文档已经说明使用前必须登录对应国家站点，并推荐 `opscli amazon-rufus init <country>`。
4. `BrowserAttachService.capture_seed_request()` 未捕获 `/rufus/cl/streaming` 时抛出 `SeedRequestNotCapturedError`。
5. 现有错误码为 `SEED_REQUEST_NOT_CAPTURED`，错误信息只提示“请确认已登录 Amazon 且站点支持 Rufus”，没有明确给出下一条命令。

### 外部资料结论

同类 CLI 对登录前置条件的处理有三个可借鉴点：

1. GitHub CLI 把认证作为显式命令 `gh auth login`，并在文档中说明认证完成后凭证会写入系统凭证存储或回退文件。参考：https://cli.github.com/manual/gh_auth_login
2. Stripe CLI 安装文档在安装步骤后紧接着要求执行 `stripe login`，并输出浏览器确认链接和 pairing code。参考：https://docs.stripe.com/stripe-cli/install
3. AWS CLI 的 `configure` 命令在首次配置时提示用户输入凭证，同时文档也提示可通过 `aws login` 使用 Console session 传递临时凭证。参考：https://docs.aws.amazon.com/cli/latest/reference/configure/
4. Amazon 官方说明 Rufus 可在 Amazon Shopping app 和 desktop 上使用，并依赖 Amazon 购物页面中的 Rufus 入口。参考：https://www.aboutamazon.com/news/retail/how-to-use-amazon-rufus

这些产品共同特点是：登录不是隐式失败后让用户猜，而是通过安装后文档、专门命令或失败提示给出明确下一步。`ops-amazon-rufus` 因依赖浏览器页面登录态，不应尝试在 CLI 内保存 Amazon 凭证；正确路径是把登录动作显式收敛到 `amazon-rufus init <country>`。

### 方案判断

采用“安装结果内嵌 next steps + 捕获失败明确 init 指令”的最小方案：

1. `skills install ops-amazon-rufus` 成功时，在 JSON `data` 中增加 Amazon 登录前置提示和下一步命令。
2. 非交互安装不额外输出 JSON 之外的散文本，避免破坏脚本解析。
3. 交互安装可以复用同一份 `data` 结构；是否额外打印人类可读行由实现阶段再按现有 TUI 输出风格最小处理。
4. 其他 Skill 的安装输出不增加 Rufus 专属字段。
5. `SeedRequestNotCapturedError` 的 message 明确包含 `opscli amazon-rufus init <country>`。
6. 不做自动登录、不自动打开 `init`、不检测 Amazon 用户身份、不读取或保存 Amazon 凭证。

### 研究结论

本轮应只改两个用户可见边界：

1. 安装成功后的 `ops-amazon-rufus` 专属 `next_steps`。
2. 未捕获 `/rufus/cl/streaming` 时的错误文案。

不应改变 `get` 的核心采集链路、题库读取、Rufus replay、报告格式化或上传 payload。该方案符合 KISS/YAGNI：把失败后的“下一步”从隐含经验变成稳定契约，不扩展认证体系。

## 2026-04-30 新增输出落地文件研究

### 触发背景

用户在实际运行 `amazon-rufus get` 时已尝试扩大 PowerShell `RawUI.BufferSize`，但长报告仍可能被 IDE 终端、宿主工具返回长度或 Agent 输出窗口截断。该问题不属于 Rufus parser 或 formatter 主动删减，而是 stdout 展示链路的承载边界。

### 本地链路观察

当前实现中，`commands/cli.py` 成功路径通过 `AnswerReportFormatter().format_data(data)` 生成完整报告，然后直接 `typer.echo()` 到 stdout。该链路有两个问题：

1. 报告内容仍完整存在于 CLI 进程内，但 stdout 消费方可能截断。
2. Agent 执行 CLI 后只能读取工具返回文本，无法保证拿到完整 stdout 历史。

### 结论

本轮应把成功报告从 stdout 改为运行时文件落地：

1. 输出目录固定为当前运行目录下的 `output/amazon-rufus`。
2. 文件名使用 `<ASIN>-YYYYMMDD-HHMMSS.md`，时间精确到秒。
3. 文件内容仍是现有 formatter 生成的 Markdown-like 答案报告。
4. stdout 只输出保存路径和状态，不再承载完整报告正文。
5. 不新增可配置 `--output` 参数，避免扩大命令心智负担。

该方案符合 KISS/YAGNI：保留现有 formatter，新增最小文件写入边界；不引入分页器、剪贴板、临时文件清理协议或交互式查看器。

## 2026-04-30 新增前端渲染对齐输出格式化研究

### 本轮需求

用户提供 `output/1.txt` 作为 `opscli amazon-rufus get` 的终端输出样例，并要求参考 `E:\code\work\operation-frontend - 1\packages\operation-frontend-core\src\project\tools\components\asinRufusView` 中的前端渲染方式，对 CLI 输出数据进行格式化。若需要其他参数，可参考 CLI 输出前拿到的全量数据结构。

样例文件使用 UTF-8 读取后有 1024 行，首行从 `4. 易用性` 开始，说明当前可见内容本身已经不是完整回答开头；同时存在以下可读性问题：

1. 连续空行过多，很多段落被拉开成“单行文本 + 多个空行”。
2. 表格内容退化为一列一行，例如“问题 / 影响 / 严重程度”和具体值被拆散；前端已有结构化表格渲染模型可参考。
3. 项目符号存在独立成行的情况，例如 `•` 单独一行，真正内容在下一行；前端已有 list block 合并模型可参考。
4. 当前 CLI 已隐藏 `seed_request` 与 `upload_payload`，但 `_emit_answers_text()` 只是 `strip()` 后拼接文本，没有格式化边界。
5. 终端滚动缓冲或宿主输出窗口导致的截断属于运行环境限制，本轮不处理。

### 当前 CLI 代码结论

相关路径：

- `opscli/amazon_rufus/commands/cli.py`
- `opscli/amazon_rufus/services/parser.py`
- `opscli/amazon_rufus/domain/models.py`
- `tests/amazon_rufus/test_core.py`

当前输出链路：

1. `RufusParserService.parse()` 从 SSE 中产出 `AnswerData.text`。
2. `RufusManager.get()` 将 `AnswerData` 转为 `answers[]`。
3. CLI `_emit_answers_text()` 遍历 `answers[]`，直接输出每个 `text.strip()`。

因此本轮格式化不应放进 parser。parser 的职责是还原 Rufus 原始回答；格式化属于 CLI 展示层，应新增独立 report formatter，读取 CLI 输出前的完整 `data`，避免污染内部结构化数据和上传 payload。

### 前端渲染结论

参考路径：

- `AsinRufusDetailBody.vue`
- `AsinRufusSectionCard.vue`
- `AsinRufusAnswerBlocks.vue`
- `utils/asinRufus/answerBlocks.ts`
- `utils/asinRufus/toSections.ts`
- `api/types/intercept.ts`

前端渲染的数据模型：

1. `AnswerData` 包含 `text`、`summaryText`、`productLinks`、`recommendedAsins`、`blocks`、`isSuccess`。
2. `AnswerBlockData` 支持 `heading`、`paragraph`、`list_item`、`table_row`，其中 `table_row` 可带 `cells`。
3. `AsinRufusSectionCard` 的展示顺序是：
   - 相关产品 `productLinks`
   - 答案正文 `AsinRufusAnswerBlocks`
   - 推荐 ASIN `recommendedAsins`
   - 总结 `summaryText`
4. `AsinRufusAnswerBlocks` 优先消费结构化 `blocks`；缺失时才解析 `text`。
5. `answerBlocks.ts` 的回退解析支持：
   - Markdown 标题 `#`
   - 无序列表 `-/*/•`
   - 有序列表 `1.` / `1)`
   - Markdown 表格，且必须存在 delimiter 行才识别为表格
   - 缩进行作为上一条列表项的续行
6. `toSections.ts` 会按 `sort`、`questionId`、`question` 排序，并对失败答案做 status 识别；CLI 当前没有前端完整 record detail，但可用 `data.answers[]` 和 `data.upload_payload.records[0].questions[]` 形成近似 section。

### 外部资料结论

1. Python 标准库 `textwrap` 提供换行、填充、缩进等文本处理能力；其中 `shorten()` 会折叠并截断文本，不适合本需求。参考：https://docs.python.org/3/library/textwrap.html
2. AWS CLI 将机器可读 JSON 与用户可读 text/table 输出区分，说明 CLI 可以为人工阅读单独设计展示层。参考：https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-output-format.html
3. Typer 官方测试建议使用 `CliRunner` 校验 stdout/stderr，可用于新增格式化输出回归测试。参考：https://typer.tiangolo.com/tutorial/testing/

### 方案判断

采用“前端渲染对齐的确定性文本报告”方案：

1. 不使用 LLM 对答案二次总结或改写，避免改变 Rufus 原意。
2. 不使用会主动丢弃内容的 `textwrap.shorten()`、`max_lines` 或固定行数限制。
3. 新增 formatter 读取完整 `data`，而不是只读取 `answers[].text`。
4. 输出按“问题 section”组织，展示问题标题、相关产品、正文、推荐 ASIN、总结。
5. 正文渲染优先使用 `answer.blocks`，按前端 block 模型输出 heading/list/table/text；缺失时再按 `answer.text` 解析 Markdown-like 文本。
6. 表格只在结构化 `table_row` 或标准 Markdown 表格中渲染，不猜测 `output/1.txt` 这种已退化的一列文本为表格，避免误伤正文。
7. CLI 默认将格式化文本写入 `output/amazon-rufus` 报告文件，不新增可配置文件输出参数。
8. 终端滚动缓冲或宿主输出窗口造成的截断通过文件落地规避，不再由 stdout 承载完整报告。
9. `--pretty` 继续只影响错误 JSON，不参与成功答案格式化。

### 研究结论

本轮不应修改 Rufus replay、parser、题库或上传 payload。最小可维护实现是新增展示层 report formatter，并让 `amazon-rufus get` 的成功输出传入完整 `data` 调用它。这样符合 KISS/YAGNI：复用前端已验证的数据展示规则，只解决 CLI stdout 可读性问题，不引入额外输出通道、GUI、分页器默认行为或新的业务协议。

## 2026-04-29 新增 init 命令研究

### 本轮需求

为 `opscli amazon-rufus` 增加初始化命令：

```bash
opscli amazon-rufus init <country>
```

命令接收一个“国家”参数，使用与现有 `get --new-chrome` 相同的 Chrome 打开方式，打开对应国家站点的 Amazon 首页，提示用户“请在新窗口中登录亚马逊”，随后结束命令。

### 现有流程复用点

参考路径：

- `opscli/amazon_rufus/services/browser.py`
- `opscli/amazon_rufus/runtime/country_map.py`
- `opscli/amazon_rufus/services/manager.py`
- `opscli/amazon_rufus/commands/cli.py`

现有 `get` 链路已经具备以下可复用能力：

1. `BrowserAttachService.DEFAULT_NEW_CHROME_ARGUMENTS` 定义固定 Chrome 调试 profile 与端口。
2. `BrowserAttachService._start_new_chrome()` 通过 PowerShell `Start-Process chrome.exe` 打开独立 Chrome 窗口。
3. `BrowserAttachService._wait_for_cdp()` 等待 `http://127.0.0.1:9222/json/version` 可用。
4. `resolve_marketplace(country)` 将 `US/UK/DE/JP` 映射到对应 Amazon 站点。
5. `get --new-chrome` 已使用独立 profile，适合承载用户 Amazon 登录态。

### 差距分析

`get` 当前会立即访问商品详情页并捕获 `/rufus/cl/streaming`，适合执行采集；但首次使用者需要先在相同 Chrome profile 中完成 Amazon 登录。若直接执行 `get`，用户常见失败点是：

- Chrome 未登录 Amazon。
- 新开的 `E:\chrome-profiles\opscli-rufus` profile 与用户默认 Chrome 登录态隔离。
- 用户不知道应该登录哪个国家站点。

因此 `init` 应作为低风险准备命令，只打开站点并保留窗口，不捕获 Rufus 请求、不读取题库、不执行 replay。

### 外部信息约束

Amazon Rufus 是 Amazon 购物体验中的 AI 购物助手，登录态与站点地域会影响用户能否看到完整购物上下文与个性化能力。公开资料只描述 Rufus 的产品能力，不提供私有 `/rufus/cl/streaming` 接口契约，因此本轮仍应复用现有浏览器 profile 与站点映射，不新增未验证的接口参数。

参考资料：

- https://www.aboutamazon.com/news/retail/amazon-rufus
- https://advertising.amazon.com/library/guides/getting-started-with-rufus
- https://sell.amazon.com/blog/amazon-rufus

### 研究结论

本轮采用“浏览器初始化最小闭环”方案：

1. 新增 `opscli amazon-rufus init <country>`。
2. 国家解析复用 `resolve_marketplace(country)`，打开该国家 Amazon 首页。
3. Chrome 打开方式复用 `BrowserAttachService` 中 `get --new-chrome` 使用的固定调试 profile 与 CDP 等待逻辑。
4. 命令打开页面后输出提示：`请在新窗口中登录亚马逊`。
5. 命令结束时不关闭 Chrome，确保登录态写入固定 profile，供后续 `get --new-chrome` 或同 CDP profile 使用。
6. 不读取题库、不捕获 seed request、不执行 Rufus replay，避免初始化命令承担采集职责。

## 2026-04-29 复刻扩展端 Rufus 行为研究

### 本轮需求

让 `opscli amazon-rufus get <asin> <country>` 尽量复刻扩展端 `AsinRufusDialog` 的“使用问题获取 Rufus 回答”行为，优先对齐请求参数，而不是改变命令形态或引入新的产品能力。

### 扩展端关键实现结论

参考路径：

- `E:/code/work/extension/frontend/packages/extensions/src/content/features/amazon/components/FloatMenu/AsinRufusDialog/composables/useAsinRufusQuery.ts`
- `E:/code/work/extension/frontend/packages/extensions/src/content/features/amazon/components/FloatMenu/AsinRufusDialog/composables/createAsinRufusRunner.ts`
- `E:/code/work/extension/frontend/packages/extensions/src/shared/api/rufus.ts`

扩展端请求模型：

1. 从已拦截记录中选择同 ASIN 的 `/rufus/cl/streaming` seed request。
2. 用 seed request 的 `requestBody` 作为基础 payload。
3. 替换 `queryContext.query` 为当前问题。
4. 显式补齐 `queryContext.actionType = "SEARCH"` 与 `queryContext.qis = "NileCLTextInput"`。
5. 显式补齐 `pageContext.originPageType = "DETAIL_PAGE"`。
6. 将 `pageContext.targetPageMetadata` 与 `pageContext.originPageMetadata` 中的 `ASIN` 对齐到目标 ASIN；不存在则追加。
7. 显式设置 `bottomSheetContext.previousTurnsBottomSheetSize = "expanded"`。
8. 显式设置 `impressionsContext.FIRST_TIME_USER_MESSAGE_SEEN_STATUS = "SEEN"`。
9. 请求 URL 以真实 `requestUrl/pageUrl` 的 origin 为基础重建 `/rufus/cl/streaming`，并设置：
   - `tabId`
   - `programId = "NILE_CLASSIC:desktop-cl"`
   - `ref = "nl_cl_dsk_csq"`
10. 请求 headers 近似完整复用拦截 headers，并使用浏览器凭证上下文。

### 当前 CLI 行为差距

参考路径：

- `opscli/amazon_rufus/services/replay.py`
- `opscli/amazon_rufus/services/browser.py`
- `opscli/amazon_rufus/services/manager.py`

当前 CLI 已具备 seed 捕获与页面内 fetch 重放能力，但参数对齐不足：

1. `build_payload()` 只替换 `queryContext.query`。
2. 不补 `actionType`、`qis`、`pageContext.originPageType`。
3. 不修正 `targetPageMetadata/originPageMetadata` 中的 ASIN。
4. 不补 `bottomSheetContext` 与 `impressionsContext`。
5. 重放 URL 直接使用 `seed.request_url`，不保证 `programId/ref` 存在。
6. headers 仅保留 `anti-csrftoken-a2z`、`content-type`、`x-amz-is-papyrus`，比扩展端更保守。
7. CLI 会把上一题解析出的 `threadId` 注入后续题，扩展端当前主流程没有动态传入该上下文；这是 CLI 已有增强，但可能影响“逐题独立复刻”的一致性。

### 外部信息约束

Amazon 官方对 Rufus 的公开定位是“购物助手”，能力包括回答商品问题、做推荐与辅助比较；这与扩展端围绕商品详情页上下文构造请求的做法一致。公开资料没有提供 `/rufus/cl/streaming` 私有接口契约，因此本需求应以内部扩展端实现作为参数基准，不应臆造未观察到的新字段。

官方资料：

- https://www.aboutamazon.com/news/retail/amazon-rufus
- https://advertising.amazon.com/library/guides/getting-started-with-rufus
- https://sell.amazon.com/blog/amazon-rufus

### 研究结论

本轮应采用“最小参数对齐”方案：

1. 在 CLI payload 构造层复刻扩展端 `buildPayloadFromRecord()` 的字段修正规则。
2. 在 CLI URL 构造层保证 `tabId/programId/ref` 与扩展端一致。
3. headers 先保持当前 allowlist，避免浏览器禁止脚本设置的 header 导致请求失败；如实测缺 header，再按 allowlist 扩展。
4. 保留 CLI 现有 `threadId` 串联能力，但把 `threadState` 补齐为扩展端默认值 `THREAD_STATE_UNKNOWN`，并在后续 Spec 中明确是否提供开关控制独立问答。

## 研究目标

为 `opscli` 增加一条新的 Amazon Rufus 能力链路，满足以下目标：

- 新增 CLI 命令：`opscli amazon-rufus get <asin> <country>`
- 新增可安装 Skill：`ops-amazon-rufus`
- Skill 支持远端升级，用于同步题库与运行参数
- 运行时复用已登录 Amazon 的本地 Chrome 会话，通过 Playwright 连接 Chrome
- 打开商品页后尽早拦截 `/rufus/cl/streaming` seed request
- 参考现有前端 `AsinRufusDialog` / `asin_rufus_batch` 的实现，重放问题并解析回答
- 上传接口本期不真正执行，但上传 payload 结构需要与现有前端口径对齐
- 上传部分需要保留真实发请求代码，默认以注释状态留在实现中

---

## 本地现状

### 当前仓库已有能力

1. `opscli amazon` 已具备 Playwright 抓取能力，但定位是商品页与搜索页采样，不包含 Rufus。
2. 现有 `amazon` 模块默认直连新开的 Chromium，会话与用户本地已登录 Chrome 隔离。
3. 现有 `ops-amazon` Skill 仅指导 AI 使用 `opscli amazon scrape/payload/search/schema/history`，没有 Rufus 工作流。
4. `opscli skills` 已支持“模板安装 + 远端升级”模式，当前 `ops-dataset-query` 是唯一远端升级样例。

### 与本需求最相关的内部 prior art

#### 仓库内 prior art

- `opscli/amazon/scraping/scraper.py`
  - 现有 Playwright 异步抓取骨架可复用。
  - 但当前实现绑定 `amazon.com` 和独立浏览器实例，不满足“复用本地 Chrome 登录态”。

#### 外部前端 prior art

主要参考以下路径：

- `E:/code/work/extension/frontend/packages/extensions/src/content/features/amazon/components/FloatMenu/AsinRufusDialog/`
- `E:/code/work/extension/frontend/packages/extensions/src/content/features/amazon/components/FloatMenu/ProductRufusAnalysisDialog/composables/runAsinRufusBatchRefetch.ts`

研究结论：

1. `AsinRufusDialog` 的核心不是直接使用拦截到的回答，而是：
   - 先从已拦截记录中选择一个 seed request
   - 基于该 request 生成新的 Rufus payload
   - 再主动重放流式请求获得回答
2. `useAsinRufusQuery.ts` 中的关键能力包括：
   - `selectAsinRufusSeedRecord()`：选择 seed request
   - `buildPayloadFromRecord()`：在原始 requestBody 基础上替换 query，并补齐 ASIN / thread context
   - `getTabIdFromRecord()`：从请求字段或 URL 提取 `tabId`
3. `shared/api/rufus.ts` 已验证前端侧可通过：
   - 复用拦截请求的 URL / headers / payload / tabId
   - 再次 `POST /rufus/cl/streaming`
   - 读取 SSE 流并解析 `inference` / `close` 事件
4. `runAsinRufusBatchRefetch.ts` 比 `AsinRufusDialog` 更接近这次 CLI 需求，但 CLI 一期应按新接口收敛数据面：
   - 拉取合并后的默认题目模板
   - 模板内直接包含题目列表
   - 逐题回放 Rufus
   - 将结果按统一 record + answer 结构上传
5. 现有前端的上传口径分两层：
   - `collectInterceptRecordsApi()`：上传一条 record 壳
   - `updateRecordAnswerApi()`：按题逐条回写结构化答案

---

## 外部官方技术约束

### Playwright 连接本地 Chrome

官方文档确认：

- Playwright Python 支持 `browser_type.connect_over_cdp()` 连接到已有 Chromium/Chrome 实例。
- 官方明确说明该方式是“较低保真”的 CDP 连接，优先用于 attach 到已有浏览器，而不是替代标准 `launch()`。
- 默认上下文会通过 `browser.contexts[0]` 暴露出来。

来源：

- https://playwright.dev/python/docs/api/class-browsertype

结论：

- 本需求可以合法走“用户手动打开 Chrome + `--remote-debugging-port=9222` + Playwright attach”的路线。
- 但实现上要尽量使用稳定、收敛的能力集合：
  - attach 到现有 Chrome
  - 复用已有 context/page
  - 做 request 监听
  - 必要时补 CDP session

### Playwright 网络监听能力

官方文档确认：

- Playwright 提供 `page.on("request")`、`page.on("response")`、`page.on("requestfinished")` 等网络事件。
- `Request.post_data()` 可读取 POST body。
- `Request.headers` 并不保证包含安全相关头和 cookie；需要使用更完整的 header 读取方法时应使用完整 header API。

来源：

- https://playwright.dev/python/docs/events
- https://playwright.dev/python/docs/network
- https://playwright.dev/python/docs/api/class-request

结论：

- seed request 的捕获应基于 Playwright request 事件完成。
- 为了得到尽可能完整的重放上下文，运行时不应只依赖简化 headers。

### Playwright 请求上下文与 cookie 共享

官方文档确认：

- `APIRequestContext` 可以与浏览器上下文共享 cookie 存储。

来源：

- https://playwright.dev/python/docs/api/class-apirequestcontext

结论：

- 理论上可以用 `browser_context.request` 做 Rufus replay。
- 但考虑到 Amazon Rufus 对浏览器环境更敏感，优先建议在已打开商品页的浏览器上下文里完成 replay，而不是切到独立 HTTP 客户端。

---

## 关键业务判断

### 1. 这不是 `ops-amazon` 的简单追加子命令

虽然 Rufus 属于 Amazon 域，但它与现有 `amazon scrape/search` 的运行模型显著不同：

- `amazon scrape/search`
  - 独立起浏览器
  - 不依赖用户本地登录态
  - 面向页面结构抓取
- `amazon-rufus get`
  - 必须 attach 到用户已登录 Chrome
  - 必须捕获并复用真实 Rufus 请求上下文
  - 面向会话化流式问答

推荐将其落成新命令模块 `amazon-rufus`，对应 Python 包目录 `opscli/amazon_rufus/`，以及新 Skill `ops-amazon-rufus`。

### 2. 运行时不能依赖宿主 Chrome MCP

用户要求里提到了“agent 使用 chrome mcp 连接 chrome”，但这属于宿主调试/观察能力，不应成为 `opscli` 运行时硬依赖。

结论：

- `opscli amazon-rufus get` 必须在纯本地 CLI 环境可运行
- Chrome MCP 只作为开发/排障辅助，不进入正式运行链路

### 3. 题库应走 Skill 远端升级，而不是运行时直连后端

项目铁律要求 Skill 不可直接直连业务后端，所有远端动作必须经由 `opscli` 正式入口。

结论：

- `ops-amazon-rufus` 采用“远端升级型 Skill”
- 运行时 `opscli amazon-rufus get` 只读本地 Skill 数据
- 题库通过 `opscli skills upgrade ops-amazon-rufus` 预同步，国家站点映射固定在代码中

### 4. 当前最接近的上传口径是 `asin_rufus_batch`

`runAsinRufusBatchRefetch.ts` 已经给出一套稳定的数据形状：

- `requestBody` 记录本次运行的业务上下文
- `questions[]` 记录题目列表
- `updateRecordAnswerApi()` 按 `{ question, answer }` 上传结构化答案

结论：

- `opscli` 一期不真正调用上传接口
- 但必须输出与该结构兼容的 payload，便于后续接真实 API
- 同时实现中要保留真实发请求代码，并默认注释掉

---

## 推荐方案

### 推荐方向

采用“新 CLI 模块 + 新远端升级 Skill + 本地 Chrome attach + seed request 重放”方案。

### 推荐命名

- CLI 名称：`amazon-rufus`
- Python 包目录：`amazon_rufus`
- 命令入口：`opscli amazon-rufus get <asin> <country>`
- Skill 名称：`ops-amazon-rufus`

### 推荐数据面

`ops-amazon-rufus` 本地数据目录建议至少包含：

- `data/VERSION.json`
- `data/question_templates.json`

`data/question_templates.json` 采用 `default-question-templates` 接口结构，模板与题目列表合并在同一 JSON 中：

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

### 推荐运行链路

1. 用户执行 `opscli amazon-rufus get <asin> <country> --new-chrome` 时，命令先新开 Chrome 调试窗口。
2. 自动启动命令固定为 `Start-Process chrome.exe -ArgumentList '--remote-debugging-port=9222 --user-data-dir="E:\chrome-profiles\opscli-rufus" --no-first-run --no-default-browser-check'`。
3. 用户在新开的 Chrome 窗口中登录 Amazon，或复用该 profile 中已有登录态。
4. 命令 attach 到 `http://127.0.0.1:9222`。
5. 在进入商品页前注册 `/rufus/cl/streaming` request 监听器。
6. 打开对应站点商品页。
7. 捕获第一个可用 seed request。
8. 从本地 Skill 数据读取合并后的默认题目模板。
9. 逐题重放 Rufus 请求并解析 SSE。
10. 返回答案结果，并同时构造标准上传 payload。

兼容模式：未传 `--new-chrome` 时，仍按既有逻辑直接连接 `--cdp-url` 指向的已启动 Chrome。

---

## 风险与对策

### 风险 1：页面打开后没有自动出现 seed request

原因：

- 某些站点或页面未自动触发 Rufus
- 用户未登录 Amazon
- 当前商品页未渲染 Rufus 区块

对策：

- 明确错误信息：请登录 Amazon、刷新页面、确认当前站点支持 Rufus
- 命令内部允许有限次页面刷新 / 等待策略

### 风险 2：仅靠 Playwright 高层 API 拿不到足够的请求上下文

对策：

- 第一实现优先使用 Playwright request 事件
- 若 headers / tabId / requestBody 不完整，再补 CDP 事件作为兜底

### 风险 3：不同国家站点 URL / 语言 / 文案差异

对策：

- 将国家映射固定在代码中，并按 `US` 等国家名维护最小可控映射
- 将题库通过 Skill 升级同步，不再拆分 runner config 与 `questions/<template_id>` 文件

### 风险 4：上传接口尚未定义

对策：

- 一期默认只构造 upload payload，不真正发请求
- 同时在代码中保留上传 HTTP 调用实现，并以注释方式禁用
- 输出结构与现有前端 `collect record + update answer` 口径保持一致

---

## 研究结论

这次需求的正确落地方式不是“在 Skill 里直接写一堆 Playwright 脚本”，而是：

- 在 `opscli` 中新增正式命令模块 `amazon-rufus`，对应包目录 `amazon_rufus`
- 在 `skills/templates/` 中新增远端升级 Skill `ops-amazon-rufus`
- 让 `opscli amazon-rufus get` 负责浏览器 attach、seed request 捕获、Rufus replay、答案解析与上传 payload 构造
- 让 `opscli skills upgrade ops-amazon-rufus` 负责题库远端同步，国家站点映射固定在代码中

这样才能同时满足：

- 仓库规范
- Skill 远端升级模型
- 与现有前端口径对齐
- 后续可接真实上传 API 的扩展性

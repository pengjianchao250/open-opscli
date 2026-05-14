# ops-amazon-rufus UIUX

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
- 明确依赖 `opscli amazon-rufus get`
- 明确说明 Chrome 与国家站点登录前置条件
- 明确说明 `opscli amazon-rufus init <country>` 是登录初始化命令
- 给出完整示例
- 给出常见错误排查

### Skill 文档的推荐章节

1. 功能简介
2. 前置要求
3. 核心命令
4. 典型工作流
5. 常见错误排查
6. 本地数据与升级说明

### Skill 文档的典型工作流

```bash
# 1. 安装 Skill
opscli skills install ops-amazon-rufus

# 2. 升级题库
opscli skills upgrade ops-amazon-rufus

# 3. 打开对应国家站点登录窗口
opscli amazon-rufus init US

# 4. 在新窗口中登录亚马逊
# 命令提示：请在新窗口中登录亚马逊

# 5. 登录完成后执行 Rufus 获取
opscli amazon-rufus get B0ABC12345 US --new-chrome
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

## UIUX 结论

本需求的一期 UIUX 重点不是“设计界面”，而是：

- 把复杂流程压缩成一条稳定命令
- 让前置依赖足够显式
- 让错误信息足够明确
- 让内部数据适合脚本和排障解析，最终回复适合人工阅读

只要这四点做对，`ops-amazon-rufus` 的首版体验就是合格的。

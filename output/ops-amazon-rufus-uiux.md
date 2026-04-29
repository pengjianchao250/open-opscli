# ops-amazon-rufus UIUX

## 2026-04-29 体验增量：UTF-8 与答案纯文本输出

### 体验目标

用户通过 Skill 获取 Rufus 结果时，不需要阅读完整 JSON。CLI 应在 UTF-8 环境运行，并仅把 `answers[].text` 作为最终答案输出。

### 终端运行体验

推荐 PowerShell 命令：

```powershell
$env:PYTHONUTF8 = "1"; $env:PYTHONIOENCODING = "utf-8"; uv run --extra amazon opscli amazon-rufus get B0B1MLVMY5 US --skills-dir ".agents/skills" --new-chrome
```

该写法只影响当前命令进程，符合最小侵入原则，不要求用户修改系统环境变量。

### 最终回复体验

最终回复只输出答案文本：

```text
第一题 Rufus 回答文本。

第二题 Rufus 回答文本。
```

不应展示：

1. 完整 JSON。
2. `seed_request`。
3. `upload_payload`。
4. request headers、cookie 或调试字段。

### 与 CLI JSON 的关系

CLI 的 JSON 输出仍是内部机器协议，用于稳定解析 `answers[].text`。Skill 使用者和 Agent 不应把该 JSON 直接作为最终结果回复给用户，除非用户明确要求查看原始结果或排障。

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
3. Skill 最终回复只展示答案文本，seed/request 细节仅保留在 CLI JSON 中用于排障。

### CLI 使用体验不变项

1. 命令入口不变：`opscli amazon-rufus get <asin> <country>`。
2. Chrome 前置条件不变：复用已登录 Amazon 的本地调试 Chrome。
3. 题库来源不变：`ops-amazon-rufus/data/question_templates.json`。
4. 输出主字段不变：`success`、`command`、`data`、`error`。

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
2. 用户需先登录 Amazon
3. 需先安装并升级 `ops-amazon-rufus`

### 3. 输出先给答案，再留上下文

Skill 最终回复的阅读顺序应为：

1. 第一题答案文本
2. 第二题答案文本
3. 后续题目答案文本

低层 request 细节只留在 CLI JSON 中，默认不展示给最终用户。

---

## CLI 交互规范

### 命令风格

沿用当前项目风格：

- CLI 统一 JSON 输出，Skill 最终只展示答案文本
- 成功时只输出答案文本，错误时返回稳定结构
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

### 紧凑输出

CLI 默认输出适合脚本和 Agent 解析：

```json
{
  "success": true,
  "command": "rufus get",
  "data": {
    "asin": "B0ABC12345",
    "country": "US",
    "answers": [...]
  },
  "error": null
}
```

### Skill 最终输出

Agent 解析 CLI JSON 后，只向最终用户输出：

```text
第一题答案文本。

第二题答案文本。
```

不得直接展示 `seed_request`、`upload_payload` 或完整 JSON。

### 答案项体验

CLI JSON 中每题至少保留：

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
- 明确说明 Chrome 前置条件
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

# 3. 启动 Chrome（remote debugging）
"C:/Program Files/Google/Chrome/Application/chrome.exe" --remote-debugging-port=9222

# 4. 或让命令先新开 Chrome 调试窗口
opscli amazon-rufus get B0ABC12345 US --new-chrome

# 5. 登录 Amazon 后执行
opscli amazon-rufus get B0ABC12345 US
```

---

## 数据输出体验

### 上传 payload 的解析策略

因为本期不真正上传，`upload_payload` 只作为 CLI JSON 内部字段，不作为 Skill 最终回复内容。

建议：

- CLI 默认可继续包含 `upload_payload`
- Agent 最终回复必须隐藏 `upload_payload`
- 用户明确要求排障时，才可提示其查看原始 JSON
- 若后续查看源码，应能看到注释态的上传调用代码，便于对照未来接入点

### 输出文件体验

若指定 `--output`：

- 命令行仍输出简要成功 JSON
- 详细结果写入文件
- 返回结果里附带 `output` 路径

---

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
- 让 CLI JSON 适合脚本解析，最终回复适合人工阅读

只要这四点做对，`ops-amazon-rufus` 的首版体验就是合格的。

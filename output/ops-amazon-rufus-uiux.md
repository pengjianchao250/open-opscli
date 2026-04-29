# ops-amazon-rufus UIUX

## 文档目标

本需求没有新增图形页面，本文件定义的是：

- CLI 交互体验
- Skill 使用体验
- 输出 JSON 的可读性
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

### 3. 输出先给结果，再给上下文

成功输出的阅读顺序应为：

1. 目标 ASIN / 国家
2. 逐题答案摘要
3. 详细 answer 结构
4. seed request 摘要
5. upload payload

不应一开始就把低层 request 细节堆满屏幕。

---

## CLI 交互规范

### 命令风格

沿用当前项目风格：

- 统一 JSON 输出
- 支持 `--pretty`
- 错误返回稳定结构

### 推荐帮助文案

```text
opscli amazon-rufus get <asin> <country>
  连接本地已登录 Chrome，复用 Rufus 请求上下文，按题库获取指定 ASIN 的回答
```

### 推荐参数设计

```text
opscli amazon-rufus get B0ABC12345 US --pretty
opscli amazon-rufus get B0ABC12345 DE --cdp-url http://127.0.0.1:9222
opscli amazon-rufus get B0ABC12345 US --new-chrome --pretty
opscli amazon-rufus get B0ABC12345 JP --launch-if-needed --chrome-path "C:/Program Files/Google/Chrome/Application/chrome.exe"
```

`--new-chrome` 面向最常见人工使用场景：命令先新开一个 Chrome 调试窗口，再连接该窗口。默认启动命令为：

```powershell
Start-Process chrome.exe -ArgumentList '--remote-debugging-port=9222 --user-data-dir="E:\chrome-profiles\opscli-rufus" --no-first-run --no-default-browser-check'
```

---

## 成功输出体验

### 紧凑输出

默认输出适合脚本消费：

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

### 美化输出

`--pretty` 面向人工阅读，应保证顶层字段稳定：

- `asin`
- `country`
- `page_url`
- `template_version`
- `answers`
- `upload_payload`

### 答案项体验

每题至少展示：

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
opscli amazon-rufus get B0ABC12345 US --new-chrome --pretty

# 5. 登录 Amazon 后执行
opscli amazon-rufus get B0ABC12345 US --pretty
```

---

## 数据输出体验

### 上传 payload 的展示策略

因为本期不真正上传，`upload_payload` 应作为“可选附带信息”，而不是主视觉焦点。

建议：

- 默认输出包含 `upload_payload`
- 通过 `--no-upload-payload` 可隐藏
- 在 `--pretty` 模式中放在 `answers` 之后
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
- 让输出 JSON 同时适合脚本与人工阅读

只要这四点做对，`ops-amazon-rufus` 的首版体验就是合格的。

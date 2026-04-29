# ops-amazon (CLI 参考文档)

使用 `opscli amazon` 子命令抓取 Amazon 商品页快照、搜索结果页样本和预留给 ops API 的标准 payload。

---

## 强制认证门禁

> **【强制】每次调用 `ops-amazon` 前，必须先检测是否已授权登录；禁止跳过认证检查直接开始抓取。**

- 进入本 Skill 后，第一步先执行 `opscli auth token status`
- 若命令失败，或输出中出现“未登录 / 未授权 / Token 过期 / expired / 401”等状态，必须立即调用 `ops-auth` Skill
- 若是“未登录 / 未授权 / 401”等状态，在 `ops-auth` 中执行 `opscli auth login` 完成授权登录
- 若是 JWT Token 过期，优先执行 `opscli auth token refresh`（例如 `opscli auth token refresh --all` 或 `opscli auth token refresh -s ops`）；刷新失败或仍异常时，再执行 `opscli auth login`
- 登录或刷新后重新执行 `opscli auth token status`
- 只有认证状态确认正常后，才允许继续执行 `opscli amazon scrape`、`payload`、`search`、`schema`、`history`
- 即使当前任务看起来只做本地抓取样本，也必须先经过这一步，保证后续与 ops 体系的账号上下文一致

**标准前置流程：**

```bash
# 1. 先检查是否已登录
opscli auth token status

# 2. 如 JWT Token 已过期，先刷新
opscli auth token refresh --all

# 3. 如未登录、未授权、刷新失败或状态仍异常，立即调用 ops-auth Skill 处理
opscli auth login

# 4. 登录后再次确认
opscli auth token status
```

---

## 使用原则

- 本 Skill 只负责指导 AI 使用 `opscli amazon` 正式命令完成抓取、取样和字段确认
- 抓取动作统一通过 `opscli amazon` 执行，禁止在 Skill 内直接调用 Amazon HTTP 接口
- 当前阶段以“先抓数据、API 预留”为主，不要求直接提交到 ops API
- 若目标是后端设计，优先使用 `scrape`、`payload`、`search`、`schema` 四个命令取样
- 搜索结果页的 `review_count_value` 应视为近似值；商品页 `scrape` 的评论数更适合作为精确快照值
- 所有 Amazon 工作流在执行前都必须先完成一次 `ops-auth` 登录检测

---

## 前置要求

首次使用前请确认本地已安装 Amazon 抓取依赖：

```bash
pip install opscli
playwright install chromium
```

如果是源码开发环境：

```bash
pip install -e .
playwright install chromium
```

---

## 何时使用

以下场景建议使用 `ops-amazon`：

- 需要抓取某个 Amazon 商品的价格、评分、评论数、配送位置
- 需要抓取关键词搜索结果做竞品样本分析
- 需要输出未来提交给 ops API 的标准 payload
- 需要拿真实样本给后端做字段设计、表结构设计、接口设计
- 需要查看某个商品的本地历史抓取记录

---

## 核心命令

### `opscli amazon scrape`

抓取单个商品页。

```bash
opscli amazon scrape --asin B09LCJPZ1P
opscli amazon scrape --asin B09LCJPZ1P --zip-code 10001 --include-raw --pretty
opscli amazon scrape --asin B09LCJPZ1P --no-save-history
```

适用场景：

- 获取商品页精确快照
- 对比价格、评分、评论数变化
- 给后端确认商品快照字段结构

---

### `opscli amazon payload`

抓取商品页，并输出预留给 ops API 的标准请求体。

```bash
opscli amazon payload --asin B09LCJPZ1P
opscli amazon payload --asin B09LCJPZ1P --zip-code 10001 --pretty
```

适用场景：

- 设计商品快照提交接口
- 给后端确认最终 payload 契约

---

### `opscli amazon search`

抓取关键词搜索结果页。

```bash
opscli amazon search --keyword "usb c cable"
opscli amazon search --keyword "usb c cable" --zip-code 10001 --limit 10 --pretty
```

适用场景：

- 采集竞品结果集
- 设计搜索批次表和搜索结果表
- 验证关键词结果样本

---

### `opscli amazon schema`

输出当前字段契约。

```bash
opscli amazon schema --pretty
```

适用场景：

- 对照字段类型
- 做 API 请求体验收
- 做数据库字段映射

---

### `opscli amazon history`

读取某个商品的本地历史抓取记录。

```bash
opscli amazon history --asin B09LCJPZ1P --pretty
```

默认历史路径：

```text
~/.config/opscli/amazon/history/<ASIN>.jsonl
```

---

## 推荐工作流

### 场景一：做商品快照字段设计

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

opscli amazon scrape --asin B09LCJPZ1P --include-raw --pretty
opscli amazon payload --asin B09LCJPZ1P --pretty
opscli amazon schema --pretty
```

### 场景二：做搜索结果表设计

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

opscli amazon search --keyword "usb c cable" --limit 10 --pretty
opscli amazon schema --pretty
```

### 场景三：查看历史变化

```bash
# 0. 先检查认证状态；如未登录则调用 ops-auth 完成登录
opscli auth token status

opscli amazon scrape --asin B09LCJPZ1P --pretty
opscli amazon history --asin B09LCJPZ1P --pretty
```

---

## 字段口径提醒

- 商品页 `review_count_value`：优先视为精确值
- 搜索页 `review_count_value`：通常是页面展示缩写解析值，适合做近似分析
- `location`：当前已做零宽字符清洗
- `raw`：建议在字段调试和后端设计阶段保留输出

---

## 当前边界

本 Skill 一期不负责：

- 直接提交到 ops API
- 本地定时调度
- 多商品批量任务编排

这些能力后续应继续收口到 `opscli amazon` 模块本身，而不是在 Skill 侧分叉实现。

---

## 认证异常处理

| 场景 | 处理方式 |
|------|---------|
| 未登录 / 未授权 | 立即调用 `ops-auth` Skill，并执行 `opscli auth login` |
| Token 过期 | 先走 `ops-auth`，优先执行 `opscli auth token refresh --all`；刷新失败或仍异常时再执行 `opscli auth login` |
| 状态不确定 | 执行 `opscli auth token status`，仍异常则在 `ops-auth` 中执行 `opscli auth doctor` |

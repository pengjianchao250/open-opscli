---
name: ops-amazon
description: 使用 opscli amazon 命令抓取 Amazon 商品页和搜索结果，并输出用于 ops API 与数据表设计的标准样本
version: v0.1.0
---

# ops-amazon

使用 `opscli amazon` 子命令抓取 Amazon 商品页快照、搜索结果页样本和预留给 ops API 的标准 payload。

---

## 使用原则

- 本 Skill 只负责指导 AI 使用 `opscli amazon` 正式命令完成抓取、取样和字段确认
- 抓取动作统一通过 `opscli amazon` 执行，禁止在 Skill 内直接调用 Amazon HTTP 接口
- 当前阶段以“先抓数据、API 预留”为主，不要求直接提交到 ops API
- 若目标是后端设计，优先使用 `scrape`、`payload`、`search`、`schema` 四个命令取样
- 搜索结果页的 `review_count_value` 应视为近似值；商品页 `scrape` 的评论数更适合作为精确快照值

---

## 前置要求

首次使用前请确认本地已安装 Amazon 抓取依赖：

```bash
pip install "opscli[amazon]"
playwright install chromium
```

如果是源码开发环境：

```bash
pip install -e ".[amazon]"
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
opscli amazon scrape --asin B09LCJPZ1P --include-raw --pretty
opscli amazon payload --asin B09LCJPZ1P --pretty
opscli amazon schema --pretty
```

### 场景二：做搜索结果表设计

```bash
opscli amazon search --keyword "usb c cable" --limit 10 --pretty
opscli amazon schema --pretty
```

### 场景三：查看历史变化

```bash
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

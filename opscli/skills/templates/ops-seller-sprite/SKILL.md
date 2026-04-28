---
name: ops-seller-sprite
description: 使用 opscli seller-sprite 命令采集卖家精灵关键词挖掘、高频词、页面截图、Markdown 和接口证据
version: v0.1.0
---

# ops-seller-sprite

使用 `opscli seller-sprite` 子命令采集卖家精灵数据。所有采集动作必须通过正式 CLI 命令执行，禁止在 Skill 内直接请求卖家精灵接口。

---

## 使用原则

- 用户提供关键词时，优先使用 `collect`
- 用户提供 ASIN 或产品链接做流量词反查时，使用 `keyword-reverse`
- 只调试高频词时，使用 `frequency`
- 只调试关键词列表时，使用 `keyword-mining`
- 需要留存页面证据时，使用默认开启的归档能力
- 不从卖家精灵 AI 报告复用成品分析结论

---

## 核心命令

### 保存命名账号

```bash
opscli seller-sprite account save --name default --username <USERNAME>
```

适用场景：

- 需要后续采集时自动登录
- 密码通过终端隐藏输入，不写入命令参数
- 密码保存到系统凭据管理器，账号元数据保存到本机 opscli 配置目录

### 建立登录态

```bash
opscli seller-sprite login
```

适用场景：

- 首次采集前手动登录卖家精灵
- 页面触发验证码时由用户在浏览器中处理
- 登录态保存在本机 opscli 卖家精灵浏览器 profile

### 检查登录态

```bash
opscli seller-sprite login-status --output-dir ./seller_sprite_runs --pretty
```

适用场景：

- 采集前确认当前 profile 是否已登录
- 保存登录状态页面截图、HTML 和 Markdown 留证

### 完整采集

```bash
opscli seller-sprite collect --keyword bed --account default --site us --period 30d --limit 50 --frequency-phrase-count 1 --trend-limit 0 --output-dir ./seller_sprite_runs --pretty
```

适用场景：

- 用户提供关键词，需要生成卖家精灵采集材料
- 需要同时采集高频词、关键词挖掘和归档证据
- 当前 profile 未登录时，使用命名账号在同一浏览器窗口中登录后继续采集
- 需要采集关键词历史走势弹窗时，显式传 `--trend-limit N`

### 高频词

```bash
opscli seller-sprite frequency --keyword bed --site us --period 30d --frequency-phrase-count 1 --output-dir ./seller_sprite_runs --pretty
```

适用场景：

- 只需要查看市场高频表达
- 只调试高频词接口响应
- 需要切换一个词、两个词或更多词组时，设置 `--frequency-phrase-count`

### 关键词挖掘

```bash
opscli seller-sprite keyword-mining --keyword bed --site us --period 30d --limit 50 --trend-limit 0 --output-dir ./seller_sprite_runs --pretty
```

适用场景：

- 只需要关键词表格、趋势、PPC、ABA、竞品 ASIN 等材料
- 用户明确要求控制关键词采集条数
- 需要关键词历史走势弹窗截图和接口证据时，传 `--trend-limit N`

### 关键词反查

```bash
opscli seller-sprite keyword-reverse --asin B07Z82895W --account default --site us --period 30d --limit 50 --trend-limit 0 --output-dir ./seller_sprite_runs --pretty
```

适用场景：

- 用户提供 ASIN 或产品链接，需要反查该产品的流量词
- 采集产品基础信息、变体 ASIN、搜索流量词占比、高频词和关键词反查主表
- 高频词复用 `frequency_terms` 输出结构
- 需要关键词历史走势弹窗截图和接口证据时，传 `--trend-limit N`

### 历史走势弹窗

```bash
opscli seller-sprite collect --keyword bed --account default --trend-limit 5 --trend-tabs all --output-dir ./seller_sprite_runs --pretty
```

适用场景：

- 点击关键词列表前 N 个关键词的历史走势 icon
- 采集搜索趋势、Google Trends、ABA集中度、PPC竞价、市场分析 5 个子 tab
- 每个子 tab 保存截图、HTML、Markdown 和切换期间捕获到的卖家精灵 JSON 响应

### 页面归档

```bash
opscli seller-sprite archive --url https://www.sellersprite.com/v3/keyword-miner --output-dir ./seller_sprite_runs --pretty
```

适用场景：

- 调试页面结构
- 保存截图、HTML 和 Markdown 留证

### 字段契约

```bash
opscli seller-sprite schema --pretty
```

适用场景：

- 查看当前标准化字段
- 和后续分析 Skill 对齐输入结构

---

## 输出读取

不指定 `--output-dir` 时，采集产物默认写入当前命令执行目录下的 `seller_sprite_runs/seller-sprite-<run_id>`。指定 `--output-dir` 时，产物写入 `<output-dir>/seller-sprite-<run_id>`。命令返回的 `data.archive_manifest.root_dir` 是本次采集目录。Agent 后续应优先读取：

- `result.json`
- `manifest.json`
- 高频词、关键词挖掘或关键词反查接口响应 JSON
- 页面 Markdown
- 页面截图路径

---

## 当前边界

- 不自动根据 ASIN 推导关键词
- 不自动识别验证码
- 不自动生成完整 Listing 上线文案
- 不自动刊登或替换 Listing

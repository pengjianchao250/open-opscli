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

### 查看命名账号

```bash
opscli seller-sprite account list --pretty
```

适用场景：

- 采集前确认本机有哪些可用账号别名
- 排查 `--account <NAME>` 指向的账号是否存在
- 只返回账号别名和用户名，不返回密码

### 删除命名账号

```bash
opscli seller-sprite account delete --name default --pretty
```

适用场景：

- 账号已失效或需要重新保存
- 清理本机保存的卖家精灵账号元数据和系统凭据

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

`--trend-tabs` 可选值：

| 值 | 含义 |
| --- | --- |
| `all` | 采集全部 5 个 tab，默认值 |
| `search` | 搜索趋势 |
| `google` | Google Trends |
| `aba` | ABA 集中度 |
| `ppc` | PPC 竞价 |
| `market` | 市场分析 |

可用英文逗号组合多个 tab，例如：

```bash
opscli seller-sprite keyword-mining --keyword bed --trend-limit 3 --trend-tabs search,ppc --output-dir ./seller_sprite_runs --pretty
```

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

## 参数边界

| 参数 | 适用命令 | 默认值 | 边界 |
| --- | --- | --- | --- |
| `--asin` | `collect`、`keyword-reverse` | `null` | 支持 10 位 ASIN 或包含 ASIN 的 Amazon 商品链接；`keyword-reverse` 必填 |
| `--keyword` | `collect`、`frequency`、`keyword-mining` | 无 | 必填，必须由用户显式提供 |
| `--site` | 采集命令 | `us` | 站点代码；当前内置 `us`、`jp`、`uk`、`de`、`fr`、`it`、`es`、`ca`、`mx`、`in`、`br`、`au`、`ae` |
| `--period` | 采集命令 | `30d` | 传卖家精灵支持的时间窗口，例如 `30d` 或 `2026-03` |
| `--limit` | `collect`、`keyword-mining`、`keyword-reverse` | `50` | `1-200` |
| `--frequency-phrase-count` | `collect`、`frequency` | `1` | `1-10` |
| `--trend-limit` | `collect`、`keyword-mining`、`keyword-reverse` | `0` | `0-50`，且不能超过 `--limit` |
| `--trend-tabs` | `collect`、`keyword-mining`、`keyword-reverse` | `all` | `all` 或 `search,google,aba,ppc,market` 的逗号组合 |
| `--archive/--no-archive` | 采集命令 | `--archive` | 是否归档截图、HTML、Markdown 和接口响应 |
| `--output-dir` | 采集与归档命令 | 当前目录下 `seller_sprite_runs` | 可传相对或绝对路径 |
| `--account` | `collect`、`keyword-reverse` | `null` | 指向 `account save` 保存的账号别名 |

---

## 输出读取

不指定 `--output-dir` 时，采集产物默认写入当前命令执行目录下的 `seller_sprite_runs/seller-sprite-<run_id>`。指定 `--output-dir` 时，产物写入 `<output-dir>/seller-sprite-<run_id>`。命令返回的 `data.archive_manifest.root_dir` 是本次采集目录。Agent 后续应优先读取：

- `result.json`
- `manifest.json`
- 高频词、关键词挖掘或关键词反查接口响应 JSON
- 页面 Markdown
- 页面截图路径

### `result.json` 关键字段

| 字段 | 含义 |
| --- | --- |
| `asin` | 本次关联的 ASIN，`keyword-reverse` 必有 |
| `keyword` | 本次显式关键词，`collect`、`frequency`、`keyword-mining` 必有 |
| `site` / `period` / `limit` | 本次采集站点、时间窗口和条数 |
| `frequency_terms` | 高频词结果；反查命令中复用该结构保存反查高频词 |
| `keyword_items` | 关键词挖掘标准化结果 |
| `reverse_keyword_items` | ASIN 流量词反查标准化结果 |
| `keyword_trends` | 关键词列表接口中的趋势数据 |
| `trend_details` | 历史走势弹窗的 tab 截图、HTML、Markdown 和响应索引 |
| `competitor_asins` | 关键词挖掘结果中的关联竞品 ASIN |
| `product_info` | 关键词反查采集到的产品基础信息 |
| `variation_asins` | 关键词反查采集到的变体 ASIN |
| `reverse_stats` | 关键词反查统计信息 |
| `market_summary` | 给 Agent 快速读取的市场摘要 |
| `archive_manifest` | 本次归档索引、验证码标记、缺失区块和错误列表 |

### `manifest.json` 关键字段

| 字段 | 含义 | 处理方式 |
| --- | --- | --- |
| `root_dir` | 本次采集目录 | 后续读取文件时以此为根目录 |
| `files` | 截图、HTML、Markdown、接口 JSON 的文件索引 | 优先读取接口 JSON，其次读取 Markdown，截图作为证据 |
| `captcha_required` | 是否检测到验证码 | 为 `true` 时停止分析，让用户先处理登录或验证码 |
| `missing_sections` | 本次未采到的区块 | 汇报缺失项，不基于缺失数据下结论 |
| `errors` | 采集过程中记录的错误 | 汇报错误信息并停止依赖对应区块 |

### 错误输出

命令失败时返回：

```json
{
  "success": false,
  "command": "seller-sprite <command>",
  "data": null,
  "error": {
    "code": "SELLER_SPRITE_ERROR",
    "message": "..."
  }
}
```

Agent 必须先检查 `success`。如果 `success=false`，不要继续读取旧目录或编造结果，应直接向用户汇报 `error.message`。

---

## 和分析 Skill 的衔接

`ops-seller-sprite` 只负责采集和证据归档。用户要求 Listing 表达与一致性优化分析时，应在采集完成后把 `result.json`、`manifest.json`、页面 Markdown 和截图路径交给 `ops-amazon-listing-analysis` 的输出约束使用。

分析输出仍只能覆盖：

- 问题定位
- 优化方向
- 修改示例

不能因为采集到了卖家精灵数据就输出完整可上线 Listing 文案。

---

## 当前边界

- 不自动根据 ASIN 推导关键词
- 不自动识别验证码
- 不绕过 `opscli seller-sprite` 直接请求卖家精灵接口
- 不从卖家精灵 AI 报告复用成品分析结论
- 不自动生成完整 Listing 上线文案
- 不自动刊登或替换 Listing

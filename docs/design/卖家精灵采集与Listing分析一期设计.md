# 卖家精灵采集与 Listing 分析一期设计

## 背景

一期目标是建设 Amazon 单平台下的 AI 产品优化分析 MVP。系统在 OpenClaw 中跑通官方 Skill，支持种子运营围绕产品问题和优化分析稳定试用，并基于分析结果生成 Listing 表达与一致性优化建议。

卖家精灵在本方案中不是最终业务产品，而是数据源和证据采集通道。卖家精灵现有 Listing 深度分析报告仅作为输出结构参考，不作为采集数据来源。

## 一期目标

围绕用户提供的 Amazon ASIN 和显式关键词，采集卖家精灵关键词挖掘、高频词、关键词列表及相关图表数据，并保留接口 JSON、截图、HTML、Markdown 和标准化结果文件。AI 基于这些材料输出 Listing 表达与一致性优化建议。

一期输出范围：

- 问题定位
- 优化方向
- 修改示例

一期不输出：

- 完整可直接上线文案
- 自动替换现有 Listing
- 多语言重写
- 自动刊登操作

## 总体分层

本需求拆成两层能力：

1. `opscli/seller_sprite`：正式 CLI 采集模块，负责浏览器自动化、接口拦截、归档和标准化结果输出。
2. `opscli/skills/templates/` 下的 Skill：负责指导 Agent 何时调用 CLI、如何读取采集结果、如何约束分析输出。

建议新增两个 Skill：

- `ops-seller-sprite`：底层数据采集 Skill，指导调用 `opscli seller-sprite ...`。
- `ops-amazon-listing-analysis`：一期业务场景 Skill，指导围绕 ASIN 做 Listing 表达与一致性优化分析。

## 技术选型

浏览器自动化统一使用 Playwright，保持与现有 `opscli/amazon` 模块一致。不引入 DrissionPage、Selenium 或新的爬虫框架。

HTML 转 Markdown 使用确定性转换工具，第一版建议使用 `html2text`。Markdown 用于分析上下文留档，不作为图表数据主来源。

验证码能力先预留 `captcha_provider` 边界，后续优先接超级鹰图形验证码接口。一期可先实现验证码检测、截图留痕和中断提示。

## CLI 模块位置

新增模块位置：

```text
opscli/seller_sprite/
├── __init__.py
├── cli.py
├── domain/
│   ├── __init__.py
│   ├── exceptions.py
│   └── models.py
├── scraping/
│   ├── __init__.py
│   ├── scraper.py
│   ├── api_recorder.py
│   ├── archiver.py
│   └── captcha.py
└── services/
    ├── __init__.py
    └── manager.py
```

顶级 CLI 注册位置：

```text
opscli/cli.py
```

新增注册：

```python
from opscli.seller_sprite.cli import app as seller_sprite_app
app.add_typer(seller_sprite_app, name="seller-sprite")
```

## 一期命令

### 保存命名账号

```bash
opscli seller-sprite account save --name default --username <USERNAME>
```

密码通过终端隐藏输入，不出现在命令参数中。密码写入系统凭据管理器，账号名和用户名保存在 opscli 配置目录。

### 建立登录态

```bash
opscli seller-sprite login
```

打开卖家精灵登录页，用户在浏览器中手动登录并处理验证码。登录态保存在 `~/.config/opscli/seller_sprite/browser_profile`。

### 检查登录态

```bash
opscli seller-sprite login-status --output-dir ./seller_sprite_runs --pretty
```

打开关键词挖掘页并归档截图、HTML、Markdown，返回当前 profile 是否已登录。

### 关键词采集主入口

```bash
opscli seller-sprite collect --keyword bed --account default --site us --period 30d --limit 50 --output-dir ./seller_sprite_runs --pretty
```

说明：

- `--asin` 是可选业务分析对象，用于关联后续 Listing 分析。
- `--keyword` 一期由用户显式传入，不从卖家精灵报告推导。
- `--site` 默认 `us`。
- `--period` 默认 `30d`。
- `--limit` 默认 `50`，用于控制关键词列表采集条数。
- `--archive` 默认开启。
- `--output-dir` 可指定输出目录；不传时默认当前命令执行目录下的 `seller_sprite_runs`。
- `--account` 可指定命名账号；当前 profile 未登录时，在同一浏览器窗口中登录后继续采集。

### 高频词采集

```bash
opscli seller-sprite frequency --keyword bed --site us --period 30d --output-dir ./seller_sprite_runs --pretty
```

采集字段来源参考 `frequency-new.json`：

```text
keyword
frequency
percentage
```

### 关键词挖掘采集

```bash
opscli seller-sprite keyword-mining --keyword bed --site us --period 30d --limit 50 --output-dir ./seller_sprite_runs --pretty
```

采集字段来源参考 `keyword-miner.json`：

```text
keyword
keywordCn
keywordJp
departments
trends
searches
purchases
purchaseRate
impressions
clicks
cvsShareRate
products
adProducts
supplyDemandRatio
avgPrice
avgReviews
avgRating
bidMin
bidMax
bid
phrasePpc
exactPpc
broadPpc
titleDensity
spr
relevancy
absoluteRelevancy
amazonChoice
monopolyAsinDtos
monopolyClickRate
gkDatas
```

### 归档命令

```bash
opscli seller-sprite archive --url <url> --output-dir ./seller_sprite_runs --pretty
```

用于调试阶段单独保存页面截图、HTML、Markdown 和接口响应。

### 字段契约

```bash
opscli seller-sprite schema --pretty
```

用于输出当前标准化结果结构，方便 Skill 和后续接口设计对齐。

## 数据采集策略

第一优先级是 Playwright 拦截接口响应。页面 DOM 和 Markdown 只作为辅助上下文，截图作为证据留存。

当前已确认两类接口样例：

- `frequency-new.json`：高频词结果。
- `keyword-miner.json`：关键词挖掘分页结果，默认一页 50 条。

后续调试时再根据真实请求 URL、method、query/body 参数固化接口调用方式。固化前由 Playwright 页面操作触发接口，并记录匹配到的响应。

## 输出目录

参考现有 `amazon` 模块使用 `CONFIG_DIR` 的方式，卖家精灵采集结果统一落到：

```text
~/.config/opscli/seller_sprite/runs/<run_id>/
```

目录结构：

```text
runs/<run_id>/
├── manifest.json
├── result.json
├── frequency/
│   ├── response.json
│   ├── page.html
│   ├── page.md
│   └── screenshot.png
├── keyword_mining/
│   ├── response.json
│   ├── page.html
│   ├── page.md
│   └── screenshot.png
└── charts/
    ├── search_trend.png
    ├── google_trends.png
    ├── aba_concentration.png
    ├── ppc_bid.png
    └── market_analysis.png
```

`manifest.json` 记录本次采集的文件索引、输入参数、采集状态、缺失数据和异常信息。`result.json` 保存给 Agent 直接消费的标准化数据。

## 标准化结果结构

```json
{
  "asin": "B00MA2T9BC",
  "keyword": "bed",
  "site": "us",
  "period": "30d",
  "limit": 50,
  "run_id": "20260427-xxxx",
  "frequency_terms": [],
  "keyword_items": [],
  "keyword_trends": [],
  "competitor_asins": [],
  "market_summary": {},
  "archive_manifest": {}
}
```

## Skill 使用边界

`ops-seller-sprite` 只指导 Agent 调用采集命令，不直接请求卖家精灵接口，不直接实现爬虫。

`ops-amazon-listing-analysis` 读取采集结果后，只输出：

- 问题定位
- 优化方向
- 修改示例

该 Skill 必须明确禁止：

- 生成完整可上线文案
- 自动替换 Listing
- 自动刊登
- 多语言重写

## 登录态与验证码

卖家精灵登录态使用 Playwright 持久化 profile 复用，避免每次运行重新登录。

验证码一期处理策略：

1. 检测验证码页面或图形验证码元素。
2. 保存验证码截图和当前页面截图。
3. 在结果中标记 `captcha_required=true`。
4. 预留 `captcha_provider`，后续接入超级鹰。

## 一期不做

- 不从卖家精灵 AI 报告接口复用成品报告。
- 不自动根据 ASIN 推导关键词。
- 不实现定时调度。
- 不实现自动验证码识别。
- 不提交数据到 ops API。
- 不做完整 Listing 文案生成。

## 自检结论

本设计以 ASIN 作为业务分析对象，以用户显式关键词作为卖家精灵采集入口，以 Playwright 作为统一自动化框架，以接口 JSON 为主数据来源，以截图、HTML、Markdown 作为证据归档。采集能力和分析 Skill 分层清晰，一期输出范围与“不自动替换、不完整上线文案”的约束一致。

# `opscli asin-data collect` 使用说明

本文说明如何通过正式入口 `opscli asin-data collect` 采集 ASIN 数据。

该命令会按 ASIN 生成统一数据包，覆盖：

- 卖家精灵关键词反查
- 卖家精灵关键词挖掘
- 卖家精灵 AI 全景分析
- Amazon 商品页抓取
- Amazon Alexa 问答/Listing 优化建议
- BI 即时综合销售数据
- 爬虫 Listing 快照数据
- 前端可直接读取的 `frontend-data.json`，以及本地预览用 `frontend-data.html`

## 1. 前置条件

正式执行前先确认登录态：

```bash
opscli auth token status
```

如果未登录或 token 过期，先走认证流程：

```bash
opscli auth login
```

## 2. 输入方式

命令支持两种输入方式，二选一。

### 2.1 批量文件

推荐 CSV：

```csv
asin,site,keyword,owner,notes
B0XXXXXXX,US,solar outdoor lights,张三,测试
B0YYYYYYY,US,"flashlight; rechargeable flashlight",李四,测试
```

支持格式：

- `.csv`
- `.xlsx`
- `.json`
- `.jsonl`

必填列只有 `asin`。`site` 默认 `US`。`keyword` 可选，也可以使用 `keywords` 或 `关键词` 作为列名。一个单元格里多个关键词可用英文逗号、中文逗号、分号、竖线或换行分隔。

### 2.2 单个 ASIN

当用户只给一个 ASIN 时，用 `--asin`：

```bash
opscli asin-data collect \
  --asin B0BY8Y5766 \
  --site US \
  --keyword "bed frame" \
  --pretty
```

`--keyword` 可以重复传入：

```bash
opscli asin-data collect \
  --asin B0BY8Y5766 \
  --site US \
  --keyword "bed frame" \
  --keyword "storage bed" \
  --pretty
```

## 3. 先 Dry Run

正式取数前，建议先 dry-run，只生成计划和输出骨架，不调用远端数据源：

```bash
opscli asin-data collect \
  --input ./asins.csv \
  --asin-column asin \
  --keyword-column keyword \
  --site-column site \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31 \
  --dry-run \
  --pretty
```

重点检查输出目录中的：

| 文件 | 用途 |
| --- | --- |
| `manifest.json` | 本次参数、输出路径、统计摘要 |
| `commands.jsonl` | 将执行的数据源计划 |
| `asin-data.jsonl` | 每个 ASIN 的计划状态 |
| `frontend-data.json` | 前端结构骨架 |

如果计划无误，再去掉 `--dry-run` 正式执行。

## 4. 正式执行

批量执行：

```bash
opscli asin-data collect \
  --input ./asins.csv \
  --asin-column asin \
  --keyword-column keyword \
  --site-column site \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31 \
  --pretty
```

单个 ASIN 执行：

```bash
opscli asin-data collect \
  --asin B0BY8Y5766 \
  --site US \
  --keyword "bed frame" \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31 \
  --pretty
```

默认会上传 UTF-8 BOM 格式的 `ASIN-asin-data-report.txt`，成功时返回 `data.upload.url`；`data.aliyun_url` 优先使用 `/dataMetrics/v1/asin-report-files` 返回的报告地址。如果只要本地文件：

```bash
opscli asin-data collect \
  --input ./asins.csv \
  --no-upload \
  --pretty
```

如果只想输出上传后的 URL：

```bash
opscli asin-data collect \
  --asin B0BY8Y5766 \
  --site US \
  --keyword "bed frame" \
  --url-only
```

如果每日任务需要在采集完成后把报告文件记录保存到后端 `ops_asin_data_report_files`，使用：

```bash
opscli asin-data collect \
  --asin B0FDG9NFQM \
  --site US \
  --no-fetch-report-files \
  --submit-report-files \
  --report-date 2026-06-10 \
  --pretty
```

## 5. 常用跳过参数

只查 BI 和爬虫，不跑外部采集：

```bash
opscli asin-data collect \
  --input ./asins.csv \
  --skip-seller-sprite \
  --skip-amazon \
  --skip-rufus \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31 \
  --pretty
```

只查 BI 销售数据：

```bash
opscli asin-data collect \
  --input ./asins.csv \
  --skip-seller-sprite \
  --skip-amazon \
  --skip-rufus \
  --skip-crawler-query \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31 \
  --pretty
```

只查爬虫 Listing 数据：

```bash
opscli asin-data collect \
  --input ./asins.csv \
  --skip-seller-sprite \
  --skip-amazon \
  --skip-rufus \
  --skip-sales-query \
  --crawler-table-id 43 \
  --pretty
```

只跑卖家精灵：

```bash
opscli asin-data collect \
  --input ./asins.csv \
  --skip-query \
  --skip-amazon \
  --skip-rufus \
  --pretty
```

跳过 Alexa：

```bash
opscli asin-data collect \
  --input ./asins.csv \
  --skip-rufus \
  --pretty
```

## 6. 关键参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--input` | 空 | CSV/XLSX/JSON/JSONL 输入文件；与 `--asin` 二选一 |
| `--asin` | 空 | 单个 ASIN；与 `--input` 二选一 |
| `--keyword` | 空 | 单个 ASIN 的关键词，可重复传入 |
| `--asin-column` | `asin` | 输入文件中的 ASIN 列 |
| `--keyword-column` | `keyword` | 输入文件中的关键词列 |
| `--site-column` | `site` | 输入文件中的站点列 |
| `--site` | `US` | 默认站点 |
| `--output-dir` | `output/asin-data` | 输出根目录 |
| `--run-id` | 自动生成 | 指定本次运行 ID |
| `--dry-run` | `false` | 只生成计划，不执行远端取数 |
| `--sales-start` | 空 | 销售数据开始日期 |
| `--sales-end` | 空 | 销售数据结束日期 |
| `--query-chunk-size` | `100` | BI/爬虫每批 ASIN 数 |
| `--seller-sprite-period` | `30d` | 卖家精灵数据周期 |
| `--keyword-source` | `reverse_top` | 无输入关键词时是否从关键词反查结果派生关键词；可用 `input_only`、`reverse_top`、`skip` |
| `--max-miner-keywords` | `1` | 每个 ASIN 最多用于 keyword-miner 的关键词数 |
| `--listing-analysis-station` | `GLOBAL` | 卖家精灵 AI 全景分析站点参数 |
| `--rufus-question` | 默认 6 题 | Alexa 临时问题，可重复传入，支持 `{{asin}}` 占位符 |
| `--rufus-country` | 空 | Alexa 国家站点，默认跟随每行 `site` |
| `--rufus-timeout-seconds` | `180` | Alexa 单题超时秒数 |
| `--skip-rufus-login-recovery` | `false` | Alexa 登录态缺失时不自动恢复 |
| `--sales-table-id` | 空 | BI 销售数据 table_id；为空时使用默认销售数据集 |
| `--sales-dataset-alias` | `ds_d35ac6f3910c` | BI 销售数据集 alias |
| `--sales-field-mode` | `full` | 销售字段模式；必要时用 `compatible` |
| `--crawler-table-id` | 空 | 爬虫 Listing table_id；已验证 `custom_crawler_amazon_details` 为 `43` |
| `--crawler-dataset-alias` | `ds_icw50TLOFu4F` | 爬虫 Listing 数据集 alias |
| `--crawler-field-mode` | `full` | 爬虫字段模式；必要时用 `compatible` |
| `--fetch-report-files/--no-fetch-report-files` | `--fetch-report-files` | 是否先从 `/dataMetrics/v1/asin-report-files` 获取最新报告地址；无 URL 时直接报错 |
| `--upload/--no-upload` | `--upload` | 是否上传 UTF-8 BOM 的 `ASIN-asin-data-report.txt` |
| `--submit-report-files/--no-submit-report-files` | `--no-submit-report-files` | 采集完成后是否 POST 保存到 `/dataMetrics/v1/asin-report-files` |
| `--report-date` | 空 | 保存报告文件记录时使用的报告日期，默认当天 |
| `--report-type` | `asin_data_merged_report_txt` | 保存报告文件记录时使用的报告类型 |
| `--report-source` | `asin_data_collect` | 保存报告文件记录时使用的来源 |
| `--register-endpoint` | 空 | 保存接口地址，默认 `/dataMetrics/v1/asin-report-files`，也可传完整 URL |
| `--include-report-content/--no-include-report-content` | `--no-include-report-content` | 保存接口 payload 是否包含报告 txt 内容和明细 JSON |
| `--url-only` | `false` | 只输出报告地址；单 ASIN 使用报告文件接口 URL |
| `--pretty` | `false` | 格式化 JSON 输出 |

常见跳过参数：

| 参数 | 说明 |
| --- | --- |
| `--skip-seller-sprite` | 跳过全部卖家精灵数据 |
| `--skip-keyword-miner` | 只跳过关键词挖掘 |
| `--skip-listing-analysis` | 只跳过卖家精灵 AI 全景分析 |
| `--skip-amazon` | 跳过 Amazon 页面抓取 |
| `--skip-query` | 跳过全部 BI/query 数据 |
| `--skip-sales-query` | 跳过 BI 销售数据 |
| `--skip-crawler-query` | 跳过爬虫 Listing 数据 |
| `--skip-rufus` | 跳过 Alexa 问答 |

## 7. 输出文件

默认输出目录：

```text
output/asin-data/<run_id>/
```

主要文件：

| 文件 | 说明 |
| --- | --- |
| `frontend-data.json` | 前端优先读取的结构化数据包 |
| `frontend-data.html` | 本地 HTML 预览文件，不上传 |
| `frontend-data.md` | 本地保留的 Markdown 交接文件 |
| `<ASIN>-asin-data-report.txt` | 单 ASIN 取数报告；UTF-8 BOM，上传文件名保持该格式 |
| `asin-data.jsonl` | 每个 ASIN 一行的完整统一结果 |
| `asin-data-summary.json` | 汇总统计 |
| `manifest.json` | 本次运行参数、文件路径、摘要 |
| `commands.jsonl` | 每个数据源的执行计划和状态 |
| `errors.jsonl` | 失败来源和错误信息；无错误时为空文件 |
| `query/*.json` | query metadata、payload、result |
| `asins/<ASIN>/*.json` | 单个 ASIN 的原始来源结果 |

命令 JSON 返回中的关键字段：

| 字段 | 说明 |
| --- | --- |
| `success` | 命令包装层是否成功 |
| `data.output_dir` | 输出目录 |
| `data.summary` | 简要统计 |
| `data.manifest` | 完整 manifest |
| `data.upload` | 上传后的报告 txt 结果 |
| `data.report_file_url` | `/dataMetrics/v1/asin-report-files` 返回的报告 URL |
| `data.aliyun_url` | 优先为 `data.report_file_url`，否则为上传报告 txt URL |

## 8. 前端数据结构

前端优先读取：

```text
output/asin-data/<run_id>/frontend-data.json
```

每个 ASIN 固定包含四段：

1. `基础数据`
2. `卖家精灵关键词数据`
3. `卖家精灵AI全景分析数据`
4. `Alexa优化建议数据`

详细字段说明见：

```text
docs/guide/ASIN取数前端数据结构.md
```

## 9. 注意事项

- `--input` 和 `--asin` 必须二选一，不能同时传，也不能都不传。
- ASIN 必须是 10 位字母或数字。
- 大批量执行前先用 1-3 个 ASIN 做 dry-run 和小样本正式执行。
- `keyword-miner` 不能只靠 ASIN 运行；如果输入没有关键词，默认 `--keyword-source reverse_top` 会尝试先跑关键词反查再派生关键词。
- 当前默认爬虫数据集 alias 为 `ds_icw50TLOFu4F`，对应数据集名 `custom_crawler_amazon_details`，已验证 `table_id=43`。
- 如果爬虫 metadata 解析失败，优先传 `--crawler-table-id 43`，或用 `--skip-crawler-query` 暂时跳过爬虫来源。
- 如果远端 metadata 字段缺失导致字段校验失败，可尝试 `--sales-field-mode compatible` 或 `--crawler-field-mode compatible`。
- Alexa 默认问题为 6 个 Listing 诊断问题；如需替换，可重复传 `--rufus-question "..."`。
- `--fetch-report-files` 默认开启，单 ASIN 会先查 `/dataMetrics/v1/asin-report-files`；接口无结果时直接返回 `取数服务异常`，不会继续静默回退。
- Windows PowerShell 下不要手写复杂内联 JSON；本命令不要求用户手写 query JSON。

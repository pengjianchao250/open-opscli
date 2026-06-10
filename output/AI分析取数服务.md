# AI 分析取数服务使用说明

> 本文基于已开发完成的 `ops-asin-data-collector`，说明 AI 分析或前端模块如何通过 ASIN 批量取数服务获取分析所需数据。该服务只负责取数、标准化和落盘，不负责生成最终运营分析结论。

## 1. 服务定位

`ops-asin-data-collector` 是面向运营 Codex / AI 分析链路的 ASIN 批量取数编排服务。

它从 ASIN 输入文件出发，统一采集以下数据源：

- 卖家精灵关键词反查数据
- 卖家精灵关键词挖掘数据
- 卖家精灵 AI 全景分析数据
- Amazon 商品页抓取数据
- BI 即时综合销售数据
- 爬虫 Listing 快照数据
- Rufus 优化建议占位结构

服务边界：取数服务只产出标准数据包，不直接写报告、不修改 Listing、不改价、不操作广告，也不直接调用后端 HTTP。所有真实取数都通过正式 `opscli` 命令入口执行。

## 2. 输入文件

推荐 CSV：

```csv
asin,site,keyword,owner,notes
B0XXXXXXX,US,solar outdoor lights,张三,测试
B0YYYYYYY,US,flashlight,李四,测试
```

支持格式：

- `.csv`
- `.xlsx`
- `.json`
- `.jsonl`

必填列只有 `asin`。`keyword` 可选；如果没有 keyword，服务会先跑 `keyword-reverse`，再按 `--keyword-source reverse_top` 尝试从反查结果派生关键词给 `keyword-miner`。

## 3. 推荐执行流程

### 3.1 先解析输入

```bash
python opscli/skills/templates/ops-asin-data-collector/scripts/parse_asin_input.py \
  --input ./asins.csv \
  --asin-column asin \
  --keyword-column keyword \
  --pretty
```

重点检查：

- `summary.record_count`
- `summary.error_count`
- `errors`

### 3.2 Dry Run 生成命令计划

```bash
python opscli/skills/templates/ops-asin-data-collector/scripts/collect_asin_data.py \
  --input ./asins.csv \
  --asin-column asin \
  --keyword-column keyword \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31 \
  --dry-run
```

重点查看输出目录中的：

- `commands.jsonl`：将要执行的 `opscli` 命令
- `manifest.json`：本次参数和输出位置
- `asin-data.jsonl`：每个 ASIN 的 planned 状态

### 3.3 正式执行

```bash
python opscli/skills/templates/ops-asin-data-collector/scripts/collect_asin_data.py \
  --input ./asins.csv \
  --asin-column asin \
  --keyword-column keyword \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31
```

默认执行链路：

1. `opscli query simple` 查询 BI 销售数据
2. `opscli query metadata` 解析爬虫数据集 `table_id`
3. `opscli query simple` 查询爬虫 Listing 快照
4. `opscli seller-sprite run keyword-reverse`
5. `opscli seller-sprite run keyword-miner`
6. `opscli seller-sprite run listing-analysis`
7. `opscli amazon scrape`

## 4. 常用模式

只取 BI 和爬虫数据，不跑外部采集：

```bash
python opscli/skills/templates/ops-asin-data-collector/scripts/collect_asin_data.py \
  --input ./asins.csv \
  --skip-seller-sprite \
  --skip-amazon \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31
```

只取 BI 销售数据：

```bash
python opscli/skills/templates/ops-asin-data-collector/scripts/collect_asin_data.py \
  --input ./asins.csv \
  --skip-seller-sprite \
  --skip-amazon \
  --skip-crawler-query \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31
```

只测试爬虫 Listing 数据：

```bash
python opscli/skills/templates/ops-asin-data-collector/scripts/collect_asin_data.py \
  --input ./asins.csv \
  --skip-seller-sprite \
  --skip-amazon \
  --skip-sales-query \
  --crawler-table-id 43
```

## 5. 输出文件

默认输出目录：

```text
output/asin-data/<run_id>/
```

核心文件：

| 文件 | 用途 |
| --- | --- |
| `frontend-data.json` | 前端 / AI 分析优先读取的聚合 JSON |
| `frontend-data.md` | 面向人工和前端联调的 Markdown 概览 |
| `asin-data.jsonl` | 每个 ASIN 一行的标准化结果，包含 `frontend_data` |
| `manifest.json` | 本次运行参数、输出路径、统计摘要 |
| `asin-data-summary.json` | 成功 / 失败数量汇总 |
| `commands.jsonl` | 每条命令的计划和执行状态 |
| `errors.jsonl` | 每个来源的结构化错误 |
| `query/*.json` | query payload 和 query 原始结果 |
| `asins/<ASIN>/*.json` | 单个 ASIN 的原始来源结果 |

前端和 AI 分析优先消费：

```text
output/asin-data/<run_id>/frontend-data.json
```

## 6. 前端 / AI 数据结构

`frontend-data.json` 顶层结构：

```json
{
  "运行信息": {
    "运行ID": "asin-data-20260608-120000-abcdef",
    "输出目录": "output/asin-data/asin-data-20260608-120000-abcdef",
    "是否DryRun": false,
    "ASIN数量": 1,
    "失败ASIN数量": 0
  },
  "数据": []
}
```

每个 ASIN 固定包含四段：

1. `基础数据`
2. `卖家精灵关键词数据`
3. `卖家精灵AI全景分析数据`
4. `Rufus优化建议数据`

说明：

- `基础数据` 包含输入信息、Amazon 抓取摘要、BI 销售数据、爬虫 Listing 数据和错误列表。
- `卖家精灵关键词数据` 包含关键词反查和关键词挖掘任务信息。
- `卖家精灵AI全景分析数据.content` 是卖家精灵 AI 全景分析任务返回的完整 `content`，脚本只解析 JSON，不摘要、不删字段、不扁平化。
- `Rufus优化建议数据` 当前是预留结构，真实接口暂未接入。

## 7. 关键参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--input` | 必填 | 输入文件 |
| `--asin-column` | `asin` | ASIN 列名 |
| `--keyword-column` | `keyword` | 关键词列名 |
| `--site` | `US` | 默认站点 |
| `--sales-start` | 空 | 销售数据开始日期 |
| `--sales-end` | 空 | 销售数据结束日期 |
| `--query-chunk-size` | `100` | BI / 爬虫数据每批 ASIN 数 |
| `--seller-sprite-period` | `30d` | 卖家精灵周期 |
| `--keyword-source` | `reverse_top` | 无输入 keyword 时的派生策略 |
| `--sales-table-id` | `1` | 即时综合数据集 table_id |
| `--crawler-dataset-alias` | `ds_icw50TLOFu4F` | 爬虫 Listing 快照数据集 alias |
| `--crawler-table-id` | 空 | 可手动指定；已验证 `ds_icw50TLOFu4F` 对应 `43` |
| `--skip-sales-query` | false | 跳过 BI 销售数据 |
| `--skip-crawler-query` | false | 跳过爬虫 Listing 数据 |
| `--skip-seller-sprite` | false | 跳过卖家精灵 |
| `--skip-listing-analysis` | false | 跳过卖家精灵 AI 全景分析 |
| `--skip-amazon` | false | 跳过 Amazon 抓取 |
| `--dry-run` | false | 只生成计划不执行 |

## 8. 固化数据源

BI 销售数据：

- `table_id`: `1`
- `dataset_alias`: `ds_d35ac6f3910c`
- 数据集：`order_sale_trend_adv_traffic_inv_set`

爬虫 Listing 数据：

- `dataset_alias`: `ds_icw50TLOFu4F`
- 已验证 `table_id`: `43`
- 数据集：`custom_crawler_amazon_details`

卖家精灵：

- `keyword-reverse`：按 ASIN 反查关键词
- `keyword-miner`：按 keyword 挖掘关键词，不能只用 ASIN
- `listing-analysis`：按 ASIN 生成 AI 全景分析，并透传完整 `content`

Amazon：

- `opscli amazon scrape --asin <ASIN>`

## 9. 失败处理约定

每个来源独立记录状态，不因单个来源失败丢弃整个 ASIN。

状态值：

- `success`
- `skipped`
- `failed`
- `partial`
- `planned`

前端中文状态：

- `成功`
- `跳过`
- `失败`
- `部分成功`
- `计划中`
- `预留`

任何 `opscli` 命令失败时，运营 Codex 必须按项目规则立即提交 `ops-feedback`。`errors.jsonl` 即使没有错误也会创建为空文件，调用方可以固定读取。

## 10. 给其他项目调用

其他项目建议通过子进程调用：

```bash
python D:/workspace/open-opscli/opscli/skills/templates/ops-asin-data-collector/scripts/collect_asin_data.py \
  --input D:/data/asins.csv \
  --output-dir D:/data/asin-data-output \
  --sales-start 2026-05-01 \
  --sales-end 2026-05-31
```

调用方读取 stdout 中的 `output_dir`，再读取：

```text
<output_dir>/frontend-data.json
<output_dir>/asin-data.jsonl
<output_dir>/manifest.json
```

Python 调用示例：

```python
import json
import subprocess
from pathlib import Path

cmd = [
    "python",
    "D:/workspace/open-opscli/opscli/skills/templates/ops-asin-data-collector/scripts/collect_asin_data.py",
    "--input",
    "D:/data/asins.csv",
    "--output-dir",
    "D:/data/asin-data-output",
    "--sales-start",
    "2026-05-01",
    "--sales-end",
    "2026-05-31",
    "--skip-seller-sprite",
    "--skip-amazon",
    "--skip-crawler-query",
]

completed = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8")
payload = json.loads(completed.stdout)
output_dir = Path(payload["output_dir"])

frontend_data = json.loads((output_dir / "frontend-data.json").read_text(encoding="utf-8"))
```

## 11. 注意事项

- Windows PowerShell 下不要用 `opscli query simple --json` 内联 JSON，统一使用 `--payload 文件`。
- 大批量跑 SellerSprite 和 Amazon 前，先用 1-3 个 ASIN 小样本验证。
- 如果爬虫 metadata 解析失败，优先传 `--crawler-table-id 43`，或用 `--skip-crawler-query` 暂时跳过爬虫来源。
- `keyword-miner` 必须有 keyword；没有 keyword 时依赖 `keyword-reverse` 派生，派生来源会写入输出。
- 取数服务不生成最终分析结论，下游分析模块应读取 `frontend-data.json` 或 `asin-data.jsonl` 再做分析。

## 12. 参考文件

- `docs/guide/ASIN批量取数服务使用说明.md`
- `docs/guide/ASIN取数前端数据结构.md`
- `docs/design/ASIN批量取数服务与Skill封装方案.md`
- `opscli/skills/templates/ops-asin-data-collector/SKILL.md`
- `opscli/skills/templates/ops-asin-data-collector/references/data-contract.md`
- `opscli/skills/templates/ops-asin-data-collector/references/source-mapping.md`

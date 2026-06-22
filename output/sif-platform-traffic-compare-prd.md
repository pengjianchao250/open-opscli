# Sif 平台查流量与多产品对比 PRD

## 目标

在现有 `opscli sif` 平台入口下新增两个业务能力：

- `查流量` / `查流量词`：围绕单 ASIN 获取流量结构、反查流量词、多变体自然位相关下载文件。
- `多产品对比`：围绕多个 ASIN 获取对比销量、对比流量结构、对比流量词相关下载文件。

执行完成后，CLI 需要像当前 Sif 查销量与 SellerSprite 一样，输出简要信息和生成文件路径，为后续数据分析、后端存储和人工验收提供稳定产物。

## 用户价值

- 快速批量导出 Sif 页面中需要手动点击下载的流量和对比数据。
- 将 Sif 同平台能力统一沉淀到 `opscli sif run`，减少使用者记忆成本。
- 让每次执行保留 `params.json/raw.json/result.json/XLSX`，便于复盘接口参数、重跑和后续分析。
- 为后续接入后端存储或 MCP 留下稳定数据契约。

## CLI 范围

### 查流量

推荐命令：

```bash
opscli sif run 查流量 --asin B01NBNDC1T --site US
opscli sif run 查流量词 --asin B01NBNDC1T --site US
```

参数：

| 参数 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- |
| `feature` | 是 | 无 | `查流量`、`查流量词`、`查流量(词)` 视为同一功能 |
| `--asin` | 是 | 无 | 单个 ASIN |
| `--site` | 否 | `US` | Sif `country` |
| `--time-piece-type` | 否 | `latelyDay` | 时间范围类型 |
| `--time-piece-value` | 否 | `7` | 时间范围值 |
| `--sections` | 否 | `all` | 可选 `structure,keywords,multi-nf` |
| `--output-dir` | 否 | 用户级配置目录 | 指定输出目录 |
| `--job-id` | 否 | 自动生成 | 指定任务 ID |

第一版默认下载全部三个子项：

- 查流量结构
- 反查流量词
- 查多变体自然位

### 多产品对比

推荐命令：

```bash
opscli sif run 多产品对比 --asin B075WPKK5P,B07KVV8RFF,B07QQ21GL2,B07YJPFJ43,B08PNQCKF7 --site US
```

参数：

| 参数 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- |
| `feature` | 是 | 无 | `多产品对比` |
| `--asin` | 是 | 无 | 逗号分隔多 ASIN；实现内规范化为列表 |
| `--site` | 否 | `US` | Sif `country` |
| `--time-piece-type` | 否 | `latelyDay` | 时间范围类型 |
| `--time-piece-value` | 否 | `7` | 时间范围值 |
| `--sections` | 否 | `all` | 可选 `sales,traffic-structure,traffic-keywords` |
| `--my-asin` | 否 | 第一个 ASIN | 对比流量词页面“我的 ASIN” |
| `--output-dir` | 否 | 用户级配置目录 | 指定输出目录 |
| `--job-id` | 否 | 自动生成 | 指定任务 ID |

第一版默认下载：

- 对比销量
- 对比流量结构：流量词、流量分
- 对比流量词：重点流量词、重点广告词

## 输出要求

每次运行生成独立目录：

```text
~/.config/opscli/sif/<feature-key>/runs/<job-id>/
  params.json
  raw.json
  result.json
  *.xlsx
```

默认输出目录按 feature 分组：

```text
~/.config/opscli/sif/sales/runs/
~/.config/opscli/sif/traffic/runs/
~/.config/opscli/sif/compare/runs/
```

查流量建议导出文件：

```text
listingScoreChart_<ASIN>_<timestamp>.xlsx
asinKeywordList_<ASIN>_<timestamp>.xlsx
asinMultiNfKeywordList_<ASIN>_<timestamp>.xlsx
```

多产品对比建议导出文件：

```text
compareBoughtByAsin_<asin-count>_<timestamp>.xlsx
compareSummaryTrafficWords_<asin-count>_<timestamp>.xlsx
compareSummaryTrafficScore_<asin-count>_<timestamp>.xlsx
compareMyTrafficKeywords_<asin-count>_<timestamp>.xlsx
compareMyAdKeywords_<asin-count>_<timestamp>.xlsx
```

终端成功输出需要展示：

- 功能名
- 站点
- ASIN 或 ASIN 数量
- 时间范围
- 任务目录
- `result.json`
- 每个 XLSX 的文件名和可打开路径
- warnings，尤其是跳过某个未确认子接口时

## result.json 契约

顶层建议：

```json
{
  "schema_version": "sif_traffic.v1",
  "feature": "查流量",
  "provider": "sif",
  "site": "US",
  "asins": ["B01NBNDC1T"],
  "collected_at": "2026-06-04T18:00:00+08:00",
  "query": {
    "time_piece_type": "latelyDay",
    "time_piece_value": "7",
    "sections": ["structure", "keywords", "multi_nf"]
  },
  "summary": {
    "export_count": 3,
    "warning_count": 0
  },
  "exports": {},
  "requests": [],
  "warnings": []
}
```

多产品对比使用：

```json
{
  "schema_version": "sif_compare.v1",
  "feature": "多产品对比",
  "provider": "sif",
  "site": "US",
  "asins": [],
  "query": {},
  "summary": {},
  "exports": {},
  "requests": [],
  "warnings": []
}
```

第一版不强制解析 XLSX 表格内容；后续如需进一步数据处理，可在 `parsed_tables` 下追加结构化表数据。

## Skill 要求

将 Sif 平台能力整理为统一 Skill：

```text
opscli/skills/templates/ops-sif/
  SKILL.md
  data/VERSION.json
```

Skill 触发范围：

- Sif 查销量、销量趋势、变体销量。
- Sif 查流量、查流量词、反查流量词、流量结构、多变体自然位。
- Sif 多产品对比、对比销量、对比流量结构、对比流量词、重点广告词。

默认路径：

- 使用 CLI：`opscli sif run ...`
- 暂不默认使用 MCP。
- 不直接由 Agent 调 Sif HTTP API。

## 不做范围

第一版不做：

- MCP 工具。
- 后端真实写入。
- XLSX 内容逐列解析和业务诊断。
- Playwright 自动点击页面下载。
- 在文档、日志、测试中写入任何 Sif 账号密码、Cookie、token。

## 验收标准

1. `opscli sif features --pretty` 能列出 `查销量`、`查流量`、`多产品对比`。
2. `opscli sif run 查流量 --asin B01NBNDC1T --site US` 生成 3 个 XLSX、`params.json`、`raw.json`、`result.json`。
3. `opscli sif run 多产品对比 --asin A,B,C --site US` 生成已确认子接口对应 XLSX、`params.json`、`raw.json`、`result.json`。
4. 终端默认输出为人可读摘要，`--json/--pretty` 输出机器可读 JSON。
5. 未登录或接口返回未授权时错误友好，不泄露敏感信息。
6. 单元测试覆盖 payload 构造、下载保存、result 结构、错误脱敏、CLI 参数。
7. 不再出现用户入口 `sales run`。
8. `--site` 支持国家名称/站点名称映射为 Sif `country` 编码，例如 `美国`、`美国站`、`US` 均解析为 `US`；首版至少覆盖美国、英国、加拿大、法国、西班牙、意大利、澳大利亚、墨西哥、阿联酋、巴西、沙特。

## 已确认参数

多产品对比“对比销量”下载 payload：

```json
{
  "pageNum": 1,
  "pageSize": 100,
  "sortBy": "",
  "desc": true,
  "asins": [
    "B075WPKK5P",
    "B07KVV8RFF",
    "B07QQ21GL2",
    "B07YJPFJ43",
    "B08PNQCKF7"
  ],
  "timePieceType": "latelyDay",
  "timePieceValue": "30"
}
```

对比流量结构枚举：

- `showType=1`：下载流量词。
- `showType=2`：下载流量分。

对比流量词枚举：

- `listType=1`：下载重点流量词。
- `listType=2`：下载重点广告词。

输出目录：

- 确认按 feature 分目录。

查流量结构下载：

- `GET /api/struct/listingscore/chart/download` 需要带页面上下文请求头，至少包含 `Referer`。
- `Referer` 按 Sif 查流量页面构造，需包含当前 `country`、`asin`、时间范围等上下文，避免下载接口因缺少页面来源返回非 XLSX。

## 待确认问题

1. 是否需要同时下载页面可见图表数据接口的 JSON，还是第一版仅下载 XLSX 并生成执行结构化 JSON。

# Sif 平台查流量与多产品对比调研

## 背景

当前仓库已经实现 Sif 平台级入口 `opscli sif run 查销量 --asin ... --site ...`，并复用了 Sif 登录、API 直连、XLSX 保存、`params.json/raw.json/result.json` 落盘和终端友好输出。新需求继续在同一 Sif 平台内扩展两个大模块：

- `查流量` / `查流量(词)`：单 ASIN，下载流量结构、反查流量词、多变体自然位搜索结果。
- `多产品对比`：多 ASIN，下载对比销量、对比流量结构、对比流量词相关结果。

新能力应继续沿用平台入口：

```bash
opscli sif run 查流量 --asin B01NBNDC1T --site US
opscli sif run 查流量词 --asin B01NBNDC1T --site US
opscli sif run 多产品对比 --asin B075WPKK5P,B07KVV8RFF,B07QQ21GL2,B07YJPFJ43,B08PNQCKF7 --site US
```

## 可复用现状

现有 Sif 模块可复用：

- `opscli/sif/cli.py`：平台级 `features/run/login-check/status`。
- `opscli/sif/config.py`：Sif 环境变量、默认输出目录、敏感信息脱敏。
- `opscli/sif/client.py`：统一登录、`_m` 请求标记、`_t` 时间戳、httpx 请求、XLSX 响应校验。
- `opscli/sif/sales/provider.py`：单功能 provider 编排、job 目录、raw/result/params/export 保存。
- `opscli/sif/sales/models.py`：运行请求、导出结果、运行结果模型。

SellerSprite 可借鉴：

- 按场景注册接口参数和默认值，不把所有逻辑写死在 CLI。
- 每次执行生成 job 目录，包含参数、原始响应、规范结果、导出文件。
- 终端输出优先展示场景、站点、核心条件、row count、导出文件名和路径。
- Skill 负责把自然语言意图映射到具体场景，底层仍通过 CLI/MCP 的稳定入口执行。

## 查流量接口清单

默认参数：

- `country=US`
- `timePieceType=latelyDay`
- `timePieceValue=7`
- `asin=<单个 ASIN>`
- `dimension=asin`
- `_t=<当前毫秒时间戳>`
- `_m=<Sif 请求标记>`

### 查流量结构

页面路径：查流量(词) -> 查流量结构 -> 下载图标。

下载接口：

```text
GET /api/struct/listingscore/chart/download
```

Query 示例：

```json
{
  "country": "US",
  "timePieceType": "latelyDay",
  "timePieceValue": "7",
  "asin": "B01NBNDC1T",
  "dimension": "asin",
  "desc": true
}
```

预期输出：平台原始 XLSX，建议文件名 `listingScoreChart_<ASIN>_<timestamp>.xlsx`。

### 反查流量词

页面路径：查流量(词) -> 反查流量词 -> 流量词下载图标。

下载接口：

```text
POST /api/updown/asinKeywordList/download
```

Query：

```json
{"country": "US"}
```

Request Payload：

```json
{
  "pageSize": 50,
  "pageNum": 1,
  "sort": "scoreInfo.scoreRatio",
  "desc": true,
  "conditions": ["totalPeriod.total"],
  "keyword": "",
  "asin": "B01NBNDC1T",
  "listingSearch": false,
  "timePieceType": "latelyDay",
  "timePieceValue": "7",
  "keywordSearch": ""
}
```

预期输出：平台原始 XLSX，建议文件名 `asinKeywordList_<ASIN>_<timestamp>.xlsx`。

### 查多变体自然位

页面路径：查流量(词) -> 查多变体自然位 -> 下载搜索结果。

下载接口：

```text
POST /api/updown/asinMultiNf/keywordList/download
```

Request Payload：

```json
{
  "searchKeyword": "",
  "pageNum": 1,
  "pageSize": 100,
  "searchAsin": "",
  "sortBy": "nfScore",
  "desc": true,
  "asin": "B01NBNDC1T",
  "timePieceType": "latelyDay",
  "timePieceValue": "7"
}
```

预期输出：平台原始 XLSX，建议文件名 `asinMultiNfKeywordList_<ASIN>_<timestamp>.xlsx`。

## 多产品对比接口清单

默认 ASIN 示例：

```text
B075WPKK5P,B07KVV8RFF,B07QQ21GL2,B07YJPFJ43,B08PNQCKF7
```

### 对比销量

页面路径：多产品对比 -> 对比销量 -> 销量明细对比 -> 下载。

下载接口：

```text
POST /api/updown/boughtByAsin/download
```

该接口和查销量的同组变体下载接口路径一致，但多产品对比场景使用多 ASIN payload，不能直接复用单 ASIN 查销量 payload。

Request Payload：

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

预期输出：平台原始 XLSX，建议文件名 `compareBoughtByAsin_<asin-count>_<timestamp>.xlsx`。

### 对比流量结构

页面路径：多产品对比 -> 对比流量结构。

下载接口：

```text
POST /api/compare/summary/multiAsin/download
```

Request Payload：

```json
{
  "timePieceType": "latelyDay",
  "timePieceValue": "7",
  "type": 1,
  "sortBy": "",
  "desc": true,
  "searchValue": "B075WPKK5P,B07KVV8RFF,B07QQ21GL2,B07YJPFJ43,B08PNQCKF7",
  "showType": 1
}
```

已确认枚举：

- `showType=1`：下载流量词。
- `showType=2`：下载流量分。

### 对比流量词

页面路径：多产品对比 -> 对比流量词。

下载接口：

```text
POST /api/compare/compareMyKeywords/download
```

Request Payload：

```json
{
  "isMine": false,
  "vipModule": false,
  "asins": [
    "B075WPKK5P",
    "B07KVV8RFF",
    "B07QQ21GL2",
    "B07YJPFJ43",
    "B08PNQCKF7"
  ],
  "sortBy": "",
  "desc": true,
  "strategy": "legacyForSales_exact",
  "granularity": "week",
  "myPageNum": 1,
  "myPageSize": 10,
  "listType": 1,
  "timePieceType": "latelyDay",
  "timePieceValue": "7",
  "myCompareField": ""
}
```

已确认枚举：

- `listType=1`：下载重点流量词。
- `listType=2`：下载重点广告词。

## 关键设计结论

1. 新增能力应放在 `opscli/sif/` 平台模块内，不恢复 `opscli/sales/`。
2. CLI 入口继续使用 `opscli sif run <功能名>`，功能名区分 `查销量`、`查流量`、`查流量词`、`多产品对比`。
3. Sif 登录逻辑共用现有 `SifApiClient`，不得复制新的登录实现。
4. 下载文件优先保存 Sif 原始 XLSX，不重建表格内容。
5. `result.json` 第一版以稳定元数据、导出文件、sanitized payload、row/file summary 为主；若后续需要分析字段，再增加 XLSX 解析和规范化数据。
6. Skill 应统一整理为 `opscli/skills/templates/ops-sif/`，覆盖 Sif 平台所有功能触发词，替代单独的 `ops-sif-sales` 管理方式。
7. 用户输入的站点/国家名称需要规范化为 Sif `country` 编码，例如 `美国`、`美国站`、`US` 均转为 `US`；站点映射需覆盖美国、英国、加拿大、法国、西班牙、意大利、澳大利亚、墨西哥、阿联酋、巴西、沙特等常用站点。
8. 默认输出目录按 feature 分目录，例如 `~/.config/opscli/sif/traffic/runs`、`~/.config/opscli/sif/compare/runs`。

## 已确认参数补充

1. 多产品对比“对比销量”下载接口使用多 ASIN POST payload，`pageSize=100`，时间范围可动态传参。
2. 对比流量结构 `showType=1` 为流量词，`showType=2` 为流量分。
3. 对比流量词 `listType=1` 为重点流量词，`listType=2` 为重点广告词。
4. 站点参数需要支持中文国家/站点名称到编码的映射，至少覆盖 `US/UK/CA/FR/ES/IT/AU/MX/AE/BR/SA`。
5. 默认输出目录从固定 `sales/runs` 扩展为按 feature 分目录。
6. 查流量结构 GET 下载需要带上页面上下文请求头，至少包含 `Referer`，Referer 应按当前 ASIN、站点、时间范围构造。

实现补充：

- 是否需要同时下载页面可见图表数据接口的 JSON，还是第一版仅下载 XLSX 并生成执行结构化 JSON。

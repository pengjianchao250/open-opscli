# ASIN取数完整数据

## 运行信息

- 运行ID：asin-data-B0BY8Y5766-20260608-current-fields
- 开始时间：2026-06-08T17:06:07
- 结束时间：2026-06-08T17:06:20
- 输出目录：output\asin-data\asin-data-B0BY8Y5766-20260608-current-fields
- ASIN数量：1
- 失败ASIN数量：1

## 数据结构

每个 ASIN 固定返回四段：

- `基础数据`：中文字段，包含输入信息、BI 销售、爬虫 Listing 和错误列表。
- `卖家精灵关键词数据`：关键词反查和关键词挖掘任务信息。
- `卖家精灵AI全景分析数据`：直接返回 SellerSprite AI 全景分析的完整 `content`。
- `Rufus优化建议数据`：暂未接入接口，返回预留占位结构。

## ASIN汇总

| ASIN | 站点 | 基础数据 | 关键词数据 | AI全景分析 | Rufus |
| --- | --- | --- | --- | --- | --- |
| B0BY8Y5766 | US | 有错误 | 跳过 | 跳过 | 预留 |

## 1. ASIN B0BY8Y5766

### 基础数据

- ASIN：B0BY8Y5766
- 站点：US
- 输入关键词：
- 关键词来源：未提供
- 输入行号：1
- 来源文件：.tmp\asin-data-B0BY8Y5766-input.csv

#### BI销售数据

```json
{
  "状态": "失败",
  "原始状态": "failed",
  "行数": 0,
  "明细": [],
  "原因": "REMOTE_BUSINESS_ERROR: 参数验证失败"
}
```

#### 爬虫Listing数据

```json
{
  "状态": "失败",
  "原始状态": "failed",
  "行数": 0,
  "明细": [],
  "原因": "REMOTE_BUSINESS_ERROR: 字段不存在: ds_icw50TLOFu4F.a_image"
}
```

#### 错误列表

```json
[
  {
    "来源": "query.sales",
    "状态": "失败",
    "原始状态": "failed",
    "原因": "REMOTE_BUSINESS_ERROR: 参数验证失败"
  },
  {
    "来源": "query.crawler_listing",
    "状态": "失败",
    "原始状态": "failed",
    "原因": "REMOTE_BUSINESS_ERROR: 字段不存在: ds_icw50TLOFu4F.a_image"
  }
]
```

### 卖家精灵关键词数据

#### 关键词反查

```json
{
  "状态": "跳过",
  "原始状态": "skipped",
  "任务ID": null,
  "行数": null,
  "结果数据": [],
  "原因": "seller sprite skipped"
}
```

#### 关键词挖掘

```json
{
  "状态": "跳过",
  "原始状态": "skipped",
  "种子关键词": [],
  "任务列表": [],
  "原因": "keyword miner skipped"
}
```

### 卖家精灵AI全景分析数据

- 状态：跳过
- 原始状态：skipped
- 任务ID：
- 报告任务ID：
- 报告状态：
- 完成时间：
- 过期时间：
- html状态：
- 原因：seller sprite skipped

#### content

```json
null
```

### Rufus优化建议数据

```json
{
  "状态": "预留",
  "接入状态": "暂未接入",
  "数据": null,
  "说明": "当前 ASIN 取数服务暂未接入 Rufus 优化建议接口，先保留固定结构给前端渲染。"
}
```


完整机器可读 JSON 数据见同目录 `frontend-data.json`。

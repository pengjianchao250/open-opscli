# SIF 数据能力与业务场景梳理

> **文档定位**：以当前 `open-opscli` 项目代码为准，盘点 SIF（`sif.com`）已经实现的数据功能、运行链路、业务覆盖和当前开放状态。
> **重要区分**：SIF 与 Sorftime 是两个不同数据源。SIF 对应 `opscli/sif`；Sorftime 对应此前调研的 `sorftime.com` 多平台数据服务。
> **版本**：v0.1
> **更新时间**：2026-07-21

---

## 一、结论摘要

SIF 在项目中不是“计划接入”或“只有文档”，而是已经完成了 Provider、HTTP 客户端、账号管理、任务落盘、XLSX 导出、CLI/MCP 包装及单元测试的实现。当前代码覆盖三组功能、十个导出子模块：

1. **查销量**：不同变体销量、同组变体销量。
2. **查流量**：流量结构、反查流量词、多变体自然位。
3. **多产品对比**：对比销量、对比流量词、对比流量分、重点流量词、重点广告词。

但当前主入口处于关闭状态：

- `opscli/cli.py` 没有注册 `opscli sif` 子命令。
- `opscli/mcp/server.py` 没有注册 SIF MCP 工具，并明确注释为“暂不开放”。
- `configs/mcp-quota.json` 中 `sif_run.enabled=false`。
- MCP 契约测试明确要求 `sif_run`、`sif_scenarios` 不出现在当前工具列表。

因此准确状态应写成：**代码已实现、运行入口暂关闭、尚未计入正式可调用场景**。恢复入口前需要先确认业务开放决定、账号可用性和真实数据验收，而不是重新建设底层能力。

---

## 二、当前实现能力

### 2.1 功能与导出模块

| 功能 | 子模块 | 输入 | 默认时间 | 默认数量 | 主要输出 | 支撑环节 |
|---|---|---|---|---:|---|---|
| 查销量 | 不同变体销量 | 单个 ASIN、站点 | 最近 30 天 | 上游图表导出 | 不同变体销量历史 XLSX；JSON 中规范化变体/颜色/尺寸销量序列 | S04、S06、S07、S14、S18 |
| 查销量 | 同组变体销量 | 单个 ASIN、站点 | 最近 30 天 | 100 | 同组子体、标题、价格、颜色、尺寸、近 30 天销量代理和趋势 | S04、S06、S07、S14、S18 |
| 查流量 | 流量结构 | 单个 ASIN、站点 | 最近 7 天 | 上游图表导出 | ASIN 流量结构 XLSX | S03、S04、S11、S12、S14 |
| 查流量 | 反查流量词 | 单个 ASIN、站点 | 最近 7 天 | 50 | 按流量得分排序的关键词 XLSX | S03、S04、S11、S12、S13 |
| 查流量 | 多变体自然位 | 单个 ASIN、站点 | 最近 7 天 | 100 | 多变体自然排名关键词 XLSX | S03、S04、S11、S12 |
| 多产品对比 | 对比销量 | 至少 2 个 ASIN、站点 | 最近 30 天 | 100 | 多 ASIN 销量对比 XLSX | S04、S06、S14、S18 |
| 多产品对比 | 对比流量词 | 至少 2 个 ASIN、站点 | 最近 7 天 | 上游汇总导出 | 多 ASIN 流量词结构 XLSX | S03、S04、S11、S12 |
| 多产品对比 | 对比流量分 | 至少 2 个 ASIN、站点 | 最近 7 天 | 上游汇总导出 | 多 ASIN 流量分 XLSX | S04、S06、S12、S14 |
| 多产品对比 | 重点流量词 | 至少 2 个 ASIN、站点 | 最近 7 天 | 10 | 多 ASIN 重点流量关键词 XLSX | S03、S04、S11、S12、S13 |
| 多产品对比 | 重点广告词 | 至少 2 个 ASIN、站点 | 最近 7 天 | 10 | 多 ASIN 重点广告关键词 XLSX | S03、S04、S12、S13 |

以上销量、流量和广告词属于 SIF 第三方数据或代理指标，不能解释为 Amazon 第一方订单、Sessions、点击、花费或广告归因。

### 2.2 站点与时间范围

项目统一支持 13 个站点：

```text
US、UK、CA、FR、ES、IT、AU、MX、AE、BR、SA、JP、DE
```

支持中文站点别名；默认站点为 `US`。时间参数按功能支持：

- `latelyDay`：最近若干天。
- `week`：历史周。
- `month`：月份。
- 查销量默认 `latelyDay/30`。
- 查流量和多产品对比默认 `latelyDay/7`；其中对比销量实际更适合使用 30 天口径。

### 2.3 项目接口与导出契约

| 功能 | 项目调用路径 | 方法 | 项目处理方式 |
|---|---|:---:|---|
| 不同变体销量查询 | `/api/search/bought/listingHistory` | POST | 取得 JSON，并规范化变体/颜色/尺寸销量序列 |
| 同组变体查询 | `/api/search/bought/asin` | POST | 取得同组变体 JSON，并规范化关键字段 |
| 不同变体销量导出 | `/api/updown/boughtListingHistory/download` | POST | 保存上游 XLSX |
| 同组变体销量导出 | `/api/updown/boughtByAsin/download` | POST | 保存上游 XLSX |
| 流量结构 | `/api/struct/listingscore/chart/download` | GET | 保存上游 XLSX，附带 SIF Traffic Referer |
| 反查流量词 | `/api/updown/asinKeywordList/download` | POST | 保存上游 XLSX |
| 多变体自然位 | `/api/updown/asinMultiNf/keywordList/download` | POST | 保存上游 XLSX |
| 多产品销量对比 | `/api/updown/boughtByAsin/download` | POST | 复用多 ASIN 参数导出 XLSX |
| 多产品流量词/流量分 | `/api/compare/summary/multiAsin/download` | POST | 通过 `showType=1/2` 区分导出 |
| 重点流量词/重点广告词 | `/api/compare/compareMyKeywords/download` | POST | 通过 `listType=1/2` 区分导出 |

目前查销量会解析一部分 JSON 为稳定结构；查流量和多产品对比主要保存上游生成的 XLSX，项目只标准化任务、请求和导出元数据。因此“文件可以导出”不等于全部字段已经进入统一指标模型。

---

## 三、工程实现状态

### 3.1 已完成的底层能力

| 能力 | 实现情况 |
|---|---|
| Provider | `SifSalesProvider`、`SifTrafficProvider`、`SifCompareProvider` 已实现 |
| 服务编排 | `SifServiceManager` 统一列场景、选择账号、执行 Provider、查询任务和返回导出 |
| 账号来源 | 优先 OPS 集成账号平台 `sif`，再回退环境变量账号密码；公开输出会掩码 |
| 登录与凭据 | 支持账号密码登录、Cookie/Token 配置和 `login_diagnostics`；敏感值不写结果 |
| 任务落盘 | 每次生成 `params.json`、`raw.json`、`result.json` |
| 导出 | 保存 XLSX；启用文件上传时返回远程 URL，否则返回本地文件 URI |
| CLI 包装 | `features`、`run`、`login-check`、`status` 已实现 |
| MCP 包装 | `sif_spec_must_read`、`sif_scenarios`、`sif_accounts`、`sif_run`、`sif_job_status`、`sif_export` 已实现 |
| 测试 | Client、Provider、Payload、CLI、Service、MCP 工具均有测试覆盖 |

### 3.2 当前未开放的入口

```text
底层 Provider/Service：已实现
独立 CLI/MCP 工具模块：已实现
主 opscli 子命令注册：关闭
主 MCP Server 注册：关闭
MCP quota policy：enabled=false
正式 Agent 可调用状态：不可用
```

这意味着可以复用现有实现恢复服务，但在入口恢复并通过真实账号冒烟测试之前，数据地图不能把 SIF 标成“已正式接入”。

### 3.3 文档一致性风险

项目同时保留两份 SIF Skill：

- `SKILL.md` 写明首版优先 CLI、MCP 延后。
- `SKILL_MCP.md` 已定义完整 MCP 使用流程。

当前主注册代码和测试才是实际运行事实：CLI 与 MCP 入口均关闭。恢复服务时需要同步更新两份 Skill，避免 Agent 按不存在的入口执行。

---

## 四、对电商运营数据地图的价值

### 4.1 最适合承担的场景

| 优先级 | 场景 | SIF 组合 | 业务输出 | 与现有来源分工 |
|:---:|---|---|---|---|
| P0 | 竞品变体销量结构 | 不同变体销量 + 同组变体销量 | 主力变体、颜色/尺寸偏好、长尾变体和趋势 | 卖家精灵看市场筛选，Keepa 验证价格/BSR 历史，SIF补变体销量代理 |
| P0 | ASIN 流量结构诊断 | 流量结构 + 反查流量词 + 多变体自然位 | 流量词池、自然位、变体承接和关键词结构 | 卖家精灵提供需求/ABA，西柚补词—品—位置时间序列，SIF补导出视角 |
| P0 | 多竞品流量差距 | 对比流量词 + 对比流量分 + 重点流量词 | 共同词、差异词、竞品流量强弱和追赶词 | 与卖家精灵多 ASIN 反查交叉校验，避免重复建设同义场景 |
| P1 | 竞品广告词线索 | 重点广告词 | 竞品可能重点投放的关键词 | 只能作为竞争情报；不能替代 Amazon Ads 第一方花费和转化 |
| P1 | 多 ASIN 销量对比 | 对比销量 | 同口径竞品销量代理比较 | 用 Keepa BSR 历史和自有 ASIN 订单样本做可信度校准 |

### 4.2 不应由 SIF 承担

- 自有订单、Sessions、CVR、广告花费、ACOS/ROAS。
- Buy Box、Offer、价格和 BSR 长期历史。
- 库存、在途、补货和物流执行。
- 采购成本、平台结算和真实利润。
- 原始评论正文、退货原因和客服 VOC。
- 多平台官方经营数据。

---

## 五、推荐恢复与验收顺序

1. **确认开放决策**：决定只恢复 CLI、只恢复 MCP，还是两者都恢复。
2. **统一 Skill**：以真实注册状态更新 `ops-sif/SKILL.md` 与 `SKILL_MCP.md`。
3. **账号冒烟**：使用 OPS 集成账号执行 `login-check`，不在日志或对话输出凭据。
4. **单 ASIN 验收**：依次验证查销量两份、查流量三份 XLSX 的字段、行数和时间口径。
5. **多 ASIN 验收**：验证五份对比导出，特别检查 `showType`、`listType` 与页面含义一致。
6. **字段入模**：对高价值 XLSX 建解析器，把关键词、销量代理、自然位和流量分进入统一数据模型。
7. **交叉校准**：与卖家精灵、Keepa、西柚和自有 ASIN 第一方样本比较完整率、趋势一致性和单位成本。
8. **恢复入口**：通过验收后再注册 CLI/MCP、启用 quota，并计入正式场景覆盖。

---

## 六、项目证据索引

| 证据 | 项目位置 |
|---|---|
| 三组功能与十个子模块 | `opscli/sif/services/manager.py` |
| CLI 功能、参数、默认时间和输出 | `opscli/sif/cli.py` |
| MCP 工具契约 | `opscli/mcp/tools/sif.py` |
| 查销量实现和规范化字段 | `opscli/sif/sales/provider.py`、`opscli/sif/sales/normalizer.py` |
| 查流量接口和 Payload | `opscli/sif/traffic/provider.py`、`opscli/sif/traffic/scenarios.py` |
| 多产品对比接口和 Payload | `opscli/sif/compare/provider.py`、`opscli/sif/compare/scenarios.py` |
| 站点白名单 | `opscli/sif/sites.py` |
| OPS 集成账号与环境变量回退 | `opscli/sif/accounts.py`、`opscli/sif/config.py` |
| 主 CLI 当前关闭 | `opscli/cli.py` |
| MCP Server 当前关闭 | `opscli/mcp/server.py` |
| quota 当前关闭 | `configs/mcp-quota.json` |
| 工具隐藏契约测试 | `tests/mcp/test_tools.py` |

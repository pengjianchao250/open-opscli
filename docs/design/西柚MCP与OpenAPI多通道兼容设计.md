# 西柚 MCP 与 OpenAPI 多通道兼容设计

**文档版本**：v1.0
**日期**：2026-09-08
**状态**：首批 MCP 试用通道已实现并完成双账号冒烟
**目标**：先通过西柚 MCP 验证数据价值，后续开通 VIP 后切换到正式 OpenAPI，并保留项目现有西柚网页接口作为补充通道。

---

## 一、结论

1. 当前可用的 `xydc MCP` 暴露了 **28 个数据查询工具**和 1 个缺失能力反馈工具，覆盖商品、流量、订单、BSR、关键词、排名、广告、变体、多 ASIN 和父体分析。
2. 西柚官方公开目录当前包含 **21 个 OpenAPI 业务接口**。MCP 中有 21 项可与公开接口直接对应，另有 7 项属于 MCP 扩展、组合或公开目录未展示的能力。
3. 项目现有 `opscli/xiyou` 不是正式 OpenAPI 客户端。它使用网页端 `authorization/cookie` 调用 `https://api.xydc.com` 的 `/v2`、`/v3`、`/v4` 业务接口，当前代码已实现 16 个 function，但 CLI、通用 MCP 注册和 quota 都处于关闭状态。
4. 不建议把 MCP 的 28 个工具直接复制成另一套独立模块。应在 `opscli/xiyou` 内建立稳定的业务 Interface，由 `MCP Adapter`、`OpenAPI Adapter`、`Web Adapter` 三个实现共享。
5. 试用期以 MCP 为主；开通 VIP 后以 OpenAPI 为主；现有网页接口仅在能力未迁移或主通道明确不可用时补充。空数据、参数错误、鉴权失败和额度不足不得触发静默回退。

---

## 二、实际试调结果

本次使用仓库已有公开测试样本执行了 4 次低成本 MCP 调用，共消耗 4 Credits。

| 工具 | 结果 | Credit | 观察 |
|---|---:|---:|---|
| `get_asin_info` | 成功 | 1 | 返回标题、价格、币种、评分、评论数、主图和 Amazon URL |
| `get_asin_traffic` | 成功 | 1 | 返回近 7 天自然、广告、总流量得分及环比；该样本全部为 0 |
| `get_keyword_info` | 成功 | 1 | 返回 ABA 周搜索量、搜索频率排名、竞争难度、CPC 和自然滚动率 |
| `get_keyword_asin_analysis` | 成功 | 1 | 返回关键词下 2,159 个竞争 ASIN；试调只取流量排序前 5 条 |

试调确认了以下契约特征：

- MCP 成功响应统一包含 `status`、`cost_credits` 和 `data`；2026-09-09 使用独立 Bearer Token 实测时 `status` 为整数 `200`，不是字符串 `success`。
- 数字类型不统一：价格和星级可能为字符串，流量占比和增长率也常为字符串。
- 排名使用 `or`、`sp`、`sor` 等位置代码，并带 `page`、`pageRank`、`totalRank` 和带时区的 `rankTime`。
- HTTP 或业务成功不代表数据一定有覆盖。流量全为 0 必须作为合法结果返回，不能误判成故障后切换数据源。

---

## 三、xydc MCP 能力清单

### 3.1 商品快照

| MCP 工具 | 能力 | 主要输入 |
|---|---|---|
| `get_asin_info` | 当前标题、价格、评分、评论数、主图、链接 | 多 ASIN、站点 |
| `get_asin_traffic` | 近 7 天自然/广告/总流量得分及环比 | 多 ASIN、站点 |
| `get_asin_orders_last_30_days` | 最近 30 天订单量 | 多 ASIN、站点 |
| `get_asin_variations` | 父体、子体及变体属性 | ASIN、站点 |

### 3.2 商品趋势

| MCP 工具 | 能力 | 时间粒度 |
|---|---|---|
| `get_asin_info_change_trends` | 标题、主图变更前后内容 | 日 |
| `get_asin_info_trends` | 价格、评分、评论数、优惠等趋势 | 日 |
| `get_asin_bsr_trends` | 各类目 BSR 排名趋势 | 日 |
| `get_asin_order_trends` | 订单量趋势 | 月 |
| `get_asin_traffic_trends` | 自然/广告流量及位置拆解 | 日 |
| `get_asin_traffic_trends_weekly` | 自然/广告流量及位置拆解 | 周 |
| `get_asin_traffic_trends_monthly` | 自然/广告流量及位置拆解 | 月 |
| `get_asin_ad_change_trends` | 每天新观测到的广告活动 | 日 |
| `get_asin_keyword_count_trends` | 自然/广告及不同排名区间的关键词数量 | 日 |

`get_asin_ad_change_trends` 的当前 MCP 说明只保证识别新增活动，不能用“未返回停止记录”证明活动仍在运行。项目旧调研中“新增/移除广告活动”的表述需要按实测契约收紧。

### 3.3 ASIN 反查关键词与词品关系

| MCP 工具 | 能力 | 说明 |
|---|---|---|
| `get_asin_keywords` | 最近 7 天反查关键词 | 快照 |
| `get_asin_keywords_daily` | 指定日期范围反查关键词 | 单次最多 30 天 |
| `get_asin_keywords_monthly` | 月度反查关键词历史 | 长周期 |
| `get_asin_keyword_traffic_trends` | 单 ASIN + 单关键词流量趋势 | 日 |
| `get_asin_keyword_rank_trends` | 单 ASIN + 单关键词排名趋势 | 日 |
| `get_asin_keyword_rank_hourly` | 单 ASIN + 单关键词小时排名 | 单日，仅 US/UK/DE |

### 3.4 关键词市场

| MCP 工具 | 能力 | 说明 |
|---|---|---|
| `get_keyword_info` | 搜索量、ABA、竞争难度、CPC、点击转化率 | 最近一周 |
| `get_keyword_aba_trends` | ABA 搜索量、排名和 Top 3 份额趋势 | 周，单批最多 52 周 |
| `get_keyword_asin_analysis` | 关键词下竞争 ASIN、排名和流量 | 最近 7 天 |
| `get_keyword_analysis_monthly` | 关键词下 ASIN 竞争格局历史 | 月 |
| `get_keyword_advertising_replay` | 单日逐小时广告位快照 | 仅 US/UK/DE |

### 3.5 多 ASIN 与父体分析

| MCP 工具 | 能力 | 说明 |
|---|---|---|
| `get_multi_asin_keyword_comparison` | 多 ASIN 关键词覆盖、排名和流量横向对比 | 最近 7 天，最多 20 个 ASIN |
| `get_multi_asin_keyword_comparison_monthly` | 多 ASIN 月度关键词横向对比 | 月 |
| `get_parent_asin_keywords` | 自动识别父体并汇总全部子体关键词 | 最近 7 天 |
| `get_parent_asin_keywords_monthly` | 父体全部子体的月度关键词汇总 | 月 |

### 3.6 非数据工具

`report_missing_xiyou_capability` 只用于向西柚记录现有工具无法满足的需求，不应出现在 opscli 的业务查询 Interface 中。

---

## 四、MCP 与公开 OpenAPI 映射

### 4.1 可直接映射的 21 项

| MCP 工具 | OpenAPI 路径 |
|---|---|
| `get_asin_info` | `/v1/asins/info` |
| `get_asin_traffic` | `/v1/asins/traffic` |
| `get_asin_orders_last_30_days` | `/v1/asins/orders` |
| `get_asin_variations` | `/v1/asins/variations` |
| `get_asin_info_change_trends` | `/v1/asins/infoChange/trends/daily` |
| `get_asin_info_trends` | `/v1/asins/info/trends/daily` |
| `get_asin_bsr_trends` | `/v1/asins/bsrInfo/trends/daily` |
| `get_asin_order_trends` | `/v1/asins/orders/trends` |
| `get_asin_traffic_trends` | `/v1/asins/trafficScore/trend/daily` |
| `get_asin_traffic_trends_weekly` | `/v1/asins/trafficScore/trend/weekly` |
| `get_asin_traffic_trends_monthly` | `/v1/asins/trafficScore/trend/monthly` |
| `get_asin_ad_change_trends` | `/v1/asins/advertisingChange/trends/daily` |
| `get_asin_keywords` | `/v1/asins/research/list/period` |
| `get_asin_keywords_monthly` | `/v1/asins/research/list/monthly` |
| `get_asin_keyword_traffic_trends` | `/v1/asinSearchTerms/traffic/trend/daily` |
| `get_asin_keyword_rank_trends` | `/v1/asinSearchTerms/rank/trends/daily` |
| `get_asin_keyword_rank_hourly` | `/v1/asinSearchTerms/rank/trends/hourly` |
| `get_keyword_info` | `/v1/searchTerms/info` |
| `get_keyword_aba_trends` | `/v1/searchTerms/abaReport/trends/weekly` |
| `get_keyword_asin_analysis` | `/v1/searchTerms/analysis/list/period` |
| `get_keyword_analysis_monthly` | `/v1/searchTerms/analysis/list/monthly` |

### 4.2 MCP 扩展或公开目录未展示的 7 项

| MCP 工具 | 判断 |
|---|---|
| `get_asin_keywords_daily` | 公开目录只有最近 7 天和月度接口；该日级范围工具需向西柚确认底层路径和 VIP 可用性 |
| `get_asin_keyword_count_trends` | 可能是聚合接口或 MCP 派生结果；公开目录未列出 |
| `get_keyword_advertising_replay` | 公开目录未列出，且仅支持 US/UK/DE |
| `get_multi_asin_keyword_comparison` | 可能由多个 ASIN 反查结果合并；需确认是否按多次底层调用计费 |
| `get_multi_asin_keyword_comparison_monthly` | 同上，需确认分页、月份和 Credit 计算方式 |
| `get_parent_asin_keywords` | 可能组合变体查询和多 ASIN 反查；需确认失败与部分成功语义 |
| `get_parent_asin_keywords_monthly` | 同上，需确认父体子体数量上限和 Credit 计算方式 |

这些工具不能仅凭 MCP 名称假设存在一一对应的公开接口。申请 VIP 前应向西柚索取准确路径、请求 Schema、计费公式和响应示例。

### 4.3 已下线能力

官方 Release Notes 显示市场洞察类接口在 2026-07-28 上线后，于 2026-08-06 全部下线。当前 MCP 也未暴露市场洞察工具，因此不纳入本次设计。

---

## 五、项目现状与兼容性

### 5.1 现有实现的定位

当前 `opscli/xiyou` 已经包含请求模型、场景定义、网页端 Client、任务管理、凭证读取和 Excel/JSON 导出，适合继续作为西柚业务模块的归属目录。但现有 `XiyouApiManager` 同时承担参数归一化、接口编排、轮询、导出和网页端异常处理，不能直接作为多数据源抽象。

现有入口目前是关闭的：

- `opscli/cli.py` 中 `xiyou` Typer 注册被注释。
- `opscli/mcp/server.py` 未注册 `opscli/mcp/tools/xiyou.py`。
- `configs/mcp-quota.json` 中 `xiyou_run.enabled=false`。
- 现有测试明确断言相关 MCP Tool 不对外暴露。

因此首期接入不能只修改配置打开旧入口。应先建立统一契约，再按明确的 allowlist 开放经过验证的 operation。

### 5.2 可直接复用的基础设施

| 现有模块 | 复用方式 |
|---|---|
| `opscli/mcp/upstream.py` | MySQL 临时方案复用其 Streamable HTTP、DNS 固定、Host/Port 和响应大小限制实现，不复用 `pnd` 的静态配置入口 |
| `opscli/api_credentials` | 试用期管理 `provider=xydc_mcp` 的 MCP URL/API Key 和额度状态；VIP 阶段另建 `provider=xydc_openapi` |
| `opscli/xiyou/export` | 继续负责标准结果的 Excel 导出；新增字段时由 operation 定义列映射 |
| `opscli/xiyou/credentials.py` | 仅保留给网页通道的 JWT/Cookie，不能存放 OpenAPI Key |
| `opscli/mcp/quota.py` 与 `configs/mcp-quota.json` | 控制 opscli 对外工具配额；不能替代西柚 Credit 预算 |
| `opscli/mcp/tool_catalog.py` | 在 operation 稳定后登记对外 MCP Tool，不直接暴露供应商原始工具 |

### 5.3 需要隔离的差异

1. **认证不同**：MCP 使用供应商 MCP 连接认证；OpenAPI 使用 `X-Auth-Version: 2.0` 和 `X-Api-Key`；网页通道使用 JWT/Cookie。
2. **路径不同**：OpenAPI 是 `https://openapi.xydc.com/v1/...`；网页通道是 `https://api.xydc.com/v2|v3|v4/...`。
3. **请求 Schema 不同**：MCP 参数接近业务语义，OpenAPI 和网页端各有自己的分页、周期、站点和排序字段。
4. **响应 Schema 不同**：数字可能是字符串，列表和分页字段位置不同，网页端还存在资源生成与轮询下载流程。
5. **计费语义不同**：MCP 在响应体返回 `cost_credits`；OpenAPI 文档定义响应头 `X-Cost-Credits` 和 `X-Trace-Id`，实际结算与异常场景仍需 VIP 开通后实测；网页通道没有同一套 Credit 回执。
6. **能力覆盖不同**：不能以某个 Adapter 的能力全集定义 opscli 的业务契约，必须逐 operation 声明支持矩阵。

---

## 六、推荐模块设计

### 6.1 总体结构

```text
CLI / opscli MCP Tools / Skills
              |
       XiyouQueryService
        |             |
 OperationRegistry  ProviderRouter
                      |
       +--------------+---------------+
       |              |               |
 xydc_mcp       xydc_openapi      xiyou_web
  Adapter          Adapter           Adapter
```

外部入口只依赖 `XiyouQueryService`。Adapter 负责供应商协议转换，Router 负责按 operation、配置和故障类型选择来源，Registry 负责描述能力而不是执行网络请求。

建议逐步整理为：

```text
opscli/xiyou/
  domain/
    operations.py       # operation 常量、OperationSpec、能力限制
    requests.py         # 标准请求与分页/周期模型
    results.py          # 标准结果、来源和 Credit 元数据
    exceptions.py       # 可路由的错误分类
  providers/
    base.py             # XiyouProvider Protocol
    mcp.py              # xydc MCP Adapter
    openapi.py          # xydc OpenAPI Adapter
    web.py              # 现有网页接口包装
  services/
    query_service.py    # 查询、缓存、审计入口
    router.py           # 来源选择和有限回退
  registry.py           # 28 个 operation 的静态注册表
```

现有 `api/client.py`、`api/payloads.py`、`api/scenarios.py` 和 `services/api_manager.py` 先作为 `xiyou_web` 的内部实现保留，再逐步把通用参数和结果模型上移，不建议一次性重写。

### 6.2 稳定 Provider Interface

Provider Interface 应保持小而深，不为 28 个工具各写一组公开方法：

```python
class XiyouProvider(Protocol):
    name: str

    def supports(self, operation: str) -> bool: ...

    async def execute(
        self,
        operation: str,
        request: XiyouQueryRequest,
    ) -> XiyouQueryResult: ...
```

标准请求至少包含：

- `country`
- `asins`、`keyword` 等 operation 专属参数
- `start_date/end_date`、`start_month/end_month`、`start_week/end_week`
- `page/page_size/sort_field/sort_order`
- `source=auto|xydc_mcp|xydc_openapi|xiyou_web`
- `max_credits` 和 `allow_fallback`

标准结果至少包含：

- `operation`、`items`、`total`、`page`、`page_size`
- `source`、`provider_request_id`、`fetched_at`
- `cost_credits`、`cache_hit`
- `raw_metadata`，仅保存非敏感且确有诊断价值的供应商元数据

业务行数据初期可以保留为 `dict[str, Any]`，但分页、来源、时间、Credit 和错误必须标准化。否则上层仍会被不同供应商响应结构绑死。

### 6.3 Operation Registry

28 个数据工具应全部登记为 canonical operation。每项静态声明：

- 标准 operation 名称和中文说明
- 请求参数、必填条件和格式
- 支持的国家、最大 ASIN 数、最大日期跨度
- 各 Adapter 是否支持，以及对应的 MCP 工具名或 OpenAPI 路径
- 分页方式、默认排序和结果提取规则
- 是否可能产生组合调用
- 缓存 TTL 和是否缓存空结果
- 预计 Credit、实际 Credit 的提取方式
- 允许回退的错误类别

Registry 是兼容层的核心。CLI 参数、MCP Tool Schema、文档和 Adapter 校验都应从这里派生或至少共享同一份定义，避免三套入口分别维护。

### 6.4 三个 Adapter 的责任边界

**xydc MCP Adapter**

- 通过 `ApiCredentialPool.acquire("xydc_mcp")` 领取包含连接 metadata 和 API Key 的账号租约。
- 复用 `opscli/mcp/upstream.py` 的安全 Streamable HTTP Transport 能力，但不读取 `mcp-upstreams.json`。
- 使用冻结 Schema 和 allowlist，不在启动时无条件导入供应商全部未知工具。
- 仅在明确识别周额度耗尽或 Key 无效时切换账号，禁止在不确定是否扣费的异常后切换。
- 将 `status/cost_credits/data` 转成标准结果。
- 供应商 MCP 工具只作为内部来源；opscli 对外仍暴露自己的稳定名称和 Schema。

**xydc OpenAPI Adapter**

- 使用独立的 `httpx.AsyncClient` 和 `https://openapi.xydc.com` Base URL。
- 从 `ApiCredentialPool` 获取 `provider=xydc_openapi` 的 Key，并设置官方要求的两个 Header。
- 按 operation 处理路径、请求体、分页和响应归一化。
- 提取 `X-Cost-Credits`、`X-Trace-Id` 和 429 场景的 `Retry-After`。
- 将 HTTP、业务码、额度、限流和超时转换成标准错误，禁止把原始 Key 写入日志或导出。

**xiyou Web Adapter**

- 包装现有 `XiyouApiManager`/`XiyouApiClient`，不把网页端 payload 泄漏到统一 Interface。
- 只声明已经有可靠映射的 operation；旧版额外能力可以保留为 legacy operation。
- 标记为不稳定补充源，继续使用现有 token 失效通知和资源轮询逻辑。

---

## 七、路由与回退规则

### 7.1 默认路由

| 阶段 | `auto` 主来源 | 补充来源 |
|---|---|---|
| MCP 试用期 | `xydc_mcp` | `xiyou_web`，仅限 Registry 明确允许 |
| VIP 上线后 | `xydc_openapi` | `xiyou_web`，仅限能力缺失或主来源在发起请求前不可用 |
| 人工核验 | 用户显式指定 `xydc_mcp` | 不自动回退 |

VIP 上线后不建议把 MCP 设为 OpenAPI 的自动第二来源。两者很可能最终消费同一供应商额度，静默重试会造成重复计费和结果难以追责。MCP 应保留为契约核验、灰度对比和 MCP-only 能力来源。

### 7.2 可以考虑回退的情况

- 当前 Adapter 在 Registry 中不支持该 operation。
- Adapter 在发送供应商请求前即不可用，例如未配置、连接未启动或熔断已打开。
- 收到可明确判定为供应商服务不可用且可确认未计费的错误。
- 组合能力中某个子能力缺失，并且 operation 明确定义了可接受的降级结果。

### 7.3 禁止自动回退的情况

- 成功响应但列表为空、流量为 0 或字段为 `null`。
- 400 参数错误或日期、站点、分页范围不合法。
- 401、404 等 Key 无效、未开通接口或鉴权错误。
- 403、Credit 不足、套餐限制或账号状态错误。
- 请求已经发出后的读取超时或其他是否扣费不明确的异常。
- 用户显式选择了来源。

每次结果必须返回实际 `source`。发生回退时还要记录 `attempted_sources` 和非敏感 `fallback_reason`，不能让调用方误以为数据来自主来源。

---

## 八、缓存、Credit 与可观测性

### 8.1 缓存

缓存键使用规范化后的 `operation + source + country + 业务参数 + 时间范围 + 分页/排序`，不能直接散列供应商原始 payload。

- 当前快照建议短 TTL，并包含合法空结果。
- 已结束的日、周、月历史可以使用较长 TTL。
- 当日小时排名和广告放映机使用短 TTL，避免把未完整采集的一天长期缓存。
- 参数、鉴权、额度和供应商故障不进入数据缓存。
- 不同来源默认不共享缓存，避免来源切换后无法判断数据差异。

### 8.2 Credit 治理

1. 调用前由 Registry 给出预计成本或“未知”。
2. 当 `max_credits` 小于预计成本时在本地拒绝调用。
3. MCP 调用后记录供应商返回的 `cost_credits`。
4. OpenAPI 读取官方 `X-Cost-Credits` 响应头，并在上线前实测成功、空结果、分页、错误和超时场景的回执与结算行为。
5. 多 ASIN、父体和多周期工具必须在调用前展示或记录潜在放大倍数。
6. 自动回退前重新执行预算检查，并阻止不确定是否已扣费后的第二次请求。

### 8.3 审计字段

建议每次调用记录：`operation`、`source`、参数指纹、国家、时间范围、请求数量、耗时、缓存命中、结果数量、实际/估算 Credit、错误类别和供应商请求 ID。日志不得保存 API Key、JWT、Cookie 或完整用户业务意图。

---

## 九、分阶段实施建议

### 阶段 0：补齐供应商信息

在编码前确认 MCP Server URL、Transport、认证方式、是否允许部署在 opscli 服务端、并发限制、Credit 规则和 Tool Schema 稳定性。当前聊天环境中能调用 xydc MCP，不等于 opscli 运行环境已经获得可配置的远程 MCP 凭据。

### 阶段 1：建立契约并接入 8 个首批 operation

先实现 Registry、标准 Request/Result、错误分类和 `xydc_mcp` Adapter，再通过内部 CLI 或测试入口验证。建议首批为：

| operation | 首批原因 |
|---|---|
| `get_asin_info` | 最低成本地验证商品基础字段和批量 ASIN |
| `get_asin_traffic` | 验证零值、自然/广告拆分和比例字段 |
| `get_asin_orders_last_30_days` | 验证批量订单快照 |
| `get_asin_variations` | 为父体组合能力建立基础 |
| `get_asin_keywords` | 覆盖现有“西游找词”核心场景 |
| `get_keyword_info` | 验证关键词容量、ABA 和 CPC 字段 |
| `get_keyword_asin_analysis` | 验证大分页竞争 ASIN 场景 |
| `get_keyword_aba_trends` | 验证周粒度、长时间范围和 Top 3 数据 |

这 8 项覆盖商品、销量、流量、关键词、竞争和趋势，又避开首期自行组合父体/多 ASIN 结果的高风险逻辑。

### 阶段 2：小范围启用

- 只开放首批 allowlist，不直接启用全部 28 项。
- 加入缓存、`max_credits`、审计和按 operation 配额。
- 对 MCP 原始响应建立契约样本测试，覆盖空结果、数字字符串、分页和错误。
- 恢复 CLI/MCP 注册时使用新的查询服务，不直接重新打开旧 `xiyou_run`。

### 阶段 3：接入 VIP OpenAPI

- 新增 `provider=xydc_openapi` 的 API Credential 配置和池化读取，与临时 MCP 账号隔离。
- 逐项实现 21 个公开 OpenAPI 映射，并用相同请求样本对比 MCP 结果。
- 灰度期间显式选择来源进行差异报告，不在一次业务调用中双查。
- 验证稳定后把 `auto` 主来源切为 `xydc_openapi`。

### 阶段 4：网页通道收口

- 将现有 16 个 function 映射到 canonical operation 或标记为 legacy。
- 只给经过验证的 operation 开启有限回退。
- 网页端独有且仍有业务价值的能力保留，不再作为正式接口 Schema 的定义来源。

### 阶段 5：扩展 MCP-only 与组合能力

在供应商确认计费和底层语义后，再接入 7 个公开目录未展示的能力。若这些能力实际由多个公开接口组合，优先在 opscli 侧透明实现并明确 Credit 估算，不依赖不可解释的黑盒结果。

---

## 十、申请 VIP 或正式开发前的确认清单

需要向西柚确认：

1. MCP 的生产 Server URL、Transport、认证方式，以及是否允许公司服务端长期连接。
2. MCP 试用 Credit 与 OpenAPI VIP Credit 是否共用账户、是否按请求或按结果计费。
3. 超时、5xx、空结果、分页下一页和批量 ASIN 的扣费规则。
4. OpenAPI 每个接口的限流、并发、日限额、最大分页和时间跨度。
5. OpenAPI 的 `X-Cost-Credits` 在错误、超时和异步结算场景中的准确含义，及 `X-Trace-Id` 的追踪保留周期。
6. 7 个 MCP 扩展能力是否存在未公开 OpenAPI、何时开放、如何计费。
7. `get_asin_ad_change_trends` 是否只表示新增观测，能否提供停止/移除状态。
8. Tool Schema 和 OpenAPI 版本的变更通知、废弃周期及测试环境。
9. 数据授权范围、缓存期限、内部二次加工和导出限制。

## 十一、资料索引

- [西柚 OpenAPI 文档首页](https://openapi-doc.xydc.com/)
- [西柚 OpenAPI 接口目录 Markdown](https://openapi-doc.xydc.com/9065291m0.md)
- [西柚 OpenAPI llms.txt](https://openapi-doc.xydc.com/llms.txt)
- [西柚 OpenAPI Release Notes](https://openapi-doc.xydc.com/8718788m0.md)
- 项目现有实现：`opscli/xiyou/`
- 上游 MCP 网关：`opscli/mcp/upstream.py`
- API Key 凭证池：`opscli/api_credentials/`

---

## 十二、MCP 试用接入路径

### 12.1 临时方案：MySQL 连接账号池

根据当前决策，xydc MCP 试用链路不依赖鹰眼 `pnd` 的部署侧 `mcp-upstreams.json`。Endpoint 在 Provider 代码中固定为 `https://mcp.xydc.com/mcp`；MySQL 凭证池只保存 API Key、账号优先级和额度状态，由专用的 `XydcMcpProvider` 读取。

```text
ext_xydc_* Tools
       |
XydcMcpProvider
       |
ApiCredentialPool.acquire(provider="xydc_mcp")
       |
账号 A -> 账号 B -> 账号 C
```

这是一条明确的临时适配链路：VIP OpenAPI 上线后关闭 `provider=xydc_mcp`，不要求它演化成通用第三方 MCP 配置中心，也不修改鹰眼 `pnd` 的现有行为。

### 12.2 MySQL 字段约定

现有凭证表可以复用，只需把 `xydc_mcp` 加入 Provider 白名单。固定 Endpoint 不进入凭证租约，也不进入账号 metadata。

| MySQL 字段 | xydc MCP 用途 |
|---|---|
| `api_provider_accounts.provider` | 固定为 `xydc_mcp`，与后续 `xydc_openapi` 分开 |
| `account_name` | 人工可识别的试用账号别名 |
| `priority` | 账号选择优先级，同优先级按最久未选择优先 |
| `status` | `active/exhausted/invalid/disabled/deleted` |
| `api_account_credentials.secret_value` | 只保存 `mcp_xxxxxx`，不包含 `Bearer ` 前缀，不放进 URL 或 metadata |
| `api_account_runtime.provider_metadata` | 只保存最近一次 Credit 等非敏感运行信息，不保存 Endpoint |
| `remaining_quota/current_usage` | 供应商能返回时记录周额度状态 |
| `quota_reset_at` | 周额度恢复时间 |
| `cooldown_until` | 短期限流或账号冷却时间 |
| `last_error_code/last_error_message` | 脱敏后的最近错误 |

建议 metadata 形态：

```json
{
  "last_cost_credits": 1
}
```

API Key 只从租约的 `secret` 读取，运行时固定组装为 `Authorization: Bearer <secret>`。`provider_metadata` 会出现在管理摘要中，因此严禁把 Key、Cookie、完整 Authorization 或带 Token 的 Query URL 写进去。

### 12.3 URL 与认证安全边界

Endpoint 不接受数据库或用户输入，运行时只访问代码中固定的西柚地址：

- 只允许 HTTPS Streamable HTTP MCP
- 固定使用 `https://mcp.xydc.com/mcp`
- 禁止从 MySQL、命令参数或供应商响应覆盖 Host、端口、Query 和 Fragment
- 禁止跟随重定向，避免 Bearer Header 被转发到其他地址
- 认证方式固定为 `Authorization: Bearer <token>`，不从数据库读取 Header 名或认证类型
- 不兼容 `?mcp_token=...` URL

这样保留 MySQL 临时配置的便利性，同时不丢失现有上游网关的 SSRF 防护。

### 12.4 多账号选择与切换

现有 `ApiCredentialPool` 已经支持领取 `active` 账号、排除本次已尝试账号、标记 `exhausted/invalid` 和查询到期的耗尽账号，可以直接复用其状态模型。

单次业务调用的选择流程：

1. 领取一个 `provider=xydc_mcp` 的账号租约。
2. 使用该账号的 URL 和 API Key 创建独立 MCP Session。
3. 成功时记录 `cost_credits`、剩余额度和最近使用时间。
4. 只有收到已确认的“周额度耗尽”业务码时，才标记 `exhausted`、写入 `quota_reset_at` 并领取下一个账号。
5. API Key 明确无效时标记 `invalid`，可以领取下一个账号。
6. 单次请求最多切换有限账号数，建议初始上限为 3。
7. 全部账号不可用时返回统一的 `XYDC_MCP_ACCOUNTS_UNAVAILABLE`，并附最早可恢复时间。

以下情况禁止切换账号：成功空结果、零流量、参数错误、普通业务错误、5xx、连接异常、读写超时，以及尚未确认语义的 429。请求可能已经到达供应商时切换账号，可能产生重复 Credit 消耗。

额度到达 `quota_reset_at` 后，可以利用现有 `next_due_exhausted()` 选择待复查账号；复查成功再恢复为 `active`，不能只按时间直接假定额度已经恢复。

### 12.5 首批开放范围

第一批只开放已经完成实际试调并确认单次消耗 1 Credit 的 4 个工具：

| 远端工具 | opscli 暴露名称 |
|---|---|
| `get_asin_info` | `ext_xydc_get_asin_info` |
| `get_asin_traffic` | `ext_xydc_get_asin_traffic` |
| `get_keyword_info` | `ext_xydc_get_keyword_info` |
| `get_keyword_asin_analysis` | `ext_xydc_get_keyword_asin_analysis` |

第二批再增加 `get_asin_orders_last_30_days`、`get_asin_variations`、`get_asin_keywords` 和 `get_keyword_aba_trends`。每个工具都应先保存一次成功、空结果和参数错误的脱敏契约样本，再进入部署 allowlist。

首期不开放多 ASIN 对比、父体聚合、长周期趋势和广告放映机。这些能力的调用放大、分页和 Credit 规则尚未验证。

### 12.6 “测试中”的落点

Tool Schema 继续冻结在代码或版本化 Registry 中，不存 MySQL，也不动态透传供应商 `tools/list`。当前 Tool Catalog 只同步 `name`、`module` 和 `description`，没有独立的 lifecycle/status 字段。首期采用三层标识：

1. 所有工具描述以 `【测试中｜消耗西柚 Credit】` 开头，并写明只有用户明确要求西柚/xydc 数据时才调用。
2. 模块名固定为 `external_xydc`；在 OPS 后台把该模块的人工 label 设置为“西柚（测试中）”。现有同步逻辑只刷新 description，不会覆盖人工 label 和 `is_active`。
3. 只向测试用户或测试角色开放 `ext_xydc_*` 权限，不进入普通用户默认工具集，也不加入任何自动数据源路由。

如果后续需要按 Beta/GA 状态筛选、灰度和自动下线，应再扩展 Tool Catalog 与后端 `/v1/mcp/sync-tools` 合同，增加结构化 `lifecycle` 字段；首期不为一个供应商提前扩大公共合同。

### 12.7 配额与 Credit 风险

xydc Tool 仍经过 `quota_wrap`，但当前 `QuotaLimiter` 从 SQLite 表 `mcp_quota_policy` 读取用户调用策略；没有策略的工具会直接放行。MySQL 账号池解决的是供应商账号额度，SQLite 解决的是 opscli 用户调用次数，两者职责不同。

首期必须给 4 个 `ext_xydc_*` 工具写入启用策略，统一使用 `service=xiyou` 和相同的低日限额。因为每日记录按 service 聚合，相同 service 可以形成“所有西柚工具合计 N 次/日”，而不是每个工具各 N 次。

调用次数不等于 Credit。当前通用限额只能限制调用次数，不能从返回结果中的 `cost_credits` 扣减用户 Credit 预算。因此试用阶段还应：

- 使用低余额或可控的共享试用账号
- 初始并发设为全局 2、单用户 1
- 先把总调用限额设得很低
- 记录返回中的 `cost_credits`，每天人工核对供应商余额
- 禁止自动重试、自动回退和后台批量任务

若要正式开放，需要让上游 Runtime 提取 `cost_credits` 并落入独立的 Credit Ledger；不能把现有“调用次数限额”当成真实成本控制。

### 12.8 部署与验收顺序

1. 确认供应商 MCP URL、API Key Header、额度耗尽错误码和服务端使用授权。
2. 给 `api_credentials` 增加 `xydc_mcp` Provider，继续复用现有无 metadata 的凭证租约。
3. 复用现有 API Credential 账号管理命令，只写入 API Key、优先级和备注；输出永不回显 Key。
4. 实现 `XydcMcpProvider`，复用现有账号领取、状态回写和安全 HTTP Transport。
5. 在代码 Registry 中冻结首批 4 个 Tool Schema，并注册为 `ext_xydc_*`。
6. 向 SQLite `mcp_quota_policy` 幂等写入首批工具策略，不能依赖空库初始化。
7. 在 OPS 后台设置“西柚（测试中）”标签，只给测试角色授权。
8. 每个账号和工具执行最小 smoke 调用，核对账号切换、`cost_credits`、遥测、配额和供应商余额。
9. 观察一段试用期后再决定第二批工具和 VIP OpenAPI 开发顺序。

### 12.9 与后续正式架构的边界

`ext_xydc_*` 和 `provider=xydc_mcp` 应明确视为试用期能力，不作为 opscli 长期业务合同，也不应被正式 Skill 大量硬编码依赖。

VIP OpenAPI Adapter 和统一 `XiyouQueryService` 完成后，对外应切换到 provider-neutral 的稳定 Tool，例如一个统一 `xiyou_query(operation=..., source=...)`，或一组从 Operation Registry 生成的 `xiyou_*` Tool。此时：

- `source=xydc_mcp` 调用临时 MySQL MCP 账号池
- `source=xydc_openapi` 调用正式 OpenAPI Adapter
- `source=xiyou_web` 调用现有网页端补充能力
- `ext_xydc_*` 降为管理员核验工具或逐步下线

VIP 上线后停止新建 `xydc_mcp` 账号，禁用相关 Tool 权限，确认没有运行中调用后把账号状态设为 `disabled/deleted`；OpenAPI Key 使用独立的 `provider=xydc_openapi`，不能复用或覆盖 MCP 记录。这样可以低成本试用 MCP，又不会让临时账号池成为后续长期负担。

---

## 十三、最终建议

先把“西柚能力”抽象成 opscli 自己的 28 个 operation 清单，再接 MCP，而不是直接开放供应商的 28 个 Tool。试用接入首批只代理 4 个已实测工具，第二批再扩展 4 个核心工具；VIP 开通后补 OpenAPI Adapter 并切换主路由；网页端现有实现保留为明确、有限、可追踪的补充来源。

首批 MCP 试用通道已经完成；后续正式 OpenAPI 开发的外部阻塞项是 VIP 开通、准确接口权限和计费合同。统一 Registry、OpenAPI Adapter 及网页补充通道收口可按试用结果继续推进。

## 十四、首批实现验证记录

2026-09-09 已完成首批试用通道实现：

- Endpoint 固定为 `https://mcp.xydc.com/mcp`，认证固定为 `Authorization: Bearer <token>`，禁止重定向和 Query Token。
- `xydc_mcp` 与未来 `xydc_openapi` 已加入 MySQL Provider 白名单；MySQL 不保存 Endpoint。
- 已注册 4 个 `ext_xydc_*` 测试工具，并通过 `service=xiyou` 的共享每日 10 次用户限额控制。
- 多账号只在结构化额度耗尽、HTTP 402、结构化 Token 无效或 HTTP 401 时切换；429、403、5xx、超时、连接错误、参数错误和空数据均不切换。
- 使用 `D:\Gitlab\.xiyou` 中两枚独立 Token 分别调用 `get_asin_info`，均返回 `status=200`、`cost_credits=1`；测试输出未包含 Token。
- 首次冒烟暴露并修复了成功状态为整数 `200` 的合同差异；该诊断过程额外产生 5 次低成本 `get_asin_info` 调用，共消耗 5 Credits。

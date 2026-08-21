# Keepa Tracking 监控能力与限制

> 调研日期：2026-08-21  
> 调研范围：Keepa Tracking API、Tracking Object、Tracking Creation Object、Notification Object。  
> 本文只梳理官方能力与接入建议，不调用真实 Keepa API，也不包含实现改动。

## 1. 结论摘要

Keepa Tracking 是由 Keepa 持续刷新商品并在条件满足时产生通知的托管监控能力，不等同于定时调用 Product API。它可以监控价格或数值阈值、缺货/到货、Tracking 过期等事件，并通过 webhook 推送或 `/tracking?type=notification` 拉取通知。

- **没有官方公布的固定 ASIN 数量上限**。官方口径是“可跟踪数量取决于 token refill rate”；每条 Tracking 会持续降低 refill rate，降到 0 后不能继续新增 Tracking，也不能调用其他需要 token 的 API。
- 单次 Add 请求最多提交 **3,000** 个 Tracking Creation Object；`list` 不分页时单批最多返回 **500,000** 条，显式分页时 `perPage` 最大 **100,000**。这些是请求/返回批量上限，不能据此理解为账户最多只能监控 500,000 个 ASIN。
- Regular Tracking 每次更新、每个站点降低 **0.9 token**；Marketplace Tracking 为 **9 token**。更新频率越高、站点越多、Tracking 类型越重，可监控数量越少。
- 新增或覆盖 Tracking 的请求成本是 **1 token/条**；读取、删除、通知拉取、列表查询、设置 webhook 的请求成本为 0，但现存 Tracking 仍持续占用 refill rate。
- 通知只保留 **24 小时**。轮询默认最多返回 **2,000** 条；webhook 失败只会在 15 秒后重试一次，因此生产方案应使用“webhook 主推 + `readOnly=1`/游标补偿轮询 + `notificationId` 去重”。
- 当前 `opscli` **尚未提供 Tracking MCP Tool**。若后续接入，应作为独立、有状态且包含写操作的子域，不应塞进现有只读 `keepa_run` 场景。

官方来源：[Tracking API](https://keepa.com/api-docs/tracking.html)、[Tracking Object](https://keepa.com/api-docs/tracking-object.html)、[Tracking Creation Object](https://keepa.com/api-docs/tracking-creation-object.html)、[Notification Object](https://keepa.com/api-docs/notification-object.html)。

## 2. 数量限制与额度消耗

### 2.1 数量不是固定上限，而是 refill rate 预算

官方明确说明：每个被跟踪商品都会降低 token refill rate；当 refill rate 降到 0 时，既不能再添加 Tracking，也不能执行其他需要 token 的 API 请求。官方没有给出“某套餐固定可跟踪 N 个 ASIN”的表，而是说明可跟踪数量由 token rate 决定。[Tracking API - Token Cost](https://keepa.com/api-docs/tracking.html#token-cost)

持续占用量可按以下方式理解：

```text
Regular 每分钟降低量
= Tracking 数 × 站点数 × 0.9 ÷ updateInterval(小时) ÷ 60

Marketplace 每分钟降低量
= Tracking 数 × 站点数 × 9 ÷ updateInterval(小时) ÷ 60
```

Keepa 的 refill rate 是整数，最终 reduction 会四舍五入。API 响应中的 `tokenFlowReduction` 可观察当前降速，但新增或删除后约每 **5 分钟**才更新，不适合拿刚写入后的即时值做强一致性校验。[Tracking API - Token Cost](https://keepa.com/api-docs/tracking.html#token-cost)

官方示例：

| 配置 | 计算结果 | refill rate 降低量 |
| --- | --- | --- |
| 2,000 条 Regular、1 个站点、每 1 小时更新 | `2000 × 0.9 / 1 = 1800 token/小时` | 30 token/分钟 |
| 700 条 Marketplace、1 个站点、每 12 小时更新 | `700 × 9 / 12 = 525 token/小时` | 四舍五入为 9 token/分钟 |

### 2.2 明确的批量和列表限制

| 限制项 | 官方限制 | 说明 |
| --- | --- | --- |
| 单次新增/更新 | 最多 3,000 条 | 批量应使用 POST；GET 会受 URL 长度限制。[Add Tracking](https://keepa.com/api-docs/tracking.html#add-tracking) |
| `list` 默认返回 | 最多 500,000 条 | 不传 `perPage` 时整批返回；这是单批返回上限，不是明确的账户总容量上限。[Get Tracking](https://keepa.com/api-docs/tracking.html#get-tracking) |
| `list` 分页大小 | `perPage` 最大 100,000 | `page` 从 0 开始，直到返回空数组。[Get Tracking](https://keepa.com/api-docs/tracking.html#get-tracking) |
| `asins-only=1` | 返回完整 ASIN 列表 | 此模式忽略分页参数，适合轻量盘点。[Get Tracking](https://keepa.com/api-docs/tracking.html#get-tracking) |
| 命名列表数 | 最多 100,000 个 | 超出需联系 Keepa；列表名最长 64 字符。[Named Tracking Lists](https://keepa.com/api-docs/tracking.html#named-tracking-lists) |
| 通知默认单次返回 | 最多 2,000 条 | `all=1` 可解除该次上限；结果按最新优先。[Get Notifications](https://keepa.com/api-docs/tracking.html#get-notifications) |
| 通知保留期 | 24 小时 | 到期删除，不能把 Keepa 当长期通知仓库。[Notification Object](https://keepa.com/api-docs/notification-object.html) |

### 2.3 请求 token 与持续成本

| 操作 | 请求 token 成本 | 是否改变账户状态 |
| --- | ---: | --- |
| `add` | 1/条 | 是；新增、覆盖或重新激活 Tracking |
| `remove` / `removeAll` | 0 | 是；删除单条、整表或命名列表 |
| `get` / `list` | 0 | 否 |
| `notification` | 0 | 默认会把返回通知标记为已读 |
| `listNames` | 0 | 否 |
| `webhook` | 0 | 是；修改账户 webhook URL |

来源：[Tracking API - Operations](https://keepa.com/api-docs/tracking.html#operations)。

## 3. 能监控什么

### 3.1 Regular 与 Marketplace Tracking

官方将 Tracking 分为两档：[Types of Tracking](https://keepa.com/api-docs/tracking.html#types-of-tracking)

| 类型 | 可监控对象 |
| --- | --- |
| Regular | Amazon、New、Used、List Price、Collectible、Refurbished、Lightning Deal、所有 Offer 数量、Sales Rank |
| Marketplace | 包含 Regular 全部能力，另含 Warehouse Deals、Buy Box New/Used、第三方 FBA/FBM、Rating、Prime Exclusive、Review Count、所有 Used/Collectible 成色及运费 |

Marketplace Tracking 使用商品最前面的 **20 个 offers** 参与监控。其持续成本是 Regular 的 10 倍，因此只有确实需要 Offer、Buy Box、评分或成色级数据时才值得启用。

### 3.2 触发规则

一个 Tracking Creation Object 可以同时包含多个站点、多个价格类型和多种触发规则：[Tracking Creation Object](https://keepa.com/api-docs/tracking-creation-object.html)

| 规则 | 字段 | 能力 |
| --- | --- | --- |
| 阈值监控 | `thresholdValues[]` | `thresholdValue` 指定最小货币单位整数；`domain` 指定站点；`csvType` 指定价格/数值类型；`isDrop=true` 监控下降，`false` 监控上升 |
| 库存状态 | `notifyIf[]` | `notifyIfType=0` 为 OUT_OF_STOCK；`1` 为 BACK_IN_STOCK |
| Tracking 过期/系统移除 | `expireNotify` | Tracking 到期或商品被系统移除时通知 |
| 监控有效期 | `ttl` | 正整数为小时；0 永不过期；负数在覆盖旧 Tracking 时保留原 TTL，新建时取绝对值 |
| 更新频率 | `updateInterval` | 创建对象允许 1-24 小时；越短越及时、持续 token 成本越高 |
| 重新触发间隔 | `individualNotificationInterval` | `-1` 使用账户默认值；0 表示同一目标价只通知一次；正整数表示多少分钟后重新武装 |
| 业务关联 | `metaData` | 最长 500 字符，可保存内部用户/任务引用；会随通知原样返回 |

价格统一由 `mainDomainId` 确定主币种。`desiredPricesInMainCurrency=true` 表示阈值已经按主站点币种提交；若为 false，Keepa 会转换。Tracking Object 官方页还说明，一个 Tracking 可包含多个 Amazon locale 的阈值。[Tracking Object](https://keepa.com/api-docs/tracking-object.html)

### 3.3 通知原因

Notification Object 的 `trackingNotificationCause` 目前定义为：[Notification Object - TrackingNotificationCause](https://keepa.com/api-docs/notification-object.html#trackingnotificationcause)

| 值 | 原因 | 业务含义 |
| ---: | --- | --- |
| 0 | `EXPIRED` | Tracking 已过期 |
| 1 | `DESIRED_PRICE` | 首次达到目标价/阈值 |
| 3 | `PRICE_CHANGE_AFTER_DESIRED_PRICE` | 达标后价格发生变化，规则已重新武装但尚未再次跨阈值 |
| 4 | `OUT_STOCK` | 指定 `csvType` 变为缺货 |
| 5 | `IN_STOCK` | 指定 `csvType` 恢复有货 |
| 6 | `DESIRED_PRICE_AGAIN` | 超出阈值并重新武装后，再次达标 |

通知还带 `notificationId`、ASIN、标题、图片名、创建时间、触发站点、`csvType`、当时各类型价格/数值 `currentPrices[]`、投递渠道、`metaData` 和命名列表。`currentPrices` 使用 Product Object 的 price type 索引；无 Offer 时值为 `-1`，Tracking 过期通知中该字段为 `null`。[Notification Object - Fields](https://keepa.com/api-docs/notification-object.html#fields)

## 4. 创建、更新、读取与删除

### 4.1 创建与更新

- `type=add` 同时承担创建与更新：同一列表内已有相同 ASIN 时会**整体覆盖**原 Tracking；已停用 Tracking 会被重新激活。
- GET 和 POST 都支持单条，批量最多 3,000 条应使用 JSON POST。
- 成功返回 `trackings[]`；批量中部分失败时，`error` 会包含逗号分隔的失败 ASIN。
- Tracking API 的列表与 Keepa 网站账户的普通价格关注列表相互独立，只能通过 API 管理。[Tracking API](https://keepa.com/api-docs/tracking.html)

命名列表会隐式创建。默认使用未命名列表；除 `webhook` 外，所有 Tracking 操作都支持 `list` 参数。命名列表允许对同一 ASIN 保存多套不同 Tracking 规则；结合 Tracking Object 的“一 ASIN 一条”口径，应理解为**每个列表内每个 ASIN 一条，跨列表可重复**。[Named Tracking Lists](https://keepa.com/api-docs/tracking.html#named-tracking-lists)

### 4.2 读取

- `type=get&asin=...`：取单条 Tracking，响应仍是 `trackings[]` 数组。
- `type=list`：取整个列表，可用 `page/perPage` 分页。
- `type=list&asins-only=1`：只返回 `asinList`，且忽略分页，适合轻量核对监控池。
- `type=listNames`：返回 `trackingListNames[]`。

来源：[Get Tracking](https://keepa.com/api-docs/tracking.html#get-tracking)、[Get Named Lists](https://keepa.com/api-docs/tracking.html#get-named-lists)。

### 4.3 删除

- `type=remove&asin=...` 删除单条；目标不存在时返回 `error`。
- `type=removeAll` 清空默认列表；配合 `list` 可删除指定命名列表及其中 Tracking。
- 删除请求成本为 0，但 `tokenFlowReduction` 不会立即更新。

来源：[Remove Tracking](https://keepa.com/api-docs/tracking.html#remove-tracking)。

## 5. Notification 已读状态与可靠消费

`type=notification` 必须传 `since`（Keepa Time 分钟）和 `revise`：[Get Notifications](https://keepa.com/api-docs/tracking.html#get-notifications)

| 参数 | 含义 |
| --- | --- |
| `since` | 返回该 Keepa Time 分钟之后、仍在 24 小时保留期内的通知 |
| `revise=0` | 不请求已标记为读的通知，适合正常消费 |
| `revise=1` | 同时请求已经标记为读的通知，适合补偿和审计 |
| `readOnly=1` | 本次返回不标记为已读，适合预览、探测和“两阶段确认” |
| `all=1` | 解除默认 2,000 条上限，可能产生很大的响应 |

官方确认：通知通过 notification API 返回或成功推送到 webhook 后会被标记为已读。`readOnly=1` 可避免拉取产生该副作用。通知按最新优先排序，所以只保存“最新 createDate”作为游标可能漏掉同分钟通知或乱序补投；项目接入时应保存重叠时间窗，并以 `notificationId` 幂等去重。

后一句属于**项目推断**：官方只规定字段和排序，没有规定消费者游标算法。推荐游标策略是保存最近成功消费的 Keepa Time，同时每次向前重叠数分钟；数据库以 `notificationId` 建唯一键，再按 `createDate` 排序处理。

## 6. Webhook 与轮询方式

### 6.1 官方确认

- `type=webhook&url=...` 设置一个账户级 webhook URL；这是唯一不支持 `list` 参数的 Tracking 操作。
- 触发时 Keepa 以 HTTP POST 发送单个 Notification Object，Content-Type 为 `application/json`。
- 接收端必须返回 HTTP 200；失败后 Keepa 只在 **15 秒后再重试一次**。
- webhook 与 API pull 共用通知已读状态；webhook 投递后通知标记为已读。

来源：[Set Webhook](https://keepa.com/api-docs/tracking.html#set-webhook)。

### 6.2 推荐部署方式（项目建议）

```text
Keepa webhook
  -> 快速校验并持久化原始 Notification
  -> 立即返回 200
  -> 异步去重、格式化、关联业务对象和发送内部告警

补偿轮询（例如每 5-15 分钟）
  -> notification + since + revise=1 + readOnly=1
  -> notificationId 去重
  -> 补入 webhook 遗漏记录
```

不建议只用 webhook：官方只有一次延迟 15 秒的重试，而且通知 24 小时后删除。也不建议高频消费式轮询直接省略 `readOnly=1`：请求成功返回即改变已读状态，业务持久化若随后失败，恢复会更复杂。

## 7. 权限、数据与运行风险

### 7.1 官方确认的风险

| 风险 | 官方行为 | 建议 |
| --- | --- | --- |
| refill rate 被占满 | 到 0 后无法新增 Tracking，也无法调用需 token 的其他 API | 单独预算；在新增前计算预计 reduction，设置账户级水位线 |
| 降套餐或 API 终止 | 不足额 Tracking 会停用并在 7 天后删除；API 访问终止时列表也按此处理 | 每日盘点 `isActive` 和 `tokenFlowReduction`，保留本地期望配置用于重建 |
| Add 覆盖旧规则 | 相同 ASIN 的现有 Tracking 会被覆盖 | 写前读取并做版本/差异确认，完整而非局部提交 |
| `removeAll` 高破坏性 | 可清空整个列表或删除命名列表 | 只允许受控 CLI/Admin 管理面执行；要求显式列表名、二次确认和审计 |
| 通知短保留 | 24 小时后删除 | webhook + 持久化 + 补偿轮询，不依赖 Keepa 做历史库 |
| webhook 低重试 | 失败仅重试一次 | 先落盘再异步处理，监控接收端可用性 |
| `metaData` 回传 | 最长 500 字符，会出现在 Tracking 和通知中 | 不写邮箱、姓名、密钥等敏感信息，只放不可逆业务引用 ID |

官方来源：[Tracking API - Important](https://keepa.com/api-docs/tracking.html)、[Add Tracking](https://keepa.com/api-docs/tracking.html#add-tracking)、[Notification Object](https://keepa.com/api-docs/notification-object.html)。

### 7.2 项目接入推断

- Tracking 的 `add/remove/removeAll/webhook` 都会改变 Keepa 账户状态，应与只读 `get/list/listNames` 分成不同权限；`notification` 还需把 `readOnly=1` 设为默认，显式消费才允许标记已读。
- `webhook` 使用 GET 设置 URL，URL 可能进入代理、访问日志和审计记录；服务端不应把 Keepa key 或带凭证的回调 URL 输出到日志。
- 官方文档没有描述 webhook 签名或共享密钥机制。接收端应至少使用 HTTPS、不可猜测的回调路径、来源限速和 `notificationId` 幂等；是否有额外官方验签能力需向 Keepa 确认。
- 允许用户任意配置 webhook URL 会引入 SSRF/内网探测风险。受控管理面应采用预登记 URL 或域名 allowlist，不能直接透传用户提供的任意 URL。
- `all=1`、默认无分页的 `list`、`asins-only=1` 都可能返回超大响应；CLI/Service 查询应只返回计数和少量预览，完整对象写 JSON/XLSX 导出。

## 8. 对 opscli 的能力建议

当前仓库已提供内部 Python Tracking API，代码位于 `opscli/keepa/tracking/`；支持全部官方操作的原始 JSON 调用、Tracking Creation Object 校验、默认只读通知预览和破坏性操作显式确认。业务代码应使用 `KeepaTrackingService`：Add/Remove/Remove All/Webhook/通知消费都要求 `confirm=True`，Webhook 还必须匹配调用方提供的精确 host allowlist；底层 Client 仅是无策略传输层。该能力不注册 MCP、不挂公开 CLI，也不纳入现有场景导出。后续产品化仍建议分三期：

1. **只读盘点**：内部 Service 已提供 `get/list/listNames` 和默认 `readOnly=1` 的 notification preview；后续受控 CLI/Admin 应只返回摘要，详情导出 JSON/XLSX。
2. **可靠通知消费**：Webhook 接收、Notification 原始持久化、`notificationId` 去重、24 小时补偿轮询和内部告警。
3. **受控写操作**：内部 Service 已提供 Add/更新、Remove、Remove All、Set Webhook，其中所有写操作和通知消费要求显式确认，Webhook 需 allowlist；对外管理面仍需补预算预估、权限分级、审计、幂等和回滚配置。

Tracking 不提供 MCP Tool；Agent 如需使用监控结果，应读取已经沉淀的通知摘要或导出文件，而不是直接管理 Keepa Tracking 状态。

推荐的业务级能力包括：

- 竞品价格/Buy Box/促销变化监控；
- 自营或竞品缺货、恢复有货监控；
- Sales Rank、Rating、Review Count 变化阈值监控；
- 店铺/类目候选 ASIN 批量入池，再由 Tracking 持续监测；
- 用命名列表隔离项目、客户、站点或监控策略；
- 监控池容量、活跃率、refill reduction、过期和停用状态治理。

不建议把 Tracking 用来保存完整商品历史。它适合“条件触发 + 通知”，详细历史仍应在事件触发后按需查询 Product API 或读取既有导出。

## 9. 待验证项

以下信息在当前官方页面没有完整说明，接入前应通过 Keepa 官方支持或沙箱/小批量实测确认：

1. `tokenFlowReduction` 四舍五入在多条、跨站点混合 Tracking 下的精确聚合边界，以及套餐 refill rate 的可用保留水位。
2. 文档中 Tracking Object 的 `updateInterval` 返回范围为 0-25，而 Tracking Creation Object 接受 1-24；0、25 是否仅为内部/历史兼容值。
3. webhook 是否存在未公开的签名、固定来源 IP、超时阈值、响应体要求及更多重试策略。
4. `all=1` 在极大量通知下的服务端硬上限、超时和响应大小边界。
5. 同一 `notificationId` 是否可能通过 webhook 和 pull 重复投递，以及 webhook 投递失败时“已读”状态的精确变化时点。
6. Tracking 的 Marketplace/Regular 类型是由所选 `csvType` 自动判定，还是存在未展示的显式控制字段；官方 Tracking Creation Object 未列独立 `type` 字段。
7. `removeAll` 对未命名列表和命名列表的空结果、并发 Add/Remove 行为及可恢复性。

## 10. 官方来源索引

- [Keepa Tracking API](https://keepa.com/api-docs/tracking.html)
- [Keepa Tracking Object](https://keepa.com/api-docs/tracking-object.html)
- [Keepa Tracking Creation Object](https://keepa.com/api-docs/tracking-creation-object.html)
- [Keepa Notification Object](https://keepa.com/api-docs/notification-object.html)
- [Keepa API Changelog](https://keepa.com/api-docs/changelog.html)
- 仓库官方口径索引：`opscli/skills/templates/ops-keepa/references/OFFICIAL.md`

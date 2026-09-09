---
name: ops-commerce-playbooks
description: 跨境电商运营案例 Skill。用于用户提出找竞品、分析 Listing 关键词差距或从多个竞品建立关键词库时，按真实运营案例组合卖家精灵、Amazon 商品数据、StyleSnap、Keepa 和 Google Trends，并输出可追溯的事实、判断、动作与验证。
metadata:
  version: v0.1.0
---

# 跨境电商运营案例

本 Skill 只提供运营方法和案例模板，不建立独立规划器。实际查询继续使用各数据源已有 Skill 和正式 `opscli` 命令。

## 案例路由

只读取与当前需求对应的案例：

- 从关键词、ASIN 或图片寻找竞品：读取 [references/如何找竞品.md](references/如何找竞品.md)。
- 比较自己的 Listing 与已确认竞品的关键词差距：读取 [references/Listing关键词差距.md](references/Listing关键词差距.md)。
- 从多个已确认竞品建立新品关键词库：读取 [references/多竞品关键词库.md](references/多竞品关键词库.md)。

用户请求不属于上述案例时，直接使用对应数据源 Skill，不要勉强套用案例。

## 共用规则

1. 先确认运营问题和最少输入，再按案例调用数据；不要要求用户理解卖家精灵场景名。
2. 卖家精灵查询读取 `ops-seller-sprite`，并以它的参数、额度、任务等待和导出规则为准。
3. Amazon 页面事实读取 `ops-amazon-product-data`；视觉相似商品读取 `ops-amazon-stylesnap`；历史和站外趋势仅在问题需要时读取 `ops-keepa`、`ops-google-trends`。
4. `competitor-lookup` 的 `asins` 是指定商品筛选，可能返回父子体或变体，不是“从 ASIN 自动发现竞品”。从 ASIN 找竞品必须先提取搜索意图，再通过共同关键词、流量关系、关联关系或 StyleSnap 建立候选池。
5. 同一父体下的多个变体先归并，再作为一个商品家族参与竞品判断；不要用变体数量放大竞品数量。
6. 把结果标记为直接竞品、搜索/流量竞品、关联商品、视觉相似商品、标杆或替代品。单一来源只能生成候选，不能直接证明竞品关系。
7. 最终输出分为事实、判断、动作和验证。每条重要判断保留来源、站点、周期、Parent/Child 层级和数据限制。

## 正式命令入口

卖家精灵场景统一通过：

```bash
opscli seller-sprite run <scenario> \
  --site <SITE> \
  --period <PERIOD> \
  --params '<JSON对象>' \
  --export-format json
```

- `scenario`：由当前案例和 `ops-seller-sprite` 共同确定。
- `site`：Amazon 站点，未提供时按 `ops-seller-sprite` 默认值处理。
- `period`：场景支持的周期，不能把所有场景都固定成同一种格式。
- `params`：只传用户条件和案例必需字段，字段名以 `ops-seller-sprite` 为准。
- `export-format`：Agent 需要读取和合并结果时使用 `json`；用户需要人工留档时可使用 `xls` / `xlsx`。

StyleSnap 没有通用 CLI 查询入口。用户明确要求执行视觉竞品搜索时，调用 `ops-amazon-stylesnap`，复用用户浏览器登录态并遵守人工接管条件。

## 完成标准

- 已执行案例所需的核心数据步骤，或明确指出因缺参、登录、额度、异步任务或数据范围而未完成的步骤。
- 候选竞品与已验证竞品分开呈现，变体已经归并。
- 结论能够回溯到具体数据来源，建议包含后续验证方式。

当前版本不自动修改 Listing、广告、价格或库存，也不承诺第三方估算等于真实订单和广告结果。

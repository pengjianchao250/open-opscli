# 新品计算器逻辑精简 PRD

## 1. 目标

- 用户创建草稿后无需填写利润相关成本费用。
- 指定二区默认选择“美东+美西”。
- `opscli calculator detail` 完整展示前端“方案切换”下的费用方案表。

## 2. 非目标

- 不修改 Polaris 前端或后端接口。
- 不实现方案单选、切换、保存及 `updatePlanApi` 调用。
- 不保留原自发货/FBA/WFS 毛利结果表。
- 不新增命令和参数。
- 不做无关兼容、重构、测试用例、type-check、eslint 或格式化检查。

## 3. 功能需求

### FR-1 成本费用自动归零

创建或复制草稿时，以下字段默认写为数值 `0`，并且不再作为必填项或正数项阻止校验：

- 商品售价 `product_price`
- 目标毛利率 `gross_profit_percent`
- 含税采购价 `purchase_cost_with_tax`
- 非税采购价 `purchase_cost`
- 税率 `tax_rate_percent`
- 平台佣金比 `fee_percent`
- 站内广告 `advertising_percent`
- 站外营销 `marketing_percent`
- 退款 `refund_percent`
- 固定成本 `fixed_cost_percent`
- 关税率 `tariff_rate`

`calc_method` 继续保留后端返回值或默认 `GROSS_PROFIT`；系统汇率 `rate` 保留后端值。

新版 `填写表格.csv` 不展示任何“成本费用”字段；这些字段只保留在 `draft.json` 和提交 payload 中，并由 CLI 自动写为 `0`。草稿包同时生成 `填写表格-旧版.csv`，保留原完整字段结构并标记弃用；校验和提交只读取新版文件。

### FR-2 指定二区默认值

- US/CA 草稿默认选择“美东+美西”。
- 已确认枚举 key 为 `zone_1_2`，草稿字段固定写为 `two_zone_combine: ["zone_1_2"]`。
- 字段说明、CSV 中文显示和 Skill 示例同步改为“美东+美西”及 `zone_1_2`。

### FR-3 结果表格

`detail` 成功后展示 `allPlans` 的全部方案，表格列为：

1. 分区推荐。
2. 首单数量；按参考前端以 `allPlans[0].first_order_qty` 控制整列显隐，展示值取 `schemes[].first_order_qty`。
3. 分区线路。
4. 每 PCS 头程费用（CNY）。
5. 每 PCS 目的仓费用（CNY）。
6. 每 PCS 尾程费用（CNY）。
7. 每 PCS 全程费用（CNY）。
8. 每 PCS 全程平均费用（CNY）。

费用值保留 4 位小数；存在区间时，在主值下一行展示 `(最小值~最大值)`。

### FR-4 只读展示

- 不显示单选列。
- 不标记或保存切换状态。
- 不调用方案切换接口。
- 仍保留任务基本摘要、Web 详情页和原始 JSON 提示。

## 4. 验收标准

- 新草稿的上述成本字段均为数值 `0`，不填写也能通过对应成本校验。
- 新生成或刷新的 `填写表格.csv` 中不存在“成本费用”分组及其字段。
- 同目录存在包含完整旧字段的 `填写表格-旧版.csv`，文件内明确标记弃用且不会被校验或提交读取。
- 新草稿的 `two_zone_combine` 默认值为 `["zone_1_2"]`，CSV 显示“美东+美西”。
- `detail` 不再输出售价、毛利、自发货/FBA/WFS 表格。
- `detail` 完整输出 `allPlans` 的所有方案、线路、费用值和区间。
- `allPlans` 为空时给出明确的“暂无方案数据”，不制造空费用。

# 新品计算器逻辑精简调研

## 1. 调研范围

本次只调整 `opscli/calculator/` 的草稿默认值与详情结果展示，参考：

- 用户提供的新品计算器表单截图。
- `polaris2.0-frontend/src/views/application/calculator/result-detail.vue` 的“方案切换”表格。
- 当前 `opscli calculator draft / validate / submit / detail` 实现。

不修改 Polaris 前端和后端接口。

## 2. 当前实现

### 2.1 成本费用

当前本地校验仍把以下利润试算字段视为必填或条件必填，并要求部分数值大于 0：

- `product_price`
- `gross_profit_percent`
- `purchase_cost_with_tax`
- `tax_rate_percent`
- `fee_percent`
- `advertising_percent`
- `marketing_percent`
- `refund_percent`
- `fixed_cost_percent`
- `tariff_rate`

这会要求用户填写本次仅用于运费方案比较、不再需要的利润参数。

进一步确认后，成本费用分组不再出现在业务填写用的新版 `填写表格.csv`；这些字段仅保留在 `draft.json` 和提交 payload 中，并由 CLI 自动归零。同时生成 `填写表格-旧版.csv` 备份原完整字段结构，但标记为已弃用且不参与校验、提交。

### 2.2 指定二区

`two_zone_combine` 当前由用户填写，US/CA 且选择 1 区全部或指定分区时为空会校验失败。已确认“美东+美西”的枚举值为 `{"key": "zone_1_2", "value": "美东+美西"}`。

### 2.3 结果展示

当前 `detail` 展示 `trial_result`，表头是自发货、FBA、WFS，内容是售价、毛利、各类费用。

目标前端的“方案切换”表格实际使用 `allPlans`，字段为：

| 层级 | 字段 | 展示 |
|---|---|---|
| 方案 | `partition_recommend` | 分区推荐 |
| 方案/线路 | `allPlans[0].first_order_qty` / `schemes[].first_order_qty` | 首个方案字段控制列显隐，线路字段展示值 |
| 线路 | `schemes[].lines` | 分区线路 |
| 线路 | `schemes[].first_fee` | 每 PCS 头程费用及区间 |
| 线路 | `schemes[].storage_fees` | 每 PCS 目的仓费用及区间 |
| 线路 | `schemes[].freight` | 每 PCS 尾程费用及区间 |
| 线路 | `schemes[].scheme_fee` / `scheme_range` | 每 PCS 全程费用及区间 |
| 方案 | `total_fee` | 每 PCS 全程平均费用 |

前端额外包含单选和切换请求；CLI 不需要这些交互。

## 3. 方案对比

### 方案 A：保留字段并自动归零，详情改读 `allPlans`（推荐）

- 后端 payload 结构不变。
- 用户无需填写利润字段。
- 指定二区默认写入 `zone_1_2`（美东+美西）。
- `detail` 直接完整展示 `allPlans`。

优点是改动小、接口兼容性最高；缺点是草稿 JSON 仍保留不再关注的成本字段。

### 方案 B：从草稿和提交 payload 删除成本字段

界面最精简，但后端是否允许缺字段没有现成契约，存在提交失败风险，不采用。

### 方案 C：保留当前结果表，再追加方案表

信息更全，但与“结果展示改为方案切换下的表格”不符，也保留了不再需要的利润结果，不采用。

## 4. 结论

采用方案 A。成本输入自动归零并保留接口字段；新版 `填写表格.csv` 删除整个成本费用分组，`填写表格-旧版.csv` 备份完整旧结构并弃用；汇率 `rate` 是系统返回值，不强制改为 0。结果页只展示方案费用表，不提供单选、保存或切换功能。

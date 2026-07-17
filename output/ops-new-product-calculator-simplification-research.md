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

进一步确认后，成本费用分组不再出现在业务填写用的新版 `填写表格.csv`；这些字段仅保留在 `draft.json` 和提交 payload 中。原数值 `0` 会导致后端计算失败，因此由 CLI 自动填充为非零占位值 `1`。同时生成 `填写表格-旧版.csv` 备份原完整字段结构，但标记为已弃用且不参与校验、提交。

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

### 2.4 当前样例数据问题

验证目录中的包装尺寸、外箱尺寸、重量和单箱数量来自本地样例，不是网页接口返回值。商品名、海关类目或尺寸分段都不足以推导这些实际物流数据，因此不应继续自动代入草稿或 CSV。

## 3. Amazon 官方尺寸资料

### 3.1 商品尺寸分段不是实际包装默认值

用户提供的 Amazon Seller Central 页面是 [Product size tiers（商品尺寸分段）](https://sellercentral.amazon.sg/help/hub/reference/external/G201105770?mons_sel_locale=zh_CN&pageName=SG%3ASC%3ATrim-help%2Fhub%2Freference%2Fexternal%2FG201105770)。该页面需要登录并由 JavaScript 渲染；其用途是依据已经测量的单件商品包装尺寸和重量判定配送计费档位，不是为未知商品提供包装尺寸默认值。

Amazon.sg 官方 [FBA fulfilment fees for Amazon.sg orders](https://m.media-amazon.com/images/G/65/SG3P/FBA_fulfilment_fees_for_Amazon.sg_orders.pdf) 进一步说明：把商品的实际包装尺寸和出库配送重量与表格比较，任一边或重量超过当前档位上限，就进入下一档；Amazon 也可能按代表性样品复测。官方档位上限如下：

| Amazon.sg FBA 档位 | 单件包装尺寸上限 | 出库配送重量范围/上限 |
|---|---:|---:|
| Small envelope | 20 × 15 × 1 cm | 0–100 g |
| Standard envelope | 33 × 23 × 2.5 cm | 最高 500 g |
| Large envelope | 33 × 23 × 5 cm | 最高 1000 g |
| Parcel | 45 × 34 × 26 cm | 最高 12 kg |
| Small oversize | 61 × 46 × 46 cm | 最高 2 kg |
| Standard oversize | 120 × 60 × 60 cm | 最高 30 kg |
| Large oversize | 最长边 150 cm | 最高 30 kg |

该 PDF 还明确：长度超过 150 cm、重量超过 30 kg 或围长超过 3 m 的商品不适用 Amazon.sg FBA。配送重量是“商品单件重量 + Amazon 包装重量”，不能等同于卖家的 `SKU毛重` 或入库 `外箱毛重`。

以上数值全部是 Amazon.sg 的单件商品包装计费边界。当前新品计算器试算站点包含美国等站点，不能把新加坡档位直接当成其他站点的计费标准，更不能把档位上限写成商品实际尺寸。

### 3.2 可提供的常规参考选项

同一份 Amazon.sg 官方 PDF 提供了以下商品示例，可作为用户主动选择的“参考模板”，但不能自动选中或直接当作真实值：

| 参考模板 | 官方示例尺寸 | 官方示例单件重量 | 官方归档 |
|---|---:|---:|---|
| SD 卡 | 3.2 × 2.4 × 0.2 cm | 30 g | Small envelope |
| 图书 | 24 × 16.2 × 3.5 cm | 150 g | Large envelope |
| 电子玩具 | 37 × 15.4 × 7 cm | 490 g | Parcel |

官方同时注明这些示例仅用于辅助评估，并不保证示例计算的准确性。因此 CLI/Skill 的选项应为：

- `按实物填写（推荐）`：不代入任何尺寸或重量。
- `Amazon.sg 官方示例：SD 卡`、`图书`、`电子玩具`：仅在用户明确选择后暂填单件包装尺寸和重量，并再次要求用户确认或修改。
- `自定义`：由用户填写实际数据。

原样例中的 `50 × 40 × 30 cm`、`12 kg`、`20 件/箱` 不具备商品或官方依据，应删除。

### 3.3 FBA 入库外箱参考

新品计算器中的两套尺寸用于不同环节，必须分开：

| 字段 | 含义 | 用途 |
|---|---|---|
| 包装长宽高、SKU 毛重 | 一件商品完成销售包装后的实际尺寸和重量 | FBA 尾程配送尺寸分段和费用 |
| 外箱长宽高、外箱毛重、单箱数量 | 多件 SKU 发往 FBA 仓的实际入库运输箱 | 亚马逊头程/入库运输费用 |

Amazon 官方公告 [Maximum box length for FBA orders to increase](https://sellercentral.amazon.com/seller-forums/discussions/t/dae82165-50b2-4b52-99d9-a7e7db80caec) 说明，自 2025 年 6 月 20 日起，美国 FBA 入库箱最大限制为 `36 × 25 × 25 in`、`50 lb`，换算约为 `91.44 × 63.5 × 63.5 cm`、`22.68 kg`。这是美国 FBA 入库外箱的合规上限，只能用于提示或校验，不能作为“常规外箱”自动写入。

Amazon 没有为不同商品提供统一的“外箱长宽高 + 外箱毛重 + 单箱数量”组合。尤其单箱数量取决于单件包装、供应商装箱和运输方案，没有官方通用默认值，必须由用户确认。其他国家/站点的限制可能不同，也不能套用美国上限。

因此可展示的外箱选项仅应是：

- `按实际装箱填写（推荐）`：由用户或供应商提供实际箱规。
- `查看美国 FBA 入库上限`：只显示 `91.44 × 63.5 × 63.5 cm / 22.68 kg` 作为合规提示，不填入表单。
- `自定义`：填写实际外箱数据，并要求确认单箱数量。

### 3.4 Skill 多轮补齐要求

Skill 不应一次询问后就带着缺失值生成试算，而应循环读取尚未填写的必填字段并分组追问：

1. 先询问单件包装长、宽、高和 SKU 毛重；可展示上述参考模板，但默认仍为空。
2. 再询问外箱长、宽、高、外箱毛重和单箱数量；可提示对应站点的 FBA 入库限制，但不把限制值当作默认值。
3. 每轮保留已经确认的数据，只追问仍为空或无效的必填字段。
4. 用户选择参考模板后，明确提示“仅为 Amazon.sg 官方示例，请按实物确认”，未确认前不提交。
5. 重复到所有必填字段有效，或用户明确取消；不得根据商品名称猜测。

## 4. 方案对比

### 方案 A：保留字段并自动填充非零值，详情改读 `allPlans`（推荐）

- 后端 payload 结构不变。
- 用户无需填写利润字段。
- 指定二区默认写入 `zone_1_2`（美东+美西）。
- `detail` 直接完整展示 `allPlans`。

优点是改动小、接口兼容性最高；缺点是草稿 JSON 仍保留不再关注的成本字段。

### 方案 B：从草稿和提交 payload 删除成本字段

界面最精简，但后端是否允许缺字段没有现成契约，存在提交失败风险，不采用。

### 方案 C：保留当前结果表，再追加方案表

信息更全，但与“结果展示改为方案切换下的表格”不符，也保留了不再需要的利润结果，不采用。

## 5. 结论

采用方案 A。成本输入自动填充为 `1` 并保留接口字段；新版 `填写表格.csv` 删除整个成本费用分组，`填写表格-旧版.csv` 备份完整旧结构并弃用；汇率 `rate` 是系统返回值，不强制修改。结果页只展示方案费用表，不提供单选、保存或切换功能。

包装、重量和箱规字段默认留空，不再把本地样例代入业务草稿。Skill 可展示 Amazon.sg 官方商品示例作为用户主动选择的 SKU 包装参考模板，但选择后仍需确认实际值；美国 FBA 入库箱上限只作为外箱合规提示。SKU 包装、入库外箱不能混用，单箱数量只通过多轮追问补齐，不做推断。

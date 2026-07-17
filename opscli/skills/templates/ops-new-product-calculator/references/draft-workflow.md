# 草稿工作流

仅在用户要新建、填写、查看、校验或提交草稿时读取本文件。

## 新建草稿

第一阶段包含站点、平台和海关类目：

| 中文字段 | CLI 参数 | 获取方式 | 默认建议 |
|---|---|---|---|
| 试算站点 | `--country` | `opscli calculator dropdown-list --json` | `US` 美国 |
| 试算平台 | `--platform` | `opscli calculator dropdown-list --json` | 试算平台默认同时选择亚马逊和沃尔玛：`--platform 1 --platform 7` |
| 海关类目 | `--hs-code-id` | `opscli calculator search-category <关键词>` | 烟测可用 `4`：USB 数据线 |

使用业务语言询问，不向用户直接询问 `country/platform/hs_code_id`。

需要查看站点和平台时：

```bash
opscli calculator dropdown-list --json
```

解析后只向用户展示与当前选择有关的 3–5 个候选项，不转贴完整 JSON。

用户给出海关类目关键词后：

```bash
opscli calculator search-category 数据线 --limit 5
```

也可先查看推荐参数：

```bash
opscli calculator recommend
```

默认烟测选择：

```text
试算站点：US 美国
试算平台：亚马逊 + 沃尔玛
海关类目：4 8544421100-USB数据线
```

生成草稿：

```bash
opscli calculator draft --country US --platform 1 --platform 7 --hs-code-id 4 --out tmp-validation/calculator/calculator-draft-usb-cable-20260703
```

输出目录必须是新的空目录；如果已有 `draft.json`，停止并更换目录。

## 继续已有草稿

用户提供草稿目录、`填写表格.csv` 或 `draft.json` 时，不重新询问第一阶段。先查看：

```bash
opscli calculator show <DRAFT_DIR>
```

普通用户使用草稿目录；高级用户才直接传 `draft.json`。

## 第二阶段草稿补全

- `填写表格.csv`：业务用户入口，只填写“请填写”列。
- `填写表格-旧版.csv`：保留完整历史字段的弃用备份，不参与校验和提交。
- `draft.json`：接口格式和自动化入口，普通用户不建议手动替换整个 JSON。
- `.dropdown-cache.json`：下拉快照，校验或提交时实时数据不可用才兜底使用。
- `使用说明.md`：下一步命令和 Web 入口。

CSV 可填写 `河北省`、`唐山市`、`算毛利`、`1区全部、指定分区`、`美东+美西` 等中文值。目录模式的 `validate` / `submit` 会按下拉数据自动转换成后端 key/code 并写回 `draft.json`。

### 单件 SKU 包装参考

`包装长/宽/高` 和 `SKU毛重` 是一件商品完成销售包装后的实际数据，用于 FBA 配送尺寸分段和尾程费用。默认向用户提供以下选项：

1. `按实物填写（推荐）`：继续询问实际长、宽、高和毛重，不代入任何参考值。
2. `Amazon.sg 官方示例：SD 卡`：`3.2 × 2.4 × 0.2 cm / 0.03 kg`。
3. `Amazon.sg 官方示例：图书`：`24 × 16.2 × 3.5 cm / 0.15 kg`。
4. `Amazon.sg 官方示例：电子玩具`：`37 × 15.4 × 7 cm / 0.49 kg`。
5. `自定义`：用户直接给出实际数据。

后三个数值来自 [Amazon.sg FBA 官方费率资料](https://m.media-amazon.com/images/G/65/SG3P/FBA_fulfilment_fees_for_Amazon.sg_orders.pdf)，仅用于理解尺寸量级，不能当作目标站点的计费档位。用户明确选择官方示例后才可暂填，并立即复述尺寸、重量，要求用户确认或修改；未确认时仍视为未补全。

### FBA 入库外箱参考

`外箱长/宽/高`、`外箱毛重` 和 `单箱数量` 是多件 SKU 发往 FBA 仓的实际入库运输箱，用于亚马逊头程/入库运输费用，不能使用单件 SKU 包装数据替代。

默认选项：

1. `按实际装箱填写（推荐）`：询问供应商实际箱规、毛重和装箱数量。
2. `查看美国 FBA 入库上限`：展示 `91.44 × 63.5 × 63.5 cm / 22.68 kg`，但不填入 CSV。
3. `自定义`：用户直接给出实际外箱数据。

美国上限来自 [Amazon FBA 官方公告](https://sellercentral.amazon.com/seller-forums/discussions/t/dae82165-50b2-4b52-99d9-a7e7db80caec)，其他站点必须重新核对。单箱数量没有通用默认值，必须让用户确认。

### 多轮补齐

1. 读取 CSV 的“当前值”和“请填写”，先收集所有仍为空或无效的必填字段。
2. 第一轮优先询问单件包装长、宽、高和 SKU 毛重；每轮最多询问 3–5 个字段。
3. 下一轮询问外箱长、宽、高、外箱毛重和单箱数量；仍遵守每轮 3–5 项。
4. 后续轮次只追问仍为空或无效的地址、备货等必填字段，不重复询问已经确认的值。
5. 用户每次回答后写入 CSV“请填写”列并重新读取；连续补充期间只更新并读取 CSV，不重复执行认证、`show`、下拉查询或 `validate`。
6. 全部必填字段有效后只运行一次 `validate`。
7. 用户选择参考模板时必须再次确认；用户未确认或明确取消时，不进入提交。

不得根据商品名称猜测包装尺寸、重量、箱规或单箱数量，也不得把“示例”列复制到“当前值”或“请填写”列。

## 字段规则

- `draft.json` 的 `pick_up_province` / `pick_up_city` 必须使用编码字符串，例如 `"130000"` / `"130200"`。
- 不要把中文省市名写入 draft.json，例如不要写 `"河北省"`、`"唐山市"`。
- 不要求用户手写 `pick_up_province_code` / `pick_up_city_code`；CLI 提交前自动派生。
- `checkbox_stock: ["one_zone_all", "specify_part"]` 对应 `1区全部、指定分区`。
- US/CA 的 `two_zone_combine` 默认是 `["zone_1_2"]`，对应“美东+美西”。
- 利润相关成本费用由 CLI 统一填 `1`，避免 `0` 导致后端计算失败；新版 `填写表格.csv` 不包含这些字段，旧版文件仅用于历史备份。
- `stock_qty_first_percent`、`stock_qty_second_percent`、`stock_qty_third_percent` 之和必须为 100。

## 空白物流字段结构

以下 JSON 只说明未知物流字段应保持空值，不可直接作为提交数据，也不要整段覆盖 CLI 已生成的 `draft.json`：

```json
{
  "package_length": null,
  "package_width": null,
  "package_height": null,
  "product_gross_weight": null,
  "box_length": null,
  "box_width": null,
  "box_height": null,
  "box_gross_weight": null,
  "box_number": null
}
```

## 校验

用户保存 CSV 后优先传草稿目录：

```bash
opscli calculator validate <DRAFT_DIR>
```

目录模式会先同步 CSV 到 `draft.json`。校验失败属于非认证类 `opscli` 失败：立即使用 `ops-feedback` 提交反馈，再解释最关键的 3–5 个问题。validate 通过后才允许进入 submit。

## 提交确认

只有 validate 通过且用户明确确认后，才执行：

```text
submit 会创建真实试算任务。确认要提交吗？
```

```bash
opscli calculator submit <DRAFT_DIR>
```

提交成功后保存任务编号和代查标识，后续按 `references/result-workflow.md` 查询。

## Web 兜底

如果用户不想编辑本地文件，使用创建页：

https://bi.xenkee.com/#/newProductCalculator

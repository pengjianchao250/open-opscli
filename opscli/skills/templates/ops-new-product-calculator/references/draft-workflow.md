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
- `draft.json`：接口格式和自动化入口，普通用户不建议手动替换整个 JSON。
- `.dropdown-cache.json`：下拉快照，校验或提交时实时数据不可用才兜底使用。
- `使用说明.md`：下一步命令和 Web 入口。

CSV 可填写 `河北省`、`唐山市`、`算毛利`、`1区全部、指定分区`、`美东+美中` 等中文值。目录模式的 `validate` / `submit` 会按下拉数据自动转换成后端 key/code 并写回 `draft.json`。

## 字段规则

- `draft.json` 的 `pick_up_province` / `pick_up_city` 必须使用编码字符串，例如 `"130000"` / `"130200"`。
- 不要把中文省市名写入 draft.json，例如不要写 `"河北省"`、`"唐山市"`。
- 不要求用户手写 `pick_up_province_code` / `pick_up_city_code`；CLI 提交前自动派生。
- `checkbox_stock: ["one_zone_all", "specify_part"]` 对应 `1区全部、指定分区`。
- US/CA 选择 `one_zone_all` 或 `specify_part` 时，`two_zone_combine` 必填；`美东+美中` 对应 `["zone_1_3"]`。
- `GROSS_PROFIT` 必须填写 `product_price`。
- `PRICING` 必须填写 `gross_profit_percent`。
- `stock_qty_first_percent`、`stock_qty_second_percent`、`stock_qty_third_percent` 之和必须为 100。

## 最小烟测 JSON

以下示例可通过当前本地校验。实际操作优先填写 CSV，不要整段覆盖 CLI 已生成的 `draft.json`：

```json
{
  "country_code": "US",
  "platforms": [1, 7],
  "hs_code_id": 4,
  "package_length": 12.5,
  "package_width": 8.2,
  "package_height": 4,
  "box_length": 50,
  "box_width": 40,
  "box_height": 30,
  "product_gross_weight": 0.65,
  "box_gross_weight": 12,
  "box_number": 20,
  "pick_up_province": "130000",
  "pick_up_city": "130200",
  "calc_method": "GROSS_PROFIT",
  "purchase_cost_with_tax": 100,
  "tax_rate_percent": 13,
  "fee_percent": 15,
  "advertising_percent": 10,
  "marketing_percent": 5,
  "refund_percent": 3,
  "fixed_cost_percent": 2,
  "tariff_rate": 25,
  "stock_qty_first_percent": 50,
  "stock_qty_second_percent": 30,
  "stock_qty_third_percent": 20,
  "checkbox_stock": ["specify_part", "one_zone_all"],
  "two_zone_combine": ["zone_1_3"],
  "three_zone_combine": [],
  "baiyi_warehouse_ids": [],
  "product_price": 39.99
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

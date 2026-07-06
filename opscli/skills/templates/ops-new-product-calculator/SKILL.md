---
name: ops-new-product-calculator
description: Use when users need Polaris 新品计算器、新品试算、新品毛利测算、新品定价测算，或需要选择试算站点、试算平台、海关类目并生成 calculator 草稿包。
---

# ops-new-product-calculator

用于引导业务用户通过 `opscli calculator` 完成 Polaris 新品计算器第一阶段下拉选择、草稿包生成、本地校验和提交确认。

---

## 何时使用

- 用户提到新品计算器、新品试算、新品毛利测算、新品定价测算。
- 用户需要选择试算站点、试算平台、海关类目。
- 用户想把网页新品计算器流程转为 CLI 草稿包。
- 用户已有草稿目录、`填写表格.csv` 或 `draft.json`，需要校验或提交试算任务。
- 用户已有新品试算任务编号，需要查询最终计算结果或打开 Web 详情页。

---

## 硬性规则

- 必须通过 `opscli calculator` 命令工作，不得直接调用 Polaris 后端 API。
- 如果出现未登录、Token 过期、401、JWT 获取失败，先回到 `ops-auth` 处理认证。
- **REQUIRED SUB-SKILL:** 任意 `opscli calculator` 命令发生非认证类失败后，必须立即提交结构化反馈：使用 `ops-feedback` 完成提交，反馈完成后再继续原任务。认证类错误按上一条处理，不重复提交反馈。
- `submit` 会创建真实试算任务，提交前必须明确提醒并获得用户确认。
- 第二阶段字段很多时，不要让用户在聊天里一次性列完；优先生成草稿包，让用户打开 `填写表格.csv`，只填写“请填写”这一列；不要把 `draft.json` 作为普通用户首选入口。
- 查询结果必须优先使用 `opscli calculator detail`，不要让用户手工拼 Polaris 后端接口请求。
- 用户粘贴浏览器 curl、JWT、Cookie、sudo 等敏感信息时，不要复述完整值；命令示例里用 `<SUDO>` 或加引号占位。
- 生成草稿时，输出目录必须是新的空目录；不得覆盖已有 draft.json。

---

## 权限与登录前置检查

使用本工具需要北极星 Polaris 权限。执行任何 `opscli calculator` 命令前，先检查当前登录状态和系统 Token：

```bash
opscli auth token status
```

根据输出处理：

- 显示“未登录”时，执行 `opscli auth login`，完成浏览器授权后重新运行 `opscli auth token status`。
- 显示“已登录”且 Polaris Token 有效时，继续新品计算器流程。
- 已登录但 Polaris Token 状态为无效/未获取时，不要反复登录；当前账号通常缺少北极星系统授权，应提示用户申请 BI/Polaris 权限，获得权限后再继续。
- 登录和权限问题属于认证类预期状态，不触发 `ops-feedback`。

---

## 第一阶段下拉交互

第一阶段有 3 个下拉项：

| 中文字段 | CLI 参数 | 获取方式 | 默认建议 |
|---|---|---|---|
| 试算站点 | `--country` | `opscli calculator dropdown-list --json` | `US` 美国 |
| 试算平台 | `--platform` | `opscli calculator dropdown-list --json` | 试算平台默认同时选择亚马逊和沃尔玛：`--platform 1 --platform 7` |
| 海关类目 | `--hs-code-id` | `opscli calculator search-category <关键词>` | 第一轮烟测可用 `4`：USB数据线 |

不要问用户 `country/platform/hs_code_id` 这类技术字段名。应使用业务语言：

- “试算站点选哪个？如果只是测试，我建议美国。”
- “试算平台默认同时勾选亚马逊和沃尔玛，可以吗？”
- “海关类目请输入关键词，例如 数据线、电源、音箱。”

---

## 推荐工作流

### 1. 检查或获取下拉项

需要查看站点和平台时：

```bash
opscli calculator dropdown-list --json
```

普通 `dropdown-list` 只显示返回字段名，选择非默认站点或平台时必须加 `--json`。解析返回后只向用户展示与当前选择有关的 3-5 个候选项，不要转贴完整 JSON。

用户给出海关类目关键词后：

```bash
opscli calculator search-category 数据线 --limit 5
```

只展示前 3-5 条匹配结果，让用户选择，不要展示全部类目。

### 2. 推荐默认烟测参数

用户只是要测试链路时，优先推荐：

```text
试算站点：US 美国
试算平台：亚马逊 + 沃尔玛
海关类目：4 8544421100-USB数据线
```

可直接提示命令：

```bash
opscli calculator draft --country US --platform 1 --platform 7 --hs-code-id 4 --out tmp-validation/calculator/calculator-draft-usb-cable-20260703
```

也可以先运行：

```bash
opscli calculator recommend
```

`recommend` 输出中的 `--out` 只是示例。真正生成前必须换成新的任务专属目录；如果目录中已有 `draft.json`，停止执行并改用新目录。

### 3. 生成草稿包

```bash
opscli calculator draft --country US --platform 1 --platform 7 --hs-code-id 4 --out tmp-validation/calculator/calculator-draft-usb-cable-20260703
```

生成后告知用户重点看：

- `填写表格.csv`：推荐给业务用户填写；只需要补“请填写”这一列。
- `draft.json`：CLI 内部提交和高级用户自动化使用；普通用户不建议手动替换整个 JSON。
- `使用说明.md`：下一步命令和网页端兜底入口。

如果用户不想在本地编辑 CSV/JSON，直接引导使用网页端新品计算器：
https://bi.xenkee.com/#/newProductCalculator

### 4. 第二阶段草稿补全

生成草稿包后，第二阶段不要继续追加大量 CLI 参数；指导用户打开 `填写表格.csv`，只补“请填写”这一列。CSV 已合并字段说明、缺失提示、单位、示例和备注，避免用户在多个文件之间来回对照。

CSV 面向业务用户展示中文选项：`算毛利` / `算定价`、`1区全部` / `指定分区`、`美东+美中`、仓库中文名、省份和城市中文名等。用户在 CSV 可以填写 `河北省`、`唐山市`、`算毛利`、`1区全部、指定分区`、`美东+美中` 这类中文值；CLI 在 `validate` / `submit` 目录模式会按下拉快照自动转换成后端 key/code 后写回 `draft.json`。

CSV 的下拉选项来自页面同源接口：公共下拉用 `dropdown-list`，站点分区/仓库用 `zones`。草稿包会保存一份 `.dropdown-cache.json` 快照；校验或提交时优先实时获取，接口不可用时使用草稿包内快照兜底。不要要求用户维护全局本地缓存。

如果用户明确表示本地填写麻烦、不会改文件、或不想继续补 CSV，不要强推 JSON；直接引导使用网页端新品计算器：
https://bi.xenkee.com/#/newProductCalculator

以下是一份可以通过当前本地 `validate` 的完整最小烟测 JSON 示例。实际操作应优先在 CLI 生成的 `填写表格.csv` 上逐项填写，不要用示例整段覆盖 `draft.json` 中后端已经返回的其它字段：

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

关键规则：

- 在 `填写表格.csv` 中，提货地址可以填写中文省市名，例如 `河北省` / `唐山市`；CLI 会转换为 `"130000"` / `"130200"` 后写回 `draft.json`。
- `draft.json` 仍是接口格式：提货地址字段使用前端表单字段名 `pick_up_province` / `pick_up_city`，值必须是下拉选项 key 的编码字符串，例如 `"130000"` / `"130200"`。
- 不要把中文省市名写入 draft.json，例如不要写 `"河北省"`、`"唐山市"`。
- 不要要求用户手写 `pick_up_province_code` / `pick_up_city_code`；CLI 提交前会从 `pick_up_province` / `pick_up_city` 自动派生这两个接口字段。
- 备货区域默认按用户要求选择 `1区全部、指定分区`，对应 JSON `checkbox_stock: ["one_zone_all", "specify_part"]`。
- US/CA 站点选择 `one_zone_all` 或 `specify_part` 时，`two_zone_combine` 条件必填；CSV 可填中文 `美东+美中`，JSON 常见烟测值可用 `["zone_1_3"]`。
- `GROSS_PROFIT` 方案必须填写 `product_price`；`PRICING` 方案必须填写 `gross_profit_percent`。
- `stock_qty_first_percent`、`stock_qty_second_percent`、`stock_qty_third_percent` 三项之和必须为 100。

### 5. 校验草稿

用户填写并保存 `填写表格.csv` 后，优先传草稿目录，让 CLI 自动同步 CSV 到 `draft.json` 后再校验：

```bash
opscli calculator validate tmp-validation/calculator/calculator-draft-usb-cable-20260703
```

高级用户也可以继续传 `draft.json` 路径，但普通用户不建议直接替换 JSON。

校验失败属于非认证类 `opscli` 命令失败：立即按 `ops-feedback` 提交结构化反馈，反馈完成后再解释中文错误并指导用户继续补 `填写表格.csv`；不要直接提交。validate 通过后才允许进入 submit。

### 6. 提交前确认

校验通过后，必须提醒：

```text
submit 会创建真实试算任务。确认要提交吗？
```

用户确认后才执行：

```bash
opscli calculator submit tmp-validation/calculator/calculator-draft-usb-cable-20260703
```

提交成功后，CLI 会输出 `任务编号`，如果后端返回 `sudo`，也会输出 `代查标识`，并给出后续查询命令。

### 7. 查询最终试算结果

提交成功后优先直接使用 submit 输出的 `查看详情` 命令。例如：

```bash
opscli calculator detail --task-code FYYC0126070300007 --sudo <SUDO>
```

注意事项：

- `--task-code` 和 `--sudo` 之间必须有空格；不要写成 `FYYC...--sudo`。
- `sudo` 很长时建议加引号，避免终端解析问题：`--sudo "<SUDO>"`。
- 普通 `detail` 输出会展示任务摘要、成本摘要，并按页面 `trial-result-teble` 的结构展示“试算结果”表格：
  - 列：`费用`、`自发货(币种)`、`FBA(币种)`、`WFS(币种)`。
  - 行：`售价`、`毛利`、`毛利率`、`非税采购价`、`头程费用`、`仓库费用`、`尾程费用`、`站内广告`、`站外促销`、`平台佣金`、`退款费`、`固定成本`、`备注`。
  - `FBA/WFS/MFN` 缺失时会自动隐藏对应列。
  - 推荐方案会在表头标记，例如 `FBA(USD) 推荐`。
- 如果需要排查原始字段或复制完整返回，再加 `--json`：

```bash
opscli calculator detail --task-code FYYC0126070300007 --sudo "<SUDO>" --json
```

### 8. 查询列表和 Web 详情页

如果 submit 未返回任务编号，或用户只知道部分信息，可以先查列表：

```bash
opscli calculator list --task-code FYYC0126070300007 --json
```

普通列表输出会尽量展示 `task_code`、站点、`sudo`、详情命令和 Web 详情页。拿到 `task_code` 与 `sudo` 后再查详情：

```bash
opscli calculator detail --task-code <TASK_CODE> --sudo "<SUDO>"
```

Web详情页格式：

```text
https://bi.xenkee.com/#/calculatorDatail?task_code=<TASK_CODE>&sudo=<SUDO>
```

---

## 常见问题处理

| 现象 | 处理 |
|---|---|
| 用户不知道站点 | 先推荐 US；需要查看其它站点时使用 `dropdown-list --json`，只展示少量候选项 |
| 用户不知道平台 | 默认同时选择亚马逊和沃尔玛，即 `--platform 1 --platform 7` |
| 用户不知道海关类目 ID | 让用户给关键词，调用 `search-category` 搜索 |
| `polaris JWT` 获取失败 | 使用 `ops-auth` 处理认证或检查当前账号是否存在于 BI/Polaris 系统 |
| `validate` 报错很多 | 先解释最关键的 3-5 个问题，引导用户继续补 `填写表格.csv` 的“请填写”列；如果用户不想本地填写，改用网页端新品计算器：https://bi.xenkee.com/#/newProductCalculator |
| 用户要求直接提交 | 先运行 `validate`，通过后再次确认真实创建任务 |
| `detail` 报 unexpected extra argument | 检查 `--task-code` 和 `--sudo` 之间是否缺少空格，正确格式是 `--task-code <TASK_CODE> --sudo "<SUDO>"` |
| `detail` 超时 | 先用 `list --task-code <TASK_CODE> --json` 看任务状态，稍后重试 `detail`；不要改为直接调用后端 API |
| 用户要“最终结果” | 使用 `calculator detail --task-code <TASK_CODE> --sudo "<SUDO>"`，普通输出已包含页面“试算结果”表格 |
| 用户要完整原始字段 | 在 detail 命令后加 `--json`，只展示必要片段，不要在回复中泄露完整 JWT/Cookie |
| 任意非认证类命令失败 | 立即使用 `ops-feedback` 提交结构化反馈，返回 `feedback_uuid`，再继续诊断或重试 |

---

## 回复风格

面向非技术运营同学时，优先使用中文业务词，不要堆 CLI 参数。可以这样说：

```text
我先帮你完成第一步下拉选择：
- 站点：默认美国
- 平台：默认亚马逊 + 沃尔玛
- 海关类目：请给我一个关键词，例如 数据线
```

确认参数后再展示将要执行的命令。

查询结果时可以这样说：

```text
我用任务编号和 sudo 帮你查最终试算结果。普通输出会直接显示和页面一致的“试算结果”表格；如果你要排查字段，我再加 --json 看原始返回。
```

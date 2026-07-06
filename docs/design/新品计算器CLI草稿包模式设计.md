# 新品计算器 CLI 草稿包模式设计

## 1. 背景

Polaris 前端 `src/views/application/calculator/index.vue` 提供“新品计算器”能力，用户先填写站点、平台、海关类目和参考项，再由后端带出完整试算参数，最后提交异步试算任务。

本设计将该网页工具封装到 `opscli` 的 CLI 模式中。第一版优先实现功能闭环，暂不实现 MCP Tool、本地 HTML 表单或完整终端向导。

## 2. 目标用户

目标用户是非技术运营同学，同时也要支持 Codex、ZCode、Claude Code 等 Agent 代用户操作。

因此 CLI 设计要满足：

1. 运营同学不需要理解后端接口和鉴权细节。
2. 运营同学不需要一次性列出全部试算参数。
3. 第二阶段字段较多时，CLI 必须提供中文字段说明、缺失项清单和中文校验错误。
4. Agent 可以读取草稿文件和说明文件，帮助用户补字段、校验和提交。
5. 第一版保持简单，不引入本地网页或复杂交互框架。

## 3. 设计结论

第一版采用“草稿包模式”：

```text
少量第一阶段参数
  ↓
opscli calculator draft
  ↓
调用 Polaris queryCost 接口
  ↓
生成草稿包目录
  ↓
用户或 Agent 按中文说明修改 draft.json
  ↓
opscli calculator validate
  ↓
opscli calculator submit
  ↓
opscli calculator list/detail 查看结果
```

草稿包目录示例：

```text
calculator-draft-20260702-001/
├── draft.json          # 机器可提交的完整参数
├── 字段说明.md          # 中文字段说明、单位、示例、是否必填
├── 缺失项.md            # 当前仍需补充或确认的字段
└── 使用说明.md          # 后续校验、提交、查询命令
```

## 4. 非目标

第一版明确不做：

1. 不实现 MCP Tool。
2. 不实现本地 HTML 表单。
3. 不实现完整的逐项终端向导。
4. 不要求用户通过 CLI 参数填写所有第二阶段字段。
5. 不在 Skill 或脚本中直连后端 API。
6. 不替代 Polaris 原网页，只提供 CLI 自动化入口。

## 5. 命令设计

新增模块命令组：

```bash
opscli calculator
```

### 5.1 创建草稿包

```bash
opscli calculator draft \
  --country US \
  --platform 1 \
  --platform 7 \
  --hs-code-id 12345 \
  --out calculator-draft-20260702-001
```

也支持 payload 文件：

```bash
opscli calculator draft --payload query.json --out calculator-draft-20260702-001
```

`query.json` 示例：

```json
{
  "country_code": "US",
  "platforms": [1, 7],
  "hs_code_id": 12345,
  "department": null,
  "reference": "NONE",
  "reference_value": null
}
```

命令行为：

1. 读取第一阶段参数。
2. 调用 `/calculator/newProduct/queryCost`。
3. 执行前端等价初始化逻辑：
   - 空字符串转 `null`。
   - 可安全转换的数字字符串转数字。
   - 未返回 `tariff_rate` 时默认填 `25`，并在说明中标注“佰易未返回，取默认值”。
   - 如返回 `bi_message`，写入 `使用说明.md`，并将 `reference` 和 `reference_value` 重置为 `NONE`/`null`。
4. 生成 `draft.json`、`字段说明.md`、`缺失项.md` 和 `使用说明.md`。
5. 在终端输出中文摘要和下一步命令。

### 5.2 查看草稿摘要

```bash
opscli calculator show calculator-draft-20260702-001/draft.json
```

输出中文摘要，重点展示：

1. 基础信息。
2. 产品信息关键字段。
3. 成本费用关键字段。
4. 备货设置关键字段。
5. 当前缺失项数量。
6. 下一步校验和提交命令。

### 5.3 校验草稿

```bash
opscli calculator validate calculator-draft-20260702-001/draft.json
```

校验通过时输出：

```text
校验通过，可以提交试算。
提交命令：opscli calculator submit calculator-draft-20260702-001/draft.json
```

校验失败时输出中文字段名、单位和示例，例如：

```text
校验失败，需要补充以下字段：

产品信息：
- 包装长：必填，单位 CM，例如 12.5。
- SKU毛重：必填，单位 KG，例如 0.65。

备货设置：
- 仓租分摊比例错误：30天、60天、90天三项之和必须等于 100。当前为 90。
```

第一版校验范围对齐前端关键校验：

1. 必填字段校验。
2. 数值最多两位小数。
3. 需要大于 0 的字段不能小于等于 0。
4. 允许为 0 的百分比字段最多两位小数。
5. 仓租分摊 30/60/90 天比例之和必须等于 100。
6. `battery_power_value` 如果填写必须大于 0 且最多两位小数。
7. `first_order_qty` 如果填写必须大于 0。
8. `calc_method=GROSS_PROFIT` 时要求 `product_price`。
9. `calc_method=PRICING` 时要求 `gross_profit_percent`。
10. 未选择指定仓库时，提交前清空 `baiyi_warehouse_ids`。

### 5.4 提交试算

```bash
opscli calculator submit calculator-draft-20260702-001/draft.json
```

命令行为：

1. 先执行与 `validate` 相同的本地校验。
2. 校验通过后调用 `/calculator/newProduct/doCalc`。
3. 成功后输出任务编号、说明和查询命令。
4. 如果后端只返回 `message=success` 而不返回任务编号，则明确提示用户通过列表命令查询最近任务。

输出示例：

```text
提交成功，试算任务已创建。

任务编号：NPC202607020001
说明：试算过程数据量较大，结果可能需要稍后生成。

查看列表：
opscli calculator list --task-code NPC202607020001

查看详情：
opscli calculator detail --task-code NPC202607020001
```

### 5.5 查询列表

```bash
opscli calculator list --status 1 --tags 采用 --limit 20
```

支持参数：

- `--task-code`：任务编号，多个可用逗号分隔。
- `--status`：试算状态，`0` 试算中，`1` 试算成功，`2` 试算失败。
- `--task-name`：任务名称。
- `--tags`：标签，例如 `采用`、`废弃`。
- `--page`：页码，默认 `1`。
- `--limit`：每页数量，默认 `20`。
- `--json`：输出原始 JSON。

对应接口：`/calculator/newProduct/forecastList`。

### 5.6 查询详情

```bash
opscli calculator detail --task-code NPC202607020001
```

支持参数：

- `--task-code`：任务编号，必填。
- `--sudo`：透传后端字段，可选。
- `--json`：输出原始 JSON。

对应接口：`/calculator/newProduct/taskDetails`。

### 5.7 复制已有任务

```bash
opscli calculator copy --task-code NPC202607010001 --out calculator-draft-copy
```

命令行为：

1. 调用 `/calculator/newProduct/copyTask`。
2. 将返回数据转换为草稿包。
3. 用户修改 `draft.json` 后通过 `validate` 和 `submit` 创建新试算任务。

## 6. 字段字典

CLI 内置字段字典，用于 `字段说明.md`、`缺失项.md`、`show` 摘要和 `validate` 报错。

字段字典至少包含：

| JSON 字段 | 中文名称 | 分组 | 单位 | 示例 | 说明 |
|---|---|---|---|---|---|
| country_code | 试算站点 | 基本信息 | - | US | 试算国家或站点 |
| platforms | 试算平台 | 基本信息 | - | [1, 7] | 支持多平台 |
| hs_code_id | 海关类目 | 基本信息 | - | 12345 | 从下拉数据中选择 |
| package_length | 包装长 | 产品信息 | CM | 12.5 | 单个 SKU 包装长度 |
| package_width | 包装宽 | 产品信息 | CM | 8.2 | 单个 SKU 包装宽度 |
| package_height | 包装高 | 产品信息 | CM | 4 | 单个 SKU 包装高度 |
| box_length | 外箱长 | 产品信息 | CM | 50 | 外箱长度 |
| box_width | 外箱宽 | 产品信息 | CM | 40 | 外箱宽度 |
| box_height | 外箱高 | 产品信息 | CM | 30 | 外箱高度 |
| product_gross_weight | SKU毛重 | 产品信息 | KG | 0.65 | 单个 SKU 毛重 |
| box_gross_weight | 外箱毛重 | 产品信息 | KG | 12 | 单箱毛重 |
| box_number | 单箱数量 | 产品信息 | 件 | 20 | 一个外箱中的产品数量 |
| pick_up_province | 提货省份 | 产品信息 | - | 广东省 | 提货地址省份 |
| pick_up_city | 提货城市 | 产品信息 | - | 深圳市 | 提货地址城市 |
| battery_power_value | 带电功率 | 产品信息 | WH | 10.5 | 带电产品填写 |
| calc_method | 试算方案 | 成本费用 | - | GROSS_PROFIT | `GROSS_PROFIT` 算毛利，`PRICING` 算定价 |
| product_price | 商品售价 | 成本费用 | 站点币种 | 39.99 | 算毛利时必填 |
| gross_profit_percent | 目标毛利率 | 成本费用 | % | 30 | 算定价时必填 |
| purchase_cost_with_tax | 含税采购价 | 成本费用 | CNY | 100 | 国内含税采购价 |
| tax_rate_percent | 税率 | 成本费用 | % | 13 | 采购税率 |
| fee_percent | 平台佣金比 | 成本费用 | % | 15 | 平台佣金比例 |
| advertising_percent | 站内广告 | 成本费用 | % | 10 | 站内广告比例 |
| marketing_percent | 站外营销 | 成本费用 | % | 5 | 站外营销比例 |
| refund_percent | 退款 | 成本费用 | % | 3 | 退款比例 |
| fixed_cost_percent | 固定成本 | 成本费用 | % | 2 | 固定成本比例 |
| tariff_rate | 关税率 | 成本费用 | % | 25 | 未返回时默认 25 |
| stock_qty_first_percent | 30天仓租分摊 | 备货设置 | % | 50 | 三项之和必须为 100 |
| stock_qty_second_percent | 60天仓租分摊 | 备货设置 | % | 30 | 三项之和必须为 100 |
| stock_qty_third_percent | 90天仓租分摊 | 备货设置 | % | 20 | 三项之和必须为 100 |
| first_order_qty | 首单数量 | 备货设置 | 件 | 100 | 可选，填写时必须大于 0 |
| two_zone_combine | 指定二区 | 备货设置 | - | [] | US/CA 部分站点适用 |
| three_zone_combine | 指定三区 | 备货设置 | - | [] | US 站适用 |
| baiyi_warehouse_ids | 指定仓库 | 备货设置 | - | [] | 勾选指定仓库时必填 |
| task_name | 试算名称 | 其他设置 | - | 新品试算 | 最长 25 字 |

## 7. 模块结构

新增目录：

```text
opscli/calculator/
├── __init__.py
├── cli.py
├── client.py
├── models.py
├── draft.py
├── fields.py
└── exceptions.py
```

职责：

| 文件 | 职责 |
|---|---|
| `cli.py` | Typer 命令定义、参数解析、终端输出 |
| `client.py` | Polaris calculator HTTP 接口封装 |
| `models.py` | 请求/响应类型和 payload 读取辅助 |
| `draft.py` | 草稿包生成、摘要、缺失项、校验逻辑 |
| `fields.py` | 中文字段字典、分组、单位、示例 |
| `exceptions.py` | calculator 模块异常 |

在 `opscli/cli.py` 注册：

```python
from opscli.calculator.cli import app as calculator_app
app.add_typer(calculator_app, name="calculator")
```

## 8. 认证与请求

Calculator 属于 Polaris 能力，client 使用现有 `AuthClient`：

```python
headers, cookies = AuthClient().build_request_auth("polaris")
```

要求：

1. 不要求用户传 token。
2. 不把 token 写入草稿包、日志或错误信息。
3. 未登录或 token 失效时，提示用户执行 `opscli auth login`。
4. HTTP 客户端统一使用 `httpx`，超时时间遵循项目规范。

## 9. 错误处理

CLI 面向运营同学，错误要转成中文可操作提示。

常见错误：

| 场景 | 提示 |
|---|---|
| 未登录 | 请先执行 `opscli auth login` 完成登录。 |
| `queryCost` 返回非成功 | 显示后端 message，并提示检查站点、平台、海关类目和参考项。 |
| 草稿文件不存在 | 提示检查路径或重新执行 `opscli calculator draft`。 |
| JSON 格式错误 | 提示具体行列和建议用编辑器检查逗号、引号。 |
| 校验失败 | 使用中文字段名、单位、示例展示。 |
| 提交成功但无任务编号 | 提示稍后用 `opscli calculator list` 查询最近任务。 |

## 10. 输出规范

默认输出中文摘要，适合运营同学阅读。

需要结构化处理时提供 `--json`。`--json` 模式输出后端原始字段或标准化结构，不输出 Rich 表格。

终端输出遵守 Windows GBK 兼容规则，避免使用 emoji 和 GBK 不安全字符。

## 11. 测试策略

第一版测试重点：

1. `client.py` 使用 mocked HTTP，不访问真实网络。
2. `draft.py` 覆盖草稿生成、缺失项识别、中文字段说明生成。
3. `validate` 覆盖：
   - 必填缺失。
   - 小数位限制。
   - 大于 0 校验。
   - 仓租分摊比例不等于 100。
   - `GROSS_PROFIT` 缺 `product_price`。
   - `PRICING` 缺 `gross_profit_percent`。
4. CLI 命令使用 Typer runner 测试：
   - `draft` 能生成四个文件。
   - `show` 输出中文摘要。
   - `validate` 成功和失败路径。
   - `submit` 提交前会先本地校验。

## 12. 后续增强

第一版完成后可按优先级增强：

1. `patch` 命令，支持中文字段名：
   ```bash
   opscli calculator patch draft.json --set 包装长=12 --set 含税采购价=100
   ```
2. Excel 草稿导出和导入，降低运营修改 JSON 的门槛。
3. `wizard` 快速向导，只询问关键缺失项。
4. 本地 HTML 表单，仅在明确有大量非技术用户直接使用 CLI 的需求后再考虑。
5. MCP Tool 和 Skill 编排文档，在 CLI 稳定后补充。

## 13. 验收标准

第一版完成后应满足：

1. 用户可以通过 `draft -> validate -> submit -> list/detail` 完成新品试算闭环。
2. 草稿包包含 `draft.json`、`字段说明.md`、`缺失项.md`、`使用说明.md`。
3. 校验错误使用中文字段名、单位和示例。
4. 不要求用户提供或处理 token。
5. 不依赖 Polaris 网页操作。
6. 所有测试不访问真实网络。
7. 终端输出不包含 GBK 不安全符号。

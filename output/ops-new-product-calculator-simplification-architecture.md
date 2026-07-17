# 新品计算器逻辑精简架构

## 1. 改动边界

仅修改：

- `opscli/calculator/fields.py`
- `opscli/calculator/draft.py`
- `opscli/calculator/cli.py`
- 新品计算器 Skill 的草稿与结果参考说明
- `docs/change-log-pending.md`

不修改客户端路由、认证逻辑、Polaris 前端和后端。

## 2. 草稿数据流

```text
queryCost 返回数据
  → normalize_draft_data 归一化
  → 未返回的包装、重量、箱规字段保持为空
  → 利润成本字段覆盖为 1
  → two_zone_combine 默认写入 ["zone_1_2"]
  → draft.json 保留完整接口字段
  → 填写表格.csv 过滤整个“成本费用”分组
  → 填写表格-旧版.csv 保留完整字段并标记弃用
  → validate 不再要求利润成本字段大于 0
  → submit 保留原字段结构提交
```

### 2.1 成本字段策略

建立一个模块内常量保存需要填充非零占位值的字段名，草稿归一化和提交 payload 准备阶段都统一覆盖为数值 `1`，避免新草稿或历史 `0` 值草稿导致后端计算失败。字段定义中的 `required`、`positive` 和条件必填规则继续取消。CSV 共用同一个底层渲染函数：新版传入排除“成本费用”的字段列表，旧版传入完整 `FIELD_SPECS` 并写入弃用说明。目录模式只读取新版 `填写表格.csv`，字段字典和 `draft.json` 保持完整。

只处理用户明确指出的利润成本输入；`rate` 不归零，`calc_method` 不改为数值。

### 2.2 包装与箱规参考策略

包装参数分为两个独立对象：

- `package_length/package_width/package_height/product_gross_weight` 表示单件 SKU 完成销售包装后的实际数据，用于 FBA 配送尺寸分段和尾程费用。
- `box_length/box_width/box_height/box_gross_weight/box_number` 表示多件 SKU 发往 FBA 仓的实际入库外箱，用于头程/入库运输费用。

接口未返回这些字段时保持空值，不使用字段示例、测试数据、商品名称或尺寸档位上限补齐。生成的 `使用说明.md` 仅展示两类参考：Amazon.sg 官方 SD 卡、图书、电子玩具示例作为单件包装候选；美国 FBA 入库箱 `91.44 × 63.5 × 63.5 cm / 22.68 kg` 作为合规上限提示。所有参考默认不选中、不写入 `draft.json` 或 CSV 当前值；单箱数量不提供默认值。

Skill 读取草稿后按“单件包装 → 入库外箱 → 其他缺失必填项”分轮追问。每轮保留已确认值，只处理仍为空或无效的字段；选择参考模板后仍要求用户确认，全部必填项有效前不进入提交确认。

新品计算器 Skill 在模板 manifest 的 `source/wheel/binary/binary_full` 四个目标中保持启用，确保更新后的补问流程随各发行形态交付。

### 2.3 指定二区策略

在草稿归一化阶段把 `two_zone_combine` 默认写为 `["zone_1_2"]`。该枚举已由业务确认，对应中文值“美东+美西”；字段示例和 Skill 草稿示例同步替换原 `zone_1_3`。

## 3. 结果数据流

```text
taskDetails 返回 data
  → detail 读取 data.allPlans
  → 每个 plan 保留方案级字段
  → schemes 逐项格式化为多行单元格
  → Rich Table 一次性只读输出
  → 默认结束，不再读取原始 JSON、成本或利润字段
```

结果展示由 `calculator detail` 固化，Skill 不重新解析或改写表格。普通查询只调用一次 `detail`；`--json` 仅用于用户明确要求的原始字段诊断。默认输出在表格后追加可直接访问的线上详情链接，但不追加 Web 页面能力说明和原始 JSON 命令，避免 Agent 沿提示继续读取成本、利润与毛利数据。

### 3.1 表格映射

| 表头 | 数据来源 | 格式 |
|---|---|---|
| 分区推荐 | `plan.partition_recommend` | 文本 |
| 首单数量 | `scheme.first_order_qty` | 原值；按 `allPlans[0].first_order_qty` 控制整列显隐 |
| 分区线路 | `scheme.lines` | 文本 |
| 每PCS头程费用(CNY) | `scheme.first_fee.value/range` | 4 位小数 + 区间 |
| 每PCS目的仓费用(CNY) | `scheme.storage_fees.value/range` | 4 位小数 + 区间 |
| 每PCS尾程费用(CNY) | `scheme.freight.value/range` | 4 位小数 + 区间 |
| 每PCS全程费用(CNY) | `scheme.scheme_fee/scheme_range` | 4 位小数 + 区间 |
| 每PCS全程平均费用(CNY) | `plan.total_fee` | 4 位小数 |

每个 `plan` 对应 Rich Table 的一行；`schemes` 内多个线路使用换行展示，保持与前端同一方案内纵向排列的结构。CLI 使用固定的完整表格渲染宽度，避免窄终端把表头和费用区间省略为省略号。

## 4. 错误与空数据

- `allPlans` 缺失或不是列表：输出“暂无方案数据”。
- 单项费用缺失：显示“未填写”，不推算。
- `schemes` 为空：仍展示方案级分区推荐和平均费用。
- 不为旧 `trial_result` 增加结果回退，避免继续输出已废弃结果形态。

## 5. 多轮交互边界

- Polaris 登录与权限在同一连续任务首次远程调用前检查一次；仅遇到 401、Token 过期或开启新任务时重新检查。
- 用户补充包装、箱规或地址时，只更新并读取当前 `填写表格.csv`，不重复执行认证、`show`、下拉查询或 `validate`。
- 全部必填字段有效后只运行一次 `validate`，校验通过后进入提交确认。
- CLI 固化确定性数据输出，Skill 仅负责阶段识别、分轮补问和提交门禁。

## 6. 实施与验证约束

- 精确修改现有函数，不新增外部依赖。
- 只补充本需求相关的草稿说明与 Skill 契约测试。
- 不运行 type-check、eslint 或格式化检查。
- 实施后只做代码差异自检和针对样例数据的 CLI 输出核对。

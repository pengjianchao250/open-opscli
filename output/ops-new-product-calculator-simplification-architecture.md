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
  → 利润成本字段覆盖为 0
  → two_zone_combine 默认写入 ["zone_1_2"]
  → draft.json 保留完整接口字段
  → 填写表格.csv 过滤整个“成本费用”分组
  → 填写表格-旧版.csv 保留完整字段并标记弃用
  → validate 不再要求利润成本字段大于 0
  → submit 保留原字段结构提交
```

### 2.1 成本字段策略

建立一个模块内常量保存需要归零的字段名，归一化时统一覆盖，避免在多个分支重复赋值。字段定义中的 `required`、`positive` 和条件必填规则同步取消。CSV 共用同一个底层渲染函数：新版传入排除“成本费用”的字段列表，旧版传入完整 `FIELD_SPECS` 并写入弃用说明。目录模式只读取新版 `填写表格.csv`，字段字典和 `draft.json` 保持完整。

只处理用户明确指出的利润成本输入；`rate` 不归零，`calc_method` 不改为数值。

### 2.2 指定二区策略

在草稿归一化阶段把 `two_zone_combine` 默认写为 `["zone_1_2"]`。该枚举已由业务确认，对应中文值“美东+美西”；字段示例和 Skill 草稿示例同步替换原 `zone_1_3`。

## 3. 结果数据流

```text
taskDetails 返回 data
  → detail 读取 data.allPlans
  → 每个 plan 保留方案级字段
  → schemes 逐项格式化为多行单元格
  → Rich Table 一次性只读输出
```

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

每个 `plan` 对应 Rich Table 的一行；`schemes` 内多个线路使用换行展示，保持与前端同一方案内纵向排列的结构。

## 4. 错误与空数据

- `allPlans` 缺失或不是列表：输出“暂无方案数据”。
- 单项费用缺失：显示“未填写”，不推算。
- `schemes` 为空：仍展示方案级分区推荐和平均费用。
- 不为旧 `trial_result` 增加结果回退，避免继续输出已废弃结果形态。

## 5. 实施与验证约束

- 精确修改现有函数，不新增外部依赖。
- 不新增测试用例。
- 不运行 type-check、eslint 或格式化检查。
- 实施后只做代码差异自检和针对样例数据的 CLI 输出核对。

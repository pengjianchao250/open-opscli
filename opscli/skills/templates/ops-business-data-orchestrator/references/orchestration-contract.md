# 业务取数编排契约

本文件定义复合业务取数任务的最小内部结构、状态语义、委托上下文和交付格式。它只描述 Codex 业务层编排，不保存底层查询实现，也不包含 Dashboard 页面状态。

## 1. 任务结构

使用以下逻辑结构组织任务。无需强制生成实体 JSON 文件；只有用户明确要求 JSON 时才输出文件或代码块。

```json
{
  "request_id": "inventory-health-001",
  "business_goal": "了解库存健康状态并识别风险商品",
  "scope": {
    "business_objects": [],
    "time_range": null,
    "confirmed_constraints": []
  },
  "questions": [
    {
      "question_key": "inventory_overview",
      "business_question": "当前整体库存规模和结构如何",
      "business_purpose": "形成库存总览",
      "result_type": "overview",
      "dependencies": [],
      "delegate_to": null,
      "status": "pending",
      "actual_dataset_name": null,
      "actual_time_range": null,
      "dimensions": [],
      "metrics": [],
      "row_count": null,
      "result_summary": null,
      "limitations": [],
      "warnings": []
    }
  ]
}
```

## 2. 字段约束

### 任务字段

- `request_id`：当前编排任务的临时稳定标识，不写入凭证或用户敏感信息。
- `business_goal`：用户原始业务目标的简洁复述。
- `scope`：只记录用户已明确或已确认的业务范围。
- `questions`：有限、互不重复的数据问题清单。

### 问题字段

- `question_key`：当前任务内唯一的英文蛇形标识。
- `business_question`：要由真实数据回答的问题。
- `business_purpose`：该结果支持什么业务判断。
- `result_type`：只能使用 `overview`、`trend`、`comparison`、`ranking`、`structure`、`risk`、`detail`。
- `dependencies`：前置 `question_key` 列表；没有依赖时为空数组。
- `delegate_to`：实际选择的 `ops-dataset-query` 或 `ops-query-wizard`。
- 查询结果字段：只在依赖 Skill 返回真实内容后填写。

不得预填数据集 ID、字段 ID、查询表达式、筛选枚举值、Dashboard 页面 ID 或认证信息。

## 3. 状态语义

| 状态 | 含义 |
| --- | --- |
| `pending` | 已规划，尚未委托 |
| `running` | 当前正在由依赖 Skill 处理 |
| `success` | 已获得可用于汇总的真实结果 |
| `blocked` | 查询失败或外部条件阻止完成 |
| `needs_confirmation` | 需要用户确认范围或选择后才能继续 |
| `not_run` | 因前置依赖阻塞或范围未获确认而未执行 |

不要用一个总状态覆盖所有问题。部分成功时，分别保留每个问题的真实状态。

## 4. 委托上下文

委托给现有 Skill 时，只传递完成当前问题所需的业务上下文：

```text
业务问题：<business_question>
业务用途：<business_purpose>
已确认范围：<用户明确确认的时间、对象和筛选范围>
前置结果：<只有当前问题确实依赖时才提供>
期望结果类型：<result_type>
```

- 不替依赖 Skill 指定数据集或字段。
- 不把其他问题的无关结果塞入上下文。
- 前置结果只做上下文，不改写为新的事实。
- 不传递或构造 Dashboard 页面上下文。

## 5. 路由判定

| 当前问题状态 | 委托方式 |
| --- | --- |
| 业务对象、时间范围、指标含义和输出粒度足够明确 | 使用 `$ops-dataset-query` |
| 存在会影响查询结果的关键缺参或语义歧义 | 使用 `$ops-query-wizard` |
| 用户指出该问题的已有结果有误 | 使用 `$ops-query-wizard` 纠错模式 |

路由后遵循被调用 Skill 的完整规则。业务层不接管其认证、元数据、字段校验、查询执行、导出或反馈闭环。

## 6. 查询前输出

```markdown
## 业务目标
<business_goal>

## 查询计划
1. <business_question> — 用途：<business_purpose>
2. <business_question> — 用途：<business_purpose>

- 预计查询数量：N
- 执行顺序：<独立项 / 前后依赖说明>
- 待确认范围：<无 / 具体问题>
```

## 7. 查询后输出

```markdown
## 业务目标
<business_goal>

## 数据问题结果
### 1. <business_question>
- 状态：<status>
- 数据范围：<真实时间、对象、维度和指标摘要>
- 结果摘要：<仅基于真实结果>
- 数据限制：<无 / 截断、缺失、口径、警告>

## 综合结果
- <多个成功结果共同支持的现象>

## 未完成或待确认
- <blocked / needs_confirmation / not_run 项目及原因>
```

如果没有成功结果，省略“综合结果”中的业务判断，只报告状态和下一步所需信息。

## 8. 完整性检查

交付前逐项确认：

- 每个问题只有一个主要业务判断。
- 没有重复问题或无业务用途的查询。
- `success` 项均有真实数据范围和结果来源。
- 阻塞项没有被写成成功或被纳入综合结论。
- 综合结论没有把相关性写成确定因果。
- 没有进入用户未要求的业务域。
- 没有读取、分析或修改当前 Dashboard 页面。
- 已回答原始目标后没有继续扩展查询。

# 执行日志与学习日记规范

本规范用于生成或更新运营 Skill 时，给目标 Skill 配套轻量日志能力。日志的目标不是监控个人，而是判断 Skill 是否真实有效、哪里失败、哪些经验可以沉淀。

## 1. 日志分层

默认分两层：

| 层级 | 建议路径 | 用途 |
| --- | --- | --- |
| 执行摘要 | `runs/YYYY-MM.jsonl` | 每次运行一行 JSON，便于统计执行次数、成功率、失败原因 |
| 学习日记 | `diary/YYYY-MM-DD.md` | 用户纠正、错误复盘、功能需求、可沉淀经验 |

目标 Skill 打包提交时，不要把 `runs/`、`diary/`、`outputs/` 放进 Skill 包。提交包只带汇总后的 `run-summary.json`。

## 2. 执行摘要 `[RUN]`

每次 Skill 完成一次真实运行后，追加一行 JSONL。

```json
{
  "time": "2026-05-18T16:30:00+08:00",
  "employee": "zhangsan",
  "department": "Amazon运营一部",
  "runtime": "codex",
  "skill_name": "amazon-keyword-rank-check",
  "skill_version": "0.1.0",
  "skill_commit": "abc123",
  "intent": "每周检查核心 ASIN 关键词自然排名",
  "input_summary": {
    "platform": "Amazon",
    "site": "US",
    "date_range": "2026-05-01~2026-05-15",
    "asin_count": 12
  },
  "data_sources": [
    {
      "type": "ops",
      "dataset": "候选数据集或导出文件",
      "fields": ["date_id", "asin", "rank"],
      "status": "success"
    }
  ],
  "status": "success",
  "output_type": "html_report",
  "output_paths": ["outputs/report.html"],
  "assertions_passed": 5,
  "assertions_total": 6,
  "error_category": "",
  "severity": "",
  "feedback": ""
}
```

必填字段：

- `time`
- `skill_name`
- `skill_version`
- `intent`
- `status`: `success` / `partial` / `failed`
- `input_summary`: 只放摘要，不放原始明细

建议字段：

- `employee`
- `department`
- `runtime`
- `skill_commit`
- `data_sources`
- `assertions_passed`
- `assertions_total`
- `error_category`
- `feedback`

## 3. 学习日记类型

学习日记使用 Markdown，按类型记录。

### `[LRN]` 用户纠正或业务规则

```markdown
### 2026-05-18 15:30 - [LRN] 判断规则: 低样本广告不能直接停投
* **Priority**: high
* **Area**: amazon_ads
* **Details**: 用户纠正：花费高但点击少时，不能直接判断浪费，需要先看样本量和转化周期。
* **Action**: 在广告诊断 Skill 中增加低样本保护规则。
* **Source**: user_feedback
* **Count**: 1
* **Status**: pending
```

### `[ERR]` 执行错误

```markdown
### 2026-05-18 16:10 - [ERR] ops 字段不存在导致查询失败
* **Priority**: high
* **Area**: ops_data
* **Error**: 字段 `acos` 不存在
* **Context**: 试图直接查询 ACOS，而不是用 spend / sales 聚合计算
* **Fix**: 生成 Skill 时必须区分原始字段和派生指标
* **Reproducible**: yes
* **Status**: pending
```

### `[FEAT]` 新需求

```markdown
### 2026-05-18 17:20 - [FEAT] 增加 HTML 周会版摘要
* **Priority**: medium
* **Area**: output
* **Request**: 运营希望把报告第一屏改成适合周会展示的摘要。
* **User Context**: 主管只看前 3 个异常和行动建议。
* **Complexity**: simple
* **Status**: pending
```

### `[REF]` 复盘反思

```markdown
### 2026-05-18 18:00 - [REF] 广告诊断输出: 建议不够可执行
* **What I did**: 生成了 ACOS 异常报告
* **Outcome**: partial
* **Reflection**: 指出异常但没有给出优先级和动作负责人
* **Lesson**: 输出异常清单时必须带动作、优先级和负责人字段
* **Status**: pending
```

## 4. 3 次确认机制

把 `self-improvement` 的 3-count 机制用于运营 Skill：

1. 第一次出现同类纠正：记录 `Count: 1`
2. 第二次出现：记录 `Count: 2`，加 `See Also`
3. 第三次出现：询问运营或负责人是否固化为长期规则

如果用户明确说“以后都这样”“记住这个”“我们团队默认这样”，可以立即进入候选规则，不必等 3 次。

进入正式 Skill 规则前，必须满足：

- 能写成清楚规则、追问条件、脚本校验或输出约束。
- 不与已有正常案例冲突；如可能冲突，先写成例外。
- 已补测试用例或断言。
- 通过旧版 vs 新版回归对比。
- 业务负责人或用户确认。

## 5. 敏感信息规则

日志不能记录：

- token、cookie、密码、密钥、授权 header。
- Amazon 后台账号、公司内部系统账号。
- 未脱敏的客户、供应商或个人信息。
- 大批量原始明细数据。

可以记录：

- 时间范围、平台、站点、ASIN 数量、字段名、数据集名。
- 输出文件路径或文件 hash。
- 错误类别和摘要。
- 用户反馈摘要。

## 6. 交付给目标 Skill 的写法

生成目标 Skill 时，加入：

```markdown
## 执行日志

- 每次真实运行后，按 `references/execution-log-schema.md` 记录一条执行摘要。
- 默认日志位置：`runs/YYYY-MM.jsonl`。
- 不把 `runs/`、`diary/`、`outputs/` 打包进 Skill。
- 出现用户纠正、错误或新需求时，写入 `diary/YYYY-MM-DD.md`。
```

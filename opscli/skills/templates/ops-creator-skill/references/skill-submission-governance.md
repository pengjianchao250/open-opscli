# 内测 Skill 提交治理

本规范用于内测运营同事创建自己的 Skill 后，判断哪些 Skill 值得同步给团队。原则是：不收灵感草稿，只收已经被真实使用证明过的候选 Skill。

## 1. 生命周期状态

| 状态 | 含义 | 是否同步 |
| --- | --- | --- |
| `personal_draft` | 个人试验，刚创建或没跑几次 | 不同步 |
| `candidate` | 多次执行有效，值得提交 | 提交候选包 |
| `team_beta` | 审核通过，给内测团队用 | 同步到团队库 |
| `standard` | 稳定、多人复用、可作为公司标准 | 进入正式发布治理 |

目标 Skill 默认先是 `personal_draft`。达到候选门槛后，由 AI 提醒运营确认是否提交。

## 2. 候选门槛

内测期默认轻量门槛：

```text
最近 14 天内执行 >= 3 次
成功率 >= 70%
至少 1 次真实业务输入
没有 critical 失败
用户没有标记“结果不可用”
SKILL.md 存在且 description 不为空
没有 token、cookie、密码、账号、密钥等敏感信息
运营本人确认愿意提交
```

更稳的团队标准门槛：

```text
执行 >= 5 次
成功率 >= 80%
至少 2 个不同真实业务场景
至少 1 条正向反馈或明确复用意愿
有 CHANGELOG 或版本号
有 2-3 个测试 prompt
涉及 ops 数据时有字段、聚合、过滤和口径说明
```

## 3. 提交包结构

候选 Skill 提交时，生成脱敏提交包：

```text
submitted-skills/
└── zhangsan/
    └── amazon-keyword-rank-check/
        └── 0.1.0/
            ├── skill.zip
            ├── submission.json
            ├── run-summary.json
            ├── safety-check.json
            └── feedback-summary.md   # 可选
```

`skill.zip` 只包含 Skill 本体，不包含：

- `.git/`
- `runs/`
- `diary/`
- `outputs/`
- `dist/`
- `tmp/`
- `.DS_Store`
- `__pycache__/`
- `*.pyc`
- `.env`
- token、cookie、密码、密钥文件

## 4. `submission.json`

```json
{
  "employee": "zhangsan",
  "department": "Amazon运营一部",
  "skill_name": "amazon-keyword-rank-check",
  "version": "0.1.0",
  "runtime": "codex",
  "status": "candidate",
  "business_use": "每周检查核心 ASIN 关键词自然排名",
  "run_count_14d": 5,
  "success_rate": 0.8,
  "last_run_at": "2026-05-18T15:30:00+08:00",
  "contains_internal_data": true,
  "contains_sensitive_data": false,
  "submit_reason": "已连续 2 周用于周会前检查，输出能直接给组长看"
}
```

## 5. `run-summary.json`

```json
{
  "runs": 5,
  "success": 4,
  "failed": 1,
  "success_rate": 0.8,
  "top_intents": ["关键词排名检查", "异常词清单生成"],
  "failure_categories": ["缺少上周对比数据"],
  "outputs": ["markdown_report", "html_report"],
  "user_feedback": ["报告结构可用", "需要补充新品例外规则"]
}
```

## 6. `safety-check.json`

```json
{
  "contains_sensitive_data": false,
  "findings": [],
  "excluded_paths": [".git/", "runs/", "outputs/"],
  "checked_at": "2026-05-18T16:30:00+08:00"
}
```

如果发现敏感信息，默认停止打包；只有用户明确确认并完成清理后，才允许重新提交。

## 7. 提交流程

1. 运营本地创建并使用 Skill。
2. 每次真实执行后写入 `runs/YYYY-MM.jsonl`。
3. 每周或用户请求时，运行 `scripts/qualify_candidate.py`。
4. 达到门槛后，AI 提醒：“这个 Skill 已经满足候选提交条件，要提交给团队候选库吗？”
5. 用户确认后，运行 `scripts/package_submission.py`。
6. 生成提交包到团队共享目录或后续 ops 后端入口。
7. 审核人决定是否进入 `team_beta` 或 `standard`。

## 8. 生成目标 Skill 时的写法

目标 Skill 应包含：

```markdown
## 内测提交

- 默认状态：`personal_draft`。
- 多次执行有效后，按 `references/skill-submission-governance.md` 判断是否成为 `candidate`。
- 使用 `scripts/qualify_candidate.py` 汇总运行日志并判断候选门槛。
- 用户确认提交后，使用 `scripts/package_submission.py` 生成脱敏提交包。
- 未经用户确认，不自动提交 Skill。

## 9. 打包边界

提交包和安装包只放运行所需内容。默认排除：

- `__pycache__/`、`.pyc`、`.pyo`、`.pytest_cache/`
- `.git/`、`.DS_Store`、`.env`
- `runs/`、`diary/`、`outputs/`、`dist/`、`tmp/`
- 维护态文件：`AGENTS.md`、`CHANGELOG.md`、`VERSIONING.md`

如果团队确实需要变更记录，把发布说明放到提交包的 `submission.json`、`run-summary.json` 或 `references/release-plan.md`，不要让运行时 Skill 依赖顶层维护文档。

打包完成后，最终回复必须列出压缩包路径、文件数量、安全检查结论和是否已获得用户确认。
```

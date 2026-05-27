# 运营 Skill 统一框架标准

本标准用于新建运营 Skill，也用于把运营同事已经制作好的旧 Skill 归一化。目标不是把所有内容塞进 `SKILL.md`，而是在不减少内容的前提下，让日常执行加载更少、测试发布时能展开更多。

## 目录结构

推荐结构：

```text
skill-name/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── references/
│   ├── flow-map.md
│   ├── data-plan.md
│   ├── data-recipes.md
│   ├── operating-rules.md
│   ├── testing-benchmark.md
│   ├── cross-tool-portability.md
│   ├── execution-log-schema.md
│   └── skill-submission-governance.md
└── scripts/
    ├── [deterministic_task].py
    ├── validate_output.py
    ├── record_run.py
    ├── qualify_candidate.py
    └── package_submission.py
```

不是每个 Skill 都必须有所有文件，但只要涉及对应能力，就使用这些固定名称或清楚的同义名称，方便跨 Skill 管理。

## SKILL.md 必备章节

`SKILL.md` 是执行路由，不是完整知识库。默认保留这些章节：

1. `## 目标`
2. `## 快速开始`
3. `## 必要参数`
4. `## 日常工作流`
5. `## 默认执行策略`
6. `## 按需加载资料`
7. `## 错误处理`
8. `## 输出规范`
9. `## 执行日志与候选提交`

可选章节：

- `## 判断规则`：只放最核心的 3-7 条规则，详细规则放 `references/operating-rules.md`。
- `## 脚本调用`：只放最常用命令，完整参数放脚本 `--help` 或 reference。
- `## 测试与基准对比`：只放一句“更新或发布前必须读取 testing-benchmark”，详细用例放 reference。

`## 默认执行策略` 用于避免已固化 Skill 每次都重新分析流程、解释方法或重复预检。默认写清：

- 用户要求“执行、分析、生成、检查”时，按已固化流程直接处理，只追问缺失的必要参数。
- 已验证的数据路径和脚本直接复用；不重复做 catalog 搜索、字段预检、baseline 测试或发布治理。
- 只有缺参数、字段/权限/空结果异常、新场景超出固化范围、用户要求解释流程、测试、优化、发布或跨工具迁移时，才加载对应 reference 并展开分析。
- 最终回复默认只给结果、关键口径、输出路径和异常提醒，不输出完整流程说明。

## 按需加载资料表

主文件必须有一张简短加载表，告诉 AI 什么时候读哪个 reference：

| 场景 | 读取 |
| --- | --- |
| 需要理解完整业务背景、案例、术语 | `references/flow-map.md` |
| 日常执行且已有固化取数规则 | 优先直接执行脚本或已验证 recipe，不重新读完整 `data-plan.md` |
| 新数据、新字段、空结果、权限失败或口径变化 | `references/data-plan.md`，必要时 `references/data-recipes.md` |
| 需要完整判断规则、阈值、例外 | `references/operating-rules.md` |
| 需要跨工具复用或降级 | `references/cross-tool-portability.md` |
| 用户要求测试、回归、评分或发布前验收 | `references/testing-benchmark.md` |
| 需要记录运行或提交候选 | `references/execution-log-schema.md`、`references/skill-submission-governance.md` |

## 内容放置规则

- 主 `SKILL.md`：放触发、参数、日常流程、错误处理、输出和加载规则。
- `flow-map.md`：放六维访谈、成功/边界/失败案例、术语、待确认问题。
- `data-plan.md`：放数据意图、候选数据集、字段聚合、过滤、取数预检、空结果和降级。
- `data-recipes.md`：放可复制的 query JSON、CLI 命令、字段映射；优先使用 `table_id`，同时记录 alias。
- `operating-rules.md`：放完整判断规则、阈值、例外、升级条件。
- `testing-benchmark.md`：放 prompt、baseline、断言、评分、回归门槛。
- `cross-tool-portability.md`：放当前工具能力和通用替代方案。
- `scripts/`：放稳定重复、可参数化、对准确性要求高的动作。

## Token 预算

日常执行建议只加载：

- `SKILL.md`
- 与本次任务直接相关的 0-2 个 reference
- 必要脚本，不全文读取脚本，优先运行 `--help` 或直接执行

目标：

- 普通运营执行：尽量控制在 6k-8k tokens 的技能上下文内。
- 新人培训、发布治理、跨工具迁移、错误排查、用户要求优化：允许加载更多 reference，但要显式说明为什么加载。
- 不为省 token 删除业务内容；通过拆分、路由和脚本固化降低默认加载量。

## 新建 Skill 验收

新建 Skill 交付前检查：

- 创建价值已通过：不是一次性通知、单条文案、临时消息、泛泛想法或无复用场景。
- `不应触发` 边界清楚：写明哪些任务应直接完成、转成 prompt 模板或停在待确认 brief。
- AI 代答和默认假设没有被写成事实；所有未确认规则都标为 `[待确认]`。
- `description` 具体说明做什么、何时触发、业务关键词。
- `SKILL.md` 有快速开始、必要参数、日常工作流、默认执行策略、按需加载资料、错误处理、输出规范。
- 涉及内部数据时有 `data-plan.md` 或等价内容，并写明字段校验和 smoke query。
- 涉及内部数据时，主流程要区分“生成/更新前的取数预检”和“日常执行的已固化取数规则”，避免每次运行都重新预检。
- 涉及团队复用时有测试、日志、候选提交和发布治理。
- 可脚本化步骤已放入 `scripts/`，脚本有明确输入输出和 JSON 摘要。
- 正式落地已通过当前环境的 skill-creator/技能创建能力，而不是只生成流程 brief。
- 交付包含安装路径、校验结果、测试清单和打包/无需打包理由；只生成本地文件不算完成。
- 至少跑过一次 smoke 测试或明确标记未验证原因。

## 旧 Skill 归一化验收

旧 Skill 改造完成后检查：

- 有改造前基线版本或备份。
- 核心行为、脚本输入输出和已有用户触发方式没有被静默破坏。
- 公共取数方案、字段更新、依赖升级等基础设施修正先同步到新旧对照版本，不作为新版优劣证据。
- 使用同一批输入数据对比旧版和新版输出。
- 差异分为：框架/流程差异、数据/基础设施差异、真实业务结论差异。
- 日常执行上下文负担有估算，并说明优化方式。

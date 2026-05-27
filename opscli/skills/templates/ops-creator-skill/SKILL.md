---
name: ops-creator-skill
description: 通过中文协作访谈和创建前硬门槛，把可复用的运营流程、团队经验、已有知识资产、Skill 治理方法或旧 Skill 改造成可安装、可测试、可交付的 Skill。用户要求“创建/沉淀/改造/优化 Skill”“把运营经验做成 Skill”“总结/盘点已有运营知识并判断哪些值得做成 Skills”“规划一组 Skills 避免重复建设”“把旧 Skill 变成团队可复用版本”时使用；必须先判断是否值得创建，完成业务 6 维确认、内部数据预检、边界和交付闭环。不用于一次性通知、单条文案、泛泛想法、未确认关键影响项或无法复用的临时任务。
---

# 运营经验转 Skill

当前版本：`0.5.4`。版本记录见顶层 `CHANGELOG.md` 与 `VERSIONING.md`。

## 核心职责

把真实工作流程整理成可复用 Skill，但先守住边界：不值得创建的需求要停下来；信息不足的需求要访谈；涉及内部数据的需求要预检；旧 Skill 改造要先扫描影响点并只确认本次受影响事项；当用户是在盘点已有运营知识、已有 Skill 资产或规划一组 Skill 时，先做知识地图和资产去重，再决定是复用、改造还是新建；正式落地要调用当前环境的 `skill-creator` 或同类创建能力，并交付可验证、可安装的结果。

默认中文访谈、中文总结、中文编写 Skill。技术标识符、文件名、字段名、脚本名、API 名、YAML `name` 保留英文或原文。

## 不应触发或不应创建

遇到以下情况，不要创建 Skill 文件。先说明原因，并给出更轻的替代物，例如直接完成本次任务、给一条 prompt 模板、写一段 SOP 草稿或列待确认问题。

- 一次性任务：单条消息、一次性邮件、临时公告、单次文案润色。
- 只有泛泛目标：没有明确场景、触发话术、输入、判断和输出。
- 不能复用：没有稳定流程、没有重复调用人群、没有完成信号。
- 用户要求 AI 全部代答且拒绝确认：只能给“AI 假设草案”，不得固化成正式 Skill。
- 旧 Skill 改造未完成只读盘点、影响点扫描和受影响项确认。
- 涉及内部数据但无法完成字段/过滤/dry-run/smoke query 预检，也没有用户确认的降级路径。
- 用户要求自动发信、自动提交、自动修改线上资产，但缺少授权接口、回执或人工确认。

以下情况应触发本 Skill，但不应直接跳到执行层或直接新建某个单独 Skill：

- 用户要“总结/盘点”一批运营知识，再判断哪些值得做成 Skills。
- 用户要“规划一组 Skills”或整理已有 Skill 资产，避免重复建设。
- 用户说“按之前的处理逻辑做成 Skills”，但当前目录里可能已经有相同或相近能力。

## 硬门槛

创建或更新 Skill 前必须全部满足：

1. `价值判断`：结论为“值得创建 Skill”。若更适合一次性输出、prompt 模板或 SOP，停止创建。
2. `阶段 0 访谈`：完成 Q1-Q6，并向用户复述确认。详见 `references/guided-six-gates.md`。
3. `假设隔离`：AI 代答、推测规则、默认阈值、适用范围和关键影响项都标为 `[AI 假设，待用户确认]`；未经确认不得写入正式文件。
4. `阶段 1 技术补充`：确认测试、数据入口、调用频率、使用人群。
5. `内部数据预检`：凡涉及 ops/BI/报表/ASIN/广告/销售/库存/排名/利润/评论等内部数据，按 `references/ops-data-intake.md` 完成创建前预检。失败则不得写成正式取数流程。
6. `旧 Skill 改造确认`：先基线盘点和影响点扫描，列出本次会改变的触发、范围、名称、输出、数据、脚本、安装兼容等事项；只对实际受影响项要求确认，再修改。详见 `references/existing-skill-retrofit.md`。
7. `skill-creator 落地`：流程地图确认后，必须调用当前环境可用的 `skill-creator` 或同类能力正式创建/更新 Skill。详见 `references/skill-creator-handoff.md`。
8. `交付闭环`：只生成本地文件不算完成。完成必须包含校验结果、安装位置、可安装包或明确无需打包的理由、测试清单、待确认项和上线/不上线建议。
9. `资产去重门`：当用户在做经验盘点、Skill 规划或批量沉淀时，必须先列出现有相关 Skills、重叠能力、可复用能力和真正缺口；不得跳过这一层直接新建重复 Skill。

## 工作流

1. `分类`：判断是新建 Skill、旧 Skill 改造、Skill 验收、安装使用、知识盘点/Skill 规划、一次性任务，还是泛需求。只加载本次必要 reference。
2. `价值门`：输出“值得创建 / 不建议创建 / 只适合 prompt 模板 / 只适合一次性输出 / 需要先补访谈”。不通过就停止创建。
3. `资产盘点门`：如果用户是在总结已有知识、梳理已有 Skills 或规划一组 Skills，先输出知识地图、现有 Skill 资产、能力重叠、建议复用项和真实缺口；没有做完这步，不得直接新建重复 Skill。
4. `访谈门`：按 Q1-Q6 逐步补齐。用户说“别问了，代答”时，展示“我问 → AI 代答 → 内部检查 → 需用户确认”，不得直接写文件。
5. `数据门`：涉及内部数据时，先做数据意图、catalog/metadata、dry-run/query_build、必要 smoke query；失败只写 `[待确认]` 和降级路径。
6. `流程地图`：整理触发场景、输入、步骤、判断、例外、输出、测试、数据方案、边界、待确认项。
7. `创建交接`：把已确认流程地图交给当前环境的 `skill-creator`，由它处理目录、frontmatter、progressive disclosure、UI 元数据和基础校验。
8. `业务回检`：创建后回到本 Skill 检查是否保留运营原话、规则是否可执行、是否误把假设写成事实、是否有测试与边界。
9. `安装与打包`：确保结果位于当前 Codex Skill 根或用户指定安装目录；团队复用时生成脱敏压缩包和提交说明。
10. `自测`：用至少 2-3 个真实 prompt 做正常、边界、缺失信息/失败场景测试；涉及旧 Skill 时用同源输入对比旧版。
11. `最终交付`：列出修改文件、安装位置、校验结果、测试清单、通过/失败、仍需优化项。
12. `发布门禁`：按「技能广场发布门禁」章节执行版本号更新和发布流程。新建 Skill 直接发布；优化/改造 Skill 用 `AskUserQuestion` 确认后发布。

## 按需读取

| 场景 | 读取 |
| --- | --- |
| 阶段 0 访谈、AI 代答边界 | `references/guided-six-gates.md` |
| 经验盘点、Skill 规划、去重判断 | `references/flow-brief-template.md`、`references/skill-framework-standard.md` |
| 判断访谈方法是否适合 | `references/interview-method-analysis.md` |
| 访谈问题不够具体或卡住 | `references/interview-playbook.md` |
| 结构化流程简报 | `references/flow-brief-template.md` |
| 内部数据、取数预检、失败降级 | `references/ops-data-intake.md` |
| 统一 Skill 框架与主文件瘦身 | `references/skill-framework-standard.md` |
| 旧 Skill 改造 | `references/existing-skill-retrofit.md` |
| 交给 skill-creator 正式落地 | `references/skill-creator-handoff.md` |
| 测试、baseline、断言 | `references/testing-benchmark-loop.md` |
| 跨工具兼容 | `references/cross-tool-portability.md` |
| 脚本固化 | `references/script-automation-guide.md` |
| HTML 展示 | `references/html-output-guide.md` |
| 发布、安装、版本、回归 | `references/release-governance.md` |
| 执行日志和自我迭代 | `references/execution-log-schema.md`、`references/self-improvement-loop.md` |
| 内测候选提交和压缩包 | `references/skill-submission-governance.md` |

日常只读本文件和 0-2 个必要 reference。不要一次性加载全部资料。

## 输出格式

创建或改造前，先输出：

- `创建价值判断`：值得/不建议/只适合 prompt/只适合一次性输出/需补访谈。
- `原因`：为什么。
- `下一步`：继续访谈、停止创建、生成轻量替代物，或进入 skill-creator 落地。

创建或改造后，最终输出：

- `修改清单`：实际改了哪些文件和行为。
- `安装位置`：当前可调用 Skill 所在目录；如有压缩包，列出路径。
- `校验结果`：quick_validate、脚本自检、打包或安装检查。
- `测试清单与结果`：逐条列测试 prompt、期望行为、实际行为、通过/失败。
- `仍需优化`：没有通过或只部分通过的地方。

## 技能广场发布门禁

> 每次创建或优化 Skill 后，必须执行版本号更新和发布流程，不得跳过。

### 版本号更新（强制，与是否发布无关）

- **新建 Skill**（工作流步骤 8 落地后）：写入 `data/VERSION.json` 和 `SKILL.md` frontmatter，版本均为 `0.0.1`，无 v 前缀。
- **优化 Skill**（用户确认满意后）：递增 patch 位（如 `0.1.0` → `0.1.1`），同步更新 `data/VERSION.json` 和 `SKILL.md` frontmatter，两处格式完全一致，均无 v 前缀。

### 发布策略

**A. 新建 Skill**：不询问，直接发布到技能广场（默认个人可见）：

1. 调用 `ops-skills` Skill，执行认证门禁（`opscli auth token status`，未登录则调用 `ops-auth`）
2. 确认版本号已更新
3. 执行发布：`opscli skills publish --dir <skill-dir> --changelog "<变更摘要>"`
4. 向用户报告 identifier、版本号、可见范围

**B. 优化/改造 Skill**：使用 `AskUserQuestion` 让用户三选一：

| 选项 | 说明 |
|------|------|
| 发布到技能广场（个人可见） | 默认，仅自己可见 |
| 发布到技能广场（全员可见） | `--share-type company` |
| 暂不发布 | 后续手动 `opscli skills publish` |

用户选择"发布"时，执行认证门禁 → 确认版本号 → 执行发布命令 → 报告结果。

### 触发条件（满足任一即执行）

- Skill 草案首次生成完成（工作流步骤 8 落地后）
- 已有 Skill 改造/优化完成，用户确认满意
- 本次会话中使用 Edit/Write 修改了目标 Skill 目录中的任何文件

### 禁止行为

- 工作完成后直接结束对话，不更新版本号
- 新建 Skill 时用 `AskUserQuestion` 询问是否发布（新建默认直接发布）
- 优化 Skill 时跳过 `AskUserQuestion` 询问
- 仅在对话文本中口头提及"你可以发布"，不执行实际发布命令

## 完成定义

只有同时满足以下条件，才能说完成：

- 文件已落在当前 Codex Skill 根或用户指定安装目录。
- `SKILL.md` frontmatter 校验通过。
- 触发与不触发边界清楚。
- 涉及内部数据的预检结论明确。
- 已调用或明确执行当前环境的 Skill 创建/更新能力。
- 已输出测试清单和结果。
- 团队复用时已生成可安装压缩包，或说明本次是安装目录内直接更新无需额外打包。
- 已执行版本号更新（`data/VERSION.json` 与 `SKILL.md` frontmatter 同步）。
- 已完成技能广场发布流程（新建直接发布，默认个人可见；优化经用户确认后发布）。

# 新品计算器 Skill 优化 PRD

## 1. 背景

`ops-new-product-calculator` 已能指导 Agent 完成新品试算，但主文件混合了通用流程与分支细节，且没有覆盖 CLI 已存在的 `show`、`copy` 命令。本次优化同时解决上下文效率和能力完整性问题。

## 2. 目标

- Agent 能根据用户当前状态直接进入正确流程。
- 主 `SKILL.md` 只加载所有场景都需要的规则。
- 详细字段和长输出模板按需加载。
- Skill 文档覆盖当前 calculator CLI 的核心业务能力。
- 关键行为可由自动化测试验证。

## 3. 非目标

- 不修改 `opscli/calculator/` 下的 CLI 或业务实现。
- 不新增命令、参数、远端 API 或本地脚本。
- 不改变认证与 `ops-feedback` 的项目级规则。
- 不修改 `data/VERSION.json` 的 `v0.0.1`。
- 不发布 Skill、不提交真实新品试算任务。

## 4. 用户场景

### 场景 A：新建试算

用户只有新品试算意图或少量基础信息。Agent 应：

1. 检查认证。
2. 获取或确认站点、平台、海关类目。
3. 生成新草稿目录。
4. 引导填写 CSV。
5. 校验后请求提交确认。

### 场景 B：继续已有草稿

用户已提供草稿目录、`填写表格.csv` 或 `draft.json`。Agent 应：

1. 检查认证。
2. 使用 `show` 查看当前草稿。
3. 使用目录模式同步 CSV 并 `validate`。
4. 只有校验通过且用户确认后才 `submit`。

### 场景 C：查询或复用已有任务

用户提供任务编号、`sudo`，或要求查询最终结果/复制试算。Agent 应：

1. 使用 `detail` 查询明确任务。
2. 信息不足时使用 `list` 定位。
3. 需要复用时使用 `copy` 生成新草稿。
4. 最终回复保留 CLI 返回的完整费用方案和主要费用行。

## 5. 功能需求

### FR-1 触发描述

frontmatter `description` 必须覆盖以下用户意图：

- 新品试算、毛利测算、定价测算。
- 生成、填写、查看、校验、提交试算草稿。
- 查询、复用或复制已有试算任务。

描述只表达触发条件，不摘要内部执行步骤。

### FR-2 入口路由

主文档必须在核心流程之前提供三类入口路由，并明确默认选择。

### FR-3 核心安全门禁

主文档必须保留：

- 只使用 `opscli calculator`，不直接调用 Polaris 后端。
- 执行 calculator 命令前检查 Polaris 登录与权限。
- 非认证类 `opscli` 失败立即使用 `ops-feedback`。
- `submit` 前必须通过 `validate` 并获得用户明确确认。
- 不复述 JWT、Cookie、`sudo` 等完整敏感值。
- `draft` / `copy` 使用新的空目录，不覆盖已有草稿。

### FR-4 草稿参考

`references/draft-workflow.md` 必须包含：

- 下拉项、类目搜索和默认烟测选择。
- `draft`、`show`、`validate`、`submit`。
- CSV 中文值转换和 `.dropdown-cache.json` 规则。
- 完整最小 JSON 示例及字段约束。
- Web 兜底入口。

主文档必须明确仅在新建或继续草稿时读取该文件。

### FR-5 结果参考

`references/result-workflow.md` 必须包含：

- `list`、`detail`、`copy`。
- `task_code`、`sudo` 和 Web 详情页规则。
- 完整费用表回复契约。
- 超时、参数拼接错误和原始 JSON 排障。

主文档必须明确仅在查询或复用任务时读取该文件。

### FR-6 回复契约

面向业务用户优先使用中文业务词。最终查询结果按以下结构输出：

1. 任务状态、推荐方案和 Web 详情页。
2. CLI 返回的所有方案列。
3. CLI 返回的主要费用行。
4. 1–2 句基于结果的解释。

### FR-7 Web 路由

主 Skill 必须提供三个线上入口的统一速查，分支参考文件必须保留对应入口：

- 创建页：`https://bi.xenkee.com/#/newProductCalculator`
- 列表页：`https://bi.xenkee.com/#/calculatorResultList`
- 结果详情页：`https://bi.xenkee.com/#/calculatorDatail?task_code=<TASK_CODE>&sudo=<SUDO>`

## 6. 质量要求

- 主 `SKILL.md` 目标为 180–220 行；若为保证关键门禁略有超出，必须仍显著少于当前 318 行。
- 详细资料只能位于一个明确引用的参考文件中，避免重复维护。
- 不新增 README、CHANGELOG 或无执行价值的辅助文件。
- 所有命令必须与 `opscli/calculator/cli.py` 的实际命令保持一致。

## 7. 验收标准

- 新增契约测试先因缺少引用文件、入口路由或命令说明而失败。
- 修改后聚焦测试全部通过。
- JSON 示例继续通过 `validate_draft_data()`。
- 主文件引用两个参考文件，且不再内嵌完整 JSON。
- `show`、`copy` 均有明确使用条件和示例。
- 三个线上 Web 路由在主 Skill 和对应分支参考中均有契约覆盖。
- `VERSION.json` 内容保持不变。

---
name: ops-new-product-calculator
description: Use when users need Polaris 新品计算器、新品试算、毛利或定价测算，或需要生成、填写、查看、校验、提交试算草稿，以及查询、复制或复用已有试算任务。
---

# ops-new-product-calculator

## 核心原则

通过 `opscli calculator` 完成 Polaris 新品试算。先识别用户当前阶段，只加载对应参考文件，不要让已有草稿或任务的用户重新走完整新建流程。

## 任务入口

| 用户现状 | 进入路径 | 必须读取 |
|---|---|---|
| 只有新品试算、毛利测算或定价测算需求 | 新建试算 | `references/draft-workflow.md` |
| 已有草稿目录、`填写表格.csv` 或 `draft.json` | 继续已有草稿 | `references/draft-workflow.md` |
| 已有任务编号、`sudo`，或要查结果、复制任务 | 查询或复用已有任务 | `references/result-workflow.md` |

- 新建试算或继续已有草稿时，必须读取 `references/draft-workflow.md`。
- 查询、定位、复制或复用已有任务时，必须读取 `references/result-workflow.md`。

## 全局门禁

- 必须通过 `opscli calculator` 工作，不得直接调用 Polaris 后端 API。
- Polaris 登录与权限在同一连续任务只检查一次：首次执行远程 calculator 命令前检查；检查通过后不要在每轮补充字段前重复检查，只有出现 401、Token 过期或开始新的独立任务时才重新检查。
- 如果出现未登录、Token 过期、401、JWT 获取失败，使用 `ops-auth` 处理认证。
- **REQUIRED SUB-SKILL:** 任意 `opscli calculator` 命令发生非认证类失败后，立即提交结构化反馈，使用 `ops-feedback` 完成提交；反馈完成后再继续原任务，并返回 `feedback_uuid`。
- `validate` 通过且用户明确确认后才允许 `submit`。固定提醒：`submit 会创建真实试算任务。确认要提交吗？`
- 用户粘贴 curl、JWT、Cookie、`sudo` 等敏感信息时，不复述完整值；命令示例使用 `<SUDO>` 或带引号占位。
- `draft` 和 `copy` 的输出目录必须是新的空目录；不得覆盖已有 draft.json。
- 普通业务用户优先填写 `填写表格.csv` 的“请填写”列，不要求其整段编辑 `draft.json`。
- `填写表格-旧版.csv` 已弃用，仅保留历史完整字段，不读取其中的修改。
- 包装、重量、箱规和单箱数量必须来自接口或用户明确确认；不得根据商品名称、测试数据或示例值猜测。
- 包装参考选项默认只展示不代入，Skill 必须持续补问到全部必填字段有效或用户取消。

## 认证前置

使用本工具需要北极星 Polaris 权限。先执行：

```bash
opscli auth token status
```

根据结果处理：

- 未登录：执行 `opscli auth login`，完成浏览器授权后重新检查。
- 已登录且 Polaris Token 有效：继续当前任务入口。
- 已登录但 Polaris Token 状态为无效/未获取：通常缺少系统授权，提示用户申请 BI/Polaris 权限；不要反复登录。
- 认证和权限问题属于预期认证状态，不触发 `ops-feedback`。

## 新建或继续草稿

读取 `references/draft-workflow.md`，然后按用户状态执行：

- 新建试算：确认站点、平台和海关类目，生成草稿包。
- 继续已有草稿：先 `show` 查看，再读取 `填写表格.csv`，分轮补齐仍为空或无效的必填字段。
- 每轮最多询问 3–5 个字段，保留已确认值；连续补充期间只更新并读取 CSV，不重复执行认证、`show`、下拉查询或 `validate`；全部必填字段有效后只运行一次 `validate`。
- 校验失败：按项目规则提交反馈，只解释最关键的 3–5 项并指导修改 CSV。
- 校验通过：等待用户明确确认后才执行 `submit`。

## 查询或复用任务

读取 `references/result-workflow.md`，然后按目标执行：

- 查询明确任务：只执行一次普通 `detail`，直接采用 CLI 输出。
- 信息不足：使用 `list` 定位任务。
- 复用已有任务：使用 `copy` 生成新的草稿目录。
- 最终结果：保留 CLI 返回的全部费用方案，默认忽略成本输入、利润和毛利，不自动读取原始 JSON。

## 命令速查

| 目的 | 命令 |
|---|---|
| 检查登录 | `opscli auth token status` |
| 获取站点/平台 | `opscli calculator dropdown-list --json` |
| 搜索类目 | `opscli calculator search-category <关键词> --limit 5` |
| 推荐参数 | `opscli calculator recommend` |
| 生成草稿 | `opscli calculator draft ... --out <NEW_DRAFT_DIR>` |
| 查看草稿 | `opscli calculator show <DRAFT_DIR>` |
| 校验草稿 | `opscli calculator validate <DRAFT_DIR>` |
| 提交草稿 | `opscli calculator submit <DRAFT_DIR>` |
| 查询列表 | `opscli calculator list --task-code <TASK_CODE> --json` |
| 查询详情 | `opscli calculator detail --task-code <TASK_CODE> --sudo "<SUDO>"` |
| 复制任务 | `opscli calculator copy --task-code <TASK_CODE> --sudo "<SUDO>" --out <NEW_DRAFT_DIR>` |

## Web 路由

| 目的 | 线上入口 |
|---|---|
| 创建新品试算 | `https://bi.xenkee.com/#/newProductCalculator` |
| 查看试算列表 | `https://bi.xenkee.com/#/calculatorResultList` |
| 查看结果详情 | `https://bi.xenkee.com/#/calculatorDatail?task_code=<TASK_CODE>&sudo=<SUDO>` |

## 失败处理

| 现象 | 处理 |
|---|---|
| 未登录、401、Polaris JWT 失败 | 使用 `ops-auth`，不提交失败反馈 |
| 任意非认证类命令失败 | 立即使用 `ops-feedback`，返回 `feedback_uuid` 后继续 |
| `validate` 报错较多 | 反馈后解释最关键的 3–5 项，不进入 `submit` |
| 输出目录已有草稿 | 停止并改用新的空目录 |
| `detail` 超时 | 使用 `list` 查看任务状态，稍后重试 |

## 回复检查

- 是否直接进入用户当前阶段。
- 是否只展示当前选择所需的 3–5 个候选项。
- 是否在提交前完成校验并获得明确确认。
- 是否隐藏 JWT、Cookie、`sudo` 等敏感值。
- 查询结果是否保留所有方案列、主要费用行和推荐标识。

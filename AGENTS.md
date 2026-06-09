# AGENTS.md — opscli 项目开发指南

> 本文件为 Codex 在 opscli 项目中的工作规范，优先级高于全局 AGENTS.md。

---

## 规范说明

**所有开发铁律、模块结构、开发流程、代码规范、文档规范均与 [CLAUDE.md](CLAUDE.md) 完全一致，请以 CLAUDE.md 为准。**

本文件不重复任何规范内容，后续维护只需更新 CLAUDE.md 即可。

---

## 全局铁律补充

### 【铁律】工具调用失败自动反馈

> 生效范围：所有在 opscli 项目中工作的 Codex / OpenCode 会话。

**规则**：任何 `opscli` CLI 命令或 MCP Tool 调用失败后，Codex **必须在同一会话中立即调用 `ops-feedback` 提交结构化反馈**，不得跳过、不得等待用户明确指示、不得在回复中仅描述错误而不提交。

**执行顺序**：
1. 工具调用返回 `success: false` 或抛出异常
2. 立即读取 `opscli/skills/templates/ops-feedback/SKILL.md`
3. 按 Skill 规范构造 `execution_summary`，重点提取：
   - `tool`：具体工具或命令
   - `call_params`：实际传入的关键参数
   - `error_message`：原始错误码和错误文本
   - `reason`：基于上下文推断的原因（不确定时标注“推测”）
   - `fix_suggestion`：已采用的修复方式或下一步建议
4. 调用 `feedback_submit`（MCP 模式）或 `opscli feedback submit`（CLI 模式）
5. 将 `feedback_uuid` 返回给用户，并继续处理原任务

**例外情况**（允许不提交反馈）：
- 认证类错误（`auth_login_start`、`auth_login_poll` 等预期内的未授权状态）
- 用户主动取消的操作（`KeyboardInterrupt`）
- 同一失败在 5 分钟内已提交过反馈（凭 `feedback_uuid` 去重）

<!-- BEGIN SUPER DEV CODEX -->
# Super Dev for Codex CLI

Treat Codex App/Desktop selecting `super-dev` or `super-dev-seeai` from the `/` list, Codex CLI explicit `$super-dev` / `$super-dev-seeai`, and natural-language `super-dev:` / `super-dev：` / `super-dev-seeai:` / `super-dev-seeai：` messages as valid Super Dev entry points.

If the repository already contains active Super Dev workflow context, the first natural-language requirement in a new session must also continue Super Dev rather than normal chat.

## Direct Activation Rule
- Do not spend a turn saying you will read the skill first, explain the skill, or decide whether to enter the workflow.
- Treat the current trigger as already authorized to execute the full Super Dev pipeline.
- If a compatibility skill under `~/.codex/skills/` is loaded, treat it as the same Super Dev contract, not a fallback mode.

## Preferred official entry order
- Codex App/Desktop: prefer selecting `super-dev` from the `/` list. This is the enabled Skill entry, not a custom project slash command file.
- Codex CLI: prefer explicit `$super-dev`.
- Natural-language fallback for both surfaces: `super-dev: <需求描述>` or `super-dev：<需求描述>` through AGENTS.md.

## SEEAI Competition Mode
- If the user triggers `super-dev-seeai`, enter the SEEAI competition-fast contract instead of the standard long chain.
- SEEAI keeps research -> compact docs -> docs confirmation -> compact spec, then goes directly into a full-stack sprint and final polish.
- SEEAI still requires real files in `output/`, but the documents must stay compact and competition-oriented.

## Required execution
1. First reply: state that Super Dev pipeline mode is active and the current phase is `research`.
2. Read `knowledge/` and `output/knowledge-cache/*-knowledge-bundle.json` when available.
3. Use Codex native web/search/edit/terminal capabilities to perform similar-product research and write `output/*-research.md` into the repository workspace.
4. Draft `output/*-prd.md`, `output/*-architecture.md`, and `output/*-uiux.md` in the same Codex session and save them as actual project files.
5. Stop after the three core documents, summarize them, and wait for explicit confirmation.
6. Only after confirmation, create `.super-dev/changes/*/proposal.md` and `.super-dev/changes/*/tasks.md`, then continue with frontend-first implementation.

## Constraints
- Do not start coding directly after `/super-dev` skill entry, `$super-dev`, `super-dev:`, or `super-dev：`.
- Do not create Spec before document confirmation.
- If the user requests architecture changes, first update `output/*-architecture.md`, then realign Spec/tasks and implementation.
- If the user requests quality or security remediation, first fix the issues, rerun the quality gate, refresh any delivery evidence the reports ask for, and only then continue.
- 开始任何 UI 实现前，必须先锁定 `output/*-uiux.md` 中冻结的图标库、字体系统、design token system、组件生态和页面骨架。
- Before any UI implementation, first lock the icon library, typography, design token system, component ecosystem, and page skeleton from `output/*-uiux.md`.
- Do not use emoji as functional icons or placeholders.
- For non-conversational AI products, avoid Claude / ChatGPT-style sidebar chat shells unless the UI plan explicitly justifies them.
- Keep using the component ecosystem and design token direction defined in `output/*-uiux.md` rather than switching ad hoc.
- If a required artifact is only described in chat and not written into the repository, treat the step as incomplete.
- Codex remains the execution host; Super Dev is the local governance workflow.
- Use local `super-dev` CLI only for governance actions such as doctor, review, quality, release readiness, or update; do not outsource the main coding workflow to the CLI.

## Conversation Continuity Contract
- If `.super-dev/SESSION_BRIEF.md` exists, read it before responding and treat it as the active workflow state.
- If the workflow is waiting for docs confirmation, preview confirmation, UI revision, architecture revision, or quality revision, then user replies like `修改`, `补充`, `继续改`, `确认`, `通过`, `继续`, or detailed feedback remain inside the current Super Dev stage.
- After each requested revision inside a gate, stay in the same stage, update the required artifacts, summarize what changed, and wait again for explicit confirmation.
- Do not silently exit Super Dev mode because the user asked for several edits, follow-up questions, or extra constraints.
- Only leave the current Super Dev workflow if the user explicitly says to cancel the workflow, restart from scratch, or switch back to normal chat.

## Super Dev System Flow Contract
- SUPER_DEV_FLOW_CONTRACT_V1
- PHASE_CHAIN: research>docs>docs_confirm>spec>frontend>preview_confirm>backend>quality>delivery
- DOC_CONFIRM_GATE: required
- PREVIEW_CONFIRM_GATE: required
- HOST_PARITY: required
<!-- END SUPER DEV CODEX -->



<claude-mem-context>
# Memory Context

# [open-opscli] recent context, 2026-06-09 4:10pm GMT+8

Legend: 🎯session 🔴bugfix 🟣feature 🔄refactor ✅change 🔵discovery ⚖️decision 🚨security_alert 🔐security_note
Format: ID TIME TYPE TITLE
Fetch details: get_observations([IDs]) | Search: mem-search skill

Stats: 24 obs (6,270t read) | 0t work

### May 7, 2026
1 2:54p 🔵 Shopify product list command supports keyword search and pagination
2 " 🔵 Shopify product list returns comprehensive product and variant data with multi-warehouse support
3 2:55p 🔵 Site 8717 contains 81 products with inventory ranging from 0 to 6045 units
S5 Update product QD171622-7 pricing to sales price 100 USD and original price 150 USD via work order system (May 7, 2:55 PM)
S1 Explored and cataloged products from aukey-release Shopify store (site 8717) (May 7, 2:55 PM)
S2 Update product pricing for SKU QD171622-7 (YS19384) to sales price 100 USD and original price 150 USD (May 7, 2:55 PM)
5 3:27p 🔵 opscli feedtask command manages feed operations with create and status subcommands
4 3:28p 🔵 opscli shopify workorder update-price command supports two pricing update modes
6 3:50p 🔵 opscli shopify workorder command provides comprehensive product management operations
S6 Update product QD171622-7 pricing and explore Shopify store configuration (May 7, 3:50 PM)
7 3:52p 🔵 opscli shopify shop list command returns configured Shopify stores with channel and currency information
S7 Update product QD171622-7 pricing to sales price 100 USD and original price 150 USD; explored opscli Shopify management capabilities (May 7, 3:52 PM)
S8 Modify QD171622-11 pricing: set sale price to 1001 and original price to 1002 in Shopify (May 7, 3:53 PM)
8 4:00p 🔵 Shopify shop configuration identified for price update task
9 4:01p 🔵 Product QD171622-11 located for price modification task
10 " ✅ Product QD171622-11 pricing updated in Shopify
11 4:02p 🔵 opscli feedtask status command available for task tracking
12 4:03p ✅ Shopify product QD171622-11 pricing updated via opscli workorder
S9 Listed Shopify products from aukey-release shop (site_id: 8717) (May 7, 4:04 PM)
13 4:19p 🔵 Authentication token status verified
14 " 🔵 Shopify shop listing retrieved
15 " 🔵 Shopify products retrieved from aukey-release shop
16 " 🔵 Shopify product pagination discovered
S10 Investigate how to update Shopify product QD71889 pricing (price: 1000, compare_at_price: 1200) in polaris system (May 7, 4:21 PM)
17 4:33p 🔵 Located QD71889 product identifiers for price update
18 " 🔵 Explored opscli price update command syntax
19 " 🔵 Retrieved complete product data structure for QD71889
20 " 🔵 Located price update implementation files in opscli codebase
21 4:36p 🔵 Analyzed Shopify domain layer architecture and data models
22 " 🔵 Update-price command implementation analyzed via explore agent
23 " 🔵 Discovered site_id vs channel_id mapping for QD71889
S11 修改产品 QD171622-4 的售价从 11.00 改为 100.00 (May 7, 4:36 PM)
24 4:38p 🔵 Retrieved complete Shopify product list from aukey-release shop
S12 修改产品 QD171622-4 的售价从 11.00 改为 100.00 (May 7, 5:57 PM)
**Investigated**: - 验证了 Polaris 认证状态（有效，剩余约 20 小时）
    - 列出 aukey-release 店铺全部 81 条商品
    - 定位目标产品 QD171622-4 的详细信息：
      * listing_id: 126
      * 当前价格: 11.00
      * 当前原价: 1.00
      * site_id: 1132（工单系统ID）
      * channel_id: 8717（API调用ID）
    - 尝试提交价格修改工单

**Learned**: - opscli 使用 RTK 包装器进行 token 优化
    - site_id 与 channel_id 是两个不同的概念：channel_id (8717) 用于 API 调用，site_id (1132) 用于内部工单提交
    - update-price 命令支持两种模式：--items JSON 文件或 --sellsku 直接指定 SKU
    - 系统具有防重复提交机制：同一产品不能有多个同类型工单同时进行
    - 工单错误信息格式：SKU + seller_sku 组合标识

**Completed**: - 成功列出 aukey-release 店铺全部 81 条商品
    - 成功定位 QD171622-4 并确认其当前价格信息
    - 确认需要使用的 site_id 为 1132
    - 执行了价格修改命令提交：`rtk opscli shopify workorder update-price --site 1132 --sellsku QD171622-4 --price 100`

**Next Steps**: - 价格修改工单提交失败，错误信息：**USAMR171622/QD171622-4 已存在同类型的进行中工单，请勿重复提交**
    - 需要等待现有工单完成后再重新提交
    - 可选操作：查看现有工单状态以了解进度
</claude-mem-context>
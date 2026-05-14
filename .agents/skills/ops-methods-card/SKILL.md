---
name: ops-methods-card
description: "用于处理 Aukeys AI 方法卡、方法卡、method card、methods card 分析任务：先通过 ops-auth 完成登录授权，再用 opscli methods-card 获取方法卡列表和详情，根据用户输入与方法卡标题/描述选择卡片，读取 Excel 数据，按方法卡规范完成分析，并参考卡片输出示例保存本地 HTML 报告。"
---

# ops-methods-card

用于 Aukeys methods card 相关任务。当前版本支持按用户输入选择方法卡、读取 Excel 数据、生成本地 HTML 分析报告。

---

## 运行模式判断

优先级如下：

1. 用户明确要求 CLI 或 MCP 时，直接遵循用户指定。
2. 在 `opscli` 项目里默认走 CLI，先执行 `opscli auth token status`。
3. 若状态失败、未登录、未授权或 Token 过期，切换到 `ops-auth`。
4. 若 CLI/MCP 都不可用，提示用户先安装或配置 `aukeys-opscli`。

---

## 强制认证门禁

> **【强制】每次调用 `ops-methods-card` 前，必须先检测是否已授权登录；禁止默认假设用户已经登录。**

- 进入本 Skill 后，第一步先执行 `opscli auth token status`
- 若认证状态有效，跳过登录，不要重复打断用户
- 若命令失败，或输出中出现“未登录 / 未授权 / Token 过期 / expired / 401”等状态，必须立即切换到 `ops-auth` Skill
- 若是 JWT Token 过期，优先执行 `opscli auth token refresh --all`
- 若是未登录、未授权、401、刷新失败或状态仍异常，在 `ops-auth` 中执行 `opscli auth login`
- 登录或刷新后必须再次执行 `opscli auth token status`
- 只有认证检查通过后，才允许继续 methods card 后续流程
- 若认证状态仍未通过，停止 methods card 后续动作

**标准前置流程：**

```bash
# 1. 先检查是否已登录
opscli auth token status

# 2. 如 JWT Token 已过期，先刷新
opscli auth token refresh --all

# 3. 如未登录、未授权、刷新失败或状态仍异常，立即调用 ops-auth Skill 处理
opscli auth login

# 4. 登录后再次确认
opscli auth token status
```

---

## 核心流程

处理分析任务时，按顺序执行：

1. 完成认证门禁。
2. 读取 `references/执行流程.md`。
3. 通过 `opscli methods-card list` 获取方法卡列表。
4. 根据用户输入、方法卡标题和描述选择最合适的卡片。
5. 通过 `opscli methods-card detail <card_id>` 获取详情。
6. 用 `scripts/xlsx_preview.py` 读取 Excel 数据。
7. 结合方法卡规范、Excel 数据和用户要求完成分析。
8. 参考 `references/卡片输出示例.html` 生成完整 HTML 文件，并保存到本地 `output/methods-card/`。

## 静态参考资料

按需读取以下文件：

- `references/执行流程.md`
- `references/方法卡接口.md`
- `references/卡片.md`
- `references/卡片输出示例.html`

默认 Excel 数据文件：

- `交叉表-1778233062511.xlsx`

---

## 使用原则

- 认证逻辑必须统一委托 `ops-auth` 或 `opscli auth`，不要在本 Skill 内直接读取凭证文件
- 后端方法卡列表和详情必须通过 `opscli methods-card` 命令获取，不要在 Skill 脚本里直接调用后端 HTTP API
- Excel 解析只读取本地文件，不访问网络
- HTML 报告必须参考 `references/卡片输出示例.html` 的页面结构，并保存到本地文件
- 后续如需新增真实业务能力，必须先补充 PRD、架构和 Spec 后再实现

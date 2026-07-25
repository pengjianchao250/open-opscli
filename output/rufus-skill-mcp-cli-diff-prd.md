# Rufus Skill MCP 与 CLI 差异审计 PRD

## 目标

明确 `ops-amazon-rufus` Skill MCP 工具与 `opscli amazon-rufus` CLI 实现之间的功能边界，并按用户反馈补齐 MCP 对 `platform-cookie get/save` 与 `curl save` 的受控支持，避免 Agent 在运行期误用 CLI 调试入口、读取历史报告或暴露敏感登录态。

## 用户问题

当前用户希望回答并调整目标：

> Rufus Skill 的 MCP 工具和 opscli 中 Rufus 实现有哪些差异？MCP 需要支持 `platform-cookie get/save`、`curl save`。

## 范围

本轮仍只做文档更新，不改业务代码；待用户确认后再进入 Spec/tasks 与实现。

覆盖范围：

- MCP Rufus 工具列表与输入输出契约。
- CLI Rufus 命令列表与参数能力。
- 新增 MCP 工具需求：`amazon_rufus_platform_cookie_get`、`amazon_rufus_platform_cookie_save`、`amazon_rufus_curl_save`。
- MCP 与 CLI 共享的 `RufusManager` 核心链路。
- Skill 文档中声明的运行期编排规则。
- 测试对上述约束的覆盖情况。

不覆盖范围：

- 不执行真实 Amazon 登录。
- 不调用生产 Rufus 获取。
- 不修改 MCP、CLI 或 Skill 实现。
- 不新增 Spec/tasks。

## 结论需求

审计输出必须能回答：

1. 哪些能力 MCP 和 CLI 都支持。
2. 哪些能力 CLI 有但 MCP 不暴露。
3. 哪些差异是安全收敛设计。
4. 哪些 CLI 能力现在需要补齐到 MCP。
5. 哪些差异可能是实现缺口或文档不一致。
6. 现有测试是否覆盖这些差异。

## 核心发现

MCP 是 Agent-facing 安全子集，CLI 是本机运维和 fallback 工具面。核心获取共用 `RufusManager.get_backend()`，但 MCP 通过 `RufusMcpManager` 做输入收敛、凭证隔离、报告写入和敏感字段过滤。

根据用户最新反馈，`platform-cookie get/save` 与 `curl save` 需要从“CLI-only 调试入口”调整为“MCP 受控排障/初始化入口”。实现时仍应坚持最小参数面和默认脱敏返回：

- `platform-cookie save`：允许保存 content，但不回显 content。
- `platform-cookie get`：默认只返回状态和长度；完整 content 需要显式参数。
- `curl save`：允许保存 raw cURL，但不回显 cURL、headers、payload 或 cookie。

需要重点关注的非预期差异：

- MCP 当前未暴露用户要求的 `platform-cookie get/save` 和 `curl save`，这是需要后续实现的功能缺口。
- Skill 声明国家站点授权偏好相互独立，但 `RemoteConsentStore` 当前用单个 `remote-consent.json` 保存单国家偏好。
- Skill 的登录恢复是 Agent 编排规则，不是 MCP Tool 或 CLI 内置自动重试。
- CLI `watch-login` 默认保留浏览器窗口，MCP 默认关闭；Skill fallback 已通过显式 `--close-browser` 补齐。

## 验收标准

- 文档列出当前 MCP 6 个 Rufus 工具与 CLI 命令差异。
- 文档明确 MCP 目标新增 `platform-cookie get/save` 与 `curl save`。
- 文档说明共享实现链路，不误判为两套获取逻辑。
- 文档标出敏感字段和 upload payload 的暴露差异。
- 文档说明新增 MCP 敏感工具的默认脱敏策略。
- 文档标出 `remote-consent` 多国家独立性风险。
- 本地相关测试运行通过并记录结果。

## 验证结果

已运行 Rufus MCP/Skill 相关测试：

```text
uv run pytest "tests/mcp/test_amazon_rufus_tools.py" "tests/amazon_rufus/test_mcp_manager.py" "tests/skills/test_ops_amazon_rufus_updater.py"
```

结果：31 passed。

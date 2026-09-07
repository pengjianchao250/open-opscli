# ops-amazon-rufus 使用说明

`ops-amazon-rufus` 提供 Amazon Rufus 默认问题模板库，并作为 Agent 使用 Rufus MCP 工具链的入口索引。Rufus 运行期以 MCP Tool 优先编排，只有明确白名单场景允许 CLI fallback。Rufus 获取 Python 文件归属 `opscli/mcp/tools/amazon_rufus.py` 和 `opscli/amazon_rufus/`；本 Skill 不包含获取脚本。

## 术语约定

- 面向用户和 Agent 的流程统一称为“亚马逊 Rufus 登录态”，不要把它描述为普通 Cookie。
- 后端接口和工具名仍保留 `platform-cookie` / OPS 平台 Cookie 命名；其 `content` 实际承载亚马逊 Rufus 登录态，当前规范直接保存浏览器 `/rufus/cl/streaming` cURL 命令态。

## 目录结构

```text
ops-amazon-rufus/
├── SKILL.md
├── README.md
├── data/
│   ├── VERSION.json
│   └── question_templates.json
└── references/
    ├── question-templates.md
    ├── rufus-mcp-workflow.md
    └── rufus-report-formatting.md
```

## 流程概览

解析 ASIN、国家和问题 -> 检查 MCP 与授权偏好 -> 检查亚马逊 Rufus 登录态 -> 获取报告 -> 判断回答质量 -> 返回本次报告地址。

主流程及 CLI fallback 条件见 [SKILL.md](SKILL.md#主流程)。登录态失效或获取错误需要重新登录时，执行[登录采集入口](references/rufus-mcp-workflow.md#登录采集入口)；本文件不重复登录步骤。

## 使用入口

- [主流程](SKILL.md#主流程)：MCP-first 编排、问题来源和回答质量重试。
- [登录采集入口](references/rufus-mcp-workflow.md#登录采集入口)：登录方式、次数限制和完成后的复查。
- [错误恢复](references/rufus-mcp-workflow.md#三类-mcp-错误的登录采集恢复)：触发条件和预清理要求。
- [CLI fallback](SKILL.md#cli-fallback-子流程)：允许的调用路径。
- [默认题库](references/question-templates.md)：题库结构和同步规则。
- [报告格式](references/rufus-report-formatting.md)：回答展示与敏感信息隐藏。

## 报告与安全

`report_path` 和 `report_url` 是不可拆分的一对：本地路径用于质量判断，最终回复使用本次报告地址，不得返回历史 ASIN 报告或历史 URL。详细要求见[报告新鲜度约束](references/rufus-mcp-workflow.md#报告新鲜度约束)。

不向报告、回复、反馈或普通日志输出亚马逊登录态及 OPS 凭证；排障工具使用边界见 [SKILL.md](SKILL.md#排障初始化-mcp-工具边界)。

## 文件边界

本 Skill 只承载文档、题库数据和 reference，不包含 Rufus 获取脚本。获取实现位于 `opscli/amazon_rufus/` 和 `opscli/mcp/tools/amazon_rufus.py`。

## 示例触发

```text
$ops-amazon-rufus 帮我分析美国站 B0B1MLVMY5：这是什么商品？评价如何？
```

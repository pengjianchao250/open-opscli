# Rufus CLI Parameter Parity Proposal

## 背景

`opscli amazon-rufus get` 当前能捕获 seed request 并逐题重放，但 replay 请求参数少于扩展端 `AsinRufusDialog`，可能导致上下文缺失或回答偏离目标 ASIN。

## 目标

- 在 CLI replay body 中复刻扩展端已验证字段。
- 在 replay URL 中补齐 `tabId/programId/ref`。
- 保持 CLI 命令、题库与输出结构不变。
- 使用最小 allowlist headers，避免浏览器脚本禁用 header 带来的失败。

## 范围

### 包含

- `RufusReplayService.build_payload()` 增强。
- 新增 replay URL 构造方法。
- `replay_with_page()` 使用规范化 URL 与目标 ASIN。
- 单元测试覆盖 body、URL 与页面 evaluate 入参。

### 不包含

- 不实现扩展端表单动态问题生成。
- 不新增 CLI 参数。
- 不接入上传 API。
- 不修改 parser 的解析契约。

## 验收

- 新增测试先失败，实施后通过。
- `tests/amazon_rufus/test_core.py` 通过。
- 现有输出字段保持兼容。

## 解析器复刻增量

### 背景

CLI 请求参数对齐后，Rufus 更可能返回插件端常见的 `JSONPatches`/`markdown_processor_*`/`text_template_*` 响应。仅复刻请求层不足以保证可读答案，CLI 解析器也需要复刻插件端的核心解析能力。

### 目标

- 支持正文类 JSONPatch group：`markdown_processor_*` 与 `text_template_*`。
- 支持 JSONPatch `add`、`replace`、`remove`。
- 支持 Markdown tree 的 `copyTemplate.prefix/suffix` 文本拼接。
- 从 Markdown link 节点提取 product links 与推荐 ASIN。
- 保留原 HTML/顶层 answer 解析能力作为兼容路径。

### 非目标

- 不完整移植插件端 DOMParser 依赖的所有 HTML 卡片解析。
- 不改变 `AnswerData.to_dict()` 输出字段。

## HTML 卡片解析增量

- `patch_groups` 对齐插件端 `collectJsonPatchTextSnapshots()` 中的 `byGroupId` 聚合机制，不删除。
- CLI 继续补齐 `ReviewAspectFlow` 的 overall/aspect summary 提取。
- CLI 继续补齐 `AsinFaceoutList` 推荐卡片与 `AsinFaceoutFooter` 描述合并。

## JSONPatch 命名对齐

- Python 端状态命名改为 `json_patch_text_snapshots_by_group_id`，对应插件端 `jsonPatchTextSnapshots` 与 `byGroupId`。
- Python 端收集方法命名改为 `_collect_json_patch_text_snapshots()`，对应插件端 `collectJsonPatchTextSnapshots()`。
- 每个 snapshot 保持 `groupId/tree/index` 结构，避免仅用裸 dict 表达 group tree。

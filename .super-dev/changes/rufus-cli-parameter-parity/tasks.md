# Rufus CLI Parameter Parity Tasks

## 任务

- [x] 为扩展端 payload 对齐写失败测试
- [x] 为 replay URL 参数补齐写失败测试
- [x] 为 `replay_with_page` 入参写失败测试
- [x] 实现 `build_payload` 字段补齐
- [x] 实现 replay URL 规范化
- [x] 更新 `replay_with_page` 调用
- [x] 运行 `pytest tests/amazon_rufus/test_core.py`

## 约束

- 保持 `RufusManager` 与 CLI 层无 Rufus 私有参数细节。
- 不复制浏览器禁止设置的 headers。
- 所有新增代码注释使用中文，且简洁。

## 解析器复刻任务

- [x] 为 `text_template_*` JSONPatches 正文写失败测试
- [x] 为 JSONPatch `remove` 写失败测试
- [x] 为 `copyTemplate.prefix/suffix` 写失败测试
- [x] 为链接 ASIN 推荐提取写失败测试
- [x] 实现正文 group 过滤与 patch remove
- [x] 实现 Markdown tree 文本渲染增强
- [x] 实现推荐 ASIN 提取
- [x] 运行 `pytest tests/amazon_rufus/test_core.py`

## HTML 卡片解析任务

- [x] 确认 `patch_groups` 与插件端 `byGroupId` 机制等价
- [x] 为 `ReviewAspectFlow` 写失败测试
- [x] 为 `AsinFaceoutList` / `AsinFaceoutFooter` 写失败测试
- [x] 实现 ReviewAspectFlow summary 优先解析
- [x] 实现推荐卡片 ASIN/title/href/description 合并
- [x] 运行 `pytest tests/amazon_rufus/test_core.py`

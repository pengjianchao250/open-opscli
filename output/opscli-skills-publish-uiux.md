# opscli Skills 发布 CLI 体验说明

## 信息架构

`opscli skills` 把用户心智分成四组：

1. 本地生命周期：`list/install/status/upgrade/link/unlink/report-usage`
2. 广场发布管理：`publish/edit/unpublish`
3. 广场浏览消费：`marketplace categories/list/search/info/versions/rate`
4. 市场同步治理：`install --sync-market` 与 `sync-exclude`

这个分组基本清晰，但文档中应持续强调“包内模板”和“广场技能”是两个来源。

## 推荐用户路径

### 发布者路径

```bash
cd opscli/skills/templates/ops-xxx
opscli skills publish --share-type personal --changelog "内部试用"
opscli skills edit username@ops-xxx --summary "更准确的一句话说明"
opscli skills publish --share-type company --changelog "扩大可见范围并发布新版本"
```

### 使用者路径

```bash
opscli skills marketplace search ops-xxx
opscli skills marketplace info username@ops-xxx
opscli skills install username@ops-xxx
```

### 换机同步路径

```bash
opscli skills install --sync-market --dry-run --pretty
opscli skills install --sync-market --pretty
```

## 输出体验

当前 CLI 同时支持富文本表格和 JSON：

- 默认富文本适合人工使用。
- `--json` 或 `--pretty` 适合脚本和 Agent 解析。
- `upgrade` 进度输出到 stderr，JSON 结果输出到 stdout，便于管道消费。

建议保持的交互原则：

- 发布和编辑失败必须输出结构化错误。
- `publish --json` 不应输出额外富文本。
- `unpublish` 默认确认，`--force` 跳过确认。
- 远程安装失败时应保留 `command`、`error.type`、`error.message`。

## 需要修正的体验风险

1. `README.md` 中 `marketplace list --category 1` 与 CLI 按 slug 匹配不一致，建议统一成 slug 或让 CLI 同时接受数字 ID。
2. `README.md` 中 sort 示例与代码字段不一致，建议统一为 `install_count/usage_count/rating_avg/new`。
3. 分享范围显示标签中存在部分非 GBK 安全字符，Windows PowerShell 下可能触发编码或显示问题，建议换成 `[个人]`、`[部门]`、`[全员]`。
4. `publish` 的 `share_type` 参数默认值为 `personal`，导致 `fm.get("share_type")` 实际不会覆盖默认值；如果希望 frontmatter 能控制分享范围，应把参数默认值改为 `None` 后再解析。
5. `edit` 文档描述“不影响版本历史”，但当前命令支持 `--version`、`--dir`、`--file` 并调用 `full_update_skill()`，可能会创建或更新版本；文档应区分“仅元数据编辑”和“带版本/文件的编辑”。

## 最小优化建议

短期：

- 修正文档中的 category 和 sort 示例。
- 将终端可见的分享标签改成 GBK 安全文本。
- 给 `publish` 增加一条测试，覆盖 frontmatter `share_type` 是否能生效。

中期：

- 给 `publish/edit/unpublish` 增加 CLI 层单元测试，mock `MarketplaceClient`。
- 给 `remote_installer` 增加 zip-slip 防护测试，避免恶意 zip 写出中央存储目录。
- 将 `publish` 的目录校验扩展为可复用 validator，避免未来 edit/upload 路径重复校验。


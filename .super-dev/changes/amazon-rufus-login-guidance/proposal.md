# amazon-rufus-login-guidance Proposal

## 背景

`ops-amazon-rufus` 依赖对应国家站点的 Amazon 浏览器登录态。当前 Skill 文档已说明前置登录要求，但安装成功输出没有直接提示；`amazon-rufus get` 未捕获 `/rufus/cl/streaming` 时，也没有明确告诉用户执行 `opscli amazon-rufus init <country>`。

## 目标

1. `opscli skills install ops-amazon-rufus` 成功后，在 JSON `data` 中提供 Amazon 登录前置提示。
2. 安装提示必须包含 `opscli amazon-rufus init <country>`。
3. `amazon-rufus get` 未捕获 `/rufus/cl/streaming` 时，错误信息必须提示执行 `opscli amazon-rufus init <country>` 并登录后重试。
4. 保持现有顶层 JSON 契约、错误码和退出码不变。

## 非目标

1. 不自动登录 Amazon。
2. 不自动调用 `amazon-rufus init`。
3. 不读取、保存或展示 Amazon cookie、headers、账号信息。
4. 不改变 Rufus replay、题库、报告格式化或上传 payload。
5. 不改变其他 Skill 的安装输出。

## 技术方案

### 安装后提示

在 `opscli/skills/commands/cli.py` 增加私有 helper：

```python
def _with_post_install_guidance(data: dict, skill_name: str) -> dict:
    ...
```

该 helper 只在 `skill_name == "ops-amazon-rufus"` 时追加：

- `requires_amazon_login: true`
- `next_steps: [...]`

非交互安装和交互安装最终 payload 都复用该 helper，避免两条路径输出不一致。

### streaming 捕获失败

在 `BrowserAttachService.capture_seed_request()` 未捕获请求时，继续抛出 `SeedRequestNotCapturedError`，只增强错误 message：

```text
未捕获 /rufus/cl/streaming。请先执行 opscli amazon-rufus init US，并在新窗口登录 Amazon 后重试；同时确认目标站点支持 Rufus: <page_url>
```

错误码仍为 `SEED_REQUEST_NOT_CAPTURED`。

## 验收标准

1. 安装 `ops-amazon-rufus` 的 JSON `data.requires_amazon_login` 为 `true`。
2. 安装 `ops-amazon-rufus` 的 `data.next_steps` 包含 `opscli amazon-rufus init <country>`。
3. 安装其他 Skill 不包含 `requires_amazon_login`。
4. 交互安装结果同样包含 Rufus 登录提示。
5. 未捕获 streaming 的错误信息包含 `opscli amazon-rufus init US`。
6. 未捕获 streaming 时不生成答案报告。
7. 相关 `skills` 与 `amazon_rufus` 测试通过。

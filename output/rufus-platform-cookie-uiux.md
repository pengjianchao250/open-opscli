# Rufus 平台 Cookie CLI 交互规范

日期：2026-06-08

## 适用范围

本需求没有前端页面。这里的 UIUX 指 CLI 命令命名、终端输出和 Skill 文案边界。

## 交互原则

- 保存命令只要求用户提供平台、国家，并从 stdin 提供 content。
- 不要求用户在聊天中复制 Cookie。
- 保存输出不回显 content。
- 读取 content 时区分 `exists` 与 `missing`，避免把后端业务 404 展示成异常堆栈。
- CLI get 的 `content` 只供内部工具消费，不展示到最终回复。
- 文案保持短句、可执行、可审计。

## 命令体验

保存或覆盖：

```powershell
opscli amazon-rufus platform-cookie save amazon US --from-stdin --pretty
```

读取 content：

```powershell
opscli amazon-rufus platform-cookie get amazon US --pretty
```

平台名校验失败：

```json
{
  "success": false,
  "command": "amazon-rufus platform-cookie save",
  "data": null,
  "error": {
    "code": "INVALID_RUFUS_PLATFORM",
    "message": "platform 不能为空"
  }
}
```

## 输出字段边界

允许输出：

- `platform`
- `country`
- `status`
- `message`
- `content`
- `content_length`

禁止输出：

- `cookie_content`
- Cookie header
- Authorization
- headers
- payload
- `storage_state`
- seed request

## Skill 文案

当 Agent 需要同步平台 Cookie 记录时，使用：

```text
我会通过 opscli 平台 Cookie 接口处理 amazon 平台记录。保存命令只传平台、国家和 stdin content；读取到的 content 只作为内部工具输入，不会写入最终回复。
```

保存后反馈：

```text
平台 Cookie content 已按后端返回完成处理。保存输出不回显 content。
```

查询未命中：

```text
当前用户在该平台和国家尚未保存 Cookie content。
```

## 文案禁用项

不得使用：

- “请把 Cookie 发给我”
- “复制完整 Cookie 到命令行”
- “安全保存 Cookie”作为绝对保证
- “永久有效”
- “把 cookie_content 单独传给接口”

推荐表达：

- “只传平台、国家、content”
- “保存输出不回显 content”
- “读取到的 content 仅供内部工具消费”

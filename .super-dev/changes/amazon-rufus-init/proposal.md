# amazon-rufus-init Proposal

## 背景

`opscli amazon-rufus get` 依赖固定 Chrome profile 中的 Amazon 登录态。首次使用或切换国家站点时，用户需要先在对应站点登录，否则 Rufus seed request 捕获与后续 replay 可能失败。

## 目标

新增 `opscli amazon-rufus init <country>`，使用与现有 Rufus 流程相同的 Chrome 调试窗口和 profile 打开对应国家 Amazon 首页，并提示用户在新窗口中登录亚马逊。

## 范围

- CLI 新增 `init` 子命令。
- Service 新增登录初始化编排方法。
- Browser 服务复用现有新开 Chrome 与 CDP 等待能力，打开国家站点首页。
- Skill 文档已补充国家站点登录前置条件。

## 非目标

- 不读取 Rufus 题库。
- 不捕获 `/rufus/cl/streaming`。
- 不执行 Rufus replay。
- 不构造上传 payload。

## 验收

- `opscli amazon-rufus init --help` 可见。
- `opscli amazon-rufus init US` 打开 `https://www.amazon.com`。
- `opscli amazon-rufus init DE` 打开 `https://www.amazon.de`。
- 成功后输出 `请在新窗口中登录亚马逊`。
- 命令结束后 Chrome 窗口保持打开。

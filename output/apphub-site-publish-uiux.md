# AppHub 发布命令 CLI 交互规范

> 日期：2026-08-31  
> 状态：待确认  
> 说明：本任务无 Web 页面，UIUX 指命令行信息架构、状态反馈和 Codex 可读输出。

## 1. 设计目标

1. 用户看到的是“发布应用”，不是 Git/Gitea/Coolify 内部实现。
2. 每个阶段都回答三个问题：正在做什么、是否成功、失败后怎么修。
3. 不用装饰性字符制造进度感，不使用 emoji 作为状态或图标。
4. 人类终端和 Codex 结构化消费都可稳定使用。
5. 安全错误不展示密钥原文、token、cookie 或完整认证头。

## 2. 命令心智

用户主入口：

```bash
opscli app publish -m "更新销售日报筛选条件"
```

用户只需要理解：

- `init`：首次把项目接入 AppHub。
- `publish`：把当前源码发布为新版本。
- `--resume`：网络中断后继续查看同一次发布。
- `git bind`：修复本机发布凭据。

不向普通用户暴露：

- Gitea admin token。
- tag API。
- Coolify deployment UUID 的内部用途。
- SSE 协议细节。

## 3. 信息层级

### 3.1 标题

```text
AppHub 发布：sales-daily
```

### 3.2 阶段

固定阶段名称：

```text
[1/6] 检查项目
[2/6] 校验配置
[3/6] 扫描敏感信息
[4/6] 提交并推送源码
[5/6] 创建发布
[6/6] 等待部署完成
```

阶段数量必须稳定。内部增加实现步骤时，不应频繁改变用户面主阶段。

### 3.3 结果摘要

成功：

```text
发布成功
应用：sales-daily
版本：v12
提交：8f31c9a2d417
地址：https://ops.xenkee.com/apps/sales-daily/
```

失败：

```text
发布失败
错误码：GIT-003
原因：远端已有其他人的新提交，当前推送被拒绝。
处理：先合并远端改动，再重新运行发布命令。
建议命令：opscli app pull
```

## 4. 进度呈现

### 4.1 交互终端

- 使用 Rich spinner 或单行状态刷新。
- 服务端 SSE 的业务消息逐行显示。
- `warn` 使用黄色语义，`error` 使用红色语义，普通信息使用中性色。
- 不显示 `hidden` 事件。
- 不把服务端原始 JSON 直接倾倒到终端。

### 4.2 非交互终端

- 禁用 spinner 和光标控制。
- 每个阶段输出一行可追加日志。
- 保证 CI 和 Codex 能按行读取。

### 4.3 JSON 模式

`--json` 只在结束时输出一个 JSON 对象：

```json
{
  "success": true,
  "slug": "sales-daily",
  "status": "healthy",
  "release_id": 42,
  "version": "v12",
  "commit_sha": "8f31c9a2d4170000000000000000000000000000",
  "tag": "v12",
  "url": "https://ops.xenkee.com/apps/sales-daily/",
  "error": null
}
```

失败时：

```json
{
  "success": false,
  "slug": "sales-daily",
  "status": "failed",
  "release_id": 42,
  "commit_sha": "8f31c9a2d4170000000000000000000000000000",
  "error": {
    "code": "AUTH-003",
    "message": "检测到疑似敏感信息，发布已阻断。",
    "fix_hint": "先吊销源系统凭据，再清理代码和本地 Git 历史。",
    "request_id": "req_xxx"
  }
}
```

## 5. 关键场景文案

### 5.1 NOOP

```text
没有可发布的改动。
远端 main 与最近一次健康发布使用同一提交：8f31c9a2d417
```

- 这是提示，不是失败。
- 退出码为 0。
- 不使用红色。

### 5.2 推送冲突

```text
远端包含新的提交，当前推送未执行。
为避免覆盖其他人的工作，请先合并远端改动：
  opscli app pull
合并完成后重新运行：
  opscli app publish -m "<本次改动说明>"
```

不得推荐 force push 或 rebase。

### 5.3 凭据缺失

```text
当前设备尚未绑定 AppHub Git 凭据。
运行以下命令完成绑定：
  opscli app git bind
```

如果服务端已有凭据但本地缺失：

```text
账号已有一枚有效凭据，但当前设备没有本地副本。
继续绑定会吊销旧凭据，其他设备上的发布将立即失效。
```

必须显式确认或要求 `--rotate`，不能静默轮换。

### 5.4 密钥命中

```text
检测到疑似敏感信息，发布已阻断。
规则：generic-api-key
文件：src/config.ts
行号：18

请先吊销源系统中的真实凭据，再清理代码。
如果内容已进入本地领先提交，还需要清理本地 Git 历史。
```

不得显示命中内容、提交作者邮箱或完整扫描报告。

### 5.5 断线

```text
与 AppHub 的连接已中断，但发布可能仍在继续。
可运行以下命令继续查看同一次发布：
  opscli app publish --resume
```

不得自动创建第二次 release。

### 5.6 runtime 不支持

```text
当前项目不是 AppHub MVP 支持的运行时。
检测到：Node.js / React 站点
AppHub 当前支持：streamlit、fastapi、gradio

源码尚未提交或推送。
请先完成 AppHub Node/static runtime 接入，再重新发布。
```

该提示必须在 Git 副作用前出现。

### 5.7 CLI 版本过低

```text
当前 opscli 版本低于 AppHub 要求的最低版本。
请升级后重试：
  opscli self-update
```

## 6. 交互确认

只在以下高影响动作确认：

1. rotate 会吊销其他设备凭据。
2. 自动 commit 时 message 缺失且当前为交互终端。
3. 未来若加入 rollback，回滚目标版本需确认。

普通 publish 不重复询问“是否 push”，因为用户执行 publish 本身已经是本次普通 commit、普通 push 和发布的明确授权。该授权不包含 force push、rebase 或修改其他仓库。

## 7. 输出脱敏

统一替换以下键和值：

- `token`
- `authorization`
- `cookie`
- `password`
- `secret`
- Git remote URL 中的 userinfo

远程地址展示前必须移除用户名和密码部分。

## 8. 终端兼容

- Windows 启动时继续使用项目现有 UTF-8 stream reconfigure 机制。
- 不依赖 Unicode 图标表达成功或失败。
- 窄终端下摘要逐字段换行，不用宽表格承载关键结果。
- `--pretty` 可使用 Rich 表格，但 `--json` 和非交互模式不使用颜色控制符。

## 9. Codex 调用规范

Codex Skill 应优先使用：

```bash
opscli app publish -m "<根据 git diff 生成的简洁说明>" --json
```

Skill 必须：

- 在执行前向用户说明这是生产发布动作。
- 不把“创建/修改站点”自动解释为“允许生产发布”。
- 遇到 `GIT-003` 时停止并解释冲突，不自行强推。
- 遇到 runtime 不支持时停止，不伪造成功。
- 只读取 JSON 结果中的稳定字段，不解析彩色人类输出。

## 10. 可用性验收

1. 第一次使用者能从错误提示找到下一条可执行命令。
2. NOOP 不被误认为失败。
3. non-fast-forward 不诱导危险 Git 操作。
4. 断线后用户知道使用 `--resume`，不会重复发布。
5. token 和密钥原文在任何模式下都不可见。
6. Node/static 不兼容提示明确说明“尚未 push”。
7. 人类模式与 JSON 模式表达同一终态，不出现语义分叉。


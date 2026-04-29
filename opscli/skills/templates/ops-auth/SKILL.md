---
name: ops-auth
description: 根据当前环境自动选择 CLI 或 MCP 方式处理 Aukeys 内部系统认证与 Token 管理
version: v1.0.0
---

# ops-auth

用于管理 Aukeys 内部系统的 OAuth2 登录授权、JWT Token、系统列表和认证诊断。

---

## 何时使用本 Skill

- 需要通过 Device Flow 完成首次登录授权
- 需要获取、校验、刷新各系统的 JWT
- 遇到 401、未登录、Token 过期等认证报错
- 需要查看、添加、同步、移除已注册系统
- 需要在脚本或其他 Skill 前置环节确认认证状态

---

## 运行模式判断

进入本 Skill 后，先判断当前环境是否可用 CLI 模式。

优先级如下：

1. 如果用户明确要求使用 CLI 或 MCP，直接遵循用户指定
2. 否则先检测是否安装了 `aukeys-opscli` Python 发行包
3. 再检测 `opscli` 命令是否可执行
4. 如果以上检测通过，读取 `references/cli.md`
5. 如果任一检测失败，读取 `references/mcp.md`

推荐检测脚本：

```bash
python - <<'PY'
from importlib import metadata
import shutil
import subprocess

dist_ok = False
opscli_ok = False

try:
    metadata.version("aukeys-opscli")
    dist_ok = True
except metadata.PackageNotFoundError:
    pass

opscli_ok = shutil.which("opscli") is not None
if opscli_ok:
    opscli_ok = subprocess.run(
        ["opscli", "auth", "--help"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0

print({
    "dist_ok": dist_ok,
    "opscli_ok": opscli_ok,
    "mode": "cli" if dist_ok and opscli_ok else "mcp",
})
PY
```

---

## 阅读入口

- CLI 模式：继续阅读 `references/cli.md`
- MCP 模式：继续阅读 `references/mcp.md`

---

## 使用原则

- 认证动作必须统一走选定模式下的正式入口，不要绕过 Skill 直接拼接鉴权请求
- `ops-auth` 是 `ops-amazon`、`ops-dataset-query` 等 Skill 的前置依赖，出现认证异常时应优先回到本 Skill
- 认证检查、Token 刷新、系统同步和诊断流程都以对应 reference 文档为准

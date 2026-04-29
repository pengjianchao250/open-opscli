---
name: ops-amazon
description: 根据当前环境自动选择 CLI 或 MCP 方式抓取 Amazon 商品页和搜索结果样本
version: v0.1.2
---

# ops-amazon

用于抓取 Amazon 商品页快照、搜索结果页样本，以及面向 ops API 和数据表设计的标准化样本数据。

---

## 何时使用本 Skill

- 需要抓取某个 Amazon 商品的价格、评分、评论数、配送位置
- 需要抓取关键词搜索结果做竞品样本分析
- 需要输出未来提交给 ops API 的标准 payload
- 需要拿真实样本给后端做字段设计、表结构设计、接口设计
- 需要查看某个商品的本地历史抓取记录

---

## 运行模式判断

进入本 Skill 后，先判断当前环境是否可用 CLI 模式。

优先级如下：

1. 如果用户明确要求使用 CLI 或 MCP，直接遵循用户指定
2. 否则先检测是否安装了 `aukeys-opscli` Python 发行包
3. 再检测 `opscli` 命令是否可执行
4. 对 `ops-amazon` 额外检测 `opscli amazon --help` 是否成功，用于确认 Amazon 扩展已就绪
5. 如果以上检测通过，读取 `references/cli.md`
6. 如果任一检测失败，读取 `references/mcp.md`

推荐检测脚本：

```bash
python - <<'PY'
from importlib import metadata
import shutil
import subprocess

dist_ok = False
opscli_ok = False
amazon_ok = False

try:
    metadata.version("aukeys-opscli")
    dist_ok = True
except metadata.PackageNotFoundError:
    pass

opscli_ok = shutil.which("opscli") is not None
if opscli_ok:
    amazon_ok = subprocess.run(
        ["opscli", "amazon", "--help"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0

print({
    "dist_ok": dist_ok,
    "opscli_ok": opscli_ok,
    "amazon_ok": amazon_ok,
    "mode": "cli" if dist_ok and opscli_ok and amazon_ok else "mcp",
})
PY
```

---

## 阅读入口

- CLI 模式：继续阅读 `references/cli.md`
- MCP 模式：继续阅读 `references/mcp.md`

---

## 使用原则

- 抓取动作必须统一走选定模式下的正式入口，不要在 Skill 内直接调用 Amazon HTTP 接口
- 认证检查仍然是强制门禁，具体门禁流程以对应 reference 文档为准
- 若目标是后端设计，优先使用商品页快照、payload、搜索结果、schema 四类能力取样
- 搜索结果页的 `review_count_value` 视为近似值；商品页抓取结果更适合作为精确快照值

---
name: ops-profit-structure-analyzer
mcp-version: v0.1.0
description: 使用 MCP Tool 查询数据并计算分析结果（无状态模式）
---

# ops-profit-structure-analyzer (MCP 无状态模式)

使用 MCP Tool 查询数据，通过本地缓存索引辅助字段检索，使用脚本完成分析计算。**无状态模式**：服务器不保存用户 OAuth 凭证，所有认证信息由调用方传入。

---

## 调用前置要求

> **【强制】每次调用 `query_*` 前，必须先确认已提供有效 `session_id`；禁止默认假设用户已经登录。**

- 进入本 Skill 后，第一步先调用 `auth_is_authenticated(session_id)` 检测 session 有效性
- 若返回 `false` 或报错，说明 `session_id` 缺失或已过期
- **若 `session_id` 缺失**：
  1. 调用 `auth_login_start()` 获取 `verification_url` + `user_code`
  2. 提示用户在浏览器中打开 URL 并输入验证码
  3. 按 `interval` 轮询 `auth_login_poll(device_code)` 直到 `status=authorized`
  4. 获取返回的 `session_id`，保存到当前对话上下文
- 只有认证状态确认正常后，才允许继续执行 `query_metadata`、`query_build`、`query_run`、`query_build_and_run`

**标准前置流程（MCP Tool 调用）：**

```python
# 1. 先检查 session 是否有效
auth_is_authenticated(session_id="xxx")

# 2. 如 session_id 缺失或过期，重新授权
auth_login_start()                     # 获取 device_code / user_code
auth_login_poll(device_code="xxx")     # 轮询直到 authorized，获取新 session_id

# 3. 登录后再次确认
auth_is_authenticated(session_id="新session_id")
```

> **【强制】使用本 Skill 前，必须先阅读 `references/data-query-service-dev-guide.md`**

---

## 使用原则

- 本 Skill 负责字段搜索、缓存读取和辅助构造查询参数
- 所有远端查询动作必须通过 MCP Tool 执行，**禁止直接调用后端 HTTP 接口**
- 本地数据过期时，先执行 `skills_upgrade(name="ops-dataset-query")` 再重试查询
- 分析计算通过对应 MCP 脚本完成（无 opscli 依赖）

---

## MCP Tool 调用参考

### 查询 成本结构数据

```python
result = query_build_and_run(
    dataset="成本结构数据（采购成本、头程、广告费、退款等）",
    dimensions=["asin"],
    limit=1000,
    session_id="xxx",
    skills_dir="/path/to/skills"
)
```

---

## 辅助脚本（无 opscli 依赖）

### `analyze_cost_structure_mcp.py` — 成本结构分析（无 opscli 依赖）

从 stdin 读取 JSON 输入或通过 `--input` 指定文件，执行分析计算并输出 JSON。**不依赖 opscli 命令行工具**。

```bash
# 从 stdin 读取
echo '{"key": "value"}' | python scripts/analyze_cost_structure_mcp.py

# 从文件读取
python scripts/analyze_cost_structure_mcp.py --input /tmp/data.json --pretty
```

---

## 典型工作流

```python
# 0. 先检查 session；如无效则重新 Device Flow 授权
auth_is_authenticated(session_id="xxx")

# 1. 查询数据
# ... 使用 query_build_and_run 获取数据

# 2. 在 AI Agent 中直接使用核心函数计算
```

---

## 【强制】比较类查询优先级规则

> 涉及环比、同比、趋势对比等场景时，**必须按以下优先级选择方案：**

| 优先级 | 场景 | 方案 |
|--------|------|------|
| ① 最优 | 当期 vs 对比期汇总对比（环比/同比） | `dataComparison`（服务端条件聚合，一次 SQL） |
| ② 次优 | 按时间粒度分组的趋势环比/同比 | `MOY` 高级计算（服务端窗口函数，一次 SQL） |
| ③ 兜底 | ①②均因工具限制无法使用时 | 多次 `query_build_and_run` + 客户端合并 |

---

## MCP 认证工具速查

### 检查 session 有效性
```python
auth_is_authenticated(session_id="860b0636485b5188a2b9b4ed5210e736")
# → {success: true, data: true}
```

### 获取 JWT
```python
auth_get_token(system="ops", session_id="860b0636485b5188a2b9b4ed5210e736")
# → {success: true, data: "eyJhbG..."}
```

---

## 错误处理

| 场景 | 解决方法 |
|------|---------|
| 本地数据为空 | `skills_upgrade(name="ops-dataset-query")` |
| dataset_alias 不存在 | 检查拼写或 `skills_upgrade` 同步最新数据集 |
| 未登录 / session 无效 | 调用 `auth_login_start()` → 浏览器授权 → `auth_login_poll()` |
| Token 过期 | `auth_token_refresh(session_id)`；如 session 也过期则重新 Device Flow |
| 分析结果异常 | 检查输入数据是否完整，补全缺失数据后重算 |

---

## 安装与管理

```python
# 安装
skills_install(name="ops-profit-structure-analyzer", skills_dir="/Users/mask/.config/opencode/skills")

# 强制重装
skills_install(name="ops-profit-structure-analyzer", force=True, skills_dir="/Users/mask/.config/opencode/skills")

# 查看版本
skills_status(skills_dir="/Users/mask/.config/opencode/skills")

# 升级
skills_upgrade(name="ops-profit-structure-analyzer", skills_dir="/Users/mask/.config/opencode/skills")
```

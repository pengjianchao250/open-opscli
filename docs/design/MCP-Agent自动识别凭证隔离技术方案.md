# MCP Agent 自动识别凭证隔离技术方案（方案 C）

> 版本：v1.0 · 日期：2026-05-12 · 项目：open-opscli

---

## 背景与目标

### 问题

当前 MCP Server 的凭证隔离仅按 **API Key** 区分用户目录：

```
~/.config/opscli/credentials_by_key/
    <SHA256(api_key)[:16]>/   ← 同一 API Key 下所有 Agent 共享同一套凭证
```

这意味着 Claude Code、Cursor、Cherry Studio 等多个 Agent 工具若使用同一 API Key 连接，会共享同一个登录状态，无法实现 **"切换工具需要重新登录"** 的隔离效果。

### 目标

- 同一用户、同一 API Key，在 **不同 Agent 工具**中连接 MCP Server 时，各自拥有独立的凭证存储
- **用户零配置**：无需手动传参、无需修改客户端配置
- 隔离逻辑在服务端自动完成

---

## 可行性验证

### MCP 协议层的 clientInfo

MCP 协议规定，客户端连接时强制执行 `initialize` 握手：

```
Client → initialize { clientInfo: { name: "claude-code", version: "1.2.0" }, ... }
Server → InitializeResult
```

`clientInfo` 的结构（来自 `mcp/types.py`）：

```python
class Implementation(BaseMetadata):
    name: str      # Agent 名称，如 "claude-code"、"cursor"
    version: str   # Agent 版本号

class InitializeRequestParams(RequestParams):
    clientInfo: Implementation
```

### 读取路径（已验证）

```
ServerSession._received_request()     # session.py:165
    → self._client_params = params    # 存储完整 InitializeRequestParams

_handle_request()                     # lowlevel/server.py:753
    → request_ctx.set(RequestContext(
          session=session,            # session 随 RequestContext 注入
      ))

任意 Tool 函数内：
    request_ctx.get().session.client_params.clientInfo.name  ✅ 可靠读取
```

`request_ctx` 由 MCP 框架在 `_handle_request` 同一任务内设置，**SSE 和 Streamable HTTP 两种传输模式下均可靠**，不受 `mcp_request_ctx` 传播链路复杂性影响（现有 `context.py` 注释有详细说明）。

---

## 方案设计

### 隔离维度

```
stdio 模式
    → api_key 不存在
    → 使用默认路径（与 CLI 共享），不隔离

HTTP / SSE 模式 + clientInfo.name 存在
    → SHA256( api_key + "::" + clientInfo_name_normalized )[:16]
    → ~/.config/opscli/credentials_by_key/<hash>/

HTTP / SSE 模式 + clientInfo.name 不存在（极端容错）
    → SHA256( api_key )[:16]
    → 退回旧行为，向后兼容
```

`clientInfo.name` 标准化规则：`.strip().lower()[:64]`，保证同一 Agent 不同版本映射到同一目录（`"Claude Code"` → `"claude code"` → 目录固定）。

### 目录结构变化

```
~/.config/opscli/credentials_by_key/
    旧：a1b2c3d4e5f6a7b8/           ← SHA256(api_key)[:16]

    新：f1e2d3c4b5a6f7e8/           ← SHA256(api_key + "::" + "claude code")[:16]
        9a8b7c6d5e4f3a2b/           ← SHA256(api_key + "::" + "cursor")[:16]
        c1d2e3f4a5b6c7d8/           ← SHA256(api_key + "::" + "cherry-studio")[:16]
```

同一 API Key，三个 Agent 工具 → 三个独立凭证目录 → 各自必须单独登录。

---

## 各模块改动清单

### 1. `opscli/mcp/context.py` — 新增 `get_current_client_name()`

```python
def get_current_client_name() -> str | None:
    """从 MCP initialize 握手中读取客户端 Agent 名称（clientInfo.name）。

    通过 MCP 框架的 request_ctx 读取 session.client_params.clientInfo，
    在 SSE 和 Streamable HTTP 两种模式下均可靠（与 api_key 读取路径无关）。

    Returns:
        标准化后的客户端名称（lowercase），或 None（未初始化 / stdio 无需区分）
    """
    try:
        from mcp.server.lowlevel.server import request_ctx
        rc = request_ctx.get()
        if rc and rc.session and rc.session.client_params:
            client_info = rc.session.client_params.clientInfo
            if client_info and client_info.name:
                return client_info.name.strip().lower()[:64]
    except (LookupError, AttributeError, Exception):
        pass
    return None
```

### 2. `opscli/mcp/key_based_storage.py` — 新增 `agent_name` 参数

```python
def get_credential_dir_for_key(
    api_key: str,
    base_root: Path,
    agent_name: str | None = None,
) -> Path:
    """将 API Key + Agent 名称映射为固定目录名。

    传入 agent_name 时联合计算哈希，实现 Agent 级别的凭证物理隔离。
    不传时退回 api_key 单独哈希（向后兼容旧目录）。

    分隔符"::"防止 api_key 与 agent_name 拼接时产生哈希碰撞。
    """
    if agent_name:
        combined = f"{api_key}::{agent_name}"
    else:
        combined = api_key
    key_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]
    path = base_root / key_hash
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path
```

### 3. `opscli/mcp/tools/helpers.py` — `_get_credential_dir()` 自动联合

```python
def _get_credential_dir() -> Path | None:
    """获取当前请求对应的凭证隔离目录。

    隔离维度：API Key + clientInfo.name（Agent 工具名称）
    - HTTP/SSE 模式：自动从 MCP initialize 握手读取 Agent 名称，联合计算目录
    - stdio 模式：返回 None，使用默认路径（与 CLI 共享）
    - clientInfo 不存在时：退回纯 API Key 隔离（向后兼容）
    """
    from opscli.mcp.context import get_current_api_key, get_current_client_name
    from opscli.mcp.key_based_storage import get_credential_dir_for_key
    from opscli.config import CONFIG_DIR

    api_key = get_current_api_key()
    if not api_key:
        return None   # stdio 模式，使用默认路径

    agent_name = get_current_client_name()   # 自动读取，None 时退回旧行为
    base_root = Path(CONFIG_DIR) / "credentials_by_key"
    return get_credential_dir_for_key(api_key, base_root, agent_name=agent_name)
```

### 4. `opscli/mcp/tools/auth.py` — `auth_mcp_login` 自动填充 `agent_name`

`agent_name` 参数保留为可选，职责拆分为两层：

- **凭证目录隔离**：完全由 `_get_credential_dir()` 基于 `clientInfo` 自动处理，不依赖工具参数
- **后端审计字段**：`agent_name` 用于写入 `cli_device_codes.agent_name`，默认自动从 `clientInfo.name` 读取

```python
async def auth_mcp_login(agent_name: str | None = None) -> dict:
    from opscli.mcp.context import get_current_client_name

    # 审计用：优先使用显式传入的名称，其次自动从 clientInfo 读取
    effective_agent_name = agent_name or get_current_client_name()

    # payload 中始终携带 agent_name（若有）
    if effective_agent_name:
        payload["agent_name"] = effective_agent_name.strip()[:128]
```

---

## 已知 clientInfo.name 值（需实测验证）

| Agent 工具 | 预期 clientInfo.name | 标准化后（目录键） |
|------------|---------------------|-----------------|
| Claude Desktop | `"Claude Desktop"` | `"claude desktop"` |
| Claude Code CLI | `"claude-code"` | `"claude-code"` |
| Cursor | `"cursor"` | `"cursor"` |
| Cherry Studio | `"cherry-studio"` | `"cherry-studio"` |
| Windsurf | `"windsurf"` | `"windsurf"` |
| MCP Inspector | `"mcp-inspector"` | `"mcp-inspector"` |

> 建议在 `auth_doctor` 返回值中加入 `client_name` 字段，便于实际接入时排查。

---

## 兼容性与迁移

| 场景 | 行为 |
|------|------|
| 旧版无 `clientInfo` 的极端客户端 | `agent_name=None` → 退回旧目录哈希，向后兼容 |
| 已有旧目录的存量用户 | 哈希变化 → 旧目录失效 → 首次访问提示重新登录（正是目标行为） |
| stdio 模式 | `api_key=None` → 默认路径不变，不受影响 |
| 同一 Agent 多版本 | name lowercase 标准化 → 目录不变，版本升级不需要重新登录 |

---

## 改动汇总

| 文件 | 改动性质 | 预估行数 |
|------|---------|---------|
| `opscli/mcp/context.py` | 新增 `get_current_client_name()` | +20 行 |
| `opscli/mcp/key_based_storage.py` | `get_credential_dir_for_key` 加 `agent_name` 参数 | +8 行 |
| `opscli/mcp/tools/helpers.py` | `_get_credential_dir()` 调用新参数 | +3 行 |
| `opscli/mcp/tools/auth.py` | `auth_mcp_login` 自动填充 `effective_agent_name` | +5 行 |
| **合计** | | **~36 行** |

无需后端改动，用户零配置，改动范围极小。

---

## 完整请求链路（改造后）

```
Client (claude-code) → initialize { clientInfo: { name: "claude-code", version: "1.2.0" } }
                       ↓ session.client_params 存储 clientInfo
                       
Client → POST /mcp (CallTool: auth_mcp_login)
    → ApiKeyAuthMiddleware 验证 API Key
    → mcp_request_ctx.set({ api_key: "opscli-mcp-xxx..." })
    → FastMCP _handle_request
    → request_ctx.set(RequestContext(session=session, ...))
    
    Tool 内：
        get_current_api_key()      → "opscli-mcp-xxx..."  （来自 mcp_request_ctx）
        get_current_client_name()  → "claude-code"         （来自 request_ctx.session）
        _get_credential_dir()      → SHA256("opscli-mcp-xxx...::claude-code")[:16]
                                   → ~/.config/opscli/credentials_by_key/f1e2d3c4.../
        
        CredentialStore(base_dir=<隔离目录>).save_session(...)
```

---

## 后续演进方向

1. **`auth_doctor` 新增 `client_name` 字段**：方便调试时确认当前 Agent 被识别为哪个名称
2. **凭证目录 meta 文件**：在隔离目录写入 `meta.json`（包含 `agent_name`、首次登录时间），便于管理员审计
3. **孤儿目录清理命令**：`opscli mcp user clean`，扫描并清理长期未使用的凭证目录

# CLAUDE.md — opscli 项目开发指南

> 本文件为 Claude Code 在 opscli 项目中的工作规范，优先级高于全局 CLAUDE.md。

---

## 项目介绍

**opscli** 是 Aukeys 内部运营 CLI 工具集，以 Python 包形式分发，命令入口为 `opscli`。

- **当前版本**：0.0.4
- **Python 要求**：>= 3.10
- **定位**：多模块可扩展 CLI，auth 是第一个子模块，后续可接入 deploy、notify 等

### 模块结构

```
opscli/
├── __init__.py              # re-export AuthClient
├── config.py                # 全局 CONFIG_DIR（~/.config/opscli/）+ 旧版自动迁移
├── cli.py                   # 顶级 Typer app，注册所有子模块
├── auth/                    # auth 子模块（认证授权）
│   ├── __init__.py          # AuthClient SDK + BUILTIN_SYSTEMS + OPS_URL
│   ├── cli.py               # auth 子命令组（login/logout/token/system/doctor）
│   ├── config.py            # auth 专属配置（读 ops/polaris 服务地址）
│   ├── exceptions.py        # 8 个异常类
│   ├── core/
│   │   ├── device_flow.py   # OAuth2 Device Flow（RFC 8628）
│   │   ├── system_registry.py  # 系统注册表（builtin/local/ops_sync）
│   │   └── token_manager.py    # JWT 管理（双层并发锁 + 三态）
│   └── storage/
│       ├── credential_store.py  # Keychain 优先 / AES-256-GCM 兜底
│       └── crypto.py            # AES-256-GCM 加密工具
├── query/                   # query 子模块（数据查询）
│   ├── __init__.py
│   ├── cli.py               # query 子命令（metadata/run/build）
│   ├── client.py            # QueryClient（HTTP 转发）
│   ├── manager.py           # QueryManager（业务编排，读本地 metadata + 执行查询）
│   ├── models.py            # 数据模型
│   └── exceptions.py        # 查询异常类
└── skills/                  # skills 子模块（Skill 生命周期管理）
    ├── __init__.py
    ├── cli.py               # skills 子命令（list/install/status/upgrade）
    ├── manager.py           # SkillsManager（安装/列表/状态/升级协调）
    ├── detector.py          # SkillDetector（扫描已安装 Skill）
    ├── updater.py           # SkillsUpdater（远端数据拉取，原子替换）
    ├── models.py            # SkillRecord、InstallResult、UpgradeResult
    └── templates/           # 内置 Skill 模板（每个子目录即一个可安装 Skill）
        ├── ops-auth/        # 认证授权 Skill
        ├── ops-dataset-query/  # 数据集查询 Skill（支持远端升级）
        └── ops-skills/      # Skill 管理 Skill
```

### CLI 命令树

```
opscli --version / -V
opscli auth
    login                              # Device Flow 授权登录
    logout                             # 清除本地所有凭证
    doctor                             # 环境检查 + 连通性测试
    token
        status                         # 查看登录状态与各系统 Token
        get -s <alias>                 # 获取 JWT（纯文本，适合脚本）
        check -s <alias>               # 检测 JWT 有效性
        refresh -s <alias> / --all     # 刷新 JWT
    system
        list                           # 列出所有系统
        sync                           # 从 ops 同步系统列表
        add --alias --url [--key]      # 手动添加系统
        remove --alias                 # 移除手动添加的系统
opscli query
    metadata [--dataset | --table-id] [--skills-dir]   # 读取数据集 metadata
    build    [--dataset] [--dimension] [--metric]       # 构造 query payload
             [--where] [--order-by] [--limit] [--offset]
             [--output] [--run]
    run      --payload <file>                           # 执行查询（转发服务端）
opscli skills
    list    [--skills-dir]             # 列出所有已安装 Skill
    install <name> [--runtime] [--force] [--skills-dir]  # 从内置模板安装
    status  [--skills-dir]             # 本地版本 + 远端版本对比
    upgrade [name] [--force] [--skills-dir]  # 升级到远端最新（默认 ops-dataset-query）
```

### 关键路径

| 职责 | 文件 |
|------|------|
| 顶级 CLI 挂载 | `opscli/cli.py` |
| auth 子命令 | `opscli/auth/cli.py` |
| SDK 入口 | `opscli/auth/__init__.py`（AuthClient） |
| 全局配置路径 | `opscli/config.py`（CONFIG_DIR） |
| auth 服务地址 | `opscli/auth/config.py`（DEFAULTS + load_config） |
| Token 管理 | `opscli/auth/core/token_manager.py` |
| 凭证存储 | `opscli/auth/storage/credential_store.py` |
| query 业务编排 | `opscli/query/manager.py`（QueryManager） |
| query HTTP 转发 | `opscli/query/client.py`（QueryClient） |
| Skill 管理协调 | `opscli/skills/manager.py`（SkillsManager） |
| Skill 发现 | `opscli/skills/detector.py`（SkillDetector） |
| Skill 远端升级 | `opscli/skills/updater.py`（SkillsUpdater） |
| Skill 模板目录 | `opscli/skills/templates/` |

### 本地配置存储

```
~/.config/opscli/
├── config.ini         # 可选，覆盖服务地址（ops_url / ops_system_url 等）
├── credentials.bin    # AES-256-GCM 加密凭证（Keychain 不可用时启用）
├── .key               # 256-bit 加密密钥，权限 600
├── systems.json       # 用户自定义 + ops_sync 系统列表
└── .lock_<key>        # 跨进程文件锁（运行时临时文件）
```

---

## 开发铁律

### 【铁律1】新增模块必须遵循模块接入规范

新增模块（如 deploy、notify）的接入方式：

1. **目录结构**：`opscli/{module_name}/`，必须包含 `__init__.py` 和 `cli.py`
2. **CLI 注册**：在 `opscli/cli.py` 追加一行，**不能修改其他地方**：
   ```python
   from opscli.{module_name}.cli import app as {module_name}_app
   app.add_typer({module_name}_app, name="{module_name}")
   ```
3. **配置路径**：必须通过 `from opscli.config import CONFIG_DIR` 获取存储路径，**禁止硬编码** `~/.config/opscli/` 或其他路径
4. **测试目录**：`tests/{module_name}/`，不能放到 `tests/` 根目录

### 【铁律2】禁止破坏现有模块的导入链

`opscli/config.py` 只能导入 Python 标准库，**绝对禁止**反向导入 `opscli.auth.*` 或任何子模块，否则会产生循环导入。

合法的依赖方向：
```
opscli.config  ←  opscli.auth.config
opscli.config  ←  opscli.auth.storage.credential_store
opscli.config  ←  opscli.auth.core.system_registry
```

### 【铁律3】两种 SDK 导入方式必须同时可用

任何时候都要保证以下两种导入均可正常使用：

```python
from opscli import AuthClient        # 通过顶层 re-export
from opscli.auth import AuthClient   # 直接导入子模块
```

修改 `opscli/__init__.py` 或 `opscli/auth/__init__.py` 时必须同时验证两种导入。

### 【铁律4】错误提示文字必须匹配当前命令名

代码中所有面向用户的错误提示必须使用当前命令名，**禁止**出现旧名称残留：

| 位置 | 正确写法 |
|------|---------|
| `token_manager.py` 未登录提示 | `opscli auth login` |
| `device_flow.py` 超时提示 | `opscli auth login` |
| `auth/cli.py` 各提示语 | `opscli auth login` / `opscli auth token status` |

### 【铁律5】Keychain 服务名不可随意更改

`credential_store.py` 中的 `_KEYRING_SERVICE = "opscli-auth"` 是用户 macOS 钥匙串的存储键，一旦修改将导致所有用户的凭证失效（需要重新登录）。

### 【铁律6】并发锁机制不可删减

`token_manager.py` 的双层锁设计（线程锁 + 跨进程文件锁）解决多进程并发重复获取 JWT 的问题，不可以为了"简化"而删除任意一层：

- **Layer 1**：`threading.Lock`（防同进程多线程并发）
- **Layer 2**：`fcntl.flock()`（防多 CLI 进程并发，Windows 自动跳过）

### 【铁律7】Token 生命周期常量不可随意调整

| 常量 | 值 | 说明 |
|------|----|------|
| `REFRESH_THRESHOLD` | 300s（5分钟） | 提前刷新阈值，过大会导致频繁刷新 |
| `MAX_JWT_TTL` | 86400s（24小时） | 防止后端返回异常超长 TTL |

调整前必须充分评估对用户侧的影响，并在 PR 描述中说明原因。

### 【铁律8】测试不依赖真实网络和系统 Keychain

所有测试必须通过 `base_dir=tmp_path`（pytest fixture）传入临时目录，自动跳过 Keychain：

```python
# 正确：测试时传入 tmp_path
store = CredentialStore(base_dir=tmp_path)

# 禁止：测试中使用默认路径（会读写真实 Keychain 和 ~/.config/opscli/）
store = CredentialStore()
```

网络请求使用 `respx` 进行 mock，不可发起真实 HTTP 请求。

### 【铁律9】内置系统（ops/polaris）不可在代码中被删除

`auth/config.py` 的 `get_builtin_systems()` 定义了两个内置系统，这是产品功能约定：
- `ops`：运营系统（ops.aukeys.com）
- `polaris`：刊登系统（bi.aukeys.com）

内置系统在 `system_registry.py` 中有保护逻辑（`remove()` 会拒绝删除 builtin 系统），不可绕过此保护。

### 【铁律10】Skills 禁止直连后端 API，所有操作必须经由 opscli 模块转发

涉及数据查询、认证、元数据获取等能力时，**Skill 脚本不能直接调用**后端 HTTP API，必须统一通过 `opscli` 的正式命令入口执行。

强制约束：

1. Skill 脚本只能负责：
   - 本地文件读取与缓存
   - 辅助构造命令参数
   - 通过 `subprocess` 调用 `opscli` 子命令
2. Skill 脚本**禁止**直接使用 `httpx` / `requests` 调用任何后端接口
3. 所有远端动作必须通过 `opscli` 命令封装，例如：
   - `opscli query metadata` / `opscli query run`
   - `opscli auth token get -s ops`
   - `opscli skills upgrade ops-dataset-query`
4. 认证、参数校验、payload 组装、错误映射统一由 `opscli` 负责
5. 后端新增接口时，默认先补 `opscli` 对应入口，再让 Skill 消费

### 【铁律11】Skill 命名必须使用 `ops-` 前缀

所有内置 Skill（`opscli/skills/templates/` 下的子目录）命名必须以 `ops-` 开头：

| 正确 | 错误 |
|------|------|
| `ops-auth` | `auth` |
| `ops-dataset-query` | `dataset-fields`、`dataset-query` |
| `ops-skills` | `skills` |

**规则**：
- `ops-` 前缀标识该 Skill 属于 Aukeys 运营工具体系，便于与用户自定义 Skill 区分
- 新增 Skill 时若不带 `ops-` 前缀，视为命名不合规，必须改名后再合入
- 安装命令示例：`opscli skills install ops-auth`

### 【铁律12】新增 Skill 必须遵循完整接入规范

新增 Skill 时，根据是否需要远端升级分两条路径：

**路径 A：纯本地 Skill（无远端升级）**

1. 在 `opscli/skills/templates/` 下创建目录，名称必须带 `ops-` 前缀
2. 目录结构必须包含：
   ```
   ops-xxx/
   ├── data/VERSION.json     # 必须，SkillDetector 识别标志
   ├── SKILL.md              # 必须，AI Agent 使用指南（见下方要求）
   └── scripts/              # 可选，具体功能脚本
   ```
3. `VERSION.json` 格式：`{"name": "ops-xxx", "version": "v1.0.0"}`
4. **无需修改** `manager.py` / `updater.py` 任何代码，install 命令自动支持

**路径 B：支持远端升级的 Skill**

在路径 A 基础上，还需修改两处代码：

1. **`opscli/skills/updater.py`**：
   - 新增 API 端点常量
   - 在 `fetch_manifest()` 中添加 skill_name 分支
   - 新增 `upgrade_ops_xxx()` 升级方法

2. **`opscli/skills/manager.py`**：
   - `status()` 中为新 Skill 添加远端版本拉取逻辑
   - `upgrade()` 中添加名称分发分支（`elif name == "ops-xxx":`）

**SKILL.md 内容要求**：

- 必须描述 `opscli` 命令，**禁止**描述 `python scripts/xxx.py` 调用方式
- 每个命令必须列出完整参数说明和使用示例
- 必须包含"典型工作流"章节
- 格式参照 `ops-auth/SKILL.md` 或 `ops-dataset-query/SKILL.md`

### 【铁律13】依赖版本约束不加不必要的上限

`pyproject.toml` 中的依赖版本约束只设下限，**不加上限**，除非有明确的 API 不兼容证据：

```toml
# 正确
"cryptography>=38"
"httpx>=0.27"

# 错误（除非有具体 breaking change 记录）
"cryptography>=38,<42"
```

**教训**：`cryptography>=38,<42` 曾导致 pip 强制降级系统已有的 v46，破坏同环境中其他包（`opscli`）。上限约束应在有明确 breaking change 时才添加，并在注释中说明原因和对应 issue。

### 【铁律14】文档必须按类型分类存放，文件名必须使用中文

所有项目文档必须遵循以下规范：

**分类目录（6 类）**：

| 目录 | 用途 | 示例 |
|------|------|------|
| `docs/guide/` | 用户使用指南 | `认证模块使用指南.md` |
| `docs/spec/` | 开发规范 | `开发规范.md` |
| `docs/analysis/` | 分析调研报告 | `授权模式对比分析报告.md` |
| `docs/release/` | 发布与运维 | `打包发布指南.md` |
| `docs/plans/` | 方案与计划 | `取数底座一期开发计划.md` |
| `docs/design/` | 技术设计文档 | `query模块设计.md` |

**命名规则**：
1. 文件名**必须使用中文**，禁止使用英文命名（纯技术术语如 `query`、`Skill`、`API` 可保留英文）
2. 新建文档时必须先确定所属分类目录，**禁止**直接放在 `docs/` 根目录
3. 同一类型的文档放入同一目录，不可散落
4. 方案类文档如涉及多阶段，可加阶段后缀（如"取数底座**一期**开发计划"）

### 【铁律15】所有代码必须有中文注释，重要业务逻辑必须全面注释

编写或修改任何 Python 代码时，必须遵循以下注释规范：

**基本要求**：
1. 所有代码注释必须使用**中文**，禁止使用英文注释（技术术语如 `JWT`、`HTTP`、`AES` 可保留英文）
2. 每个模块（`.py` 文件）顶部必须有模块级 docstring，简要说明模块职责
3. 每个公开类和公开方法必须有中文 docstring，说明其用途、参数和返回值
4. 关键业务逻辑（如认证流程、加密解密、并发锁控制、Token 刷新等）必须逐行或逐段注释

**注释粒度要求**：

| 代码位置 | 注释要求 |
|----------|----------|
| 模块顶部 | 必须，说明模块职责和主要类/函数 |
| 类定义 | 必须，说明类的用途和主要状态 |
| 公开方法 | 必须，docstring 说明参数、返回值、异常 |
| 私有方法 | 建议，说明内部逻辑意图 |
| 重要业务逻辑块 | 必须，段落注释说明"为什么这样做" |
| 复杂条件判断 | 必须，说明分支含义和边界条件 |
| 常量定义 | 必须，说明常量的用途和取值依据 |
| 并发/锁相关代码 | 必须，详细说明锁的作用和顺序 |

**示例（正确写法）**：
```python
# 双层锁设计：先获取线程锁防止同进程并发，再获取文件锁防止多进程并发
with self._thread_lock:
    # 检查 Token 是否在刷新阈值内即将过期（提前 5 分钟刷新）
    if token_exp - time.time() < REFRESH_THRESHOLD:
        with file_lock(self._lock_path):
            # 二次检查：其他进程可能已完成刷新，避免重复刷新
            token = self._load_token()
            if token_exp - time.time() < REFRESH_THRESHOLD:
                token = self._do_refresh(token)
```

**禁止行为**：
- ❌ 编写无注释的业务逻辑代码
- ❌ 使用英文注释（`# Get token` → 应改为 `# 获取 Token`）
- ❌ 只写"做了什么"而不写"为什么"（`# 刷新 token` → 应补充原因）
- ❌ 公开方法缺少 docstring
- ❌ 复杂逻辑只靠变量名自说明，不加任何注释

---

## 开发流程

### 环境准备

```bash
cd /Users/mask/python3/opscli
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

### 验证安装

```bash
opscli --version          # 输出 opscli v0.0.4
opscli auth --help        # 显示 auth 子命令列表
opscli auth token status  # 查看登录状态
```

### 运行测试

```bash
pytest tests/ -v                              # 全量（当前 74 个测试）
pytest tests/auth/ -v                         # 仅 auth 模块
pytest tests/skills/ -v                       # 仅 skills 模块
pytest tests/query/ -v                        # 仅 query 模块
pytest tests/auth/test_token_manager.py -v    # 单文件
```

### 本地开发覆盖服务地址

```ini
# ~/.config/opscli/config.ini
[systems]
ops_url = http://localhost/api
ops_system_url = http://ops.cm
ops_token_endpoint = /api/v1/auth/cli-token
polaris_system_url = http://po2.cm
polaris_token_endpoint = /api/auth/cli-token
```

### 打包发布

```bash
rm -rf dist/
python -m build
twine upload --repository testpypi dist/*   # 先验证
twine upload dist/*                          # 正式发布
```

详见 [docs/release/打包发布指南.md](docs/release/打包发布指南.md)。

---

## 代码规范

- **Python 版本**：>= 3.10，可使用 `X | Y` 类型联合、`match` 语句等新特性
- **类型注解**：公开方法必须标注返回类型和参数类型
- **注释语言**：中文，重要逻辑必须注释说明
- **异常**：业务异常必须继承 `opscli/auth/exceptions.py` 中的 `AuthError`；新模块可定义自己的基类，但命名需加模块前缀（如 `DeployError`）
- **HTTP 客户端**：统一使用 `httpx`，超时设置 `timeout=10`
- **不引入新的全局状态**：模块级变量仅用于线程锁（参考 `token_manager.py` 的 `_thread_locks`）

---

## 文档位置

> 文档按类型分类存放，所有文档必须使用中文名称。详见【铁律14】。

### 目录结构

```
docs/
├── guide/        # 使用指南（面向用户）
├── spec/         # 开发规范（面向开发者）
├── analysis/     # 分析调研报告
├── release/      # 发布与运维
├── plans/        # 方案与计划
├── design/       # 技术设计文档
└── README.md     # 文档索引
```

### 文档索引

| 分类 | 文档 | 路径 |
|------|------|------|
| 使用指南 | 认证模块使用指南 | `docs/guide/认证模块使用指南.md` |
| 发布运维 | 打包发布指南 | `docs/release/打包发布指南.md` |
| 分析调研 | 授权模式对比分析报告 | `docs/analysis/授权模式对比分析报告.md` |
| 开发规范 | opscli 开发规范 | `docs/spec/开发规范.md` |
| 项目说明 | README | `README.md` |
| 方案计划 | 认证模块设计方案 | `docs/plans/认证模块设计方案.md` |
| 方案计划 | 认证模块实施计划 | `docs/plans/认证模块实施计划.md` |
| 方案计划 | 取数底座一期开发计划 | `docs/plans/取数底座一期开发计划.md` |
| 方案计划 | 取数底座一期验收手册 | `docs/plans/取数底座一期验收手册.md` |
| 方案计划 | 取数底座一期联调记录 | `docs/plans/取数底座一期联调记录.md` |
| 方案计划 | 取数底座一期发布检查清单 | `docs/plans/取数底座一期发布检查清单.md` |
| 方案计划 | 取数底座一期剩余任务 | `docs/plans/取数底座一期剩余任务.md` |
| 技术设计 | query 模块设计 | `docs/design/query模块设计.md` |
| 技术设计 | Skills 多工具调研规划 | `docs/design/Skills多工具调研规划.md` |
| 技术设计 | AI 取数能力底座开发需求 | `docs/design/AI取数能力底座开发需求.md` |
| 技术设计 | 数据查询服务开发说明 | `docs/design/数据查询服务开发说明文档.md` |
| 技术设计 | 数据集字段技能系统技术方案 | `docs/design/数据集字段技能系统技术方案.md` |
| 技术设计 | 通用 Skill 版本控制架构 | `docs/design/通用Skill版本控制架构.md` |
| 使用指南 | Skills 基础开发培训手册 | `docs/guide/Skills基础开发培训手册.md` |

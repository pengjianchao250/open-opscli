# CLI 子命令懒加载方案

> 日期：2026-08-28　状态：已实施（2026-09-21，分支 `feature/cli-lazy-loading`）　关联排查：`docs/change-log-pending.md` 2026-08-28 条目
>
> **实施说明（与 §3.1 的偏差）**：落地时未覆写 `list_commands`/`get_command`/`resolve_command`，改为在 `LazyTyperGroup.__init__` 把懒加载代理直接放入 `self.commands`——代理零导入，命令列表、建议、补全复用 click/typer 原生实现。原因：实测发现 typer 0.25 绑定真实 click、typer 0.27 绑定内置 `_click`，两类后端类层次不同，覆写/跨层 super 耦合在后者断裂。另将 `opscli/__init__.py` 顶层 re-export 改为 PEP 562 惰性（铁律3 语义不变），`import opscli.cli` 的模块数从预估 ~16 进一步降到 3。最终实测：升级后首跑 4.89s（<5s 达标）、二次 0.12s。

## 一、问题与根因

升级 opscli 后首次执行任意命令（含 `opscli -V`）耗时 30s～90s，第二次起恢复 1.5s。

排查结论（干净 venv 复现三次，数据一致）：

| 指标 | 首次运行 | 二次运行 |
| --- | --- | --- |
| `import opscli.cli` 总耗时 | 27.1s | ~1.0s |
| opscli 自有 399 个模块 self 时间之和 | 26.6s | 0.98s |
| 单模块平均 / 最大 | 67ms / 0.33s | 2.5ms / 0.07s |
| 进程 CPU 占用 | 2%～8% | 75% |

- 耗时**均匀摊在每个模块**上，无热点 → 不是某处代码做网络请求或重计算
- CPU 极低 → 进程在等待系统，而非执行 Python
- 正式 wheel 为 Cython 编译，含 **319 个 `.so`**，每个都带系统托管的 `com.apple.provenance` 属性；macOS 对新落盘二进制**首次 `dlopen` 逐个做安全评估**，单个数十至数百毫秒
- `opscli/cli.py` 顶层 **28 处 `add_typer` 急切导入**全部子模块，`opscli -V` 就加载了 **231 个 `.so` / 1310 个模块**，把上述单次开销放大到分钟级

`c83bc0fb`（2026-07-24）修复的是启动/退出路径的**网络阻塞**（秒级），与本问题无关，代码仍在生效。

## 二、目标与验收标准

| 目标 | 验收方式 |
| --- | --- |
| `opscli -V` / `opscli --help` 不导入任何子模块 | `python -X importtime -c "import opscli.cli"` 中 opscli 模块数从 399 降到 ≤ 20 |
| 单个子命令只导入自身依赖 | `opscli auth --help` 后 `sys.modules` 中不含 `opscli.seller_sprite`、`opscli.query` 等无关模块 |
| 升级后首次 `opscli -V` 秒级 | 干净 venv 重装后 `time opscli -V` < 5s（当前 30～90s） |
| 行为零变化 | `opscli --help` 子命令列表、顺序、help 文案与现状逐字一致；`pytest tests/` 无新增失败 |
| 铁律 1 不破坏 | 新增子模块仍是"在注册表追加一行" |

## 三、技术方案

### 3.1 核心机制

利用 click 的分发链路：`Group.invoke` → `resolve_command` → `get_command(ctx, name)` → `cmd.make_context()` → `sub_ctx.command.invoke()`。
Typer 渲染 `--help` 时对子命令对象只读取 `name` / `hidden` / `deprecated` / `rich_help_panel` / `get_short_help_str()`（`typer/rich_utils.py:628-630`）。

因此：

1. 顶级 `app` 改用自定义 `TyperGroup` 子类（`typer.Typer(cls=LazyTyperGroup)`，Typer 0.25 已支持 `cls`）
2. `list_commands` 返回"注册表名单 + 本文件内直接定义的命令（`self-update`）"，保持现有顺序
3. `get_command` 对注册表中的名字返回一个**轻量代理** `LazyGroupProxy(click.Group)`：
   - 构造时只带 `name` 与 `help`（来自注册表，不导入模块）→ `--help` 渲染零开销
   - 覆写 `make_context` / `invoke` / `get_command` / `list_commands` / `get_params` / `get_help` / `format_help` / `get_usage` / `shell_complete`：首次调用时 `importlib.import_module` 真实模块，`typer.main.get_group(sub_app)` 转成 click Group 并缓存，之后全部委托给真实对象
4. `opscli/__main__.py`、`pyproject.toml` 入口、所有 `from opscli.cli import app` 的测试**无需改动**：`app` 仍是 `typer.Typer` 实例，`CliRunner.invoke(app, [...])` 走同一条 click 分发链

### 3.2 注册表设计

`cli.py` 顶部 28 行 `from ... import app as xxx_app` + 28 行 `add_typer` 合并为一张表，一条记录一行：

```python
# (命令名, 模块路径, help 文案)；help 与各子模块 typer.Typer(help=...) 保持一致
_SUBCOMMANDS: tuple[tuple[str, str, str], ...] = (
    ("auth",              "opscli.auth.cli",              "认证授权管理"),
    ("api-credentials",   "opscli.api_credentials.cli",   "统一管理 SerpAPI、Canopy、scrape.do 的多账号 API Key。"),
    ("amazon",            "opscli.amazon.cli",            "Amazon 商品抓取与 ops 提交通道"),
    ...  # 共 21 条启用项，顺序与当前 opscli --help 输出一致
)
```

- help 文案事实来源：当前 `opscli --help` 的输出（已在排查时逐条抓取）
- 被注释掉的 8 个（`canopy-debug`、`shopify`、`sif`、`xiyou` 等）保留为注释行，不进注册表
- `asin-review` 的可选性：`list_commands` 中用 `importlib.util.find_spec("opscli.asin_review")` 判断（只查找不执行），找不到则不列出，等价于现在的 `try/except ModuleNotFoundError`

### 3.3 help 文案一致性保障

注册表里的 help 是各子模块 `typer.Typer(help=...)` 的**副本**，存在漂移风险。增加一条回归测试：对注册表每一项真正导入子模块，断言 `get_group(sub_app).help == 注册表 help`。漂移时测试即失败。

### 3.4 不做的事（铁律 20/21）

- 不改任何子模块的 `cli.py`
- 不改 `main` 回调、遥测、显式授权参数摘取逻辑
- 不引入配置项或环境变量开关
- 不处理 MCP 入口（`opscli/mcp/server.py` 独立进程，不经过 `cli.py`）

## 四、改动清单

| 文件 | 改动 | 规模 |
| --- | --- | --- |
| `opscli/cli.py` | 删除 28 行急切导入 + 28 行 `add_typer`；新增注册表、`LazyGroupProxy`、`LazyTyperGroup`（约 90 行含中文注释） | 净增约 +40 行 |
| `tests/test_cli_lazy_loading.py`（新建） | ① `-V` / `--help` 后 `sys.modules` 无子模块；② 单子命令只加载自身；③ `--help` 文案与现状快照一致；④ 注册表 help 与子模块 `Typer(help=)` 一致；⑤ `asin-review` 缺失时不列出 | 约 80 行 |
| `docs/change-log-pending.md` | 追加变更记录 | — |
| `CLAUDE.md` 铁律 1 | "CLI 注册：在 `opscli/cli.py` 追加一行"的示例代码由 `add_typer` 改为注册表元组 | 3 行 |

## 五、风险与对策

| 风险 | 对策 |
| --- | --- |
| 子模块 cli 内部有 `typer.Typer(no_args_is_help=True)` 等定制（如 `collector_monitor`） | 代理委托给 `typer.main.get_group(sub_app)` 产出的真实 Group，定制全部保留；`tests/collector_monitor/test_registration.py` 覆盖 |
| shell 补全（`--install-completion` / `--show-completion`）枚举子命令 | 补全只需 `list_commands` + 代理的 `name`/`help`；补全到子命令内部参数时再按需加载该一个模块，符合预期 |
| 子模块导入失败（非 `asin-review` 的其他缺包场景） | 现状是整个 CLI 起不来；懒加载后只有调用到该子命令才报错，其他命令可用——行为**变好**，不是回归 |
| Cython 编译：`cli.py` 在 `_KEEP_SOURCE_MODULE_NAMES` 白名单中保留源码 | 新增类均在 `cli.py` 内，不受 Cython 约束；无需再跑本地 cythonize 验证 |
| 遥测 `command` 字段取自 `sys.argv`，与加载方式无关 | 无影响，`tests/telemetry/test_cli_integration.py` 覆盖 |

## 六、实施步骤（带验证）

1. 抓取现状快照：`opscli --help` 输出存入测试 fixture → 验证：文件存在
2. 改写 `cli.py`（注册表 + 代理 + Group 子类）→ 验证：`opscli --help` 与快照 diff 为空
3. 新建 `tests/test_cli_lazy_loading.py` → 验证：5 个用例通过
4. 全量回归 `pytest tests/ -q` → 验证：失败集合 ⊆ 已知预存失败（见 memory `opscli-test-baseline`）
5. 效果实测：`SKIP_CYTHON=1` 环境 `python -X importtime` 模块数 ≤ 20；`python -m build --sdist` 后在干净 venv 安装，`time opscli -V` 首次 < 5s
6. 更新 `CLAUDE.md` 铁律 1 示例、追加 `change-log-pending.md`

## 七、预期收益

| 场景 | 现状 | 预期 |
| --- | --- | --- |
| 升级后首次 `opscli -V` | 30～90s | < 5s |
| 日常 `opscli -V` / `--help` | 1.5s | < 0.3s |
| 日常单个子命令（如 `auth login`） | 1.5s + 命令本身 | 该子模块导入时间 + 命令本身（多数 < 0.5s） |
| 升级后首次执行某子命令 | 30～90s | 仅该子模块的 `.so` 首次开销（按占比估算 2～10s） |

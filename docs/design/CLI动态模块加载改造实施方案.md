# opscli CLI 动态模块加载改造实施方案

> 适用场景：将 `opscli` 从当前顶级 CLI 静态注册子模块的模式，逐步改造为“静态内建 + 动态外部模块”的兼容加载模式。
>
> 文档状态：实施方案
> 创建时间：2026-04-23

---

## 1. 改造目标

本方案的目标不是一次性完成全面插件化，而是在**不破坏现有用户体验**的前提下，先把 `opscli` 具备“加载外部模块”的能力。

本次改造完成后，应满足以下结果：

1. 现有 `opscli auth/query/skills` 命令行为保持不变
2. 顶级 CLI 具备扫描外部模块 `entry_points` 的能力
3. 外部模块加载失败时，不影响核心 CLI 启动
4. 后续可基于同一套数据结构扩展 `module list/doctor/info`
5. 为未来拆分 `opscli-core` 和独立模块包打下兼容基础

---

## 2. 当前现状

当前项目的顶级 CLI 入口为 [`opscli/cli.py`](/Users/mask/python3/opscli/opscli/cli.py:1)，采用如下模式：

- 直接 import `auth/query/skills` 的 Typer app
- 在模块加载时调用 `app.add_typer(...)`
- 所有模块都与主包一起安装和发布

当前优点是简单、明确、稳定，但存在以下限制：

- 新模块必须修改核心入口文件
- 外部团队不能独立安装和接入模块
- CLI 无法识别模块兼容性、冲突和加载状态

---

## 3. 总体改造策略

本次采用“**双通道注册**”策略：

1. 内建模块仍静态注册
2. 外部模块通过 `entry_points("opscli.modules")` 动态注册

这样做的原因：

- 兼容当前 AGENTS 中“新增内建模块改 `opscli/cli.py`”约束
- 不破坏现有测试和用户命令路径
- 可以边运行边演进，不需要一次性拆包

---

## 4. 改造后目标结构

第一阶段建议新增一个插件管理文件：

```text
opscli/
├── cli.py
├── plugins.py
├── version.py
├── auth/
├── query/
└── skills/
```

职责划分：

- `cli.py`：只负责创建顶级 `Typer app` 并串联加载流程
- `plugins.py`：负责模块协议、发现、校验、注册和结果收集

---

## 5. 分阶段实施计划

### 阶段 1：抽离模块协议与加载器骨架

目标：

- 不改现有命令行为
- 先引入公共数据结构和加载函数

建议新增：

- [`opscli/plugins.py`](/Users/mask/python3/opscli/opscli)

建议包含：

- `ModuleSpec`
- `ModuleRecord`
- `ModuleLoadResult`
- `load_external_modules(app)`
- `_iter_module_entry_points()`
- `_validate_module_spec(...)`

本阶段原则：

- 可以先只做“发现 + 记录”，不一定马上暴露 CLI 命令
- 允许加载结果先只存在内存中

### 阶段 2：改造顶级 CLI 组装方式

目标：

- 让 `cli.py` 不再直接承担所有注册细节

建议把当前顶级 app 初始化改造成：

```python
def create_app() -> typer.Typer:
    app = typer.Typer(...)
    register_builtin_modules(app)
    load_external_modules(app)
    return app


app = create_app()
```

建议新增函数：

- `register_builtin_modules(app)`

这样后续：

- 内建模块注册逻辑有清晰边界
- 外部模块加载逻辑可独立测试

### 阶段 3：补齐错误容错与冲突保护

目标：

- 外部模块出错时不影响主程序
- 避免多个模块抢同一个命令名

需要支持的场景：

1. entry point 不可导入
2. 插件注册函数执行失败
3. `ModuleSpec` 缺失或字段非法
4. `command_name` 冲突
5. `requires_core` 不兼容

本阶段输出：

- 结构化错误对象
- 加载结果缓存
- 冲突与失败的诊断信息

### 阶段 4：补治理命令

目标：

- 让模块加载状态对用户和维护者可见

建议新增内建命令组：

```bash
opscli module list
opscli module doctor
opscli module info <name>
```

建议顺序：

1. 先做 `module list`
2. 再做 `module doctor`
3. 最后做 `module info`

### 阶段 5：选择一个试点模块

目标：

- 用真实模块验证插件协议

推荐优先级：

1. 新增业务模块
2. `query`
3. `skills`

不建议第一批直接拿 `auth` 试点，因为它耦合度最高。

---

## 6. 文件级改造建议

### 6.1 `opscli/cli.py`

建议改造点：

- 保留 `--version` 行为
- 把顶级 app 初始化改为工厂函数
- 新增 `register_builtin_modules(app)`
- 在 app 创建时调用 `load_external_modules(app)`

目标状态：

- 顶级 CLI 只负责装配
- 不直接承载插件发现与校验逻辑

### 6.2 `opscli/plugins.py`

建议新增并承载以下职责：

1. 定义模块协议数据结构
2. 发现外部模块 entry points
3. 校验模块规范
4. 处理命令冲突
5. 收集并返回加载结果

建议函数清单：

```python
def load_external_modules(app: typer.Typer) -> list[ModuleLoadResult]:
    ...


def register_builtin_module(
    app: typer.Typer,
    *,
    module_app: typer.Typer,
    spec: ModuleSpec,
) -> ModuleLoadResult:
    ...
```

说明：

- 虽然名字叫 `plugins.py`，但也建议顺带把内建模块结果统一纳入同一数据模型
- 这样未来 `module list` 才能同时展示 builtin 和 external

### 6.3 `opscli/version.py`

当前已有版本模块，可继续复用。

后续建议增加辅助函数：

- `get_core_version()` 或直接复用现有版本函数

用途：

- 做 `requires_core` 兼容校验

### 6.4 新增 `opscli/module_cli.py` 或等价实现

如果后续要加治理命令，建议新增单独模块，而不是继续塞进 `cli.py`：

```text
opscli/
├── module_cli.py
```

该文件负责：

- `module list`
- `module doctor`
- `module info`

---

## 7. 测试实施建议

### 7.1 第一批测试目标

第一批不需要追求覆盖所有边界，但至少要覆盖以下场景：

1. 内建模块仍正常注册
2. 没有任何外部模块时，CLI 正常启动
3. 有一个合法外部模块时，可以成功注册
4. 外部模块导入失败时，不影响 CLI 启动
5. 命令名冲突时，冲突模块不会覆盖内建模块

### 7.2 推荐测试文件

建议新增：

```text
tests/test_plugins.py
tests/test_cli_plugin_loading.py
```

如果后续增加治理命令，再补：

```text
tests/test_module_cli.py
```

### 7.3 测试实现方式

建议通过 monkeypatch 模拟 `importlib.metadata.entry_points()` 返回值，而不是依赖真实安装包。

优点：

- 测试稳定
- 不依赖真实 pip 安装
- 更容易覆盖异常分支

---

## 8. 兼容策略

### 8.1 对用户的兼容

用户侧应尽量无感知：

- `opscli auth ...` 不变
- `opscli query ...` 不变
- `opscli skills ...` 不变

只是在安装了额外模块时，命令树中会自动出现对应命令。

### 8.2 对现有开发规范的兼容

当前 AGENTS 中关于“新增模块必须在 `opscli/cli.py` 中追加 `add_typer(...)`”的规则，可以暂时解释为：

- 内建模块适用
- 外部可安装模块不适用

后续建议正式更新为两条规范：

1. 内建模块接入规范
2. 插件模块接入规范

### 8.3 对发布流程的兼容

第一阶段不要求：

- 立即拆分 PyPI 包
- 立即更改现有发布命令

只要在代码中具备外部模块加载能力即可。

---

## 9. 风险与注意事项

### 9.1 命令冲突风险

如果不做命令名保护，外部模块可能覆盖现有内建命令。

处理建议：

- 内建模块优先
- 冲突模块直接拒绝注册

### 9.2 启动时性能风险

如果外部模块过多，CLI 启动扫描可能变慢。

处理建议：

- 第一阶段先接受轻量扫描
- 后续若有必要，再做懒加载或缓存

### 9.3 模块副作用风险

某些模块在 import 时可能执行副作用代码。

处理建议：

- 规范要求插件入口模块必须尽量纯净
- 核心侧对导入异常做容错

### 9.4 版本兼容风险

如果模块声明与核心版本不兼容，可能在运行时失败。

处理建议：

- 注册前先校验 `requires_core`
- 不兼容时直接阻止注册

---

## 10. 建议的任务拆分

如果要正式排期，建议拆成以下任务包：

### 任务包 A：插件基础设施

包含：

- 新增 `opscli/plugins.py`
- 定义 `ModuleSpec` 等数据结构
- 实现 `load_external_modules(app)`

### 任务包 B：顶级 CLI 重构

包含：

- `cli.py` 改造成工厂函数
- 抽出 `register_builtin_modules(app)`
- 接入外部模块加载器

### 任务包 C：测试补齐

包含：

- 新增插件发现与冲突测试
- 验证内建模块行为不变

### 任务包 D：模块治理命令

包含：

- `module list`
- `module doctor`
- `module info`

### 任务包 E：试点模块接入

包含：

- 选择一个模块以插件协议接入
- 验证真实安装和自动发现链路

---

## 11. 推荐实施顺序

建议按如下顺序推进：

1. 先做任务包 A
2. 再做任务包 B
3. 补任务包 C
4. 再做任务包 D
5. 最后做任务包 E

原因：

- 先有底座，后有装配
- 先保住兼容，再扩治理能力
- 先做虚拟测试，再上真实试点

---

## 12. 完成标志

可以认为第一阶段改造完成的标准是：

1. 现有 `auth/query/skills` 命令测试全部通过
2. 顶级 CLI 已具备外部模块发现能力
3. 外部模块加载失败不会中断 CLI
4. 至少有一组插件加载测试覆盖成功和失败场景
5. 文档中已有正式的插件接入协议和安装分层方案

---

## 13. 当前建议

如果接下来准备真正开始写代码，我建议直接从“任务包 A + 任务包 B”开始。

也就是说，下一步最值得做的是：

1. 新增 `opscli/plugins.py`
2. 把 [`opscli/cli.py`](/Users/mask/python3/opscli/opscli/cli.py:1) 改成 `create_app()` 模式
3. 先接入外部模块加载器，但不急着加 `module` 管理命令

这样风险最小，而且最容易验证方向是否正确。


# P1 契约与版本治理 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 完成 `skills` 模块结构化错误契约统一，并建立 `opscli` 版本单一事实源与一致性校验。

**Architecture:** 先通过测试固定 `skills` CLI/manager/updater 的错误 JSON 结构，再抽离 `opscli/skills/exceptions.py` 作为统一异常入口；版本治理侧以 `pyproject.toml` 为唯一真源，收敛 CLI fallback 和文档中的当前版本表述，补一个轻量一致性校验测试。

**Tech Stack:** Python 3.10+，Typer，pytest，httpx，pathlib，importlib.metadata

---

### Task 1: 固定 Skills 结构化错误契约

**Files:**
- Modify: `tests/skills/test_cli.py`
- Modify: `tests/skills/test_updater.py`
- Modify: `tests/skills/test_manager.py`

**Step 1: 写 CLI 错误输出失败测试**

在 `tests/skills/test_cli.py` 增加三个断言：

```python
def test_status_outputs_structured_error(monkeypatch):
    class DummyManager:
        def status(self, skills_dir=None):
            from opscli.skills.exceptions import SkillsError
            raise SkillsError("状态查询失败")

    monkeypatch.setattr("opscli.skills.cli.SkillsManager", lambda: DummyManager())
    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"] == {
        "type": "SkillsError",
        "message": "状态查询失败",
    }
```

同样方式补 `install`、`upgrade` 场景，确保 `error` 不再是字符串。

**Step 2: 写 updater 结构化异常失败测试**

在 `tests/skills/test_updater.py` 增加断言：

```python
def test_skill_remote_error_to_dict():
    from opscli.skills.exceptions import SkillRemoteError

    error = SkillRemoteError(
        "远端失败",
        endpoint="/v1/test",
        status_code=503,
    )

    assert error.to_dict() == {
        "type": "SkillRemoteError",
        "message": "远端失败",
        "endpoint": "/v1/test",
        "status_code": 503,
    }
```

**Step 3: 写 manager 远端错误结构失败测试**

在 `tests/skills/test_manager.py` 增加断言，约束 `remote_error` 为对象：

```python
def test_status_wraps_remote_error(monkeypatch):
    manager = SkillsManager()
    monkeypatch.setattr(manager, "list_skills", lambda **_: [])

    def fail(_name):
        from opscli.skills.exceptions import SkillRemoteError
        raise SkillRemoteError("未登录", endpoint="/manifest", status_code=401)

    monkeypatch.setattr(manager.updater, "build_remote_summary", fail)
    payload = manager.status()

    assert payload["remote_error"] == {
        "type": "SkillRemoteError",
        "message": "未登录",
        "endpoint": "/manifest",
        "status_code": 401,
    }
```

**Step 4: 运行测试确认先失败**

Run:
```bash
pytest tests/skills/test_cli.py tests/skills/test_updater.py tests/skills/test_manager.py -v
```

Expected: FAIL，报错点集中在 `opscli.skills.exceptions` 不存在或 `error` 仍是字符串。

**Step 5: Commit**

```bash
git add tests/skills/test_cli.py tests/skills/test_updater.py tests/skills/test_manager.py
git commit -m "test: lock skills structured error contract"
```

### Task 2: 抽离 Skills 异常模块并统一序列化

**Files:**
- Create: `opscli/skills/exceptions.py`
- Modify: `opscli/skills/updater.py`

**Step 1: 新增异常模块**

创建 `opscli/skills/exceptions.py`：

```python
from __future__ import annotations


class SkillsError(Exception):
    """skills 模块统一异常基类。"""

    def to_dict(self) -> dict:
        return {
            "type": self.__class__.__name__,
            "message": str(self),
        }


class SkillRemoteError(SkillsError):
    """远端 Skill 接口异常。"""

    def __init__(
        self,
        message: str,
        *,
        endpoint: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.endpoint = endpoint
        self.status_code = status_code

    def to_dict(self) -> dict:
        payload = super().to_dict()
        if self.endpoint is not None:
            payload["endpoint"] = self.endpoint
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        return payload
```

**Step 2: updater 改为引用新异常模块**

在 `opscli/skills/updater.py` 中：
- 删除本地 `SkillRemoteError` 类定义
- 改为 `from opscli.skills.exceptions import SkillRemoteError`

**Step 3: 运行测试确认通过**

Run:
```bash
pytest tests/skills/test_updater.py -v
```

Expected: PASS

**Step 4: Commit**

```bash
git add opscli/skills/exceptions.py opscli/skills/updater.py tests/skills/test_updater.py
git commit -m "refactor: extract skills exception module"
```

### Task 3: 统一 CLI 和 Manager 错误对象输出

**Files:**
- Modify: `opscli/skills/cli.py`
- Modify: `opscli/skills/manager.py`

**Step 1: 增加错误序列化辅助函数**

在 `opscli/skills/cli.py` 增加：

```python
from opscli.skills.exceptions import SkillsError


def _serialize_error(exc: Exception) -> dict:
    if isinstance(exc, SkillsError):
        return exc.to_dict()
    return {
        "type": exc.__class__.__name__,
        "message": str(exc),
    }
```

**Step 2: 改写 install/status/upgrade 错误输出**

将三处：

```python
"error": str(exc),
```

改为：

```python
"error": _serialize_error(exc),
```

**Step 3: 改写 manager.status 的 remote_error**

在 `opscli/skills/manager.py` 中：

```python
from opscli.skills.exceptions import SkillsError
```

并将：

```python
except Exception as exc:
    remote_error = str(exc)
```

改为：

```python
except Exception as exc:
    if isinstance(exc, SkillsError):
        remote_error = exc.to_dict()
    else:
        remote_error = {
            "type": exc.__class__.__name__,
            "message": str(exc),
        }
```

**Step 4: 跑测试确认结构稳定**

Run:
```bash
pytest tests/skills/test_cli.py tests/skills/test_manager.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add opscli/skills/cli.py opscli/skills/manager.py tests/skills/test_cli.py tests/skills/test_manager.py
git commit -m "refactor: unify skills error payloads"
```

### Task 4: 建立版本单一事实源

**Files:**
- Create: `opscli/version.py`
- Modify: `opscli/cli.py`
- Modify: `AGENTS.md`
- Modify: `docs/spec/开发规范.md`

**Step 1: 新增版本读取模块**

创建 `opscli/version.py`：

```python
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

PACKAGE_NAME = "opscli"
FALLBACK_VERSION = "0.0.4-dev"


def get_version() -> str:
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return FALLBACK_VERSION
```

**Step 2: 顶级 CLI 改为统一走版本模块**

在 `opscli/cli.py` 中把 `_version_callback()` 改为：

```python
from opscli.version import get_version


def _version_callback(value: bool):
    if value:
        typer.echo(f"opscli v{get_version()}")
        raise typer.Exit()
```

**Step 3: 文档当前版本统一**

同步修改：
- `AGENTS.md` 中“当前版本”
- `docs/spec/开发规范.md` 中“文档版本：v2（与 pyproject.toml 版本 ... 对齐）”附近的版本说明

要求：
- 当前版本必须与 `pyproject.toml` 保持一致
- 不再出现 `0.4.0` 与 `0.0.4` 并存

**Step 4: 跑命令人工确认**

Run:
```bash
python -m opscli.cli --version
```

Expected: 输出 `opscli v0.0.4` 或开发态受控版本，不再出现手写漂移值 `0.4.0-dev`。

**Step 5: Commit**

```bash
git add opscli/version.py opscli/cli.py AGENTS.md docs/spec/开发规范.md
git commit -m "chore: centralize opscli version source"
```

### Task 5: 补版本一致性校验

**Files:**
- Create: `tests/test_version_consistency.py`

**Step 1: 新增版本一致性测试**

创建测试：

```python
from pathlib import Path


def test_pyproject_and_fallback_version_are_aligned():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    version_module = Path("opscli/version.py").read_text(encoding="utf-8")

    assert 'version = "0.0.4"' in pyproject
    assert 'FALLBACK_VERSION = "0.0.4-dev"' in version_module
```

如果希望更稳，可后续再改为真正解析 TOML；当前先用轻量测试防止再次漂移。

**Step 2: 全量回归关键测试**

Run:
```bash
pytest tests/skills/test_cli.py tests/skills/test_manager.py tests/skills/test_updater.py tests/test_version_consistency.py -v
```

Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_version_consistency.py
git commit -m "test: add version consistency guard"
```

### Task 6: 收尾与验收

**Files:**
- Modify: `docs/spec/开发规范.md`

**Step 1: 更新附录 D 状态**

在 [docs/spec/开发规范.md](/Users/mask/python3/opscli/docs/spec/开发规范.md) 中，将 D1、D2 标记为：
- 已完成，或
- 已纳入当前迭代并列出落地文件

**Step 2: 汇总验收结果**

Run:
```bash
pytest tests/skills/test_cli.py tests/skills/test_manager.py tests/skills/test_updater.py tests/test_version_consistency.py -v
git diff --stat
```

Expected:
- 所有相关测试通过
- 仅出现预期文件变更

**Step 3: 最终提交**

```bash
git add opscli/skills/exceptions.py opscli/skills/updater.py opscli/skills/cli.py opscli/skills/manager.py opscli/version.py opscli/cli.py AGENTS.md docs/spec/开发规范.md tests/skills/test_cli.py tests/skills/test_manager.py tests/skills/test_updater.py tests/test_version_consistency.py
git commit -m "refactor: tighten skills contract and version governance"
```

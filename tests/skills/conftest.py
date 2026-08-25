"""tests/skills 目录级测试隔离：自动重定向 Skill 版 enum_cache 的磁盘缓存目录。

背景：C3 引入的 enum_cache 模块在权限枚举成功时会把结果写入磁盘（Skill 侧
默认路径 ~/.config/opscli/enum_cache/）。tests/skills 下已有多个测试会
mock subprocess.run 让枚举"成功"返回，若不做隔离，这些既有测试会在不知情
的情况下把 mock 数据真的写进开发者本机的 ~/.config/opscli/enum_cache/
（铁律8 明确禁止测试触碰真实用户目录）。这里用 autouse fixture 把
Skill 版 enum_cache 的缓存目录统一重定向到 pytest 的 tmp_path，对本目录
下所有测试透明生效，不需要逐个既有测试文件显式改造。

本文件内显式请求 enum_cache 缓存隔离的测试（如 test_enum_cache.py 的
skill_cache fixture）仍可按需再次 monkeypatch 覆盖，两者不冲突：autouse
fixture 先生效，显式 fixture 后生效并覆盖，最终以显式 fixture 的路径为准。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = (
    Path(__file__).parents[2]
    / "opscli"
    / "skills"
    / "templates"
    / "ops-dataset-query"
    / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture(autouse=True)
def _isolate_skill_enum_cache(tmp_path, monkeypatch):
    """把 Skill 版 enum_cache 的磁盘缓存目录重定向到本用例的 tmp_path。"""
    import enum_cache as skill_enum_cache

    monkeypatch.setattr(skill_enum_cache, "_cache_dir", lambda: str(tmp_path / "enum_cache"))

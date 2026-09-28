"""tests/skills 目录级 pytest 配置。

历史说明：ops-dataset-query Skill 的本地规划器（query_plan/enum_cache 等脚本）
移除后，本目录不再有任何测试 import 模板 scripts 目录下的模块，因此原先的
sys.path 注入与 Skill 版 enum_cache 缓存目录重定向（autouse fixture）都已失效
并被删除。枚举缓存的隔离改由内核用例通过 `base_dir=tmp_path` 参数完成
（见 tests/query/planner/test_enum_cache.py），符合铁律8。

安装测试隔离用户 Hook 写入，避免验证安装逻辑时修改真实用户配置。
"""

import pytest


@pytest.fixture(autouse=True)
def isolate_install_hook(monkeypatch):
    """安装流程测试只记录 Hook 调用，不修改用户配置。"""
    from unittest.mock import Mock

    hook = Mock()
    monkeypatch.setattr("opscli.skills.hooks.settings_injector.ensure_skill_usage_hook", hook)
    return hook

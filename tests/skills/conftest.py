"""tests/skills 目录级 pytest 配置。

历史说明：ops-dataset-query Skill 的本地规划器（query_plan/enum_cache 等脚本）
移除后，本目录不再有任何测试 import 模板 scripts 目录下的模块，因此原先的
sys.path 注入与 Skill 版 enum_cache 缓存目录重定向（autouse fixture）都已失效
并被删除。枚举缓存的隔离改由内核用例通过 `base_dir=tmp_path` 参数完成
（见 tests/query/planner/test_enum_cache.py），符合铁律8。

本文件保留为空配置，供 pytest 识别目录级 rootdir 语义；后续如需目录级 fixture
再在此追加。
"""

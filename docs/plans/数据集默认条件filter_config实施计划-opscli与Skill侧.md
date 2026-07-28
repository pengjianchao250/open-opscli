# 数据集默认条件（filter_config）opscli 与 Skill 侧实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** opscli query 模块透传 filter_configs（R4），ops-dataset-query 规划器感知默认条件、执行器注入校验、回答强制披露（R5），Skill 版本升至 1.4.0。

**Architecture:** 数据流为「字段 CSV `filter_config` 列 → scoped_dataset_reader 解析 → dataset_guidance 聚合 → query_plan 投影到 execution_ref.default_filters + model_view 中文披露 → run_query precheck 注入去重」。query 模块侧 QueryMetadataResult 增加透传字段。所有任务可用 fixture CSV 先行 TDD，端到端验证依赖服务端计划 Task 3/4 上线 QA。

**Tech Stack:** Python >= 3.10 / pytest / dataclasses

**需求文档:** `docs/design/数据集默认条件filter_config接入需求.md`（已评审定稿）
**姊妹计划:** `docs/plans/数据集默认条件filter_config实施计划-服务端.md`

**工作目录:** `/Users/mask/python3/opscli`（当前分支 master_pjc）

## Global Constraints

- 所有代码注释必须中文，公开方法必须有中文 docstring（铁律17）
- 测试不依赖真实网络与 Keychain：文件用 `tmp_path`，网络用 mock（铁律8）
- 终端输出字符必须 GBK 兼容，禁用 `✓✗✅❌⚠️` 等（铁律23）；Skill 脚本 stdout 输出的中文披露文案同样遵守
- 极简优先：只实现需求要求的功能，不加未请求的配置项（铁律20）；精确变更不美化邻里代码（铁律21）
- Skill 脚本禁止直连后端 API（铁律11）；Skill 文档禁止手写 `userEmail`/`from.table`/`from.permission`（铁律12）
- 每次代码修改后追加变更记录到 `docs/change-log-pending.md`（铁律18）
- 只 `git commit` 本地，**不得 push**
- CSV 新列是**可选列**：`scoped_dataset_reader.FIELD_COLUMNS` 等必需列集合**不得加入新列**（旧 CSV 兼容，验收标准 12）
- 合并语义与服务端一致：required 静默 AND 合并 + 同值/子集去重、optional 用户优先（评审结论 1、2）
- 环境准备：`cd /Users/mask/python3/opscli && source .venv/bin/activate`

---

### Task 1: 【R4】QueryMetadataResult 透传 filter_configs

**Files:**
- Modify: `opscli/query/domain/models.py:8-28`（QueryMetadataResult）
- Modify: `opscli/query/services/manager.py:76-155`（metadata 方法）
- Test: `tests/query/test_manager.py`

**Interfaces:**
- Consumes: 后端 query-metadata 响应中数据集对象的 `filter_configs` 数组（服务端计划 Task 3 产物；本任务用 mock payload 不依赖后端上线）
- Produces: `QueryMetadataResult.filter_configs: list[dict] | None`，`to_dict()` 含 `filter_configs` 键。MCP `query_metadata` 工具与 CLI `opscli query metadata` 自动透出。

**设计决策（对需求文档 R4 条款 2 的简化）**：不做字段 CSV 兜底重建。本地回退读取的 `query_metadata.json` 是远端响应的同源缓存（`updater.apply_upgrade_data` 原样落盘），服务端 R1 上线后该文件自然携带 `filter_configs`，`matched.get("filter_configs")` 远端/本地两条路径通吃。`select_columns` 需要 CSV 兜底是旧缓存缺字段的历史原因，新字段无此包袱（铁律20 极简优先）。Step 6 同步更新需求文档该条款。

- [ ] **Step 1: 编写失败测试**

在 `tests/query/test_manager.py` 中追加（沿用文件内既有 `_setup_metadata_local_fallback` fixture 风格）：

```python
def test_metadata_passes_through_filter_configs(tmp_path, monkeypatch):
    """数据集对象携带的 filter_configs 应透传到 QueryMetadataResult 与 to_dict。"""
    manager = QueryManager()
    filter_configs = [
        {
            "column_name": "date_type",
            "verbose_name": "日期类型",
            "field_type": "dimension",
            "component_dataset_alias": "ds_xxx",
            "filter_config": {
                "type": "required", "enabled": True, "operator": "equals",
                "filter_type": "enum", "enum_value": ["QUARTER"],
                "value": None, "filter_agg": "none",
            },
        }
    ]
    payload = {
        "datasets": [{
            "table_id": 1103, "dataset_alias": "ds_xxx",
            "filter_configs": filter_configs,
        }],
        "fields": [{"table_id": 1103, "field_name": "date_id"}],
    }
    _setup_metadata_local_fallback(manager, tmp_path, monkeypatch, payload)

    result = manager.metadata(dataset_alias="ds_xxx")

    assert result.filter_configs == filter_configs
    assert result.to_dict()["filter_configs"] == filter_configs


def test_metadata_filter_configs_absent_for_legacy_payload(tmp_path, monkeypatch):
    """旧缓存无 filter_configs 字段时返回空列表，不报错（兼容验收标准 12）。"""
    manager = QueryManager()
    payload = {
        "datasets": [{"table_id": 1103, "dataset_alias": "ds_xxx"}],
        "fields": [],
    }
    _setup_metadata_local_fallback(manager, tmp_path, monkeypatch, payload)

    result = manager.metadata(dataset_alias="ds_xxx")

    assert result.filter_configs == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/query/test_manager.py -k filter_configs -v`
Expected: FAIL —— `QueryMetadataResult.__init__() got an unexpected keyword argument 'filter_configs'` 或 AttributeError

- [ ] **Step 3: 实现 models.py 改动**

`QueryMetadataResult` 增加字段与 to_dict 输出：

```python
@dataclass
class QueryMetadataResult:
    """query metadata 查询结果。"""

    dataset: dict
    fields: list[dict]
    source: str
    all_datasets: list[dict] | None = None
    select_columns: list[dict] | None = None
    # 数据集默认条件（服务端按"自身+组件字段"聚合下发，见需求文档 R1）
    filter_configs: list[dict] | None = None

    def to_dict(self) -> dict:
        result: dict = {
            "dataset": self.dataset,
            "fields": self.fields,
            "source": self.source,
        }
        if self.all_datasets is not None:
            result["all_datasets"] = self.all_datasets
        if self.select_columns is not None:
            result["select_columns"] = self.select_columns
        if self.filter_configs is not None:
            result["filter_configs"] = self.filter_configs
        return result
```

- [ ] **Step 4: 实现 manager.py 改动**

`metadata()` 中 select_columns 提取块之后、`return QueryMetadataResult(...)` 之前插入，并把新字段传入构造：

```python
        # 提取数据集默认条件：远端响应与本地 query_metadata.json（远端同源缓存）
        # 均在 dataset 对象内嵌 filter_configs，旧缓存缺该字段时回退空列表
        filter_configs = list(matched.get("filter_configs") or [])

        return QueryMetadataResult(
            dataset=matched,
            fields=matched_fields,
            source=source,
            select_columns=select_columns,
            filter_configs=filter_configs,
        )
```

- [ ] **Step 5: 运行测试确认通过 + query 模块回归**

Run: `pytest tests/query/ -v`
Expected: 新增 2 tests PASS，既有测试无回归

- [ ] **Step 6: 更新需求文档 R4 条款并记录变更**

把 `docs/design/数据集默认条件filter_config接入需求.md` 4.4 节第 2 条改为："本地回退路径：`query_metadata.json` 为远端同源缓存，服务端上线后自然携带 `filter_configs`，`matched.get("filter_configs")` 统一提取，旧缓存缺字段时回退空列表（不做字段 CSV 兜底重建）"。追加变更记录到 `docs/change-log-pending.md`（铁律18 模板）。

- [ ] **Step 7: 提交**

```bash
cd /Users/mask/python3/opscli
git add opscli/query/domain/models.py opscli/query/services/manager.py tests/query/test_manager.py docs/change-log-pending.md "docs/design/数据集默认条件filter_config接入需求.md"
git commit -m "feat(query): QueryMetadataResult 透传数据集默认条件 filter_configs（R4）"
```

---

### Task 2: 【R5a】scoped_dataset_reader 解析 filter_config 可选列

**Files:**
- Modify: `opscli/skills/templates/ops-dataset-query/scripts/scoped_dataset_reader.py`
- Test: `tests/skills/test_scoped_reader_filter_config.py`（新建）

**Interfaces:**
- Consumes: 字段 CSV 新列 `filter_config`（JSON 字符串，服务端计划 Task 4 产物）；datasets.csv 摘要列 `filter_config_count` / `filter_config_names`
- Produces:
  - `parse_filter_config(raw: str) -> dict | None`（模块级函数）：空/缺失返回 None，`enabled` 非真返回 None，非法 JSON 抛 `ValueError("invalid_filter_config")`
  - `load_dataset_fields()` 返回行新增键 `row["filter_config"]: dict | None`
  - `load_datasets()` 返回行透传摘要列（DictReader 自带，无需代码；仅规范化 `filter_config_count` 缺失时为 "0"）

- [ ] **Step 1: 确认测试导入方式**

Run: `head -30 /Users/mask/python3/opscli/tests/skills/test_dataset_query_planner.py`
记录其导入 scripts 模块的方式（sys.path 注入或 conftest fixture），新测试文件沿用同一方式。

- [ ] **Step 2: 编写失败测试**

```python
"""scoped_dataset_reader 对字段 CSV filter_config 可选列的解析测试。"""
import json

import pytest

# 导入方式与 test_dataset_query_planner.py 保持一致（Step 1 确认后调整此行）
import scoped_dataset_reader


FIELDS_HEADER = (
    "dataset_alias,dataset_name,field_name,verbose_name,field_type,"
    "summary_expression,detail_expression,snapshot_metric,has_formula_config,filter_config"
)
ENABLED_FC = json.dumps({
    "type": "required", "enabled": True, "operator": "equals",
    "filter_type": "enum", "enum_value": ["QUARTER"], "value": None, "filter_agg": "none",
})


def _write_fields_csv(data_dir, rows):
    data_dir.mkdir(parents=True, exist_ok=True)
    lines = [FIELDS_HEADER] + rows
    (data_dir / "dataset_fields.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # 若 _source_content 的快照一致性校验要求三个源文件齐全，
    # 此处同时写入最小 datasets.csv / dataset_select_columns.csv（列头照抄 SOURCE 常量）


def test_parse_filter_config_enabled():
    result = scoped_dataset_reader.parse_filter_config(ENABLED_FC)
    assert result["type"] == "required"
    assert result["enum_value"] == ["QUARTER"]


def test_parse_filter_config_empty_and_disabled():
    assert scoped_dataset_reader.parse_filter_config("") is None
    assert scoped_dataset_reader.parse_filter_config(
        json.dumps({"enabled": False, "operator": "equals"})
    ) is None


def test_parse_filter_config_invalid_json_raises():
    with pytest.raises(ValueError, match="invalid_filter_config"):
        scoped_dataset_reader.parse_filter_config("{not json")


def test_load_dataset_fields_attaches_filter_config(tmp_path):
    """带 filter_config 列的字段 CSV：启用行解析为 dict，空行为 None。"""
    fc_cell = '"' + ENABLED_FC.replace('"', '""') + '"'  # CSV 内嵌 JSON 转义
    _write_fields_csv(tmp_path, [
        f"ds_a,主数据集,date_type,日期类型,dimension,,,0,0,{fc_cell}",
        "ds_a,主数据集,gmv,GMV,metric,,,0,0,",
    ])
    rows = scoped_dataset_reader.load_dataset_fields(tmp_path, "ds_a")
    assert rows[0]["filter_config"]["type"] == "required"
    assert rows[1]["filter_config"] is None


def test_load_dataset_fields_without_column_is_compatible(tmp_path):
    """旧版 CSV 无 filter_config 列：所有行为 None，不报错（验收标准 12）。"""
    header = FIELDS_HEADER.rsplit(",", 1)[0]  # 去掉最后一列
    (tmp_path / "dataset_fields.csv").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "dataset_fields.csv").write_text(
        header + "\n" + "ds_a,主数据集,date_id,日期,dimension,,,0,0\n",
        encoding="utf-8",
    )
    rows = scoped_dataset_reader.load_dataset_fields(tmp_path, "ds_a")
    assert rows[0]["filter_config"] is None
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/skills/test_scoped_reader_filter_config.py -v`
Expected: FAIL —— `AttributeError: module 'scoped_dataset_reader' has no attribute 'parse_filter_config'`

- [ ] **Step 4: 实现 scoped_dataset_reader 改动**

模块级新增函数（放在 SOURCE_FILES 常量区之后），并在 `load_dataset_fields` 的行校验循环末尾追加一行挂载。**FIELD_COLUMNS 必需列集合保持不动**：

```python
def parse_filter_config(raw: str | None) -> dict | None:
    """解析字段 CSV filter_config 列（可选列，旧数据无此列）。

    空值/缺列返回 None；enabled 非真视为未配置返回 None；
    非法 JSON 抛 ValueError（与本模块 fail-fast 校验哲学一致，
    坏数据应在升级链路暴露而非静默吞掉）。
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        config = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_filter_config") from exc
    if not isinstance(config, dict) or not config.get("enabled"):
        return None
    return config
```

文件头 `import csv` 处补 `import json`。`load_dataset_fields` 行循环（`row["snapshot_metric"] = snapshot_flag or "0"` 之后）追加：

```python
        # 字段级默认条件（可选列）：服务端 1.4.0+ 下发，旧 CSV 无此列时为 None
        row["filter_config"] = parse_filter_config(row.get("filter_config"))
```

- [ ] **Step 5: 运行测试确认通过 + skills 回归**

Run: `pytest tests/skills/ tests/query/ -v`
Expected: 新增 5 tests PASS，既有规划器/updater 测试无回归（旧 fixture CSV 无新列 → 全部 None 路径）

- [ ] **Step 6: 变更记录 + 提交**

追加 `docs/change-log-pending.md` 记录后：

```bash
git add opscli/skills/templates/ops-dataset-query/scripts/scoped_dataset_reader.py tests/skills/test_scoped_reader_filter_config.py docs/change-log-pending.md
git commit -m "feat(skills): scoped_dataset_reader 解析字段 CSV filter_config 可选列（R5）"
```

---

### Task 3: 【R5b】dataset_guidance 聚合 default_filters

**Files:**
- Modify: `opscli/skills/templates/ops-dataset-query/scripts/dataset_guidance.py`
- Test: `tests/skills/test_dataset_guidance_default_filters.py`（新建，fixture 沿用 Task 2 的 CSV 写法）

**Interfaces:**
- Consumes: Task 2 的 `row["filter_config"]`（fields 行）；select_columns 行（组件关联）
- Produces: `build_guidance()` 返回体顶层新增键 `"default_filters"`，元素结构：

```python
{
    "field_name": str,            # 字段技术名
    "verbose_name": str,          # 中文名
    "field_type": str,            # dimension | metric
    "source_dataset_alias": str,  # 自身字段 = 本数据集 alias；组件字段 = 组件 alias
    "filter_config": dict,        # 规范化配置原样携带
}
```

Task 4（query_plan 投影）依赖该键。

- [ ] **Step 1: 编写失败测试**

```python
"""dataset_guidance 默认条件聚合测试。"""
# 导入方式与 test_dataset_query_planner.py 一致
import dataset_guidance

# fixture：写 datasets.csv / dataset_fields.csv（含 filter_config 列）/ dataset_select_columns.csv
# 结构参照 test_dataset_query_planner.py 的 _write_ready_metadata，主数据集 ds_a 的
# date_type 字段配置 required 默认条件；组件数据集 ds_comp 的 platform_name 配置 required；
# ds_a 通过 select_columns 关联 platform_name → ds_comp


def test_build_guidance_collects_default_filters(tmp_path):
    data_dir = _write_metadata_with_filter_config(tmp_path)  # 本文件内实现 fixture
    result = dataset_guidance.build_guidance(
        data_dir, {"dataset_alias": "ds_a"}, query="按日期看GMV"
    )
    defaults = result["default_filters"]
    by_name = {item["field_name"]: item for item in defaults}
    # 自身字段
    assert by_name["date_type"]["source_dataset_alias"] == "ds_a"
    assert by_name["date_type"]["filter_config"]["enum_value"] == ["QUARTER"]
    # 组件关联字段
    assert by_name["platform_name"]["source_dataset_alias"] == "ds_comp"


def test_build_guidance_default_filters_empty_when_unconfigured(tmp_path):
    data_dir = _write_metadata_without_filter_config(tmp_path)
    result = dataset_guidance.build_guidance(
        data_dir, {"dataset_alias": "ds_a"}, query="按日期看GMV"
    )
    assert result["default_filters"] == []
```

fixture 函数 `_write_metadata_with_filter_config` / `_write_metadata_without_filter_config` 在测试文件内实现：复制 `test_dataset_query_planner.py` 的 `_write_ready_metadata` CSV 内容，字段 CSV 增加 `filter_config` 列（Task 2 的 `FIELDS_HEADER` 与转义写法）。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/skills/test_dataset_guidance_default_filters.py -v`
Expected: FAIL —— KeyError: 'default_filters'

- [ ] **Step 3: 实现聚合函数并接入 build_guidance**

`dataset_guidance.py` 新增模块级函数（放在 `_permission_scope` 之后）：

```python
def _default_filters(
    dataset_alias: str,
    fields: list[dict],
    select_columns: list[dict],
) -> list[dict]:
    """聚合数据集的默认条件（需求 R5）。

    范围 = 自身字段 + select_columns 关联的组件数据集字段中
    filter_config 已启用的条目。来源与服务端 query-metadata 的
    filter_configs 聚合口径一致（自身字段 source 取本数据集 alias）。
    """
    entries: list[dict] = []

    def _entry(row: dict, source_alias: str) -> dict:
        return {
            "field_name": row["field_name"],
            "verbose_name": row.get("verbose_name", ""),
            "field_type": row.get("field_type", "dimension"),
            "source_dataset_alias": source_alias,
            "filter_config": row["filter_config"],
        }

    # 自身字段
    for row in fields:
        if row.get("dataset_alias") == dataset_alias and row.get("filter_config"):
            entries.append(_entry(row, dataset_alias))
    # 组件关联字段：按 (component_dataset_alias, column_name) 回查全量字段表
    field_index = {
        (row.get("dataset_alias"), row.get("field_name")): row
        for row in fields
        if row.get("filter_config")
    }
    for relation in select_columns:
        if relation["current_dataset_alias"] != dataset_alias:
            continue
        row = field_index.get(
            (relation["component_dataset_alias"], relation["column_name"])
        )
        if row is not None:
            entries.append(_entry(row, relation["component_dataset_alias"]))
    return entries
```

`build_guidance` 的 `result` 字典中（`"permission_scope"` 键之后）加入：

```python
        "default_filters": _default_filters(dataset_alias, fields, select_columns),
```

注意：`_load_target_metadata` 返回的 `fields` 若只含目标数据集字段（按 alias 过滤），组件字段查不到——先 `grep -n "_load_target_metadata" dataset_guidance.py` 核对；若是过滤后的，改为传入 `load_dataset_fields(data_dir)` 全量加载的结果给 `_default_filters`（只在该函数内用，不改其他消费方）。

- [ ] **Step 4: 运行测试确认通过 + 输出体积校验**

Run: `pytest tests/skills/ -v`
Expected: 全部 PASS。若 `_validate_output_size` 因新增键超限报错，把 `default_filters` 中 `filter_config` 压缩为仅保留 `type/operator/filter_type/enum_value/value/filter_agg` 六键（丢弃 enabled）。

- [ ] **Step 5: 变更记录 + 提交**

```bash
git add opscli/skills/templates/ops-dataset-query/scripts/dataset_guidance.py tests/skills/test_dataset_guidance_default_filters.py docs/change-log-pending.md
git commit -m "feat(skills): dataset_guidance 聚合数据集默认条件 default_filters（R5）"
```

---

### Task 4: 【R5c】query_plan 投影 —— execution_ref.default_filters + model_view 中文披露

**Files:**
- Modify: `opscli/skills/templates/ops-dataset-query/scripts/query_plan.py`（build_model_contract 约 1124-1170 行区域）
- Test: `tests/skills/test_dataset_query_planner.py`（追加用例）

**Interfaces:**
- Consumes: Task 3 的 `guidance["default_filters"]`
- Produces:
  - `execution_ref["default_filters"]`: `[{"field_name","label_zh","operator","values","type","filter_type","filter_agg"}]`（Task 5 的 run_query `--default-filters` 参数值即此数组的 JSON）
  - `model_view["default_filters_zh"]`: `list[str]`，如 `["日期类型 等于 QUARTER（强制）"]`
  - `answer_contract.required_disclosures_zh` 追加默认条件披露项
  - `execution_ref["query_template"]` 的 filters 预填 required 默认条件

- [ ] **Step 1: 编写失败测试**

在 `tests/skills/test_dataset_query_planner.py` 追加（fixture `_write_ready_metadata` 的字段 CSV 增加 filter_config 列，未配置行留空——先确认该改动不破坏既有用例，空列全走 None 路径）：

```python
def test_query_plan_projects_default_filters(tmp_path: Path):
    """配置了 filter_config 的数据集：规划结果必须携带默认条件与中文披露。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata_with_filter_config(data_dir)  # 新 fixture：ds_ads 的 date_type 配 required QUARTER

    result = query_plan.build_model_query_plan(
        "SP 广告数据集 ACOS",
        data_dir=data_dir,
        rules_path=RULES_PATH,
    )

    assert result["status"] == "planned"
    defaults = result["execution_ref"]["default_filters"]
    assert defaults[0]["field_name"] == "date_type"
    assert defaults[0]["operator"] == "equals"
    assert defaults[0]["values"] == ["QUARTER"]
    assert defaults[0]["type"] == "required"
    # 用户可见层中文披露
    assert any("QUARTER" in text for text in result["model_view"]["default_filters_zh"])
    # 回答合同强制披露
    assert any("默认条件" in text for text in result["answer_contract"]["required_disclosures_zh"])


def test_query_plan_no_default_filters_key_when_unconfigured(tmp_path: Path):
    """未配置默认条件：execution_ref 不带 default_filters 键，行为与现状一致。"""
    data_dir = tmp_path / "data"
    _write_ready_metadata(data_dir)

    result = query_plan.build_model_query_plan(
        "SP 广告数据集 ACOS", data_dir=data_dir, rules_path=RULES_PATH,
    )
    assert "default_filters" not in result["execution_ref"]
    assert "default_filters_zh" not in result["model_view"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/skills/test_dataset_query_planner.py -k default_filters -v`
Expected: FAIL —— KeyError: 'default_filters'

- [ ] **Step 3: 实现投影**

`query_plan.py` 新增模块级辅助函数（与 `_filter_components` 相邻）：

```python
# filter_config 操作符 → 中文描述（披露文案用，与后台配置表单 label 一致）
_FILTER_OPERATOR_ZH = {
    "equals": "等于", "notEquals": "不等于", "gt": "大于", "gte": "大于等于",
    "lt": "小于", "lte": "小于等于", "isEmpty": "为空", "isNotEmpty": "不为空",
}


def _default_filters_ref(guidance: dict) -> list[dict]:
    """把 guidance.default_filters 投影为执行引用形态（模型直接填充查询用）。"""
    refs = []
    for item in guidance.get("default_filters") or []:
        config = item.get("filter_config") or {}
        values = config.get("enum_value") or []
        if not values and config.get("value") not in (None, ""):
            raw = config["value"]
            values = raw if isinstance(raw, list) else [raw]
        refs.append({
            "field_name": item["field_name"],
            "label_zh": item.get("verbose_name", ""),
            "operator": config.get("operator", "equals"),
            "values": values,
            "type": config.get("type", "required"),
            "filter_type": config.get("filter_type", "enum"),
            "filter_agg": config.get("filter_agg", "none"),
        })
    return refs


def _default_filters_zh(refs: list[dict]) -> list[str]:
    """默认条件的用户可见中文描述（回答披露用）。"""
    lines = []
    for ref in refs:
        op_zh = _FILTER_OPERATOR_ZH.get(ref["operator"], ref["operator"])
        value_text = "、".join(str(v) for v in ref["values"]) or "-"
        type_zh = "强制" if ref["type"] == "required" else "可选"
        lines.append(f"{ref['label_zh'] or ref['field_name']} {op_zh} {value_text}（{type_zh}）")
    return lines
```

在 `build_model_contract` 的 execution_ref 组装区（`filter_components` 赋值之后）插入：

```python
    default_filters = _default_filters_ref(guidance)
    if default_filters:
        execution_ref["default_filters"] = default_filters
        model_view["default_filters_zh"] = _default_filters_zh(default_filters)
        answer_contract["required_disclosures_zh"].append(
            "本次查询已自动应用数据集默认条件：" + "；".join(model_view["default_filters_zh"])
        )
```

注意两点（实现时核对实际代码）：① `guidance` 变量在该作用域的取得方式——与 `_filter_components(guidance)` 同源；② `answer_contract` 组装位置若在 execution_ref 之后，把追加语句移到其组装之后。

query_template 预填：在 `_build_query_template(...)` 调用处，模板生成后把 required 默认条件并入模板 filters（多值→操作符 in）：

```python
        if template is not None and default_filters:
            # filter_config 操作符 → 简化查询操作符（与 run_query 的映射保持一致）
            op_map = {"equals": "=", "notEquals": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
            template_filters = template.get("filters") or []
            for ref in default_filters:
                if ref["type"] != "required" or ref["filter_agg"] != "none":
                    continue  # optional 由模型按用户语境决定；having 度量条件服务端兜底
                op = op_map.get(ref["operator"])
                if op is None or not ref["values"]:
                    continue  # isEmpty/isNotEmpty 等暂不支持的操作符跳过，服务端兜底
                if len(ref["values"]) > 1 and ref["operator"] == "equals":
                    template_filters.append({"field": ref["field_name"], "operator": "in", "value": ref["values"]})
                else:
                    template_filters.append({"field": ref["field_name"], "operator": op, "value": ref["values"][0]})
            template["filters"] = template_filters
```

- [ ] **Step 4: 运行测试确认通过 + 规划器全量回归**

Run: `pytest tests/skills/test_dataset_query_planner.py -v`
Expected: 新增 2 tests PASS，既有规划器用例全部 PASS

- [ ] **Step 5: 变更记录 + 提交**

```bash
git add opscli/skills/templates/ops-dataset-query/scripts/query_plan.py tests/skills/test_dataset_query_planner.py docs/change-log-pending.md
git commit -m "feat(skills): 规划器投影默认条件到 execution_ref 并强制中文披露（R5）"
```

---

### Task 5: 【R5d】run_query precheck 注入与披露

**Files:**
- Modify: `opscli/skills/templates/ops-dataset-query/scripts/run_query.py`
- Test: `tests/skills/test_run_query_default_filters.py`（新建）

**Interfaces:**
- Consumes: Task 4 的 `execution_ref["default_filters"]`（模型经 `--default-filters` 参数传入其 JSON）
- Produces:
  - CLI 参数 `--default-filters '<JSON数组>'`（可选）
  - `_apply_default_filters(payload: dict, defaults: list[dict]) -> list[str]`：注入缺失的 required 条件（同值/子集去重、多值→in、不拦截冲突），返回中文披露行
  - stdout 披露新增键 `disclosures["default_filters_zh"]`

- [ ] **Step 1: 编写失败测试**

```python
"""run_query 默认条件注入测试。"""
# 导入方式与 test_dataset_query_planner.py 一致
import run_query


REQUIRED_DEFAULT = {
    "field_name": "date_type", "label_zh": "日期类型", "operator": "equals",
    "values": ["QUARTER"], "type": "required", "filter_type": "enum", "filter_agg": "none",
}


def test_apply_injects_missing_required():
    payload = {"filters": [{"field": "date_id", "operator": ">=", "value": "2026-07-01"}]}
    notes = run_query._apply_default_filters(payload, [REQUIRED_DEFAULT])
    injected = [f for f in payload["filters"] if f["field"] == "date_type"]
    assert injected == [{"field": "date_type", "operator": "=", "value": "QUARTER"}]
    assert any("QUARTER" in note for note in notes)


def test_apply_dedupes_same_or_subset_value():
    payload = {"filters": [{"field": "date_type", "operator": "=", "value": "QUARTER"}]}
    run_query._apply_default_filters(payload, [REQUIRED_DEFAULT])
    assert len([f for f in payload["filters"] if f["field"] == "date_type"]) == 1


def test_apply_keeps_both_on_conflict():
    """冲突不拦截：与服务端静默 AND 合并行为一致，披露中说明（评审结论 1）。"""
    payload = {"filters": [{"field": "date_type", "operator": "=", "value": "MONTH"}]}
    notes = run_query._apply_default_filters(payload, [REQUIRED_DEFAULT])
    assert len([f for f in payload["filters"] if f["field"] == "date_type"]) == 2
    assert any("同时生效" in note for note in notes)


def test_apply_multi_values_uses_in_and_optional_skipped():
    multi = dict(REQUIRED_DEFAULT, values=["QUARTER", "MONTH"])
    payload = {"filters": []}
    run_query._apply_default_filters(payload, [multi])
    assert payload["filters"][0]["operator"] == "in"

    optional = dict(REQUIRED_DEFAULT, type="optional")
    payload2 = {"filters": [{"field": "date_type", "operator": "=", "value": "MONTH"}]}
    run_query._apply_default_filters(payload2, [optional])
    assert len(payload2["filters"]) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/skills/test_run_query_default_filters.py -v`
Expected: FAIL —— AttributeError: no attribute '_apply_default_filters'

- [ ] **Step 3: 实现注入函数与参数接线**

`run_query.py` 新增函数（放在 `_precheck` 之后）：

```python
# filter_config 操作符 → 简化查询操作符（与规划器 query_template 预填映射一致）
_DEFAULT_FILTER_OP_MAP = {
    "equals": "=", "notEquals": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=",
}


def _apply_default_filters(payload: dict, defaults: list[dict]) -> list[str]:
    """把规划器下发的数据集默认条件注入 payload（需求 R5）。

    语义与服务端保持一致（评审结论 1/2）：required 缺失即注入、
    同值/子集去重、冲突不拦截静默 AND 合并但必须披露"同时生效"；
    optional 用户已有同字段条件则跳过；filter_agg != none 的度量
    条件服务端 having 兜底，本地不注入。返回中文披露行列表。
    """
    notes: list[str] = []
    filters = payload.setdefault("filters", [])
    for default in defaults or []:
        if default.get("filter_agg", "none") != "none":
            continue
        op = _DEFAULT_FILTER_OP_MAP.get(default.get("operator", "equals"))
        if op is None:
            continue  # isEmpty/isNotEmpty 等暂不支持的操作符：服务端兜底，本地不注入
        field = default["field_name"]
        values = default.get("values") or []
        if not values:
            continue
        user_conditions = [f for f in filters if isinstance(f, dict)
                           and str(f.get("field", "")).split(".")[-1] == field]
        label = default.get("label_zh") or field
        value_text = "、".join(str(v) for v in values)

        if default.get("type") == "optional":
            if user_conditions:
                continue
        elif user_conditions:
            # required + 用户同字段：同值/子集去重，否则 AND 合并披露双条件生效
            covered = any(
                set(c["value"] if isinstance(c.get("value"), list) else [c.get("value")]) <= set(values)
                for c in user_conditions
            )
            if covered:
                notes.append(f"默认条件 {label}={value_text} 与你的条件一致，已去重")
                continue
            notes.append(
                f"[!] 数据集强制默认条件 {label}={value_text} 与你的条件同时生效（AND），结果可能为空"
            )
        condition = (
            {"field": field, "operator": "in", "value": values}
            if len(values) > 1 and default.get("operator", "equals") == "equals"
            else {"field": field, "operator": op, "value": values[0]}
        )
        filters.append(condition)
        if not user_conditions:
            notes.append(f"已自动应用数据集默认条件：{label} = {value_text}（{default.get('type', 'required')}）")
    return notes
```

`_parse_args` 增加参数：

```python
    parser.add_argument(
        "--default-filters",
        default="",
        help="规划器 execution_ref.default_filters 的 JSON 数组，执行前自动注入缺失的 required 默认条件",
    )
```

`main()` 中 `_precheck(payload)` 之前插入：

```python
        default_filters = json.loads(args.default_filters) if args.default_filters.strip() else []
        default_notes = _apply_default_filters(payload, default_filters)
```

`disclosures` 组装处追加：

```python
        if default_notes:
            disclosures["default_filters_zh"] = default_notes
```

注意披露文案 GBK 兼容：用 `[!]` 不用 `⚠️`（铁律23）。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/skills/ -v`
Expected: 新增 4 tests PASS，无回归

- [ ] **Step 5: 变更记录 + 提交**

```bash
git add opscli/skills/templates/ops-dataset-query/scripts/run_query.py tests/skills/test_run_query_default_filters.py docs/change-log-pending.md
git commit -m "feat(skills): run_query 执行前注入 required 默认条件并强制披露（R5）"
```

---

### Task 6: 【R5e】Skill 文档更新 + 版本 1.4.0

**Files:**
- Modify: `opscli/skills/templates/ops-dataset-query/SKILL.md`（"确认与执行"章节）
- Modify: `opscli/skills/templates/ops-dataset-query/references/rules.md`（"禁止发明默认筛选"条款）
- Modify: `opscli/skills/templates/ops-dataset-query/references/simple-query-guide.md`（新章节）
- Modify: `opscli/skills/templates/ops-dataset-query/QUERY_SPEC.md`（MCP 契约）
- Modify: `opscli/skills/templates/ops-dataset-query/data/VERSION.json`（1.3.5 → 1.4.0）

**Interfaces:**
- Consumes: Task 4/5 的字段名（`default_filters` / `default_filters_zh` / `--default-filters`）
- Produces: 模型侧使用契约文档

- [ ] **Step 1: SKILL.md 执行章节追加**

在"确认与执行"小节（CLI 执行器命令行之后）插入：

```markdown
- 默认条件（filter_configs）：规划结果 model_view.default_filters_zh 存在时，
  必须在回答中向用户披露这些默认条件；执行时把 execution_ref.default_filters
  原样作为 --default-filters 参数传给执行器：
  python3 scripts/run_query.py --table-id "$TABLE_ID" --json "$QUERY_JSON" --default-filters "$DEFAULT_FILTERS_JSON"
  强制（required）条件不可移除；用户条件与其冲突时两者同时生效（AND），须提示结果可能为空。
```

- [ ] **Step 2: rules.md 例外条款**

在"禁止发明默认筛选"条款后追加：

```markdown
【例外】来自服务端元数据 filter_configs 的默认条件不属于"发明"：它是数据集口径
的一部分，必须应用且必须在回答中披露（default_filters_zh 原文转述）。
除此之外仍然禁止凭推断添加任何筛选。
```

- [ ] **Step 3: simple-query-guide.md 新章节**

文末追加：

```markdown
## 默认条件（filter_configs）的自动应用与覆盖

数据集可由管理员配置字段级默认条件，服务端在查询执行时强制应用：

| 配置 type | 未提供该字段条件 | 提供了该字段条件 |
|-----------|-----------------|-----------------|
| required（强制） | 服务端自动注入 | 与你的条件 AND 合并（同值/子集自动去重），不可移除 |
| optional（可选） | 服务端自动注入 | 以你的条件为准 |

- 客户端行为：执行器 run_query.py 会按 --default-filters 预注入 required 条件，
  与服务端行为对齐，保证披露与实际执行一致；
- 多枚举值默认条件按 in 语义生效；日期预设（如 thisQuarter）由服务端在执行时刻解析；
- 回答中必须披露已生效的默认条件（规划器 default_filters_zh 原文）。
```

- [ ] **Step 4: QUERY_SPEC.md 契约补充**

在响应契约小节追加一行说明：`query_metadata 返回的数据集对象含 filter_configs 数组（字段级默认条件，required 类型服务端强制应用）；query_simple 结果口径已含默认条件`。

- [ ] **Step 5: VERSION.json 升级**

```json
{"name":"ops-dataset-query","version":"1.4.0","data_state":"placeholder"}
```

注意保留现有 `data_state` 键值原样（若当前文件为发布包形状无此键则不添加）。

- [ ] **Step 6: 验证 + 提交**

Run: `pytest tests/skills/ -v && python3 -c "import json; print(json.load(open('opscli/skills/templates/ops-dataset-query/data/VERSION.json'))['version'])"`
Expected: 测试全 PASS；输出 `1.4.0`

```bash
git add opscli/skills/templates/ops-dataset-query/ docs/change-log-pending.md
git commit -m "docs(skills): ops-dataset-query 默认条件使用契约 + 版本 1.4.0（R5）"
```

---

### Task 7: 全量回归 + 端到端验收（依赖服务端上线 QA）

**Files:** 无新代码；验收记录追加需求文档或联调记录

**Interfaces:**
- Consumes: 全部前置任务 + 服务端计划 Task 3/4 已发布 QA
- Produces: 需求文档验收标准 6-11 的 Skill/opscli 侧验证记录

- [ ] **Step 1: 全量回归**

Run: `cd /Users/mask/python3/opscli && source .venv/bin/activate && pytest tests/ -v`
Expected: 全部 PASS（含 auth/query/skills 全模块）

- [ ] **Step 2: 真实升级链路验证（验收标准 10）**

```bash
opscli skills upgrade ops-dataset-query --force
head -1 ~/.claude/skills/ops-dataset-query/data/dataset_fields.csv   # 应含 filter_config 列
head -1 ~/.claude/skills/ops-dataset-query/data/datasets.csv          # 应含 filter_config_count 列
python3 ~/.claude/skills/ops-dataset-query/scripts/query_plan.py "已配置默认条件数据集的一个真实查询"
```
Expected: 规划输出含 `default_filters` 与 `default_filters_zh`（验收标准 6）

- [ ] **Step 3: 端到端执行验证（验收标准 7）**

按规划器输出执行 run_query 带 `--default-filters`，确认 stdout `disclosures.default_filters_zh` 存在且查询结果与后台配置口径一致。

- [ ] **Step 4: 记录验收结果并收尾**

验收结果逐条记录；追加 `docs/change-log-pending.md` 收尾条目；确认 `git status` 无未提交改动。

---

## 依赖与排期说明

- Task 1 独立可先行；Task 2 → 3 → 4 → 5 顺序依赖；Task 6 依赖 4/5 定名；Task 7 依赖全部 + 服务端 QA 上线。
- Task 1-6 全部用 fixture/mock 驱动，**不依赖服务端进度**，可与服务端计划并行开发。
- 发布顺序：服务端先发 QA → opscli 发版（含 Skill 模板 1.4.0）→ `opscli skills upgrade` 分发 → Task 7 端到端验收。

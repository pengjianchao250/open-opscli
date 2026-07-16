# 待归档变更记录

## 2026-07-16 auth/storage - macOS 禁用 Keychain 改纯 AES 加密文件，消除频繁密码弹窗

**变更原因**：macOS 钥匙串按应用二进制签名授权，而 uv/pyenv/Homebrew 安装的 Python 均为 ad-hoc 签名（`Identifier=-`、无 TeamIdentifier），无法形成稳定授权；叠加 keyring 25.7.0 的 `set_generic_password` 实现为"先删除再重建"条目（每次 JWT 刷新都重置授权 ACL），导致多解释器环境下用户频繁遭遇"Python 想访问钥匙串"密码弹窗。Windows 凭据管理器按用户会话授权无此问题。纯文件方案威胁模型与 Windows 现状等价（按用户隔离，不按应用隔离），且所存凭证均为短生命周期（session 有过期时间、JWT TTL ≤ 24h）。
**改动点**：
1. `opscli/auth/storage/credential_store.py`：`CredentialStore.__init__` 新增 `_keyring_available` 字段并使 `_use_keyring` 在 `sys.platform == "darwin"` 时恒为 False（macOS 纯走 AES-256-GCM 加密文件，Windows/Linux 不变）；`_save()` 文件写入改为 pid 后缀临时文件 + `os.replace` 原子替换（防多进程并发写坏）；`clear()` 改用 `_keyring_available` 判断，保证 macOS 上仍能清理历史遗留钥匙串条目；同步更新模块/类 docstring。
2. `tests/mcp/test_credential_cache.py`：`test_credential_cache_default_base_dir` 补三处 monkeypatch（CONFIG_DIR 之外新增强制 `_KEYRING_AVAILABLE=False` 和清空 `_mcp_credential_caches` 缓存池）。该测试此前在 macOS 上实际写入开发者真实钥匙串（违反铁律8），旧行为下"通过"纯属写读恰好都走全局钥匙串的巧合。
**验证结果**：`pytest tests/auth/ tests/mcp/ tests/query/` 失败清单与改动前基线完全一致（16 个存量失败，0 新增，comm 对比确认）；模块导入/读写冒烟通过；`opscli auth token status` 正常（因历史超时降级已在文件留有凭证副本，本机无需重新登录）。
**影响范围**：仅 macOS 用户凭证存储路径；钥匙串中无文件副本的存量用户需重新 `opscli auth login` 一次；Windows/Linux 行为不变；钥匙串遗留条目在 logout 时仍会被清理。
**回滚方式**：`git revert` 本次对 `credential_store.py` 与 `test_credential_cache.py` 的提交即可，无数据迁移需回退。
---

## 2026-07-15 skills/run_query - 默认条件改为只披露不预注入，服务端权威注入

**变更原因**：`_apply_default_filters` 原先会把默认条件预注入进 `payload["filters"]` 再发送给服务端。对日期预设值（如 `beforeYesterday`/`thisQuarter`），客户端注入的是字面量字符串，服务端收到后同时注入自己解析后的真实日期，两者 AND 合并导致字面量永不匹配日期列，致使配置了日期默认条件的数据集经 Skill 查询恒返回 0 行（QA 实证）。服务端是默认条件注入的唯一权威方（评审结论 5），客户端预注入是冗余且有害的。
**改动点**：
1. `opscli/skills/templates/ops-dataset-query/scripts/run_query.py`：`_apply_default_filters` 重写为只读 `payload["filters"]`（不再写入），移除所有 `filters.append(...)` / `payload.setdefault("filters", [])` 的写入操作；保留并完善中文披露 notes 生成（required 缺失/同值/冲突/optional/having 均有对应文案）；日期预设值原样展示并注明"服务端解析为执行日"；更新 docstring 与 main() 调用处注释说明服务端权威注入语义。
2. `tests/skills/test_run_query_default_filters.py`：所有断言从"payload 被注入"翻转为"payload 不变 + 正确披露"；测试函数重命名以反映新语义（`test_apply_injects_*` → `test_apply_discloses_*` 等）。
**验证结果**：`pytest tests/skills/test_run_query_default_filters.py -v` 全部 6 tests PASSED；回归 `pytest tests/skills/ tests/query/ --ignore=tests/skills/test_packaging.py -v` 共 208 tests，无新增失败，6 个预存失败均为模板漂移与本次修改无关。
**影响范围**：`_apply_default_filters` 函数行为根本改变——不再 mutate payload，由服务端统一注入默认条件；披露输出（disclosures["default_filters_zh"]）保持不变；main() 调用接线不变。
**回滚方式**：将 `run_query.py` 中 `_apply_default_filters` 恢复为含 `filters.append(...)` 的旧版本，将测试文件中所有断言改回"payload 被注入"形式。

---

## 2026-07-15 skills/run_query - 去重判定限定等值操作符族，防 required 被同值异操作符绕过

**变更原因**：`_apply_default_filters` 中的 `covered` 判定只比较值集合，未检查操作符——当用户传 `date_type != QUARTER` 时，required 默认条件（`= QUARTER`）被错误判定为"已覆盖"而静默丢弃，击穿 required 不可绕过的语义保证。服务端已完成同源修复（去重仅限等值操作符族），opscli 侧需对齐。
**改动点**：
1. `opscli/skills/templates/ops-dataset-query/scripts/run_query.py`：`_apply_default_filters` 的 `covered` 判定新增操作符感知——仅当用户条件的 operator 属于等值族（`=`/`==`/`in`）且值集合为默认值子集时才判定为已覆盖；异操作符（如 `!=`/`>`）属冲突场景，走 AND 合并并披露"同时生效"。
2. `tests/skills/test_run_query_default_filters.py`：新增 `test_apply_not_deduped_on_operator_mismatch` 测试，覆盖同值异操作符（`!=`）不去重的终审修复场景。
**验证结果**：`pytest tests/skills/test_run_query_default_filters.py -v` 全部 6 tests PASSED（含新增测试）；回归 `pytest tests/skills/ tests/query/ --ignore=tests/skills/test_packaging.py -v` 共 208 tests，无新增失败，6 个预存失败均为模板版本漂移与本次修改无关。
**影响范围**：仅影响 `_apply_default_filters` 中的 `covered` 分支逻辑；用户 operator 为等值族时行为不变（去重仍生效）；用户 operator 为非等值族时改为 AND 合并并披露，修复前的静默丢弃行为被消除。
**回滚方式**：将 `run_query.py` 中 `covered = any(...)` 恢复为不含 `equality_ops` 判断的原始版本，删除 `test_apply_not_deduped_on_operator_mismatch` 测试，删除本条变更记录。

---

## 2026-07-15 skills/query_plan - 移除 query_template 默认条件预填，改由服务端权威注入

**变更原因**：`build_model_contract` 中的默认条件投影段落将 required 默认条件（包含日期预设字面量如 `beforeYesterday`/`QUARTER`）预填进 `execution_ref["query_template"]["filters"]`。客户端预填的字面量与服务端在查询执行时解析后的真实日期 AND 合并，导致配置了日期默认条件的数据集查询恒返回 0 行。服务端是默认条件注入的唯一权威方，客户端预填是冗余且有害的。
**改动点**：
1. `opscli/skills/templates/ops-dataset-query/scripts/query_plan.py`：删除 1225-1241 行的 `query_template` 默认条件预填 if 块（含 `op_map`、`template_filters` 循环、`template["filters"] = template_filters`）；保留 `execution_ref["default_filters"]`、`model_view["default_filters_zh"]`、`answer_contract` 披露追加（仅披露，不注入）；在 `query_template_fill_rules_zh` 文案末尾追加说明"默认条件由服务端自动应用，请勿手动加入 filters；仅需在回答中向用户披露 default_filters_zh"。
2. `tests/skills/test_dataset_query_planner.py`：`test_query_plan_projects_default_filters` 中原断言 `query_template.filters` 含 `date_type=QUARTER` 翻转为反向断言：`template_filters` 不含 `date_type` 值为 `QUARTER` 的默认条件（注：date_type 作为时间维度的日期范围 >=/<= 过滤仍合法保留）；保留 `default_filters`/`default_filters_zh`/`answer_contract` 披露断言。
**验证结果**：`pytest tests/skills/test_dataset_query_planner.py -v` 全部 26 tests PASSED；回归 `pytest tests/skills/ tests/query/ --ignore=tests/skills/test_packaging.py -v` 无新增失败（6 个预存失败与本次修改无关）。
**影响范围**：`query_plan.py` `build_model_contract` 函数：query_template.filters 不再含默认条件；`default_filters`/`default_filters_zh`/`answer_contract` 披露路径不变；服务端执行时仍自动注入默认条件，查询结果不受影响。
**回滚方式**：在 `query_plan.py` 的默认条件投影段重新插入 `op_map`+`template_filters` 预填 if 块，将测试断言改回"template_filters 含 date_type=QUARTER"形式，删除本条变更记录。

---

## 2026-07-15 skills/dataset_guidance - 聚合数据集默认条件 default_filters（R5）

**变更原因**：需求 R5 要求 `build_guidance()` 返回体顶层包含 `default_filters` 键，聚合"自身字段 + select_columns 关联组件字段"中 filter_config 已启用的条目，供 Task 4（query_plan 投影）消费。
**改动点**：
1. `opscli/skills/templates/ops-dataset-query/scripts/dataset_guidance.py`：
   - `_load_target_metadata()` 返回值新增第 6 项 `snapshot`，供调用方复用快照（不额外读盘）。
   - 新增模块级函数 `_default_filters(dataset_alias, fields, select_columns)`，分两路聚合：自身字段（dataset_alias 匹配 + filter_config 非 None）；组件关联字段（按 select_columns 回查全量字段索引）；filter_config 只保留六键（type/operator/filter_type/enum_value/value/filter_agg）防止体积超限。
   - `build_guidance()` 中拆包新增 `snapshot`；用同一快照加载全量字段 `all_fields`（不带 alias 参数）；在 `result` 字典 `permission_scope` 之后追加 `"default_filters": _default_filters(dataset_alias, all_fields, select_columns)`。
2. 新建 `tests/skills/test_dataset_guidance_default_filters.py`（2 个测试）。
**验证结果**：RED 阶段 `pytest tests/skills/test_dataset_guidance_default_filters.py -v` 2 tests FAILED（KeyError: 'default_filters'）；GREEN 阶段实现后同命令 2 tests PASSED；回归 `pytest tests/skills/ tests/query/ --ignore=tests/skills/test_packaging.py -v` 共 200 tests，新增 2 PASSED，6 FAILED 均为预先存在的失败，无新增回归。
**影响范围**：影响 `dataset_guidance.build_guidance()` 返回结构（新增 `default_filters` 列表键）；`_load_target_metadata` 返回元组长度从 5 变为 6（仅模块内部使用，无外部消费方）；不改 `_permission_scope` 等邻里函数。
**回滚方式**：回退 `opscli/skills/templates/ops-dataset-query/scripts/dataset_guidance.py` 中的 `_default_filters` 函数定义、`_load_target_metadata` snapshot 返回、`build_guidance` 中 all_fields 加载与 default_filters 键追加；删除 `tests/skills/test_dataset_guidance_default_filters.py` 和本条变更记录。

---

## 2026-07-15 skills/scoped_dataset_reader - 解析字段 CSV filter_config 可选列（R5）

**变更原因**：服务端计划在字段 CSV（dataset_fields.csv）行尾新增可选列 `filter_config`（JSON 字符串），记录字段级默认查询条件；需要在统一数据读取层解析该列，旧版 CSV 无此列时必须完全兼容（返回 None 不报错）。
**改动点**：`opscli/skills/templates/ops-dataset-query/scripts/scoped_dataset_reader.py`：在文件头补 `import json`；在 SOURCE_FILES 常量区之后新增模块级函数 `parse_filter_config(raw: str | None) -> dict | None`（空/缺失返回 None，enabled 非真返回 None，非法 JSON 抛 ValueError）；在 `load_dataset_fields` 行循环末尾追加 `row["filter_config"] = parse_filter_config(row.get("filter_config"))` 一行；`FIELD_COLUMNS` 必需列 frozenset 保持不动（filter_config 是可选列）。新建 `tests/skills/test_scoped_reader_filter_config.py`（5 个测试）。
**验证结果**：RED 阶段 `pytest tests/skills/test_scoped_reader_filter_config.py -v` 按预期 5 tests FAILED（AttributeError/KeyError/TypeError）；GREEN 阶段实现后同命令 5 tests PASSED；回归 `pytest tests/skills/ tests/query/ --ignore=tests/skills/test_packaging.py -v` 共 198 tests，新增 5 PASSED，6 FAILED 均为预先存在的失败（版本不匹配/模板缺失/依赖文件缺失），无回归。
**影响范围**：仅影响 `load_dataset_fields()` 返回行结构（新增 `filter_config` 键，值为 dict 或 None）；旧版 CSV 无该列时全部行返回 None，完全向后兼容；上层消费方（scoped_metadata_index、dataset_guidance）Task 3 起才开始读取该键。
**回滚方式**：回退 `opscli/skills/templates/ops-dataset-query/scripts/scoped_dataset_reader.py` 中的 `import json`、`parse_filter_config` 函数定义、行循环追加行，删除 `tests/skills/test_scoped_reader_filter_config.py` 和本条变更记录。

---

## 2026-07-15 query - QueryMetadataResult 透传数据集默认条件 filter_configs（R4）

**变更原因**：数据集默认条件（filter_config）从后台配置逐级下发到查询执行，opscli query 模块需要透传后端 query-metadata 接口返回的 `filter_configs`，支持远端直接获取和本地缓存回退，为上层 MCP 工具与 Skill 规划器提供元数据。
**改动点**：`opscli/query/domain/models.py` 的 `QueryMetadataResult` 新增 `filter_configs: list[dict] | None` 字段和 `to_dict()` 对应输出；`opscli/query/services/manager.py` 的 `metadata()` 方法在 `select_columns` 提取后增加 `filter_configs` 提取逻辑，从 `matched.get("filter_configs")` 统一读取（远端响应和本地 query_metadata.json 缓存均在 dataset 对象内嵌 filter_configs，旧缓存缺该字段时回退空列表）。
**验证结果**：RED 阶段运行 `pytest tests/query/test_manager.py -k filter_configs -v` 按预期失败于 `QueryMetadataResult` 缺少 `filter_configs` 属性（2 tests FAILED）；GREEN 阶段实现改动后同命令通过（2 tests PASSED）；聚焦回归 `pytest tests/query/ -v` 全量通过（71 tests PASSED，覆盖新增 2 个测试和既有 69 个测试无回归）。
**影响范围**：影响 `opscli query metadata` CLI 命令和 MCP `query_metadata` 工具的返回结构（新增可选字段），MCP 客户端自动在结果中透出 `filter_configs`；不修改 `opscli query build/build_simple` 参数结构（默认条件由服务端强制应用）。
**回滚方式**：回退 `opscli/query/domain/models.py`、`opscli/query/services/manager.py`、`tests/query/test_manager.py` 中新增的两个测试用例、`docs/design/数据集默认条件filter_config接入需求.md` 的 4.4 节第 2 条更新和本条变更记录。

---

## 2026-07-15 skills/run_query - 执行前注入 required 默认条件并强制披露（R5 Task5）

**变更原因**：需求 R5 Task 5 要求 `run_query.py` 在执行前将规划器下发的数据集默认条件（`execution_ref["default_filters"]`）注入 payload，required 缺失时自动补全，同值/子集去重，冲突不拦截但强制披露"同时生效"，optional 有用户条件时跳过；注入结果通过 `disclosures["default_filters_zh"]` 输出到 stdout。
**改动点**：
1. `opscli/skills/templates/ops-dataset-query/scripts/run_query.py`：
   - 在 `_precheck` 之前新增模块级常量 `_DEFAULT_FILTER_OP_MAP`（filter_config 原生操作符 → 简化查询操作符映射）和函数 `_apply_default_filters(payload, defaults)`（注入逻辑主体，返回中文披露行列表）。
   - `_parse_args` 新增 `--default-filters` 参数（默认空字符串，接收规划器 JSON 数组）。
   - `main()` 在 `_precheck(payload)` 之前插入 JSON 解析与注入调用（`default_filters = json.loads(...); default_notes = _apply_default_filters(...)`）。
   - `disclosures` 组装处追加：`if default_notes: disclosures["default_filters_zh"] = default_notes`。
   - 所有新增输出使用 GBK 安全字符，警示用 `[!]` 替代 `⚠️`（铁律23）。
2. 新建 `tests/skills/test_run_query_default_filters.py`（4 个测试）。
**验证结果**：RED 阶段 `pytest tests/skills/test_run_query_default_filters.py -v` 4 tests FAILED（AttributeError: module 'run_query' has no attribute '_apply_default_filters'）；GREEN 阶段实现后同命令 4 tests PASSED；回归 `pytest tests/skills/ tests/query/ --ignore=tests/skills/test_packaging.py -v` 共 206 tests，新增 4 PASSED，6 FAILED 均为预先存在的模板版本漂移/依赖缺失失败，无新增回归。
**影响范围**：影响 `run_query.py` 的 CLI 接口（新增可选 `--default-filters` 参数）和 stdout 结构（有注入时新增 `disclosures.default_filters_zh` 键）；`_precheck` 本身未被修改；不影响现有测试和其他模块。
**回滚方式**：删除 `_DEFAULT_FILTER_OP_MAP` 常量和 `_apply_default_filters` 函数，移除 `_parse_args` 中的 `--default-filters` 参数、`main()` 中的注入调用和 disclosures 追加；删除 `tests/skills/test_run_query_default_filters.py` 和本条变更记录。

---

## 2026-07-15 skills/query_plan - 投影默认条件到 execution_ref 并强制中文披露（R5 Task4）

**变更原因**：需求 R5 Task 4 要求规划器 `build_model_contract` 把 `guidance["default_filters"]` 投影到三处输出：`execution_ref["default_filters"]`（执行引用，供 Task 5 run_query 消费）、`model_view["default_filters_zh"]`（用户可见中文披露）、`answer_contract["required_disclosures_zh"]`（回答强制披露），并在 `query_template` 预填 required 默认条件。
**改动点**：
1. `opscli/skills/templates/ops-dataset-query/scripts/query_plan.py`：
   - 在 `_filter_components` 之后新增模块级常量 `_FILTER_OPERATOR_ZH`（操作符 → 中文映射）、函数 `_default_filters_ref(guidance)`（投影执行引用形态）、函数 `_default_filters_zh(refs)`（生成中文披露文案）。
   - 在 `build_model_contract` 的查询模板骨架之后插入默认条件投影逻辑：调用 `_default_filters_ref(guidance)` 获取条目列表；若非空则写入 `execution_ref["default_filters"]`、`model_view["default_filters_zh"]`、预填 required 条件到模板 filters。
   - 将 `_answer_contract()` 调用提前到 return 前赋变量 `answer_contract`，再对其 `required_disclosures_zh` 追加默认条件披露项。
2. `tests/skills/test_dataset_query_planner.py`：新增 fixture `_write_ready_metadata_with_filter_config`（ds_ads date_type 字段配置 required QUARTER 默认条件）；新增测试 `test_query_plan_projects_default_filters`（正向：三处投影 + template 预填）和 `test_query_plan_no_default_filters_key_when_unconfigured`（负向：无配置时键不存在）。
**验证结果**：RED 阶段运行 `pytest tests/skills/test_dataset_query_planner.py -k default_filters -v`，`test_query_plan_projects_default_filters` FAILED（KeyError: 'default_filters'），`test_query_plan_no_default_filters_key_when_unconfigured` PASSED；GREEN 阶段实现后两个测试均 PASSED；全量回归 `pytest tests/skills/ tests/query/ --ignore=tests/skills/test_packaging.py -v` 196 passed，6 FAILED 均为预先存在的模板版本漂移/依赖缺失失败，无新增回归（比基线多 2 PASSED）。
**影响范围**：影响 `build_model_contract` 输出结构（当数据集有 filter_config 配置时新增 3 个键）；未配置的数据集输出与现状完全一致；不修改其他投影逻辑和字段。
**回滚方式**：回退 `opscli/skills/templates/ops-dataset-query/scripts/query_plan.py` 中新增的三个辅助定义及 `build_model_contract` 中新增的投影块和 answer_contract 变量化，删除测试文件中新增的 fixture 和两个测试函数，删除本条变更记录。

---

## 2026-07-15 skills/ops-dataset-query - Skill 文档更新 + 版本升级 1.4.0（R5 Task6）

**变更原因**：R5 默认条件（filter_configs）接入完成 Task 1-5 后，需要更新 Skill 文档以描述新接口契约（model_view.default_filters_zh、execution_ref.default_filters、--default-filters 参数），并将版本升级至 1.4.0 作为本次 R5 发布的前置。
**改动点**：
1. `opscli/skills/templates/ops-dataset-query/SKILL.md`："构造与执行"小节第 5 条 CLI 执行器命令行之后，插入默认条件（filter_configs）披露与 --default-filters 参数说明。
2. `opscli/skills/templates/ops-dataset-query/references/rules.md`：文末追加"禁止发明默认筛选"小节并补充例外条款（来自 filter_configs 的默认条件不属于"发明"，必须应用且披露）。
3. `opscli/skills/templates/ops-dataset-query/references/simple-query-guide.md`：文末追加"默认条件（filter_configs）的自动应用与覆盖"新章节（表格 + 客户端行为说明）。
4. `opscli/skills/templates/ops-dataset-query/QUERY_SPEC.md`：第 4 节（正式 query_simple）末尾追加 filter_configs 响应契约说明。
5. `opscli/skills/templates/ops-dataset-query/data/VERSION.json`：version 从 1.3.5 升级至 1.4.0，其余键（name、data_state）保持原样。
**验证结果**：`python3 -c "import json; print(json.load(open('opscli/skills/templates/ops-dataset-query/data/VERSION.json'))['version'])"` 输出 1.4.0；`pytest tests/skills/ tests/query/ -v --ignore=tests/skills/test_packaging.py` 201 passed，6 FAILED 均为预先存在的失败（test_install_dataset_fields_template、test_install_ops_amazon_template 等），无新增回归。
**影响范围**：仅 Skill 文档和 VERSION.json，无生产代码变更；安装此版本 Skill 的 AI Agent 将获得默认条件相关使用契约指引。
**回滚方式**：回退上述 5 个文件至修改前内容，删除本条变更记录。

---

## 2026-07-14 asin-data - Polaris 鉴权回退与用户手册

**变更原因**：ASIN 刊登实时取数在个人 Polaris JWT 和直接 exchange 均失败时缺少 BJX Token 自动兜底，同时 CLI/MCP 的公开命令、返回协议和 Polaris 开关说明尚未形成独立完整手册。
**改动点**：默认 `user` 模式按当前用户 Polaris JWT、直接 `/api/auth/cli-token` exchange、OPS `/dataMetrics/v1/asin-report-files/polaris-bjx-token` 的顺序获取刊登鉴权，前一路成功即停止；三路均失败时返回 `POLARIS_USER_AUTH_MISSING`，错误只保留异常类型、业务码或 HTTP 状态，不包含 Token、Cookie、Session ID、账号、密码或远端敏感正文。显式 `managed`、`bi_login` 模式保持原语义。新增 `docs/guide/ASIN取数CLI命令手册.md` 和 `docs/guide/ASIN取数MCP工具手册.md`，完整说明 `live-data`、`fetch-file`、yicopy、类目 Top 的参数、成功/失败协议、Polaris 开关和恢复流程；类目 Top 补充 AI 顺序调用规范：先从实时 `listing_basic` 的 `类目` 字段按英文逗号取最后一个非空最小类目，再调用 Top10，空类目不得猜测；新增文档契约测试。
**验证结果**：TDD 阶段新增 5 个鉴权测试，其中 4 个在实现前按预期失败；实现后 `tests/asin_data/test_bi_report_data.py` 结果为 `25 passed`，文档契约测试结果为 `3 passed`。运行全部 `tests/asin_data`、MCP ASIN 工具和限流测试，结果为 `112 passed`；执行 `python -m compileall -q opscli/asin_data opscli/mcp/tools/asin_data.py`、`git diff --check` 和手册敏感信息扫描均通过。
**影响范围**：影响 `live-data --data-scope basic/listing/listing_basic/all`、MCP `asin_data_live_data` 和 `asin_data_category_top` 的刊登鉴权回退；个人 Polaris 可用时权限不变，BI-only、历史文件、yicopy、卖家精灵和 Rufus 取数逻辑不变。
**回滚方式**：回退 `bi_report_data.py` 的 BJX 回退分支、对应鉴权测试、两份用户手册、文档契约测试、设计与实施计划及本条变更记录。

---

## 2026-07-14 asin-data - crawler-details 多站点取数

**变更原因**：`crawler-details` 接口新增 `country` 参数，现有 ASIN live-data、MCP 和类目 Top10 链路需要统一支持默认 US、指定站点及批量多站点分组请求。
**改动点**：`AsinBiReportDataClient` 为 `crawler_details` 增加按标准化站点分组的专用请求逻辑，每次请求携带 `country`，未提供站点时默认 `US`；不同站点并行获取并按站点首次出现顺序合并 `rows`，部分失败保留成功数据并返回 `country_errors`。CLI、MCP 和类目 Top10 继续复用现有 `site/site_by_asin` 参数，补充公开参数说明和站点透传回归测试；新增设计与实施计划文档。
**验证结果**：先运行 `tests/asin_data/test_bi_report_data.py -k "crawler or fetches_all_sources" -q` 验证旧实现出现 4 个预期失败，完成实现后同命令 `4 passed`；运行 `tests/asin_data/test_bi_report_data.py tests/asin_data/test_category_top.py tests/asin_data/test_asin_data_cli.py tests/mcp/test_asin_data_tools.py -q` 通过，结果 `54 passed`；执行 `python -m py_compile` 检查 `bi_report_data.py`、`cli.py` 和 MCP `asin_data.py` 通过。
**影响范围**：影响 `live-data --data-scope basic/all`、MCP `asin_data_live_data` 和 `asin_data_category_top` 中的爬虫详情请求；不改变公开参数、`crawler_details.rows` 数据结构、刊登数据、其他 BI 数据源、卖家精灵或 Rufus。
**回滚方式**：回退 `bi_report_data.py` 的 crawler country 分组方法、CLI/MCP 参数说明、相关测试以及设计和实施计划文档。

---

## 2026-07-14 asin-data/mcp - 同步 ASIN 取数服务到 release

**变更原因**：需要将 `codex/asin-data-service-merge` 中已经整理完成的 ASIN 取数 CLI/MCP 能力同步到 `release`，并保留 Top10/category-top 取数修复和默认当前用户北极星鉴权策略，便于后续 release 部署使用。
**改动点**：同步 `opscli asin-data live-data/fetch-file/category-top/yicopy-keyword-engine` 相关服务、AI Ready 返回、xlsx/OSS 上传、MCP `asin_data_live_data`/`asin_data_fetch_file`/`asin_data_category_top`/`asin_data_yicopy_keyword_engine` 工具、ASIN MCP 限流与 health 工具；刊登取数默认使用当前用户 Polaris token，兼容 `OPSCLI_ASIN_DATA_LISTING_AUTH_MODE=managed/bi_login`；修复 token URL 拼接，避免系统 URL 和 endpoint 同时带斜杠时出现双斜杠；补充 ASIN、MCP、文件上传、auth 配置等测试。
**验证结果**：执行 `D:\workspace\open-opscli\.venv\Scripts\python.exe -m pytest tests\auth\test_config.py tests\auth\test_token_manager.py tests\asin_data\test_ai_response.py tests\asin_data\test_asin_data_cli.py tests\asin_data\test_bi_report_data.py tests\asin_data\test_category_top.py tests\asin_data\test_category_top_workbook.py tests\asin_data\test_daily_pipeline.py tests\asin_data\test_direct_runner.py tests\asin_data\test_report_files.py tests\asin_data\test_single_asin_collect.py tests\asin_data\test_split_package_builder.py tests\asin_data\test_yicopy_keyword_engine.py tests\mcp\test_asin_data_limit.py tests\mcp\test_asin_data_tools.py tests\mcp\test_health_tool.py tests\shared\test_file_uploads.py -q` 通过，结果 `122 passed`；执行 `D:\workspace\open-opscli\.venv\Scripts\python.exe -m py_compile opscli\auth\config.py opscli\auth\core\token_manager.py opscli\asin_data\cli.py opscli\asin_data\services\bi_report_data.py opscli\asin_data\services\collector.py opscli\asin_data\services\daily_pipeline.py opscli\asin_data\services\split_package_builder.py opscli\asin_data\services\category_top.py opscli\asin_data\services\category_top_workbook.py opscli\asin_data\services\yicopy_keyword_engine.py opscli\mcp\asin_data_limit.py opscli\mcp\tools\asin_data.py opscli\mcp\tools\health.py opscli\shared\file_uploads.py` 通过。
**影响范围**：影响 ASIN 取数 CLI、ASIN MCP 工具、ASIN 取数 Skill 模板、文件上传客户端和 Polaris 鉴权配置；不包含 seller_sprite、sif、scrape_do、shopify 等非 ASIN 改动。
**回滚方式**：回退本次提交中 ASIN/MCP/文件上传/Skill 模板/测试文件以及本条 changelog 即可。
---

## 2026-07-10 ASIN 取数 - release 合入刊登授权回退

**变更原因**：用户要求将 ASIN 取数服务中“默认走托管北极星 token，刊登接口未登录时再用固定 BI 账号登录回退”的修改合并回 release 并推送，避免部署到 MCP 后继续优先使用本地 BI_AUTH/BI_COOKIE 或旧 token。
**改动点**：`opscli/asin_data/services/bi_report_data.py` 移除 `BI_AUTH` / `BI_COOKIE` 对刊登基础数据鉴权的优先级，新增默认 BI 登录账号常量和“未登陆/未登录”识别，在托管 token 被刊登接口判定失效时强制使用默认账号登录后重试；新增 `tests/asin_data/test_bi_report_data.py` 覆盖托管 token 优先和未登录回退登录两条路径。
**验证结果**：已设置 `PYTHONPATH=当前工作区` 后运行 `python -m pytest tests/asin_data/test_bi_report_data.py -q`，结果 2 passed；已运行 `python -m compileall opscli/asin_data/services/bi_report_data.py opscli/mcp/tools/asin_data.py` 通过；已运行 `python -c "import importlib; importlib.import_module('opscli.mcp.server')"` 通过（导入时存在既有工具重复注册 warning，但退出码为 0）；已运行 `git diff --check` 通过。
**影响范围**：影响 `asin-data live-data --data-scope basic/listing_basic` 及 MCP ASIN 基础刊登取数的授权选择；BI 数据、卖家精灵、Rufus 和非刊登数据源不受影响。
**回滚方式**：回退 `opscli/asin_data/services/bi_report_data.py`、`tests/asin_data/test_bi_report_data.py` 和本条变更记录即可。

---

## 2026-06-29 Amazon Rufus - watch-login 页面生命周期诊断

**变更原因**：用户反馈 `amazon-rufus watch-login` 打开浏览器后保留 Amazon 页面，但另一个页签会反复打开并关闭。静态代码无法直接确认该页签来源，需要增加可控诊断日志，并避免页面关闭时透出裸 Playwright 异常。

**改动点**：`opscli/amazon_rufus/services/browser.py` 新增 `OPS_RUFUS_DEBUG_PAGES=1` 控制的 page 创建、导航、关闭诊断输出，按 `existing`、`external`、`ops-login`、`ops-product` 标记页签来源，并对诊断 URL 仅保留 scheme、host、path；`_wait_page_or_sleep()` 将 Playwright 页面关闭类错误转换为 `SeedRequestNotCapturedError`；`tests/amazon_rufus/test_core.py` 新增页面生命周期、URL query 脱敏和关闭异常包装回归测试。

**验证结果**：RED 阶段新增用例在旧实现下失败：`./.venv/Scripts/python.exe -m pytest "tests/amazon_rufus/test_core.py" -k "debug_pages or wraps_closed_page_wait_error" -q`，结果 3 failed；GREEN 后同命令通过，3 passed；运行 `./.venv/Scripts/python.exe -m pytest "tests/amazon_rufus/test_core.py" -k "watch_login or debug_pages or closed" -q` 通过，7 passed；运行 `./.venv/Scripts/python.exe -m pytest "tests/amazon_rufus/test_core.py" -q` 通过，90 passed；运行 `./.venv/Scripts/python.exe -m py_compile "opscli/amazon_rufus/services/browser.py"` 通过。

**影响范围**：仅影响 Rufus `watch_login_and_capture_seed_request()` 的可选诊断输出和页面关闭错误口径；默认未设置 `OPS_RUFUS_DEBUG_PAGES` 时不输出诊断日志，不改变 MCP schema、CLI 参数、登录页打开次数、商品页打开次数或 headless 后端获取链路。

**回滚方式**：回退 `opscli/amazon_rufus/services/browser.py`、`tests/amazon_rufus/test_core.py` 中本次页面生命周期诊断和关闭异常包装相关改动，并删除本条变更记录。

---

## 2026-06-22 Amazon Rufus - watch_login 单次触发与 DevTools 参数修复

**变更原因**：亚马逊 Rufus 登录态失效时，同一次 Skill 调用内多个错误分支都可能再次触发 `watch_login`，导致浏览器反复打开登录页或商品页；同时 Chrome 启动参数会自动打开 DevTools 页签，增加额外页面干扰。

**改动点**：移除 `opscli/amazon_rufus/services/browser.py` 中的 `--auto-open-devtools-for-tabs`；更新 `.agents/skills/ops-amazon-rufus` 与 `opscli/skills/templates/ops-amazon-rufus` 的 `SKILL.md`、`README.md`、`references/rufus-mcp-workflow.md`，新增 `watch_login_attempted` 约束，要求 MCP/CLI 登录采集在同一次 Skill 调用内最多触发一次；同步新增 `.super-dev/changes/amazon-rufus-watch-login-once` 与 `output/amazon-rufus-skill-*` 产物；补充 `tests/amazon_rufus/test_core.py` 和 `tests/skills/test_ops_amazon_rufus_updater.py` 回归测试。

**验证结果**：已先运行新增测试并确认旧实现失败于 DevTools 参数仍存在、Skill 文档缺少 `watch_login_attempted`；修复后运行 `uv run pytest "tests/amazon_rufus/test_core.py" -q`，结果 86 passed；运行 `uv run pytest "tests/skills/test_ops_amazon_rufus_updater.py" -q`，结果 10 passed；运行 `uv run python -m py_compile "opscli/amazon_rufus/services/browser.py"` 通过；运行 pretty-mermaid 渲染命令重新生成 `output/amazon-rufus-skill-flow.svg` 成功。

**影响范围**：影响 Rufus 自动启动调试浏览器的参数、Agent/Skill 登录采集编排、内置模板、已安装项目版 Skill、Super Dev 设计产物和文档契约测试；不改变 MCP Tool schema、远程授权偏好、CLI fallback 白名单、Rufus 后端请求逻辑或敏感字段隐藏规则。

**回滚方式**：回退 `browser.py` 启动参数修改、上述 Skill 文档与 Super Dev 产物中的 `watch_login_attempted` 规则，以及新增/调整的回归测试和本变更记录。

---

## 2026-06-11 Amazon Rufus Skill - README 补充三条整体调用链

**变更原因**：用户纠正应保存最初讨论的 Rufus 整体调用链，而不是只记录 OPS 平台 Cookie `content` 读取局部链路；README 中需要按三条链路说明 Skill、MCP 和 CLI 的调用关系。
**改动点**：将 Rufus Skill 模板 README 中的局部 `content` 读取小节替换为“整体调用链（三条）”，分别描述 Skill 编排链、MCP 后端获取链、CLI fallback 链，并在 MCP 后端获取链中保留 `content` 裸 cURL 读取、旧 JSON record 兼容和旧 `curl_data` / 仅 `storage_state` 失效规则。
**验证结果**：已运行 `uv run pytest tests/skills/test_ops_amazon_rufus_updater.py tests/skills/test_cli.py -q`，结果 20 passed。
**影响范围**：仅影响 `opscli/skills/templates/ops-amazon-rufus/README.md` 文档说明和本变更记录，不改变代码行为、MCP schema、CLI 参数或后端 API 契约。
**回滚方式**：删除 README 中新增的“整体调用链（三条）”小节，并移除此变更记录。

---

## 2026-06-22 ops-amazon-rufus Skill - 增加回答质量重试规则

**变更原因**：Rufus 获取成功后可能出现无回答、拒答、答非所问，或用户询问评价/风险/适配性等复杂问题但回答退化为商品详情的情况；原 Skill 缺少问题改写和有限重试规则。

**改动点**：更新 `.agents/skills/ops-amazon-rufus` 与 `opscli/skills/templates/ops-amazon-rufus` 的 `SKILL.md`、`README.md`、`references/rufus-mcp-workflow.md`，新增 `answer_rewrite_attempts_by_question`、回答质量判断、子 agent 固定提示词、同一个 Rufus 对话处理多问题、每个问题最多 10 次的问题改写重试规则；新增 `.super-dev/changes/amazon-rufus-answer-retry` 和 `output/amazon-rufus-skill-*` 文档与流程图；补充 `tests/skills/test_ops_amazon_rufus_updater.py` 文档契约测试。

**验证结果**：新增测试先失败于缺少“回答质量判断”规则；补充文档后 `uv run pytest "tests/skills/test_ops_amazon_rufus_updater.py" -q` 为 9 passed。补充运行 `uv run pytest "tests/amazon_rufus" -q` 时发现既有失败：`test_get_platform_cookie_sends_platform_query` 期望 timeout 为 10，当前实际为 180；该失败与本次 Skill 文档变更无关，未在本次处理。

**影响范围**：影响 `ops-amazon-rufus` Agent 编排规则、内置模板、已安装项目版 Skill、Super Dev 设计产物和文档契约测试；不改变 Rufus MCP 工具参数、Python 后端获取逻辑、登录恢复、远程授权偏好、CLI fallback 白名单或敏感字段隐藏规则。

**回滚方式**：回退上述 Skill 文档、Super Dev change、`output/amazon-rufus-skill-*` 产物和 `tests/skills/test_ops_amazon_rufus_updater.py` 中新增的回答质量重试断言。

**补充修正**：根据用户确认，将回答质量重试上限改为按问题独立计算，并明确 Rufus 获取会在同一个 Rufus 对话中处理多个问题；已同步项目版、模板版、Super Dev 文档和流程图。

---

## 2026-06-11 Amazon Rufus - 平台 Cookie content 直接保存 streaming cURL

**变更原因**：用户确认从浏览器获取亚马逊 Rufus 登录态时，保存到后端 `/v1/platform-cookies` 的 `content` 应该直接是 `/rufus/cl/streaming` 浏览器 cURL 命令态，而不是包含 `storage_state`、`curl` 和请求种子摘要的 JSON 包装。
**改动点**：`RufusBrowserStateStore.save()` 在远端平台 Cookie client 存在且已捕获 streaming seed 时，直接把构造出的 cURL 命令态写入 `content`；`_load_remote()` 支持裸 cURL content，并继续兼容旧 JSON record；`RufusBackendSecretProvider` 可从裸 cURL 的 payload 中恢复内部 `SeedRequestRecord`，避免默认 `get_backend` 因缺少 JSON 摘要重新 headless 捕获；同步更新 Rufus Skill 模板、`.agents` 副本、MCP/CLI 帮助文案和测试。
**验证结果**：已先用更新后的目标用例验证旧实现失败于 `content` 仍为 JSON 包装和裸 cURL 读取无效；实现后运行 `uv run pytest tests/amazon_rufus/test_core.py -q`，结果 85 passed；运行 `uv run pytest tests/amazon_rufus/test_transport.py tests/amazon_rufus/test_mcp_manager.py tests/mcp/test_amazon_rufus_tools.py tests/skills/test_ops_amazon_rufus_updater.py tests/skills/test_cli.py -q`，结果 60 passed；文档同步后补跑 `uv run pytest tests/amazon_rufus/test_core.py tests/skills/test_ops_amazon_rufus_updater.py tests/skills/test_cli.py -q`，结果 105 passed。
**影响范围**：影响 Rufus `watch_login`、`save_curl` 等默认远端保存链路以及 `login_status` / `get_backend` 读取远端 content 的行为；后端 API path 和 POST 字段仍保持 `platform`、`country`、`content` 三字段；本地 fallback `browser-state-<COUNTRY>.json` 仍保留内部 JSON record。
**回滚方式**：回退 `opscli/amazon_rufus/services/browser_state_store.py`、`backend_secret.py`、`commands/cli.py`、`opscli/mcp/tools/amazon_rufus.py`、Rufus Skill 文档和相关测试中关于裸 cURL content 的修改，恢复远端 content JSON record 保存方式。

---

## 2026-06-11 Amazon Rufus Skill - 登录态术语改为亚马逊 Rufus 登录态

**变更原因**：用户要求 Rufus Skill 中关于亚马逊登录态的描述统一改为“亚马逊 Rufus 登录态”，避免把实际保存为浏览器 cURL 命令态的状态误描述为普通 Cookie；后端接口名仍保留平台 Cookie 命名。
**改动点**：更新 `opscli/skills/templates/ops-amazon-rufus/` 与 `.agents/skills/ops-amazon-rufus/` 的 `SKILL.md`、`README.md`、`references/rufus-mcp-workflow.md`，新增术语约定并把授权、登录态检查、登录采集和恢复路径改为“亚马逊 Rufus 登录态”；同步更新 Rufus MCP/CLI 帮助文案、401 错误提示和相关测试断言。
**验证结果**：已运行 `uv run pytest tests/skills/test_ops_amazon_rufus_updater.py tests/skills/test_cli.py tests/amazon_rufus/test_transport.py -q`，结果 28 passed；已运行 `uv run pytest tests/amazon_rufus/test_core.py -q`，结果 85 passed；最终文档微调后重跑 `uv run pytest tests/skills/test_ops_amazon_rufus_updater.py tests/skills/test_cli.py -q`，结果 20 passed。
**影响范围**：影响 Rufus Skill 文档、安装后引导、CLI/MCP 帮助文案和平台 Cookie 401 错误提示；不改变 `platform-cookie` 接口名、MCP Tool 名、CLI 命令、状态保存结构或 Rufus 获取逻辑。
**回滚方式**：回退本次对 Rufus Skill 模板、`.agents` 安装副本、Rufus 帮助/错误文案、测试断言和本变更记录的修改。

---

## 2026-06-10 Amazon Rufus - CLI fallback 限域流程调整

**变更原因**：用户要求 Rufus Skill 从绝对 MCP-only 调整为 MCP 优先，并仅在必需 MCP Tool 不可用或用户拒绝保存复用 Amazon 登录态两种场景回退 CLI；同时要求 OPS 平台 Cookie 鉴权错误、`RUFUS_PLATFORM_COOKIE_AUTH_ERROR` 或 401 进入 MCP 登录采集。
**改动点**：更新 `ops-amazon-rufus` 模板与 `.agents` 安装副本的 Skill/README/workflow 文档，明确 bounded CLI fallback、denied 分支 CLI 获取和 401 分支 MCP `amazon_rufus_watch_login`；更新安装后 `next_steps`；更新文档契约测试和当前流程图。
**验证结果**：已完成 RED/GREEN 定向验证：旧实现下 `.venv/Scripts/python.exe -m pytest "tests/skills/test_ops_amazon_rufus_updater.py" "tests/skills/test_cli.py" -q` 失败 4 项；实现后定向回归 `.venv/Scripts/python.exe -m pytest "tests/skills/test_ops_amazon_rufus_updater.py" -q` 通过，8 passed；`.venv/Scripts/python.exe -m pytest "tests/skills/test_cli.py" -q` 通过，12 passed；`.venv/Scripts/python.exe -m pytest "tests/mcp/test_amazon_rufus_tools.py" -q` 通过，14 passed。
**影响范围**：影响 Rufus Skill Agent 编排、安装后提示、报告流程图和文档契约测试；不新增 MCP Tool、不新增 CLI 命令、不暴露 cookie、localStorage、`storage_state`、headers、payload 或请求种子。
**回滚方式**：回退本轮对 `opscli/skills/templates/ops-amazon-rufus/`、`.agents/skills/ops-amazon-rufus/`、`opscli/skills/commands/cli.py`、`tests/skills/`、`output/rufus-current-skill-flow.*` 和本变更记录的修改，恢复旧 MCP-only 文案与断言。

---

## 2026-06-09 Amazon Rufus - 默认状态读写切换到平台 Cookie content

**变更原因**：用户要求替换默认 `browser-state-<COUNTRY>.json` 文件保存/获取方式，Rufus 登录态和请求种子默认必须使用线上 `/v1/platform-cookies` 保存与读取接口。
**改动点**：`RufusManager.browser_state_store` 默认创建注入 `RufusTransportClient` 的 `RufusBrowserStateStore`，`save_state`、`watch_login`、`save_cookie`、`save_curl`、`login_status`、`get_backend`、`logout` 默认通过 `platform=amazon` 的平台 Cookie content 读写；`RufusBackendSecretProvider` 独立实例化时也默认使用线上 store；`RufusBrowserStateStore(base_dir=...)` 仅保留为显式 local fallback；同步更新 Rufus Skill 模板、`.agents` 副本、Super Dev PRD/Architecture/Tasks 和文档契约测试。
**验证结果**：新增 RED/GREEN 测试证明默认 `save_cookie` / `cookie_status` 只调用线上 content 且不创建 `browser-state-<COUNTRY>.json`，默认 `get_backend` 可从线上 content 恢复 `seed_request`；定向回归 `.venv/Scripts/python.exe -m pytest "tests/amazon_rufus/test_transport.py" "tests/amazon_rufus/test_core.py" "tests/mcp/test_amazon_rufus_tools.py" "tests/skills/test_ops_amazon_rufus_updater.py" -q` 通过，106 passed；Skill CLI 回归 `.venv/Scripts/python.exe -m pytest "tests/skills/test_cli.py" -q` 通过，12 passed。
**影响范围**：影响 Rufus 默认状态读写、MCP/headless 后端凭证读取、登录恢复文档和测试；旧 `browser-state-<COUNTRY>.json` 不再作为默认读写源，如只有本地旧状态需要重新执行 `watch-login` 写入线上平台 Cookie content。
**回滚方式**：回退 `opscli/amazon_rufus/services/manager.py`、`backend_secret.py`、`browser_state_store.py` 中默认线上 store 相关改动，恢复 Skill/README/reference 和测试中关于平台 Cookie content 默认读写的断言。

---

## 2026-06-09 Amazon Rufus - OPS 平台 Cookie 鉴权边界修复

**变更原因**：平台 Cookie API HTTP 401 代表 OPS/MCP 鉴权失败，不是 Amazon 登录态缺失。旧逻辑暴露泛化 `RUFUS_REMOTE_HTTP_ERROR`，Skill 容易误触发 `logout -> watch-login`，导致用户重复登录 Amazon 但无法修复 OPS API 401。

**改动点**：新增 `RufusPlatformCookieAuthError` 并只在平台 Cookie GET/POST 的 HTTP 401 上映射；MCP `amazon_rufus_get` 通过当前请求隔离凭证目录创建 Rufus manager；补充 transport、manager、MCP 和 Skill 文档契约测试；同步 `ops-amazon-rufus` 模板与 `.agents` 副本的禁止恢复规则。

**验证结果**：已运行 `E:/code/work/open-opscli/.venv/Scripts/python.exe -m pytest tests/amazon_rufus/test_transport.py tests/amazon_rufus/test_core.py tests/mcp/test_amazon_rufus_tools.py tests/skills/test_ops_amazon_rufus_updater.py -q`，结果为 116 passed；已扫描 Rufus auth boundary 文档、Skill 模板和 `.agents` 副本，未发现真实 JWT、session、Cookie、CSRF 等敏感样例值。

**影响范围**：影响 Rufus 平台 Cookie API 错误分类、MCP Rufus 当前请求凭证隔离、`ops-amazon-rufus` 错误恢复流程和相关测试；不改变 MCP schema、平台 Cookie API path、三字段保存契约或 Rufus upload 错误语义。

**回滚方式**：回退 `opscli/amazon_rufus/domain/exceptions.py`、`opscli/amazon_rufus/transport/client.py`、`opscli/mcp/tools/amazon_rufus.py`、Rufus/Skill 测试以及 `ops-amazon-rufus` Skill 文档中的本轮改动。

---

## 2026-06-08 Amazon Rufus - 平台 Cookie content 远端读写 CLI

**变更原因**：用户要求参考 Apifox `/v1/platform-cookies` 文档，为 Rufus Skill/CLI 接入平台 Cookie 保存与读取能力，并约束 CLI/API 只使用 `platform`、`country`、`content` 三个字段；除国家和平台外，Rufus 内部状态整合为大 JSON 存入 `content`。
**改动点**：`RufusTransportClient` 新增 `save_platform_cookie()` / `get_platform_cookie()`，POST 只发送 `platform/country/content`，GET 只按 `platform` 查询；`RufusBrowserStateStore` 支持注入平台 Cookie client，把完整 Rufus record 序列化进远端 `content` 并反序列化供 `RufusBackendSecretProvider` 读取；`RufusManager` 新增 `save_platform_cookie()` / `get_platform_cookie()` 参数校验与 404 missing 映射；`opscli amazon-rufus` 新增 `platform-cookie save/get` 子命令；同步更新 `ops-amazon-rufus` 模板、已安装 Skill 和 Super Dev 文档。
**验证结果**：已完成 RED/GREEN 定向测试：`.venv/Scripts/python.exe -m pytest "tests/amazon_rufus/test_transport.py" "tests/amazon_rufus/test_core.py" -k "platform_cookie" -q` 通过，4 passed；完整定向回归 `.venv/Scripts/python.exe -m pytest "tests/amazon_rufus/test_transport.py" "tests/amazon_rufus/test_core.py" "tests/mcp/test_amazon_rufus_tools.py" "tests/skills/test_ops_amazon_rufus_updater.py" -q` 通过，104 passed；Skill CLI 引导回归 `.venv/Scripts/python.exe -m pytest "tests/skills/test_cli.py" -q` 通过，12 passed。
**影响范围**：影响 Amazon Rufus transport、manager、browser state store 可注入远端 content 读写、CLI 子命令、Skill 文档和 Super Dev 文档；不新增 MCP Tool，不把 `cookie_content`、账号、域名、headers、payload、`storage_state` 或请求种子拆成 CLI/API 独立参数；后续 2026-06-09 变更已把默认状态链路切换为平台 Cookie content，本地 JSON 仅保留显式 fallback。
**回滚方式**：回退 `opscli/amazon_rufus/transport/client.py`、`opscli/amazon_rufus/services/browser_state_store.py`、`opscli/amazon_rufus/services/manager.py`、`opscli/amazon_rufus/commands/cli.py`、`opscli/amazon_rufus/domain/exceptions.py`、Rufus Skill 模板和 `.agents/skills/ops-amazon-rufus` 文档、`output/rufus-platform-cookie-*.md`、相关测试与本变更记录。
## 2026-06-16 MCP - 处理 server.py 工具注册冲突

**变更原因**：`opscli/mcp/server.py` 在合并工具清单自动上报与卖家精灵限额切面时出现冲突，需要同时保留两侧能力。
**改动点**：在 `_TelemetryMcpProxy.tool()` 的注册代理中保留 `record_tool()` 工具清单采集，并将注册函数按“限额切面 -> 遥测切面 -> FastMCP 注册”的顺序包裹。
**验证结果**：`.\.venv\Scripts\python.exe -m pytest tests\mcp\test_tool_catalog.py tests\mcp\test_quota.py tests\mcp\test_seller_sprite_tools.py -q` 通过，25 passed in 1.57s；`rg -n "<<<<<<<|=======|>>>>>>>" opscli\mcp\server.py` 无匹配。附加回归 `.\.venv\Scripts\python.exe -m pytest tests\mcp\test_tool_catalog.py tests\mcp\test_quota.py tests\mcp\test_seller_sprite_tools.py tests\mcp\test_tools.py -q` 中 29 passed、1 failed，失败为 `test_mcp_exposes_expected_tools` 在当前 stdio 未登录/权限过滤环境下只返回基础 auth 工具，和本次冲突块无直接关系。
**影响范围**：影响 MCP 工具注册链路；工具清单同步、遥测采集和受限工具限额逻辑会同时生效。
**回滚方式**：回退 `opscli/mcp/server.py` 中本次冲突块合并，并删除本条变更记录。

## 2026-06-29 skills - 统一 Keepa 每日额度提示

**变更原因**：`keepa_run` 已通过 MCP 限额中间件返回每日调用额度，但 Keepa Skill 仍要求隐藏剩余额度，导致最终回复未像卖家精灵一样提示用户当天的额度使用情况。
**改动点**：更新 `ops-keepa/SKILL.md` 与 `SKILL_MCP.md`，补充 `keepa_quota_status` / `opscli keepa quota-status` 使用说明，并要求 `keepa_run` 顶层存在 `quota` 时展示已用、总额、剩余和重置时间；`job_status` / `export` 不重复提示；Keepa API token 余额和账号信息继续隐藏。`tests/mcp/test_keepa_tools.py` 增加两份 Skill 模板的额度提示契约测试。
**验证结果**：RED 阶段运行 `.\.venv\Scripts\python.exe -m pytest tests\mcp\test_keepa_tools.py::test_keepa_skill_templates_require_daily_quota_prompt -q`，按预期失败于 Keepa Skill 缺少额度提示模板；GREEN 阶段同命令通过（1 passed）。聚焦回归 `.\.venv\Scripts\python.exe -m pytest tests\mcp\test_keepa_tools.py tests\keepa\test_remote_adapter.py tests\keepa\test_cli_remote.py -q` 通过（21 passed）。`ops-keepa` manifest 条目、`SKILL.md`、`SKILL_MCP.md` 和 `data/VERSION.json` 定向校验通过。全局 `validate_release_manifest()` 被仓库既存问题阻断：提交 `eb665b4` 删除了 `ops-canopy`、`ops-google-trends` 目录但 manifest 仍保留声明；`tests/skills/test_packaging.py` 另有 Windows 路径分隔符既存断言失败，均未在本次变更中扩范围修复。
**影响范围**：仅影响 Keepa Skill 的用户回复与额度查询指引，不修改 `keepa_run` 参数、MCP 返回结构、限额计算或底层 Keepa token 预检逻辑。
**回滚方式**：回退两份 Keepa Skill、对应契约测试和本条变更记录。
---

## 2026-06-25 skills - 新增 Keepa / Google Trends / Canopy 服务 Skill 模板

**变更原因**：本地 CLI 调远端 public MCP 的正式链路已经完成改造，需要补齐 Keepa、Google Trends、Canopy 三个服务的标准 Skill 模板，统一说明正式 CLI 代理远端 MCP 的调用流程、基础参数和场景能力，便于后续 AI Agent 直接按公开命令面工作。
**改动点**：在 `opscli/skills/templates/` 下新增 `ops-keepa`、`ops-google-trends`、`ops-canopy` 三个 Skill 目录；每个目录补充 `SKILL.md`（面向正式 CLI 代理链路）、`SKILL_MCP.md`（面向远端 MCP 直连语境）和 `data/VERSION.json`。其中 `SKILL.md` 统一收口到正式 `opscli keepa`、`opscli google-trends`、`opscli canopy` 命令路径，说明默认链路、最小工作流、关键命令参数、典型场景和用户回复边界，并明确禁止向用户暴露内部调试命令；同时补充显式前置约束：正式 CLI 依赖本机已完成 OPS 授权，若本机未登录或登录态过期，必须先执行 `opscli auth login`，避免 CLI 代理远端 MCP 时因缺少本机登录态直接报错。`SKILL_MCP.md` 则单独约束对应远端 `keepa_*`、`google_trends_*`、`beta_canopy_*` tools 的直接调用语境。同步将原 `opscli/mcp/references/keepa`、`google_trends`、`beta` 的参考规范整合进模板目录，改为由 `opscli/mcp/tools/keepa.py`、`google_trends.py`、`beta.py` 直接读取模板目录作为单一规范来源，不再维护重复副本。同步更新 `opscli/skills/templates/manifest.json`，为三个新模板补充发版清单声明、tier 和 reason。
**验证结果**：执行 `.\.venv\Scripts\python.exe -c "from opscli.skills.packaging import validate_release_manifest; problems = validate_release_manifest(); print(problems)"`，返回 `[]`；执行 `.\.venv\Scripts\python.exe -c "from opscli.skills.services.manager import SkillsManager; import json; data = [item for item in SkillsManager().list_templates() if item['name'] in {'ops-keepa','ops-google-trends','ops-canopy'}]; print(json.dumps(data, ensure_ascii=False, indent=2))"`，确认三个新模板都能被模板扫描逻辑识别。
**影响范围**：影响 Skills 模板目录与发版清单；不改动 Keepa、Google Trends、Canopy 的正式 CLI 实现、远端 MCP 适配层或底层服务逻辑。
**回滚方式**：删除 `opscli/skills/templates/ops-keepa`、`opscli/skills/templates/ops-google-trends`、`opscli/skills/templates/ops-canopy` 三个目录，回退 `opscli/skills/templates/manifest.json` 和本条变更记录。
---

## 2026-06-25 canopy - 正式远端命令面 / 本地调试命令面分轨

**变更原因**：远程 MCP 代理 CLI 统一改造要求 `opscli canopy` 对外去掉 beta 命名，收敛为正式远端命令面，同时把本地直连执行链路下沉到 `opscli canopy-debug`，并补齐 `job-status` / `export` 以对齐 Keepa、Google Trends 的统一命令面。
**改动点**：`opscli/canopy/remote_adapter.py` 新增 `CanopyRemoteAdapter`，复用共享 `RemoteMcpAdapter` 基座并将正式 CLI 映射到 `beta_canopy_scenarios`、`beta_canopy_run`、`beta_canopy_job_status`、`beta_canopy_export` 四个远端 tools；`opscli/canopy/cli.py` 改为正式远端命令面，只保留 `scenarios`、`run`、`job-status`、`export`，其中正式 `run` 不再暴露 `--output-dir`；新增 `opscli/canopy_debug/__init__.py` 与 `opscli/canopy_debug/cli.py`，迁入本地直连执行链路，并为 `run`、`job-status`、`export` 保留或补齐 `--output-dir`；`opscli/mcp/tools/beta.py` 扩展 `beta_canopy_job_status`、`beta_canopy_export`，并将 public beta MCP 返回统一收口为不暴露 `api_key_placeholder_used`、不回退 `file://`、在无远端上传 URL 时由 `run` / `job-status` 追加 warning、`export` 直接返回结构化错误；`opscli/cli.py` 新增顶级 `canopy` 与 `canopy-debug` 命令注册。新增 `tests/canopy/test_remote_adapter.py`、`tests/canopy/test_cli_remote.py`、`tests/canopy/test_cli_split.py`，并扩展 `tests/mcp/test_beta_tools.py` 覆盖正式/调试命令分轨、远端 tool 映射、public 返回脱敏和导出 URL 行为。
**验证结果**：回归 `.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\shared\test_remote_mcp_adapter.py tests\seller_sprite\test_remote_adapter.py tests\seller_sprite\test_remote_refresh.py tests\keepa\test_remote_adapter.py tests\keepa\test_cli_remote.py tests\keepa\test_cli_split.py tests\google_trends\test_remote_adapter.py tests\google_trends\test_cli_remote.py tests\google_trends\test_cli_split.py tests\canopy\test_remote_adapter.py tests\canopy\test_cli_remote.py tests\canopy\test_cli_split.py tests\mcp\test_keepa_tools.py tests\mcp\test_google_trends_tools.py tests\mcp\test_beta_tools.py tests\mcp\test_server_google_trends_registration.py -q` 通过，`85 passed in 3.10s`；顶级命令树检查 `.\.venv\Scripts\python.exe -m opscli.cli --help` 通过，并确认 `keepa-debug`、`google-trends-debug`、`canopy`、`canopy-debug` 都在。
**影响范围**：影响公开 `opscli canopy` / `opscli canopy-debug` 的命令面、正式远端调用链路以及 beta Canopy public MCP 返回口径；底层 `opscli/beta/canopy/` 本地 service 仍保留并继续服务 debug 命令与内部调用。
**回滚方式**：回退 `opscli/canopy/`、`opscli/canopy_debug/`、`opscli/mcp/tools/beta.py`、`opscli/cli.py`、对应 Canopy/MCP 测试和本条变更记录。
---

## 2026-06-25 google_trends - 正式远端命令面 / 本地调试命令面分轨并恢复 MCP 注册

**变更原因**：远程 MCP 代理 CLI 统一改造要求 `opscli google-trends` 对外收敛为正式远端命令面，恢复 Google Trends MCP Server 注册，同时把本地直连执行链路下沉到 `opscli google-trends-debug`，避免正式命令继续依赖本地 pytrends/落盘环境。
**改动点**：`opscli/mcp/server.py` 恢复 `google_trends` 工具导入与注册，使正式 MCP Server 再次暴露 `google_trends_spec_must_read`、`google_trends_scenarios`、`google_trends_run`、`google_trends_job_status`、`google_trends_export`；并把缺失 `asin_review` MCP 模块改为可选导入，避免导入 server 时直接中断。`opscli/google_trends/remote_adapter.py` 新增 `GoogleTrendsRemoteAdapter`，复用共享 `RemoteMcpAdapter` 基座，将正式 CLI 映射到 `google_trends_scenarios`、`google_trends_run`、`google_trends_job_status`、`google_trends_export` 四个远端 tools；`opscli/google_trends/cli.py` 改为正式远端命令面，正式 `run` 不再暴露 `--output-dir`；新增 `opscli/google_trends_debug/__init__.py` 与 `opscli/google_trends_debug/cli.py`，迁入原本的本地直连执行、任务状态读取和导出提取逻辑；`opscli/mcp/tools/google_trends.py` 将 public 返回统一收口为不暴露服务器本地 `path` / `file://`，在无远端上传 URL 时由 `job-status` 追加 warning、`export` 直接返回结构化错误；`opscli/cli.py` 新增顶级 `google-trends-debug` 命令注册。新增 `tests/mcp/test_server_google_trends_registration.py`、`tests/google_trends/test_remote_adapter.py`、`tests/google_trends/test_cli_remote.py`、`tests/google_trends/test_cli_split.py`，并扩展 `tests/mcp/test_google_trends_tools.py` 覆盖正式 MCP Server 注册、远端 tool 映射、正式 CLI 远端执行路径、正式/调试命令分轨，以及 public 导出 URL 契约。
**验证结果**：RED：`.\.venv\Scripts\python.exe -m pytest tests\mcp\test_server_google_trends_registration.py tests\google_trends\test_remote_adapter.py tests\google_trends\test_cli_remote.py tests\google_trends\test_cli_split.py -q` 初始失败，暴露 `opscli.google_trends.remote_adapter` 缺失、`opscli.google_trends_debug` 缺失，以及 `opscli.mcp.server` 导入时缺少可选 `asin_review` MCP 模块。GREEN：同命令复跑通过，`11 passed in 1.84s`；跟进 public 契约统一后回归 `.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\mcp\test_google_trends_tools.py tests\mcp\test_server_google_trends_registration.py tests\google_trends\test_remote_adapter.py tests\google_trends\test_cli_remote.py tests\google_trends\test_cli_split.py -q` 通过，`19 passed in 1.83s`。
**影响范围**：影响正式 `opscli google-trends` 命令的执行链路与公开口径，现改为“CLI auth -> 远端 MCP 配置 -> 远端 tool 调用”；`opscli google-trends-debug` 保留本地 pytrends/落盘调试链路；Google Trends MCP 工具重新出现在正式 MCP Server 的工具列表中。
**回滚方式**：回退 `opscli/mcp/server.py`、`opscli/google_trends/cli.py`、`opscli/google_trends/remote_adapter.py`、`opscli/google_trends_debug/`、`opscli/cli.py`、对应测试和本条变更记录。
---

## 2026-06-25 keepa - 正式远端命令面 / 本地调试命令面分轨

**变更原因**：远程 MCP 代理 CLI 统一改造要求 `opscli keepa` 对外收敛为正式远端命令面，只保留 `scenarios/run/job-status/export`，同时把本地直连执行和 `token-status` 下沉到 `opscli keepa-debug`，避免普通用户接触 Keepa 额度与本地账号细节。
**改动点**：`opscli/keepa/remote_adapter.py` 新增 `KeepaRemoteAdapter`，复用共享 `RemoteMcpAdapter` 基座并将正式 CLI 映射到 `keepa_scenarios`、`keepa_run`、`keepa_job_status`、`keepa_export` 四个远端 tools；`opscli/keepa/cli.py` 改为正式远端命令面，移除 `token-status`，新增 `job-status` 和 `export`，正式 `run` 不再暴露 `--output-dir`；新增 `opscli/keepa_debug/__init__.py` 与 `opscli/keepa_debug/cli.py`，迁入 Keepa 本地直连逻辑并保留 `token-status`、`scenarios`、`run`、`job-status`、`export`；`opscli/mcp/tools/keepa.py` 将 public 返回统一收口为不暴露服务器本地 `path` / `file://`，在无远端上传 URL 时由 `job-status` 追加 warning、`export` 直接返回结构化错误；`opscli/cli.py` 新增顶级 `keepa-debug` 命令注册，并在 `opscli.asin_review` 缺失时跳过可选注册，保证 `import opscli.cli` 仍可用；新增 `tests/keepa/test_remote_adapter.py`、`tests/keepa/test_cli_remote.py`、`tests/keepa/test_cli_split.py`，并扩展 `tests/mcp/test_keepa_tools.py` 覆盖远端 tool 映射、正式 CLI 远端执行路径、正式/调试命令分轨、`token-status` 下沉，以及 public 导出 URL 契约；跟进质量修复移除了 Keepa 测试里的假 `sys.modules` stub，改为直接测试 `keepa_cli.app` / `keepa_debug_cli.app`，并补充根 CLI 的 `keepa-debug` 注册断言以及 `keepa-debug export` 缺失导出时的明确报错。
**验证结果**：RED：`.\.venv\Scripts\python.exe -m pytest tests\keepa\test_remote_adapter.py tests\keepa\test_cli_remote.py tests\keepa\test_cli_split.py -q` 初始失败，报 `ModuleNotFoundError: No module named 'opscli.keepa.remote_adapter'` 和 `ModuleNotFoundError: No module named 'opscli.keepa_debug'`；质量修复阶段 `.\.venv\Scripts\python.exe -m pytest tests\keepa\test_cli_remote.py tests\keepa\test_cli_split.py -q` 初始失败，暴露 `opscli.cli` 导入时缺少 `opscli.asin_review` 以及 `keepa-debug export` 缺失导出仍返回 `null`。GREEN：聚焦回归通过，验证正式 `keepa` 仅走远端 adapter、`keepa-debug` 保留本地执行与 `token-status`，且根 CLI 可在缺少 `asin_review` 模块时成功导入；跟进 public 契约统一后回归 `.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\mcp\test_keepa_tools.py tests\keepa\test_remote_adapter.py tests\keepa\test_cli_remote.py tests\keepa\test_cli_split.py -q` 通过，`18 passed in 1.75s`。
**影响范围**：影响公开 `opscli keepa` 的命令面与执行链路；普通用户不再看到 `token-status`，正式命令改为远端 MCP 代理；本地 Keepa 直连、落盘查询与额度查看能力迁移到 `opscli keepa-debug`。
**回滚方式**：回退 `opscli/keepa/cli.py`、`opscli/keepa/remote_adapter.py`、`opscli/keepa_debug/`、`opscli/cli.py`、对应 Keepa 测试和本条变更记录。
---

## 2026-06-25 shared / seller_sprite - 远端 MCP CLI 共享适配基座收口

**变更原因**：远端 MCP 代理 CLI 统一改造需要先把 `seller_sprite` 已有的远端配置拉取、HTTP server 选择、401 重试和空参数过滤抽成共享能力，后续供 `keepa`、`google_trends`、`canopy` 复用，同时要求 `seller_sprite` 对外命令行为保持不变。
**改动点**：新增 `opscli/shared/remote_mcp_adapter.py`，封装 `McpConfigClient` + `RemoteMcpClient` 的公共基座，固定从 `data.http.mcpServers` 中优先选择 `BI运营系统`，调用前过滤顶层 `None` 参数，并在远端调用链路出现 `401` 时重拉配置后重试一次，兼容 `PermissionError`、`HTTPStatusError` 与 `ExceptionGroup` 等异常形态；`opscli/seller_sprite/remote_adapter.py` 改为继承共享基座，保留原有 `seller_sprite_*` tool 映射和 `session_id` 注入，只把远端调用细节下沉到公共层；新增 `tests/shared/test_remote_mcp_adapter.py` 覆盖共享基座的 server 选择、`None` 过滤、非 `401` 错误直抛、`preferred_name` 透传，以及 `PermissionError` / `ExceptionGroup(HTTP 401)` 两条重试链路，并更新 `tests/seller_sprite/test_remote_adapter.py` 与 `tests/seller_sprite/test_remote_refresh.py` 断言正式 CLI 仍透传 `session_id`，且在真实风格的 401 异常链路下只刷新一次配置。
**验证结果**：RED：`.\.venv\Scripts\python.exe -m pytest tests\shared\test_remote_mcp_adapter.py -q` 初始失败，报 `ModuleNotFoundError: No module named 'opscli.shared.remote_mcp_adapter'`；`.\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_remote_adapter.py -q` 初始失败，因现有实现仍向远端透传 `output_dir=None` 与 `job_id=None`。GREEN：`.\.venv\Scripts\python.exe -m pytest tests\shared\test_remote_mcp_adapter.py tests\seller_sprite\test_remote_adapter.py -q` 通过，`5 passed in 0.49s`。跟进质量补强与 401 异常链路扩展后，回归 `.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\shared\test_remote_mcp_adapter.py tests\seller_sprite\test_remote_adapter.py tests\seller_sprite\test_remote_refresh.py -q` 通过，`12 passed in 0.56s`。
**影响范围**：影响正式 CLI 远端调用共享层和 `seller_sprite` 远端参数整理逻辑；`seller_sprite` 的 tool 名映射、`session_id` 注入、CLI 命令面和返回结构不变。
**回滚方式**：回退 `opscli/shared/remote_mcp_adapter.py`、`opscli/seller_sprite/remote_adapter.py`、对应测试和本条变更记录。
---

## 2026-06-24 seller_sprite - 正式 CLI 远端调用显式透传 session_id

**变更原因**：`opscli seller-sprite` 正式 CLI 已能用本机 `opscli auth login` 拉取远端 MCP 配置，但调用远端 `seller_sprite_run` 时未显式带上本机 `session_id`，导致“本机 CLI 已登录、远端卖家精灵 MCP 仍报无 session_id”的断层。
**改动点**：`opscli/seller_sprite/remote_adapter.py` 新增 `AuthClient` 依赖注入，默认复用 `config_client.auth_client`；`run()` 调远端 `seller_sprite_run` 前显式读取本机 `AuthClient.get_session("ops")`，并将 `session_id` 一并透传给远端工具。`tests/seller_sprite/test_remote_adapter.py` 新增回归断言，要求正式 CLI 远端调用参数包含 `session_id`。
**验证结果**：RED：`.\.venv\Scripts\python.exe -m pytest tests/seller_sprite/test_remote_adapter.py -q` 初始失败，`KeyError: 'session_id'`。GREEN：同命令复跑通过，`3 passed in 0.46s`；回归 `.\.venv\Scripts\python.exe -m pytest tests/seller_sprite -q` 通过，`82 passed in 9.33s`。
**影响范围**：仅影响正式 `opscli seller-sprite` 远端调用参数；`seller-sprite-debug`、远端 MCP 凭证隔离模型、卖家精灵任务调度和导出逻辑不变。
**回滚方式**：回退 `opscli/seller_sprite/remote_adapter.py`、`tests/seller_sprite/test_remote_adapter.py` 和本条变更记录。

---

## 2026-06-23 seller_sprite - 收紧登录等待与失败冷却上限

**变更原因**：卖家精灵 browser-route 默认失败冷却上限仍为 20 秒，登录页密码框等待上限为 15 秒，体感偏慢；同时需要锁定“参数错误不冷却”的回归行为。
**改动点**：`opscli/seller_sprite/config.py` 将 `DEFAULT_BROWSER_COOLDOWN_SECONDS` 从 `20.0` 调整为 `10.0`；`opscli/seller_sprite/browser_route/worker.py` 将 `BrowserRouteRequest.cooldown_seconds` 默认值同步改为 `10.0`，并把密码框 `wait_for(..., timeout=15000)` 调整为 `5000`；`tests/seller_sprite/test_browser_route_worker.py` 新增默认冷却值断言、参数错误不冷却断言和登录页密码框最大等待 5 秒的回归测试。
**验证结果**：RED：`.\\.venv\\Scripts\\python.exe -m pytest tests/seller_sprite/test_browser_route_worker.py -q` 初始失败于默认冷却仍为 `20.0`、密码框等待仍为 `15000ms`。GREEN：同命令复跑通过，`18 passed in 0.47s`。
**影响范围**：影响卖家精灵 browser-route 的默认失败冷却上限与登录页账号密码框等待时长，不影响网络错误 `3-5s` 和风控错误 `15-20s` 的基础分类逻辑，只收紧默认 cap。
**回滚方式**：将上述两个默认值改回原值，回退新增测试断言，并删除本条变更记录。
---

## 2026-06-18 seller_sprite - SQLite 单账号排队一期

**变更原因**：当前卖家精灵 MCP 入口同时混合同步直跑、browser-route 忙时自动异步和任务目录文件状态，用户无法稳定看到排队序号；第一阶段需要先补单账号 SQLite 队列、统一入队返回和可查询状态，为后续多账号扩展预留结构。
**改动点**：新增 `opscli/seller_sprite/services/task_queue_store.py`，提供 SQLite 队列仓储、排队序号计算、运行中任务恢复和任务认证上下文持久化；新增 `opscli/seller_sprite/services/task_scheduler.py`，实现单账号 FIFO 调度、后台消费和完成态 `result.json` 合并；`opscli/seller_sprite/services/__init__.py` 导出新调度入口；`opscli/mcp/tools/seller_sprite.py` 新增 `_get_task_scheduler()` 与 `_build_request()`，将 `seller_sprite_run` / `seller_sprite_start` 统一改为入队返回，`seller_sprite_job_status` / `seller_sprite_export` 改为走调度器状态；新增 `tests/seller_sprite/test_task_queue_store.py`、`tests/seller_sprite/test_task_scheduler.py`，并更新 `tests/mcp/test_seller_sprite_tools.py` 以覆盖统一入队和状态查询。
**验证结果**：RED：`.\\.venv\\Scripts\\python.exe -m pytest tests/seller_sprite/test_task_queue_store.py -q` 初始失败于缺少 `task_queue_store` 模块；`.\\.venv\\Scripts\\python.exe -m pytest tests/seller_sprite/test_task_scheduler.py -q` 初始失败于缺少 `task_scheduler` 模块；`.\\.venv\\Scripts\\python.exe -m pytest tests/mcp/test_seller_sprite_tools.py -q` 初始失败于 `seller_sprite` MCP 工具缺少 `_get_task_scheduler`。中途 `uv run --extra dev pytest ...` 因 `.venv\\Scripts\\opscli-mcp.exe` 被占用失败，已按项目要求提交反馈 `4f63cc51-23df-4982-afbc-de7bd776dce9` 后改用 `.venv\\Scripts\\python.exe -m pytest` 直跑。GREEN：`.\\.venv\\Scripts\\python.exe -m pytest tests/seller_sprite/test_task_queue_store.py tests/seller_sprite/test_task_scheduler.py tests/seller_sprite/test_api_manager.py tests/mcp/test_seller_sprite_tools.py -q` 通过，`29 passed`。
**影响范围**：影响卖家精灵 MCP 的任务提交与状态查询口径；`seller_sprite_run` 现统一返回排队任务信息，不再在入口层直跑同步任务；单账号执行逻辑仍复用现有 `SellerSpriteApiManager.run()`，`status.json/result.json` 继续保留为任务目录产物。
**回滚方式**：删除 `task_queue_store.py`、`task_scheduler.py`，回退 `opscli/mcp/tools/seller_sprite.py` 到原先的 `run/start` 分支逻辑，回退 `opscli/seller_sprite/services/__init__.py` 和新增/修改测试，并删除本条变更记录。

---

## 2026-06-18 卖家精灵 - browser-route 调度与导航优化

**变更原因**：browser-route 每个任务固定访问首页、正常任务固定等待 8 秒，并对所有失败统一冷却 120 秒，导致无效导航和队列阻塞；默认运行时切换为 Patchright 后，基础卖家精灵依赖和文档也需要保持一致。
**改动点**：`opscli/seller_sprite/browser_route/worker.py` 改为同目标页刷新、不同目标页直接导航，不再固定访问首页；正常任务随机间隔 1-5 秒，网络错误随机冷却 3-5 秒，429/验证码/疑似风控随机冷却 15-20 秒，登录失效立即重新登录并只重试主请求一次，配置和未知代码错误不冷却；`opscli/seller_sprite/config.py` 将任务间隔上限调整为 5 秒、冷却上限调整为 20 秒；`pyproject.toml` 让基础 `seller-sprite` extra 安装默认 Patchright 运行时；同步更新 README、MCP Skill 和 worker 单元测试。
**验证结果**：RED：worker 测试分别因缺少随机等待分类函数、仍固定访问首页、主请求不支持会话重试而失败；GREEN：`.\.venv\Scripts\python.exe -m pytest tests/seller_sprite/test_browser_route_worker.py -q` 通过，17 passed；回归 `.\.venv\Scripts\python.exe -m pytest tests/seller_sprite tests/mcp/test_seller_sprite_tools.py -q` 通过，49 passed；`uv lock` 成功并确认基础 `seller-sprite` extra 包含 Patchright；对已安装 Patchright 1.60.1 做 API 冒烟检查，确认 `launch_persistent_context(no_viewport)`、`Page.reload/route/expect_response` 和 `APIRequestContext.post` 均可用。全量 `pytest tests -q` 在收集阶段被仓库既存同名测试模块阻断，首个错误为 `tests/amazon_rufus/test_transport.py` 与 `tests/feedback/test_transport.py` 的 import file mismatch，与本次卖家精灵变更无关。
**影响范围**：影响同账号 browser-route 的页面导航、任务等待、失败恢复和默认安装依赖；不改变 `api-direct`、场景 payload、MCP schema、导出格式和异步任务状态结构。
**回滚方式**：恢复 `worker.py` 的首页探测、固定间隔和统一冷却，恢复 `config.py` 默认值，移除对应测试，并从基础 `seller-sprite` extra 删除 Patchright 依赖后回退 README 与 Skill 说明。

---

## 2026-06-17 卖家精灵 - browser-route 支持 Patchright 运行时

**变更原因**：卖家精灵 browser-route 需要启用 Patchright 进行本地验证，以降低 Playwright 自动化特征和 webdriver/CDP 检测风险，同时保留 Playwright 路线作为兼容回退。
**改动点**：`opscli/seller_sprite/config.py` 新增 `OPSCLI_SELLER_SPRITE_BROWSER_RUNTIME` 配置并限制为 `playwright`/`patchright`，默认运行时设为 `patchright`；`opscli/seller_sprite/browser_route/worker.py` 将 async API 加载和启动参数构造收敛为局部 runtime 策略，Patchright 模式使用 `no_viewport` 且保留 persistent context；`ops-seller-sprite` MCP Skill 文档和 README 补充 Patchright 安装与运行时配置说明；新增 browser-route 单元测试覆盖默认配置、环境变量解析、Patchright loader 和启动参数。
**验证结果**：RED：`.\\.venv\\Scripts\\python.exe -m pytest tests/seller_sprite/test_browser_route_worker.py -q` 在实现前 3 failed，失败点为 `SellerSpriteSettings.browser_runtime` 不存在、worker 未提供 `_load_async_playwright`、未提供 Patchright 启动参数构造。GREEN：同一命令通过（10 passed）；默认值由用户先行本地调整后补充回归断言，因此该断言未单独经历 RED。回归：`.\\.venv\\Scripts\\python.exe -m pytest tests/seller_sprite tests/mcp/test_seller_sprite_tools.py -q` 通过（43 passed）。依赖锁定：`uv lock` 成功，新增 `patchright v1.60.1`；当前 `.venv` 已安装 Patchright 1.60.1 及其 Chromium，实际启动后 `navigator.webdriver` 为 `False`。补充检查：`.\\.venv\\Scripts\\python.exe -m pytest tests/mcp/test_tools.py -q` 当前 2 failed、4 passed，失败点为当前 MCP 权限/注册上下文只暴露 10 个 auth 类工具且 `seller_sprite_run` 未出现在 `Client(mcp).list_tools()` 中；该失败不在本次 browser-route runtime 改动路径内。
**影响范围**：影响卖家精灵 browser-route 的浏览器启动层和部署配置；默认 runtime 改为 Patchright，可通过 `OPSCLI_SELLER_SPRITE_BROWSER_RUNTIME=playwright` 回退，不影响 `api-direct`、MCP schema、导出逻辑、账号池和 Rufus 模块。
**回滚方式**：回退 `config.py`、`worker.py`、`pyproject.toml`、`tests/seller_sprite/test_browser_route_worker.py`、`ops-seller-sprite/SKILL_MCP.md`、`README.md` 和本变更记录。

---

## 2026-06-17 MCP - 卖家精灵长期日加额

**变更原因**：现有限额只支持全局默认日额度，无法按用户长期追加卖家精灵 MCP 每日额度；运维又不希望新增公开 CLI 命令，因此需要在 SQLite 层增加长期日加额能力，并统一以邮箱作为主匹配口径。
**改动点**：`opscli/mcp/quota.py` 将限额身份解析调整为邮箱优先，并增加本地凭证邮箱回退；`SQLiteQuotaStore` 新增 `mcp_quota_bonus_daily` 表和 `upsert_bonus_daily_limit()`，运行时按 `base_limit + bonus_daily_limit` 计算实际额度并把实际额度写入 `quota.limit` / `limit_count`；`tests/mcp/test_quota.py` 新增邮箱优先、本地凭证邮箱回退和长期日加额生效回归测试；新增内部文档 `docs/guide/卖家精灵MCP长期日加额内部SQL手册.md`，提供只面向内部运维的 SQL 操作说明。
**验证结果**：RED 阶段 `$env:SKIP_CYTHON='1'; uv run --extra dev pytest tests/mcp/test_quota.py::test_identity_resolver_prefers_email_then_api_key_hash tests/mcp/test_quota.py::test_identity_resolver_falls_back_to_local_credential_email tests/mcp/test_quota.py::test_sqlite_quota_store_applies_bonus_daily_limit -q` 失败，原因分别为身份仍优先 `user_id`、缺少本地邮箱回退、缺少 `upsert_bonus_daily_limit()`；GREEN 阶段 `$env:SKIP_CYTHON='1'; uv run --extra dev pytest tests/mcp/test_quota.py -q` 为 `17 passed`；目标回归 `$env:SKIP_CYTHON='1'; uv run --extra dev pytest tests/mcp/test_quota.py tests/mcp/test_seller_sprite_tools.py tests/mcp/test_tools.py -q` 为 `31 passed`。
**影响范围**：影响 `seller_sprite_run` 的限额主身份口径、SQLite schema 和 `quota.limit` 返回值；不新增公开 CLI 命令，不改变非 `seller_sprite_run` MCP 工具的限额行为。
**回滚方式**：回退 `opscli/mcp/quota.py` 对邮箱主匹配和 `mcp_quota_bonus_daily` 的改动，删除对应测试和内部 SQL 手册；如需清理本地策略数据，删除 SQLite 中 `mcp_quota_bonus_daily` 表。

---

## 2026-06-16 MCP beta - 评论分页默认值与导出上传

**变更原因**：用户反馈使用 beta/Canopy 查询 Amazon 评论时，首次未带分页参数容易因数据量过大在 30 秒内超时；同时导出结果只返回本地路径口径，未复用 Keepa 的服务器上传能力，最终回复缺少统一模板。
**改动点**：`opscli/mcp/tools/beta.py` 将 beta 默认超时调整为 60 秒，并在 `product-reviews` 场景未显式传 `page` 时默认补 `page=1`；`opscli/beta/canopy/services/api_manager.py` 复用 `FileUploadClient` 上传 Excel 导出，上传成功后写入远端 `export.url`，上传失败时追加 `file_upload` warning；`opscli/mcp/references/beta/SKILL_MCP.md` 补充评论默认分页、默认超时、导出上传和回复模板；`tests/mcp/test_beta_tools.py` 与 `tests/beta/canopy/test_api_manager.py` 增加默认分页/超时和上传 URL 回归测试，并在 beta MCP 单测中禁用真实上传。
**验证结果**：RED 阶段 `.\.venv\Scripts\python.exe -m pytest tests\mcp\test_beta_tools.py::test_beta_canopy_run_product_reviews_defaults_page_and_longer_timeout -q` 失败于缺少 `page`；RED 阶段 `.\.venv\Scripts\python.exe -m pytest tests\beta\canopy\test_api_manager.py::test_manager_uploads_export_and_returns_download_url -q` 失败于 `export.url` 仍为本地 `file://`；GREEN 阶段两个单测分别通过；回归 `.\.venv\Scripts\python.exe -m pytest tests\mcp\test_beta_tools.py tests\beta\canopy -q` 通过，29 passed in 2.14s。
**影响范围**：影响 beta Canopy `product-reviews` 默认调用参数、beta MCP 默认超时和 Canopy 导出文件返回口径；不改变其它 Canopy 场景必填参数和 xls 用户导出格式。
**回滚方式**：回退 `opscli/mcp/tools/beta.py` 中默认超时和评论默认 `page` 逻辑，删除 `CanopyApiManager` 的文件上传调用和 helper，恢复 beta MCP 规范中的旧导出说明，并移除对应测试。

---

## 2026-06-16 MCP beta - 移除源码中的 Canopy key

**变更原因**：用户误将 Canopy 测试 key 写入 `opscli/beta/canopy/config.py`，源码不应保存真实凭据。
**改动点**：从 `opscli/beta/canopy/config.py` 删除硬编码 key 赋值，并将该值迁移到项目内本地文件 `opscli/beta/canopy/api_key`；未在变更记录中记录完整 key。
**验证结果**：`Select-String -Pattern '^CANOPY_API_KEY\\s*=' opscli/beta/canopy/config.py` 无输出；本地 `api_key` 文件存在且长度为 36。
**影响范围**：仅影响本地测试服务凭据放置位置；`beta_canopy_run` 仍通过本地配置文件读取 key。
**回滚方式**：不建议回滚到源码硬编码；如需撤销本地 key，删除 `opscli/beta/canopy/api_key`。

---

## 2026-06-16 MCP beta - 隐藏 Canopy key 文档说明

**变更原因**：用户要求 `opscli/mcp/references/beta/SKILL_MCP.md` 不再包含 api-key 相关描述，对用户隐藏 Canopy key 管理细节，并且不对用户开放 CLI/直连调用方式。
**改动点**：删除 beta MCP 内部规范中的认证章节、key 管理工具说明、`api_key` 调用示例和 key 替换提示；新增规则要求对用户只开放 MCP beta 查询能力，不提供 CLI、curl、Python 或直连 REST 调用方式；保留场景、参数、导出和错误处理说明；错误处理仅保留 401 为 Canopy 认证配置异常。
**验证结果**：`rg -n "api_key|API key|API-KEY|YOUR_CANOPY|beta_canopy_api_key|CANOPY_API_KEY|key" opscli/mcp/references/beta/SKILL_MCP.md` 无匹配；`rg -n "CLI|cli|curl|Python|直连|REST 示例" opscli/mcp/references/beta/SKILL_MCP.md` 仅保留禁止向用户提供相关调用方式的规则。
**影响范围**：影响 beta MCP 参考文档展示口径；MCP 不再对用户暴露 key 管理工具，Canopy 调用行为仍由项目内本地 key 文件支撑。
**回滚方式**：从 Git 历史恢复 `opscli/mcp/references/beta/SKILL_MCP.md` 中的 key 管理说明和示例。

---

## 2026-06-16 MCP beta - Canopy 本地 API key 管理

**变更原因**：用户使用 MCP beta Canopy 时，MCP Server 进程未必继承当前 shell 的 Canopy 环境变量，导致同一 key 用 curl 成功但 MCP 调用可能使用错误或缺失的 key。测试服务只需要本地保存一个 Canopy API key，并由 beta 调用默认读取。
**改动点**：`opscli/beta/canopy/config.py` 只保留项目内本地 `api_key` 文件读取能力，路径为 `opscli/beta/canopy/api_key`；`beta_canopy_run` 的 key 读取顺序调整为显式内部参数、项目内本地 key、占位符，不再读取 Canopy key 环境变量；MCP 对用户仅注册 `beta_spec_must_read`、`beta_canopy_scenarios`、`beta_canopy_run`；同步更新 Canopy MCP 规范和用户指南。
**验证结果**：`.venv\Scripts\python.exe -m pytest tests/beta/canopy tests/mcp/test_beta_tools.py -q` 通过，27 passed in 1.96s；真实 `beta_canopy_run(product)` 冒烟成功，`placeholder_used=False`，确认已读取项目内本地 key 文件，返回 `row_count=1` 并生成 `canopy-local-key-smoke.xlsx`。
**影响范围**：仅影响 beta Canopy 测试服务的 API key 获取；不改变 Canopy 请求参数、导出格式、任务文件脱敏策略或其它 MCP 工具。
**回滚方式**：删除 `opscli/beta/canopy/config.py` 中本地 key 读取逻辑，回退 `opscli/mcp/tools/beta.py` 的 key 读取顺序，并回退 Canopy 文档说明。

---

## 2026-06-16 MCP beta - Canopy 评论自然语言别名映射

**变更原因**：用户反馈使用 beta/Canopy `product-reviews` 查询评论时，希望自然语言中的“差评”“已验证购买”等表达能自动映射为 Canopy 官方筛选参数，降低 Agent 调用时遗漏结构化字段的概率。
**改动点**：`opscli/mcp/tools/beta.py` 在 `product-reviews` 场景解析 `params` 后增加轻量别名归一化，支持从 `query`、`text`、`natural_language`、`naturalLanguage`、`user_input`、`userInput` 中识别星级和已验证购买表达；结构化 `rating`、`onlyVerifiedReviews` 显式入参优先，不被自然语言覆盖；同步补充 MCP beta 规范、Canopy 使用指南和 MCP 工具测试。
**验证结果**：`.venv\Scripts\python.exe -m pytest tests\mcp\test_beta_tools.py -q` 通过，15 passed in 1.70s；`.venv\Scripts\python.exe -m pytest tests\beta\canopy tests\mcp\test_beta_tools.py -q` 通过，24 passed in 1.86s。
**影响范围**：仅影响 beta Canopy `product-reviews` 场景参数归一化；不改变其它 Canopy 场景、Canopy API 调用层或导出层；无法规避 Canopy 上游 HTTP 500。
**回滚方式**：移除 `opscli/mcp/tools/beta.py` 中评论别名归一化 helper 与调用，删除 `tests/mcp/test_beta_tools.py` 新增用例，并回退对应文档说明。

---

## 2026-06-15 MCP beta - 接入 Canopy REST API 文档与接口

**变更原因**：用户要求基于 Canopy Swagger/OpenAPI 与 Python 示例，先生成 API 文档和测试阶段 beta MCP 相关接口；API key 暂用占位符，后续再提供真实 key。
**改动点**：新增 `opscli/mcp/references/beta/SKILL_MCP.md` 和 `OFFICIAL.md` 整理 Canopy MCP 使用规范与 17 个 REST endpoint；新增 `docs/guide/Canopy API接口使用指南.md`；新增 `opscli/mcp/tools/beta.py`，提供 `beta_spec_must_read`、`beta_canopy_scenarios`、`beta_canopy_run`，内置 Canopy 场景清单，使用 `domain` 参数、`API-KEY` header 与 `<YOUR_CANOPY_API_KEY>` 占位符；在 `opscli/mcp/server.py` 注册 beta 工具；新增 `opscli/beta/canopy/` 集中管理 Canopy API 调用任务、`params.json`/`raw.json`/`result.json` 落盘和 Excel 导出，用户侧导出格式只允许 `xls`，内部按 Keepa 兼容方式生成 `.xlsx` 并通过 `export.url` 返回；新增 `tests/mcp/test_beta_tools.py` 与 `tests/beta/canopy/` 覆盖场景、参数、API key、MCP 注册、导出格式限制、路径脱敏和 xlsx 生成；按用户要求收紧 beta 触发规则，明确只有用户提到 beta/Canopy/测试服务时才调用 `beta_*` 工具，普通 Amazon 查询不得自动路由到 beta；根据真实 Canopy 评论接口响应，将 beta 默认 HTTP timeout 调整为 30 秒，并在导出层展开 `data.amazonProduct.reviewsPaginated.reviews` 为逐条评论行，保留商品上下文、分页统计和评论人/标题/正文/评分/已验证购买等字段，避免真实评论响应导出成单行巨型 JSON。
**验证结果**：`.venv\Scripts\python.exe -m pytest tests/mcp/test_beta_tools.py tests/mcp/test_keepa_tools.py tests/mcp/test_amazon_rufus_tools.py -q` 通过，22 passed in 1.47s；收紧触发规则后复跑 `.venv\Scripts\python.exe -m pytest tests/mcp/test_beta_tools.py -q` 通过，10 passed in 1.06s；新增 beta xls 导出后复跑 `.venv\Scripts\python.exe -m pytest tests/mcp/test_beta_tools.py tests/beta/canopy tests/mcp/test_keepa_tools.py -q` 通过，22 passed in 1.71s；追加评论查询本地调试用例后复跑 `.venv\Scripts\python.exe -m pytest tests/mcp/test_beta_tools.py -q` 通过，12 passed in 1.34s；真实接口调试确认 Windows User 环境存在 `OPSCLI_BETA_CANOPY_API_KEY`，当前子进程需显式注入后可用，商品详情接口真实调用成功，评论接口在默认 10 秒超时时曾超时，调整为 30 秒后真实调用成功；修正真实评论响应展开后复跑 `.venv\Scripts\python.exe -m pytest tests\beta\canopy tests\mcp\test_beta_tools.py -q` 通过，21 passed in 1.30s；使用真实 Canopy key 对 `product-reviews`（US、ASIN `B0B3JBVDYP`）冒烟成功，默认 30 秒超时下返回 `row_count=10`，`data_preview` 来源为 `reviewsPaginated.reviews`，分页总数 `totalResults=26`，导出 `canopy-review-real-default-timeout-after-fix.xlsx`。
**影响范围**：新增 beta MCP Canopy 只读 API 查询能力、xls 用户导出能力和文档；MCP 进程需重启后才能暴露新工具/新参数；真实 API key 只从参数或环境变量读取，不写入任务文件，不影响既有 Keepa/Rufus 工具。
**回滚方式**：删除 `opscli/mcp/tools/beta.py`、`opscli/beta/`、`tests/mcp/test_beta_tools.py`、`tests/beta/canopy/`、`opscli/mcp/references/beta/`、`docs/guide/Canopy API接口使用指南.md`，并还原 `opscli/mcp/server.py` 中 beta import/register 改动。
---

## 2026-06-15 Keepa - XLSX 流式导出优化

**变更原因**：Keepa MCP 已不再支持 JSON 用户导出，需要提升 XLSX 导出对较大结果集的承载能力，避免普通 openpyxl 工作簿逐格写入带来的内存和耗时压力。
**改动点**：`opscli/keepa/export/xlsx.py` 改为 `Workbook(write_only=True)` 流式工作簿，通过 `sheet.append()` 写入表头和数据行；列扫描改为基于原始 rows 遍历，避免额外复制整表 normalized 数据；保留中文表头、表头样式、冻结窗格、列宽和 extra sheets 行为；`tests/keepa/test_export.py` 新增流式 workbook 约束测试。
**验证结果**：RED 阶段 `.\.venv\Scripts\python.exe -m pytest tests\keepa\test_export.py::test_xlsx_export_uses_streaming_workbook -q` 失败于当前实现调用普通 `Workbook()`；GREEN 阶段同一命令通过，`1 passed`；回归 `.\.venv\Scripts\python.exe -m pytest tests\keepa\test_export.py tests\keepa\test_api_manager.py tests\mcp\test_keepa_tools.py -q` 通过，`21 passed`。
**影响范围**：影响 Keepa XLSX 文件生成方式；输出文件格式、字段标题、extra sheets 和 MCP 返回结构保持不变。
**回滚方式**：恢复 `opscli/keepa/export/xlsx.py` 为普通 `Workbook()` + `sheet.cell()` 逐格写入，并移除 `tests/keepa/test_export.py` 中流式 workbook 约束测试。

---

## 2026-06-15 Keepa - 禁用 JSON 用户导出

**变更原因**：Keepa MCP 当前只支持面向用户的 xls/xlsx 表格导出，JSON 导出对运营用户没有实际价值，旧文档和实现仍允许请求 JSON，容易让 Agent 返回不可用的用户交付物。
**改动点**：`opscli/mcp/tools/keepa.py` 在 MCP 入口校验导出格式，只允许 `xls/xlsx`；`opscli/keepa/services/api_manager.py` 移除 JSON 用户导出和大结果自动转 JSON 路径，直接拒绝 `json`；同步更新 CLI 帮助、Keepa MCP 规范和内部 Keepa 参考文档；新增/调整 Keepa MCP 与 manager 测试覆盖非法 JSON 导出。
**验证结果**：RED 阶段 `.\.venv\Scripts\python.exe -m pytest tests\mcp\test_keepa_tools.py tests\keepa\test_api_manager.py -q` 失败于 MCP 和 manager 仍接受 `export_format="json"`；GREEN 阶段同一命令通过，`14 passed`。
**影响范围**：影响 Keepa MCP、Keepa CLI/Python manager 的用户导出格式；`params.json`、`raw.json`、`result.json` 任务内部文件仍保留，用于排障和后端比对。
**回滚方式**：恢复 `opscli/keepa/services/api_manager.py` 的 JSON 导出分支和大结果自动 JSON 逻辑，恢复 `opscli/mcp/tools/keepa.py` 对 `export_format` 的原样透传，并回退相关文档和测试。

---

## 2026-06-08 Amazon Rufus - 获取前登录态检查

**变更原因**：用户要求在发起 Rufus 获取前先检查是否已有 Amazon 登录态；没有可用登录态时再走登录采集流程，避免 allowed/denied 路径直接获取后才失败或重复打开登录窗口。
**改动点**：新增 `RufusManager.login_status()` 脱敏摘要能力；`opscli amazon-rufus` 新增 `login-status <COUNTRY>` 命令；`ops-amazon-rufus` Skill、README、workflow reference 和安装后提示改为 `remote-consent -> login-status -> 必要时 watch-login --close-browser -> allowed/denied 获取`；Super Dev architecture/proposal/tasks 同步追加获取前登录态检查状态机；补充 manager、CLI、Skill 文档和安装提示契约测试。
**验证结果**：定向 RED/GREEN 已完成：`.venv/Scripts/python.exe -m pytest "tests/amazon_rufus/test_core.py" -k "login_status or cli_help_exposes" -q` 通过，4 passed；`.venv/Scripts/python.exe -m pytest "tests/skills/test_ops_amazon_rufus_updater.py" -k "template_uses_mcp_boundary" -q` 通过，1 passed；`.venv/Scripts/python.exe -m pytest "tests/skills/test_cli.py" -k "rufus_outputs_login_guidance" -q` 通过，2 passed。`.venv/Scripts/opscli.exe skills install ops-amazon-rufus --skills-dir ".agents/skills" --force` 成功，安装输出已包含 `login-status` 获取前检查引导；完整回归 `.venv/Scripts/python.exe -m pytest "tests/amazon_rufus/test_core.py" "tests/mcp/test_amazon_rufus_tools.py" "tests/skills/test_ops_amazon_rufus_updater.py" "tests/skills/test_cli.py" -q` 通过，109 passed；`.venv/Scripts/opscli.exe amazon-rufus login-status US --pretty` 冒烟成功，返回 `status=ready`、`can_get_backend=true`，未输出敏感字段；子代理验证 allowed 路径先执行 `remote-consent status -> login-status`，因已有登录态跳过 `watch-login` 并调用 `amazon_rufus_get`，生成 `output/amazon-rufus/B0B1MLVMY5-20260608-172248.md`；子代理验证 denied 路径先执行 `remote-consent status -> login-status`，因已有登录态跳过 `watch-login` 并调用 `opscli amazon-rufus get-backend`，生成 `output/amazon-rufus/B0B1MLVMY5-20260608-172506.md`。两次均两题有答案且未发现敏感字段泄露；测试后已将 US consent 恢复为 `allowed`。
**影响范围**：影响 Amazon Rufus CLI、Rufus 获取前 Agent 编排、`ops-amazon-rufus` 模板与已安装 Skill 文档、安装后引导和相关测试；不改变 MCP schema，不暴露 cookie、localStorage、`storage_state`、headers、payload 或请求种子。
**回滚方式**：回退 `opscli/amazon_rufus/services/manager.py`、`opscli/amazon_rufus/commands/cli.py`、`opscli/skills/commands/cli.py`、Rufus Skill 模板与 `.agents/skills/ops-amazon-rufus` 安装副本文档、`.super-dev/changes/amazon-rufus-remote-consent/`、`output/rufus-remote-consent-architecture.md` 和相关测试中的 `login-status` 变更。

---

## 2026-06-08 Amazon Rufus - 远程授权偏好与拒绝授权 CLI 获取闭环

**变更原因**：Rufus Skill 需要在保存 Amazon 登录态用于 MCP/headless 任务前取得用户授权；用户拒绝时仍需完成登录采集并关闭浏览器，然后通过 CLI 复用后端获取逻辑拿到 Rufus 数据，避免把拒绝路径继续交给 MCP 获取。
**改动点**：新增 `RemoteConsentStore` 保存 `remote-consent.json` 授权偏好摘要；`opscli amazon-rufus` 新增 `remote-consent status/set` 和 `get-backend` 命令；`watch-login` 增加 `--close-browser/--keep-browser-open`，仅关闭本次由 opscli 启动的调试浏览器；同步更新 `ops-amazon-rufus` 模板 Skill、README、workflow reference 和契约测试，约束 allowed 走 `amazon_rufus_get`，denied 走通用登录采集后调用 `opscli amazon-rufus get-backend`。
**验证结果**：`.venv/Scripts/python.exe -m pytest "tests/amazon_rufus/test_core.py" "tests/mcp/test_amazon_rufus_tools.py" "tests/skills/test_ops_amazon_rufus_updater.py" "tests/skills/test_cli.py" -q` 通过，106 passed；`.venv/Scripts/opscli.exe skills install ops-amazon-rufus --skills-dir ".agents/skills" --force` 成功，安装输出已包含 `remote-consent`、`--close-browser` 和 `get-backend` 引导；子代理用指定 `$ops-amazon-rufus` 提示词测试 allowed 路径，确认执行 `remote-consent status` 后调用 `amazon_rufus_get`，生成 `output/amazon-rufus/B0B1MLVMY5-20260608-164046.md`，两题均有答案且未发现敏感字段；denied 路径首次暴露 `watch-login --close-browser` 在 Playwright 退出后关闭浏览器导致 `Event loop is closed`，已修复关闭时序并补充 RED/GREEN 回归，复测确认执行 `remote-consent status -> watch-login --launch-if-needed --close-browser -> get-backend`，生成 `output/amazon-rufus/B0B1MLVMY5-20260608-164939.md`，两题均有答案且未发现敏感字段。失败反馈提交尝试因当前 ops JWT 401 未生成 feedback_uuid，stdio 模式无法使用 `auth_mcp_login` 自动恢复。
**影响范围**：影响 Amazon Rufus CLI、Rufus 本地授权偏好文件、`watch-login` 浏览器生命周期、`ops-amazon-rufus` Agent 编排文档和相关测试；不改变 MCP schema，不在 MCP 参数、报告、CLI 成功输出或 Skill 文档中暴露 cookie、localStorage、`storage_state`、headers、payload 或请求种子。
**回滚方式**：回退 `opscli/amazon_rufus/services/remote_consent.py`、`opscli/amazon_rufus/commands/cli.py`、`opscli/amazon_rufus/services/browser.py`、`opscli/amazon_rufus/services/manager.py`、`opscli/skills/commands/cli.py`、Rufus Skill 模板与 `.agents/skills/ops-amazon-rufus` 安装副本文档、`.super-dev/changes/amazon-rufus-remote-consent/` 和相关测试中的本次新增断言。

---

## 2026-06-05 query metadata - 把 --dataset / --table-id 参数透传给后端 API

**变更原因**：`opscli query metadata --dataset ds_xxx` 命令此前把参数仅用于本地内存过滤，远端请求拉取全量 datasets+fields，造成网络浪费、opscli 端处理负担线性增长、后端无法做权限层面针对性优化；改造为参数透传，让后端按需返回。
**改动点**：
- `opscli/query/transport/client.py`：`fetch_query_metadata()` 增加可选关键字参数 `dataset_alias` / `table_id`，按 snake_case 拼接为 `httpx.get(params=...)`；None 值自动忽略，无参调用 `params=None` 与原行为一致
- `opscli/query/services/manager.py`：`QueryManager.metadata()` 把 `dataset_alias` / `table_id` 透传给 `self.client.fetch_query_metadata(...)`；保留远端失败回退本地 + 本地过滤的兜底链路
- `tests/query/test_client.py`：原 `test_fetch_query_metadata_sends_get_request` 增加 `params is None` 断言；新增 3 个带参测试 `test_fetch_query_metadata_with_dataset_alias_param` / `with_table_id_param` / `with_both_params`
- `tests/query/test_manager.py`：将 15 处 `fetch_query_metadata` mock lambda 改为 `lambda **kw:` 以接受新关键字参数（仅 fetch_query_metadata 的 mock 改动，其他 mock 不变）
- `auto-scheduler/vendor/aukey/data-metrics/src/Http/Controllers/DatasetSkillApiController.php`：`queryMetadata(Request $request)` 从 `$request->query()` 读取 `dataset_alias` / `table_id` 透传给 service；空串/null 统一归一化为 `null`
- `auto-scheduler/vendor/aukey/data-metrics/src/Services/DatasetSkillService.php`：`buildQueryMetadataForUser()` 增加 `?string $datasetAlias = null, ?int $tableId = null` 参数；在 `buildExportPayloadForUser()` 权限收敛之后做过滤（datasetAlias 优先于 tableId，按 datasetAlias 或 datasetName 匹配；指定参数时按命中的 table_id 集合收敛 fields）；**未指定过滤参数时显式将 `fields` 置空**（联调时发现：原实现保留 fields 全量返回，违反"裸调用 → 仅 datasets 列表（不带 fields）"的契约，导致单纯探索数据集时传输大量冗余字段）
**验证结果**：
- 单元测试：`pytest tests/query/test_client.py tests/query/test_manager.py -v` → 53 通过；`pytest tests/query/ -v` → 68 通过，无回归
- 关键决策：参数命名 snake_case（`dataset_alias` / `table_id`）；裸调用保留原行为（返回全量 datasets 列表不含 fields）；复用现有端点 `GET /v1/data-metrics/datasets/query-metadata`，不开新路由
- 兼容矩阵：后端先上线 + opscli 旧版本调用 → 后端走原分支返回全量（向后兼容）；opscli 先上线 + 后端旧版本 → 后端忽略未识别 params 返回全量，opscli 本地过滤兜底（向前兼容）
**影响范围**：opscli CLI `query metadata` 子命令、MCP `query_metadata` 工具、`mcp/tools/chatgpt.py:261/305` 内部调用、后端 `GET /v1/data-metrics/datasets/query-metadata` 接口；现有所有消费方均通过 `Manager.metadata()` 间接受益，零调用方改动
**回滚方式**：
1. opscli 侧：还原 `client.py` `fetch_query_metadata()` 签名（去掉 `dataset_alias`/`table_id` 参数和 params 组装）；还原 `manager.py` `metadata()` 调用处去掉关键字参数；还原 `test_client.py` 删除 3 个新增测试并移除 `params is None` 断言；`test_manager.py` 把 `lambda **kw:` 改回 `lambda:`
2. 后端侧：还原 `DatasetSkillApiController::queryMetadata()` 直接调用 `buildQueryMetadataForUser((int) $userId)`；还原 `DatasetSkillService::buildQueryMetadataForUser()` 签名只保留 `$userId` 并去掉过滤逻辑
3. 由于双侧改造都保持了向后/向前兼容，单独回滚任一侧都不会破坏对端
## 2026-06-05 xiyou - 站点白名单与中文别名归一化

**变更原因**：MCP `xiyou_run` 仅在 `_site()` 里做 `str.upper()`，任何未支持的取值（含中文国家名"柬埔寨"等）会原样透传给西柚后端，由西柚返回模糊错误，Agent 难以纠错；同时 `XiyouApiManager.scenarios()` 里 `sites` 是 5 项硬编码字符串数组，与真实支持的 13 个站点严重不一致，导致 Agent 误以为西柚只支持 5 个国家。需要建立单一可信源的站点白名单 + 中文别名兜底 + fail-fast 校验。
**改动点**：
- `opscli/xiyou/api/payloads.py`：新增 `SUPPORTED_SITES`（frozenset，覆盖西柚官网披露的 13 个站点 US/CA/MX/BR/DE/UK/FR/IT/ES/JP/AE/SA/AU）、`SITE_ALIASES`（中文国家名/带"站"后缀/常见别名映射到 ISO2 code，含 `gb→UK` 兜底）、`normalize_site(value)`（依次走别名表→大写白名单→fail-fast 抛 `XiyouConfigError`，错误信息列出所有支持值）；`_site()` 改为调用 `normalize_site`，`make_ranking_payload` 同步改用 `_site` 而非内联 `str.upper()`，确保 ranking/resource 两条路径走同一归一化
- `opscli/xiyou/services/api_manager.py`：`scenarios()` 中 `sites` 硬编码列表改为 `sorted(SUPPORTED_SITES)`，从 `payloads` 派生，避免两处不同步
- `opscli/skills/templates/ops-xiyou/SKILL.md`：`site` 参数说明从单行 5 个站点扩展到分区列出 13 个完整站点及中文标注，明确"中文名 Agent 应优先映射 + opscli 内部有兜底"
- `tests/xiyou/test_payloads.py`：新增 7 个用例覆盖支持站点集合冻结、中文别名归一化、ISO2 大小写不敏感、空值默认 US、不支持站点报错带详情、ranking/resource 两条路径都会被归一化校验
**验证结果**：`.venv\Scripts\python.exe -m pytest tests/xiyou/ -v` → 42 passed in 9.32s（含新增 7 个用例和之前的 35 个）
**影响范围**：所有走 xiyou ranking/resource 场景的入口（CLI `opscli xiyou run` 与 MCP `xiyou_run`）；`scenarios()` 输出的 `sites` 数组从 5 项变为 13 项排序输出；用户传不支持的站点（含中文）现在会被 opscli 提前拦截并返回包含支持站点列表的错误，而非到西柚后端才报错；现有所有传 US/DE 等合法 code 的调用零变化；**MCP 进程需要重启才能生效**
**回滚方式**：删除 `payloads.py` 顶部 `SUPPORTED_SITES`/`SITE_ALIASES`/`normalize_site` 块，将 `_site()` 恢复为 `str(params.get("site") or params.get("country") or "US").upper()`、`make_ranking_payload` 的 `country` 恢复为 `str(params.get("site") or "US").upper()`；`api_manager.py` 删除 `SUPPORTED_SITES` 导入并把 `sites` 改回 `["US", "DE", "UK", "CA", "FR"]`；`SKILL.md` 的 `site` 行还原为单行；删除 `tests/xiyou/test_payloads.py` 末尾新增 7 个用例及 `SUPPORTED_SITES`/`normalize_site` 导入
---

## 2026-06-05 xiyou - resource 导出补全 row_count 与 page_size 警告

**变更原因**：MCP `xiyou_run` 在 `reverse-keyword` 等 resource 导出场景下 `row_count` 长期硬编码为 0，导致 Agent 误判为"导出失败"或"零结果"；调用方传 `page_size=10` 实际拿到 1600+ 行也无任何提示，原因是西柚 resource 接口固定返回全量数据、`pageSize` 仅对网页分页生效。这两个问题让 AI 在拿到结果后无法判断数据有效性，也无法理解为什么 page_size 没生效。
**改动点**：
- `opscli/xiyou/services/api_manager.py`：`_run_resource` 提前初始化 `warnings`/`row_count`，xlsx 下载成功后调用新增的 `_count_xlsx_rows` 读取真实数据行数；当调用方显式传 `page_size` 且与返回行数不符时追加 `stage=resource_export` warning 说明西柚后端忽略 pageSize；`XiyouRankingResult.row_count` 改用真实值
- `opscli/xiyou/services/api_manager.py`：末尾新增 `_count_xlsx_rows(path)` 工具函数，使用 `openpyxl.load_workbook(read_only=True)` 读 `max_row - 1`，文件损坏时返回 0 不中断主任务
- `tests/xiyou/test_api_manager.py`：新增 4 个测试 —— `_count_xlsx_rows` 对真实 xlsx / 损坏文件的行为，以及 `_run_resource` xlsx 分支在 page_size 不足/默认情况下的 `row_count` 与 warning 行为；新增 `DummyResourceXlsxClient` 通过 `_build_xlsx_bytes(n)` 用 openpyxl 真实生成可下载字节
**验证结果**：`.venv/Scripts/python.exe -m pytest tests/xiyou -v` → 35 passed in 9.03s（含新增 4 个用例与之前的 31 个）
**影响范围**：仅影响 xiyou resource 导出场景返回结构（`row_count` 现在反映真实行数，必要时增加 `resource_export` 阶段 warning）；`_run_ranking` / 排行榜场景零影响；MCP `xiyou_run` / CLI `opscli xiyou run` 对外签名不变
**回滚方式**：还原 `opscli/xiyou/services/api_manager.py` `_run_resource` 的 `warnings/row_count` 初始化与 `row_count=0` 写法，删除 `_count_xlsx_rows`；删除 `tests/xiyou/test_api_manager.py` 末尾新增的 4 个测试与 `DummyResourceXlsxClient`

---

## 2026-06-05 xiyou - 修复 OSS 预签名链接下载 403 SignatureDoesNotMatch

**变更原因**：MCP `xiyou_run` 在 `reverse-keyword` 等 resource 导出场景下载 `excel.xydc.com` 的 xlsx 文件时稳定报 403 `SignatureDoesNotMatch`。根因为 `XiyouApiClient.get_bytes` 复用了 `XiyouApiClient` 内部的 httpx 客户端并显式传入 `_browser_headers()`，将西柚业务请求头（`authorization` JWT、`cookie`、`origin`、`referer`、`content-type` 等）一并发给了 OSS；部分 OSS bucket 检测到请求同时存在 `Authorization` 头和 `Signature` query 参数时会按 Authorization 头优先解析签名，从而将合法的预签名链接判为签名不匹配。此外西柚返回的 URL path 把分隔符 `/` 误编码为 `%2F`，需要在客户端规范化以避免 httpx 或中间代理处理不一致。
**改动点**：
- `opscli/xiyou/api/client.py`：重写 `get_bytes`，改为使用独立 `httpx.AsyncClient`，仅携带 `user-agent`，并对 URL 调用新增的 `_normalize_oss_url` 做 path 规范化（仅 unquote path，query 严格保留）；响应体片段从 1000 提升到 2000 便于保留 OSS 错误体的关键字段
- `opscli/xiyou/services/api_manager.py`：在 `_run_resource` 的 xlsx 下载处包装 `XiyouApiError`，转为 `XiyouConfigError` 并附带 `resource_url` 与 OSS 响应片段（含 `<StringToSign>` / `<SignatureProvided>` 等），便于反向定位签名问题；新增 `XiyouApiError` 导入
- `tests/xiyou/test_api_client.py`：新增 4 个测试：`_normalize_oss_url` path 规范化与 query 保留、`get_bytes` 不向 OSS 泄漏业务头、`get_bytes` 在 403 时抛出含 OSS 错误片段的异常
**验证结果**：`pytest tests/xiyou -v` → 31 passed in 7.65s（含新增 4 个用例与排行榜原有全部用例）
**影响范围**：仅影响 xiyou resource 导出场景（`reverse-keyword` / `asin-compare` / `keyword-analysis` / `keyword-explorer` 的 xlsx 下载链路）；排行榜场景 `_run_ranking` 本地生成 xlsx，不经过 `get_bytes`，零影响；MCP `xiyou_run` / CLI `opscli xiyou run` 对外签名不变
**回滚方式**：还原 `opscli/xiyou/api/client.py` 与 `opscli/xiyou/services/api_manager.py` 对应修改，删除 `tests/xiyou/test_api_client.py`

---

## 2026-06-03 ops-dataset-query 二期服务端 S-5 - 字段语义索引表 + API

**变更原因**：服务端 P1 任务，为 AI 客户端提供"业务用语 → 数据集字段"的映射索引，后续在后台录入数据后可支持语义搜索
**改动点**：
- `vendor/aukey/data-metrics/src/database/migrations/2026_06_03_000003_create_dm_field_semantic_index_table.php`：新建迁移，创建 `dm_field_semantic_index` 表（table_id、field_name、field_type、semantic_term、needs_disambiguation、disambiguation_hint、aggregation_hint、status + 3 个索引）
- `vendor/aukey/data-metrics/src/Services/DatasetSkillService.php`：新增 `buildFieldSemanticIndexForUser()` 方法，按用户权限过滤并返回字段语义索引
- `vendor/aukey/data-metrics/src/Http/Controllers/DatasetSkillApiController.php`：新增 `exportFieldSemanticIndex()` 方法
- `vendor/aukey/data-metrics/src/Http/routes.php`：注册 `GET /skill/field-semantic-index` 路由
**验证结果**：`artisan migrate` 成功（DONE，212ms）；`Schema::hasTable('dm_field_semantic_index')` → PASS；`buildFieldSemanticIndexForUser(1)` → PASS entry_count=0（表为空的预期值）；路由已注册于 routes.php:66
**影响范围**：data-metrics 包新增 API 端点，向后兼容（表为空时返回空 entries 数组）
**回滚方式**：`php artisan migrate:rollback --path=vendor/aukey/data-metrics/src/database/migrations/2026_06_03_000003_create_dm_field_semantic_index_table.php`；还原 DatasetSkillService.php、DatasetSkillApiController.php、routes.php 对应修改

---

## 2026-06-02 ops-dataset-query 二期客户端优化 - 完整落地

**变更原因**：将二期结构化产物（intent_taxonomy、dataset_profiles 等）从草案目录落地到 Skill 模板，新增本地意图路由脚本，使 AI 在远端 Catalog 未命中时能进行四级回退路由而非直接跌落关键词搜索
**改动点**：
- `opscli/skills/templates/ops-dataset-query/data/`：新增 6 个结构化产物文件（intent_taxonomy.yml、dataset_profiles.yml、dataset_relationships.yml、field_semantic_index.yml、routing_eval_cases.yml、query_plan.schema.json）
- `opscli/skills/templates/ops-dataset-query/data/VERSION.json`：版本升级 1.0.2→1.1.0，data_state=ready
- `pyproject.toml`：新增 `pyyaml>=6` 依赖
- `opscli/skills/templates/ops-dataset-query/scripts/route_intent.py`：本地意图路由脚本，支持 direct_intent/embedded_intent 路由、澄清触发、fallback 检测
- `tests/skills/test_route_intent.py`：11个单元测试，覆盖账单销售路由、embedded_intent 映射、SP 澄清、无关问题回退、CLI 入口验证等
- `opscli/skills/templates/ops-dataset-query/SKILL.md`：新增铁律三-B（四级回退链）
- `opscli/skills/templates/ops-dataset-query/references/rules.md`：新增零-A 章节（字段语义解析流程 + 高风险多义词快查表）
**验证结果**：`pytest tests/skills/test_route_intent.py -v` 11/11 PASSED；3 个路由冒烟用例（billing_sales、embedded_intent、SP 澄清）全部符合预期
**影响范围**：ops-dataset-query Skill 模板，已安装版本需重新 install 获取新文件
**回滚方式**：`git checkout HEAD -- opscli/skills/templates/ops-dataset-query/ tests/skills/test_route_intent.py pyproject.toml`

---

## 2026-06-02 ops-dataset-query 二期 - 规划文档产出

**变更原因**：完成二期优化的全面规划，为客户端意图路由落地和服务端约束字段扩展提供完整 TDD 实施路径
**改动点**：
- `docs/plans/ops-dataset-query二期优化方案.md`：7章完整优化方案，含客户端P0-P2、服务端P0-P1优先级排期
- `docs/plans/ops-dataset-query二期客户端实施计划.md`：8任务 TDD 客户端实施计划，含完整 `route_intent.py` + `test_route_intent.py` 代码
- `docs/plans/ops-dataset-query二期服务端实施计划.md`：5任务（S-1~S-5）TDD 服务端实施计划，含完整 Laravel Migration PHP + DatasetSkillService 代码
**验证结果**：文档已创建，规划覆盖优化方案所有 P0/P1 条目
**影响范围**：仅文档，代码变更待用户确认后逐任务执行
**回滚方式**：删除三个新增 md 文档

---

## 2026-06-01 query - simple 接口 filters operator 符号写法自动标准化

**变更原因**：`query simple` 的 `_validate_simple_filter_operators()` 只校验不转换，用户/AI Agent 按文档传入符号操作符（如 `=`）会被拒绝并报 `INVALID_PAYLOAD`，而 `query build` 路径已有 `_WHERE_OP_MAP` 做符号标准化。两条路径行为不一致，且文档中列出的 operator 与代码白名单不匹配。
**改动点**：
- `opscli/query/services/manager.py`（`_validate_simple_filter_operators` 方法）：
  - 校验前用 `_WHERE_OP_MAP` 将符号操作符（=, >=, <=, >, <, !=, <>, ==）转换为语义操作符（eq, gte, lte, gt, lt, neq, neq, eq）
  - 就地修改 node 的 operator 字段，确保后续 build_simple 构造 payload 时使用标准化后的值
- `opscli/skills/templates/ops-dataset-query/references/simple-query-guide.md`：
  - 补全所有支持的操作符（13 个语义 + 8 个符号），明确标注符号写法会自动转换
**验证结果**：`pytest tests/query/ -v`
**影响范围**：所有通过 `query simple` / `query_build_and_run` / MCP `query_simple` 入口传入 filters 的调用场景
**回滚方式**：`git revert` 此次改动即可恢复原行为（符号操作符被拒绝）

---

## 2026-05-29 Skills 分享码功能 - 全链路实现

**变更原因**：技能广场中 personal/department 类型的技能只有创建者或同部门成员可安装。需要允许创建者生成临时分享码（默认 30 分钟有效），持码的任意登录用户可绕过权限限制完整安装技能。
**改动点**：
- **DB Migration**（`vendor/aukey/data-metrics/src/Database/Migrations/`）：
  - `2026_05_29_000001_create_dm_skill_share_codes_table.php`：新建 `dm_skill_share_codes` 表（`ops_metrics` 连接），字段含 `code`/`skill_id`/`creator_user_id`/`expires_at`/`max_uses`/`used_count`/`note`/软删除
  - `2026_05_29_000002_add_share_code_fields_to_dm_skill_installs.php`：为 `dm_skill_installs` 新增 `install_source`（normal|share_code）和 `share_code_id` 字段（`ops_metrics` 连接）
- **Model**（`vendor/aukey/data-metrics/src/Models/SkillShareCode.php`）：新增，含 `isValid()`/`remainingSeconds()` 方法
- **Service**（`vendor/aukey/data-metrics/src/Services/SkillMarketplaceService.php`）：
  - 新增 `createShareCode()`/`listShareCodes()`/`getShareCodeInfo()`/`revokeShareCode()`/`validateShareCode()` 五个方法
  - `getByIdentifier()`/`getDownloadUrl()` 新增 `$shareCode` 参数，有效码时跳过 `checkSkillVisibility()`
  - `recordInstall()` 新增 share_code 来源记录逻辑，有码时 `increment('used_count')`
- **Controller**（`vendor/aukey/data-metrics/src/Http/Controllers/SkillShareCodeController.php`）：新增，含 `store`/`index`/`show`/`destroy` 四个方法
- **Controller 修改**：`SkillMarketplaceController.showByIdentifier()` 和 `SkillVersionController.download()` 透传 `share_code` 查询参数
- **Controller 修改**：`SkillStatController.recordInstall()` 新增 `share_code` 字段校验
- **Routes**（`vendor/aukey/data-metrics/src/Http/routes.php`）：注册四条 share-codes 路由（静态路由置于 `/{id}` 之前防止冲突）
- **CLI**（`opscli/skills/marketplace/client.py`）：`get_by_identifier()`/`get_download_url()` 新增 `share_code` 参数，新增 `get_share_code_info()` 方法
- **CLI**（`opscli/skills/marketplace/remote_installer.py`）：`install_remote_skill()` 新增 `share_code` 参数，Steps 1/2/6 透传
- **CLI**（`opscli/skills/commands/cli.py`）：`install_skill()` 命令新增 `--share-code` 选项

**验证结果**（2026-05-29 本地全链路验收）：
- Test 1: 查询不存在分享码 → `valid=false, reason="分享码不存在"` √
- Test 2: 创建分享码（max_uses=5）→ 返回 8 位大写码 `HMGYONTS`，`valid=true` √
- Test 3: 查询有效分享码 → 返回 `valid=true`，技能基础信息完整 √
- Test 4: 列出创建者视角分享码 → 正确返回列表含 `valid`/`remaining_seconds` √
- Test 5: 携带 share_code 获取 by-identifier（department 类型技能）→ 200 返回详情 √
- Test 6: 携带 share_code 获取 download URL → 200 返回 OSS 下载链接 √
- Test 7: 安装回调携带 share_code → `recorded=true` √
- Test 8: 安装回调后 used_count 从 0 变 1 √
- Test 9: 吊销分享码 → 200 删除成功 √
- Test 10: 吊销后查询 → `valid=false, reason="分享码已被吊销"` √
- Test 11: 用已吊销分享码获取技能详情 → 403 拒绝 √
- Test 12: CLI `--share-code` 参数 → 帮助文档正确显示 √

**影响范围**：skills 广场 personal/department 权限校验链路，`dm_skill_installs` 表新增两列（历史记录默认 `install_source=normal`，无影响）
**回滚方式**：
1. `php artisan migrate:rollback --step=2`（回滚两个 Migration）
2. git checkout 还原 5 个 PHP 文件（Service/Controller/routes）和 3 个 Python 文件（client/remote_installer/cli.py）
---


## 2026-06-08 Amazon Rufus - 本地浏览器状态改为明文 JSON 保存

**变更原因**：用户要求 Rufus 本地 Amazon 登录态去掉加密，直接明文保存，便于复制状态文件到其他环境复用；同时明确代码不需要兼容旧 `.bin` 密文迁移。

**改动点**：`RufusBrowserStateStore` 移除 Rufus 状态存储对 `Crypto` 和 `.browser-state-key` 的依赖，状态文件改为 `browser-state-<COUNTRY>.json`，以 UTF-8 明文 JSON 保存 `storage_state`、可选 `curl_data` 和 streaming seed 摘要，并保留 `0600` 文件权限；`load()` 只读取 `.json`，缺失时返回 `None`，不读取或迁移旧 `.bin`；`delete()` 只删除 `.json`。同步更新 backend secret、manager、CLI、cookie/curl parser 注释和 `ops-amazon-rufus` 模板/已安装 Skill 文案，明确本地明文状态敏感、旧 `.bin` 不再读取。

**验证结果**：RED：更新 Rufus 状态存储、cookie/curl 保存和 legacy `.bin` no-fallback 单测后，旧实现 6 failed，失败点为仍写 `.bin`、仍加密、仍创建/读取 `.browser-state-key`。GREEN：`uv run pytest "tests/amazon_rufus/test_core.py" -q` 通过（76 passed）；`uv run pytest "tests/mcp/test_amazon_rufus_tools.py" -q` 通过（6 passed）；`uv run pytest "tests/skills/test_ops_amazon_rufus_updater.py" -q` 通过（7 passed）。

**影响范围**：影响 Rufus 本地状态文件格式和登录态复用方式；MCP schema、CLI/MCP 输出脱敏、Rufus 报告格式和登录恢复主流程保持不变。旧 `.bin` 和 `.browser-state-key` 即使存在也不会被新版本读取，需要重新 `watch-login` 或 `save-state` 生成 `.json`。

**回滚方式**：回退 `opscli/amazon_rufus/services/browser_state_store.py`、相关注释文案、`ops-amazon-rufus` Skill 模板/已安装副本、`tests/amazon_rufus/test_core.py`、`tests/skills/test_ops_amazon_rufus_updater.py`、`.super-dev/changes/amazon-rufus-plaintext-state/` 和本条变更记录。

## 2026-06-06 Amazon Rufus - 固定接口 path 并复用 ops_url

**变更原因**：Rufus 默认题库和上传接口的 path 属于后端契约，不应暴露为用户配置项；用户明确要求只配置前缀域名/base URL，path 固定写在代码中，并继续复用 opscli 既有 `.env / config.ini / DEFAULTS` 环境切换模式。

**改动点**：删除 Rufus 专属 endpoint 配置项；`SkillsUpdater` 固定请求 `/opencalw/default-question-templates` 并按 `OPS_URL + 固定 path` 复用 ops 登录态；`RufusTransportClient` 固定提交 `/v1/rufus/upload` 并按 `ops_url + 固定 path` 发送，复用 ops 登录态、MCP API Key 透传和统一远端错误解析；`RufusManager` 保留显式 `submit_upload` 开关，CLI `opscli amazon-rufus get` 保留 `--submit-upload`，默认不上传，MCP 默认行为不变；Skill 和 Super Dev 文档同步说明只配置 `ops_url` / `OPSCLI_OPS_URL`。

**验证结果**：`.venv/Scripts/python.exe -m pytest "tests/auth/test_config.py" "tests/amazon_rufus/test_transport.py" "tests/amazon_rufus/test_core.py" "tests/mcp/test_amazon_rufus_tools.py" "tests/skills/test_ops_amazon_rufus_updater.py" "tests/skills/test_cli.py" -q` 通过，96 passed；补注释后 `.venv/Scripts/python.exe -m pytest "tests/amazon_rufus/test_transport.py" -q` 通过，3 passed；`.venv/Scripts/opscli.exe skills install ops-amazon-rufus --force --skills-dir ".agents/skills" --pretty` 成功；旧 Rufus endpoint 配置名与 Skill/mock/curl 暴露文案残留扫描无命中；`git diff --check` 通过，仅有既有 Windows 行尾 warning。

**影响范围**：影响 auth 配置读取、Rufus 默认题库升级、Rufus CLI 显式上传、Rufus 传输客户端、Skill reference 和相关测试；不改变 `amazon_rufus_get` MCP schema，不让 MCP 默认上传或返回 upload payload。

**回滚方式**：回退 `opscli/auth/config.py`、`opscli/skills/sync/updater.py`、`opscli/amazon_rufus/transport/client.py`、`opscli/amazon_rufus/services/manager.py`、`opscli/amazon_rufus/commands/cli.py`、Rufus Skill 文档和新增/调整测试。

## 2026-06-06 Amazon Rufus - 清理 MCP/Skill 手动状态导入暴露

**变更原因**：用户明确要求清理临时状态导入相关功能，不能出现在 MCP 或 Skill 中。Rufus 当前对 Agent 的稳定边界应保持为：Skill 只编排 `watch-login -> amazon_rufus_get` 等确认流程，MCP 只暴露 Rufus 获取工具，不暴露 cookie、headers、payload、curl 或本地状态写入入口。

**改动点**：清理 `ops-amazon-rufus` 模板 Skill、已安装 `.agents` Skill、README、workflow reference 和安装后 next_steps 中的手动 cookie/curl 状态导入指引；MCP schema 契约测试新增禁止 `curl`、`curl_data`、`payload_template`、`raw_curl` 等参数断言；Skill 文档契约测试新增禁止手动状态导入和浏览器复制请求文案断言。CLI 底层状态导入能力暂保留为服务层调试能力，但不再作为 Skill 或 MCP 用户路径暴露。

**验证结果**：已重新安装 `ops-amazon-rufus` 到 `.agents/skills` 并确认安装提示只包含登录监听和 `amazon_rufus_get`；`.venv/Scripts/python.exe -m pytest "tests/amazon_rufus/test_core.py" "tests/mcp/test_amazon_rufus_tools.py" "tests/skills/test_ops_amazon_rufus_updater.py" "tests/skills/test_cli.py" -q` 通过，87 passed。MCP/Skill 暴露面扫描无 mock、curl/curl_data、cookie 保存命令或浏览器复制请求路径；用户提供的敏感 cookie/curl 片段扫描无命中。

**影响范围**：影响 Rufus Skill 文档、已安装 Skill 副本、安装后提示、MCP schema 契约测试和 Super Dev 交付文档；不改变 `amazon_rufus_get` MCP 获取路径，不新增 MCP 参数，不输出敏感请求材料。

**回滚方式**：回退 `ops-amazon-rufus` 模板 Skill、`.agents` 已安装副本、`opscli/skills/commands/cli.py`、Rufus Skill/MCP 契约测试和本轮文档清理。

## 2026-06-06 ops-amazon-rufus - 补齐登录态保存闭环并重试 MCP

**变更原因**：`amazon_rufus_get` 默认通过后端/headless 链路读取本地加密浏览器状态并派生 Cookie header，但缺少用户完成 Amazon 登录后捕获并保存 Playwright `storage_state` 的生产入口，导致未登录或登录态失效时容易卡在 `RUFUS_SECRET_NOT_READY`，且 Skill 文档仍把登录后直接执行 CLI `get --launch-if-needed` 作为恢复路径。
**改动点**：`BrowserAttachService` 新增 `capture_storage_state()`，复用当前 CDP Chrome context 捕获 Playwright `storage_state`；`RufusManager` 新增 `save_state()`，按国家站点调用 `RufusBrowserStateStore.save()` 加密保存状态并返回非敏感摘要；CLI 新增 `opscli amazon-rufus save-state <COUNTRY>`，`init` 补齐 `--chrome-path` 和默认启用的 `--launch-if-needed`；安装后指引、模板 Skill、`.agents` 副本、workflow reference 和流程图统一为 `init --launch-if-needed -> 用户登录 -> save-state -> amazon_rufus_get`，并保留“宿主未暴露 MCP 工具时才使用 CLI get”的兼容边界；文档契约测试补充 `save-state` 和禁止旧恢复文案/`--new-chrome` 推荐的断言。
**验证结果**：RED：新增 `RufusManager.save_state()`、CLI `save-state`、`init --chrome-path`、安装后指引和文档契约测试后，先确认旧实现缺少对应生产入口和文档闭环。GREEN：`.venv/Scripts/python.exe -m pytest "tests/amazon_rufus/test_core.py" "tests/skills/test_cli.py" "tests/skills/test_ops_amazon_rufus_updater.py" "tests/mcp/test_amazon_rufus_tools.py" -q` 通过，73 passed in 2.13s；`node C:/Users/A/.agents/skills/pretty-mermaid/scripts/render.mjs --input "output/ops-amazon-rufus-cookie-flow.mmd" --output "output/ops-amazon-rufus-cookie-flow.svg" --format svg --theme github-light` 成功重渲染流程图。
**影响范围**：影响 Rufus CLI 登录态初始化/保存命令、`RufusManager` 公共接口、Browser attach 服务、ops-amazon-rufus Skill 文档与安装后 next steps、Rufus 流程图和相关测试；MCP 工具 schema 仍只暴露 `amazon_rufus_get`，不新增 cookie、localStorage、`storage_state`、CDP 参数或 remote 工具。
**回滚方式**：回退 `opscli/amazon_rufus/services/browser.py`、`opscli/amazon_rufus/services/manager.py`、`opscli/amazon_rufus/commands/cli.py`、`opscli/skills/commands/cli.py`、两侧 `ops-amazon-rufus` 文档、`tests/amazon_rufus/test_core.py`、`tests/skills/test_cli.py`、`tests/skills/test_ops_amazon_rufus_updater.py`、`output/ops-amazon-rufus-cookie-flow.*`、`.super-dev/changes/amazon-rufus-login-state-loop/` 和本条变更记录。
---

## 2026-06-05 ops-amazon-rufus - 恢复 CLI/Skill 的 CDP 兼容链路，MCP 继续禁用 CDP

**变更原因**：用户要求恢复 Rufus 的 CDP 代码，但明确限定 MCP 工具不再使用 CDP 链路；恢复后的 CDP 代码仅供 opscli CLI 与 Skill fallback 使用。本条用于修正上一条“彻底删除 CDP 与 remote 链路”中的 CLI/Skill 结论。
**改动点**：恢复 `opscli/amazon_rufus/services/browser.py`，提供本机 Chrome CDP 连接、seed request 捕获、`--launch-if-needed` 自动拉起和 `--chrome-path` 指定 Chrome 能力；`RufusManager` 恢复 `init()` 与 CDP `get()`，同时保留现有 `get_backend()` / `get_headless()`，并继续对空 `answers` 按正常结果处理；CLI `opscli amazon-rufus get` 恢复走 `RufusManager.get()`，重新暴露 `--cdp-url`、`--new-chrome`、`--keep-chrome-open`、`--chrome-path`、`--launch-if-needed`，同时恢复 `opscli amazon-rufus init`；MCP `amazon_rufus_get` 保持只调用 `get_backend()`，不恢复 `amazon_rufus_init`、`amazon_rufus_get_remote` 和任何 CDP 参数；同步更新 `ops-amazon-rufus` 模板与 `.agents` 副本文档，明确“默认 MCP headless，宿主无 MCP 时 CLI/CDP fallback”边界；补充/修正相关测试契约。
**验证结果**：RED：`uv run pytest "tests/amazon_rufus/test_core.py" -k "cli_help_exposes_init_and_cdp_options or cli_get_writes_manager_result_to_report_file or cli_get_outputs_manager_error or cli_init_calls_manager or manager_get_uses_browser_cdp_and_replay or manager_get_returns_reportable_result_when_answers_are_empty" -q` 在实现前 6 failed，证明 CLI 尚未恢复 init/CDP 入口，Manager 尚未恢复 `get()`/`browser` 注入；RED：`uv run pytest "tests/skills/test_ops_amazon_rufus_updater.py" -k "ops_amazon_rufus_template_uses_mcp_boundary" -q` 在文档更新前 1 failed，证明 Skill 文档仍未恢复 CLI/CDP fallback 指引。GREEN：`uv run pytest "tests/amazon_rufus/test_core.py" -q` 通过（47 passed）；`uv run pytest "tests/mcp/test_amazon_rufus_tools.py" -q` 通过（6 passed）；`uv run pytest "tests/skills/test_ops_amazon_rufus_updater.py" -q` 通过（5 passed）；`uv run pytest "tests/mcp/test_tools.py" -q` 通过（4 passed）；`git diff --check` 通过，仅有既有 LF/CRLF warning。
**影响范围**：影响 Rufus CLI help/参数、`RufusManager` 公共接口、Browser attach 服务、Skill fallback 文档和相关测试；MCP 工具暴露面、schema 和默认后端/headless 获取路径保持不变；remote/browser-state 捕获链路仍未恢复。
**回滚方式**：回退 `opscli/amazon_rufus/services/browser.py`、`opscli/amazon_rufus/services/manager.py`、`opscli/amazon_rufus/commands/cli.py`、`opscli/amazon_rufus/domain/exceptions.py`、两侧 `ops-amazon-rufus` 文档、相关测试，以及本条记录。
---

## 2026-06-05 ops-amazon-rufus - 彻底删除 CDP 与 remote 链路

**变更原因**：用户明确要求 Rufus MCP/CLI/Service/Skill 彻底删除 CDP 和 `amazon_rufus_get_remote` 链路，并要求空 `answers` 按正常结果处理，不再触发登录恢复判断。
**改动点**：`amazon_rufus_get` MCP 工具删除 CDP 兼容参数，MCP 注册只保留 `amazon_rufus_get`；CLI `amazon-rufus get` 改为直接调用 `RufusManager.get_backend()`，删除 `init` 子命令和 CDP/remote 参数；`RufusManager` 删除 CDP `init/get` 和 remote browser state 获取方法，`get_backend()` / `get_headless()` 空答案正常返回；删除 `services/browser.py` 和无引用 CDP/remote/login 异常；Skill 模板与 `.agents` 副本删除 remote authorization reference 和当前流程中的 CDP 指引；新增 `.super-dev/changes/amazon-rufus-remove-cdp/`。
**验证结果**：RED：`uv run pytest "tests/mcp/test_amazon_rufus_tools.py" -q` 在实现前 3 failed，证明 MCP 仍暴露 init/remote 和 CDP 参数；RED：`uv run pytest "tests/amazon_rufus/test_core.py" -k "cli_help_removes_init_and_cdp_options or cli_get_writes_manager_result_to_report_file or manager_get_backend_returns_reportable_result_when_answers_are_empty or manager_get_headless_returns_reportable_result_when_answers_are_empty" -q` 在实现前 4 failed，证明 CLI 仍有 init/CDP 参数且空答案仍抛登录错误；RED：`uv run pytest "tests/skills/test_ops_amazon_rufus_updater.py" -k "ops_amazon_rufus_template_uses_mcp_boundary" -q` 在文档更新前 1 failed，证明 Skill 仍含 CDP/remote 指引。GREEN：`uv run pytest "tests/amazon_rufus/test_core.py" -q` 通过（44 passed）；`uv run pytest "tests/mcp/test_amazon_rufus_tools.py" -q` 通过（6 passed）；`uv run pytest "tests/skills/test_ops_amazon_rufus_updater.py" -q` 通过（5 passed）；`uv run pytest "tests/mcp/test_tools.py" -q` 通过（4 passed）；Rufus 当前执行路径残留扫描无命中；`git diff --check` 通过。
**影响范围**：影响 Rufus MCP 工具 schema、CLI 参数兼容性、Manager 公共方法、Rufus Skill 当前编排文档和相关测试；默认题库、报告格式、headless capture 页面重试和 Rufus HTTP streaming 逻辑不改变。
**回滚方式**：回退 `opscli/mcp/tools/amazon_rufus.py`、`opscli/amazon_rufus/commands/cli.py`、`opscli/amazon_rufus/services/manager.py`、`browser_state_store.py`、`domain/exceptions.py`、删除文件恢复、Rufus Skill 文档、相关测试和 `.super-dev/changes/amazon-rufus-remove-cdp/`。
---

## 2026-06-04 ops-amazon-rufus - Rufus 获取默认改为每题 180 秒

**变更原因**：用户指出 MCP 内部 `timeout_seconds` 应表达“每个问题 3 分钟”，多题场景内部总等待预算应随问题数累加；原默认 90 秒不符合该业务约定，且容易与 MCP Router/宿主外层约 60 秒超时混淆。
**改动点**：新增 `opscli/amazon_rufus/constants.py` 定义 `DEFAULT_RUFUS_TIMEOUT_SECONDS=180`；`amazon_rufus_get`、`amazon_rufus_get_remote`、CLI `amazon-rufus get` 和 `RufusManager` 获取入口统一使用该默认值；新增 MCP、CLI、Manager、Headless client 测试，覆盖默认 180 秒和多题逐次传参；更新 `ops-amazon-rufus` workflow reference、架构/PRD 超时说明和 `.super-dev/changes/amazon-rufus-per-question-timeout/`。
**验证结果**：RED：`uv run pytest "tests/mcp/test_amazon_rufus_tools.py" "tests/amazon_rufus/test_core.py" -k "writes_report_and_filters_sensitive or remote_uses_manager_after_consent or manager_get_backend_defaults_to_three_minutes or headless_client_uses_timeout_for_each_question or cli_get_writes_manager_result_to_report_file" -q` 在实现前因默认仍为 90 秒失败。GREEN：同一定向命令通过（5 passed, 69 deselected）。回归：`uv run pytest "tests/mcp/test_amazon_rufus_tools.py" "tests/amazon_rufus/test_core.py" "tests/skills/test_ops_amazon_rufus_updater.py" -q` 通过（79 passed）。
**影响范围**：影响 Rufus MCP/CLI/Manager 获取默认超时；`amazon_rufus_init` 登录页打开超时仍为 30 秒；同步 MCP 外层请求上限不受内部 180 秒控制，长任务仍需后续异步 job/polling 架构。
**回滚方式**：回退 `constants.py`、上述 Python 默认值替换、相关测试、Skill reference、Super Dev change 文档和本条变更记录。
---

## 2026-06-04 ops-amazon-rufus - MCP 默认获取切换到后端 headless

**变更原因**：用户指出 `amazon_rufus_get` MCP 默认实现不应打开浏览器或依赖 Chrome CDP；应参考 extension/python 的 Rufus runner，用无头浏览器捕获上下文并通过后端 HTTP streaming 请求 Rufus。
**改动点**：新增 `opscli/amazon_rufus/services/backend_secret.py`，提供内部 Rufus secret/provider；新增 `RUFUS_SECRET_NOT_READY` 错误；`RufusManager` 新增 `get_backend()`，串联 secret、headless capture 和 streaming client；`amazon_rufus_get` 默认改调 `get_backend()`，不再向默认路径传 CDP 参数；同步更新 `ops-amazon-rufus` 模板和 `.agents` 副本的 README、SKILL、Rufus workflow/remote authorization reference；新增 `.super-dev/changes/amazon-rufus-mcp-headless-backend/` proposal/tasks；补充 MCP 与 Manager 单元测试。
**验证结果**：RED：`uv run pytest "tests/mcp/test_amazon_rufus_tools.py" -k "amazon_rufus_get_writes_report_and_filters_sensitive or amazon_rufus_get_accepts_multiple_questions or amazon_rufus_get_ignores_cdp_launch_options_on_default_backend_path or amazon_rufus_get_runs_manager_outside_event_loop" -q` 在实现前 4 failed，证明默认仍调用 CDP `get()`；RED：`uv run pytest "tests/amazon_rufus/test_core.py" -k "manager_get_backend" -q` 在实现前失败，原因是 `RufusManager.__init__()` 不支持 `backend_secret_provider`。GREEN：`uv run pytest "tests/mcp/test_amazon_rufus_tools.py" "tests/amazon_rufus/test_core.py" "tests/skills/test_ops_amazon_rufus_updater.py" -q` 通过（77 passed）。
**影响范围**：影响 MCP `amazon_rufus_get` 默认获取路径、Rufus Manager 后端入口、Rufus 授权状态缺失错误、ops-amazon-rufus Skill 默认编排文档；CLI 本机 CDP 兼容路径和 `amazon_rufus_get_remote` 安全门保留。
**回滚方式**：回退 `backend_secret.py`、`domain/exceptions.py`、`services/manager.py`、`mcp/tools/amazon_rufus.py`、Rufus Skill/README/reference、相关测试和 `.super-dev/changes/amazon-rufus-mcp-headless-backend/`。
---

## 2026-06-04 ops-amazon-rufus - CDP 未启动时自动发现并启动 Chrome

**变更原因**：Rufus CLI/MCP 获取依赖 Chrome CDP；当用户没有预先启动 CDP 时，当前流程会直接失败。用户要求 Skill/CLI 帮助先检查 CDP，未启动时搜索本机 Chrome，并通过 Python 启动带 CDP 的 Chrome。
**改动点**：
- `opscli/amazon_rufus/services/browser.py`：新增 CDP 存活探测、Chrome 路径发现、Python `subprocess.Popen()` 启动 CDP Chrome 的逻辑；`capture_seed_request()` 支持 `launch_if_needed` 与 `chrome_path`。
- `opscli/amazon_rufus/services/manager.py`：将已有 `launch_if_needed`、`chrome_path` 参数透传到浏览器捕获服务。
- `opscli/amazon_rufus/commands/cli.py`：将 `--launch-if-needed` 和 `--chrome-path` 从预留文案改为真实可用参数说明。
- `opscli/mcp/tools/amazon_rufus.py`：`amazon_rufus_get` 新增 `launch_if_needed` 与 `chrome_path` 参数，并透传到 Rufus Manager。
- `opscli/skills/templates/ops-amazon-rufus/SKILL.md`、`.agents/skills/ops-amazon-rufus/SKILL.md`、两份 README：新增 `CHROME_CDP_UNAVAILABLE` 处理分支，推荐 `launch_if_needed=True`，自动搜索失败时再询问 `chrome_path`。
- `tests/amazon_rufus/test_core.py`、`tests/mcp/test_amazon_rufus_tools.py`、`tests/skills/test_ops_amazon_rufus_updater.py`：新增 CDP 自动启动、参数透传和 Skill 文档契约测试。
**验证结果**：
- RED：`uv run pytest "tests/amazon_rufus/test_core.py" -k "launch_if_needed or chrome_path" -q` 在实现前失败，失败点为缺少 `_is_cdp_available`、Manager 未透传参数。
- RED：`uv run pytest "tests/mcp/test_amazon_rufus_tools.py" -k "launch_if_needed or chrome_path" -q` 在实现前失败，失败点为 MCP 工具不接收 `launch_if_needed`。
- RED：`uv run pytest "tests/skills/test_ops_amazon_rufus_updater.py" -k "mcp_boundary" -q` 在文档更新前失败，失败点为 Skill 文档缺少 `CHROME_CDP_UNAVAILABLE` 分支。
- GREEN：`uv run pytest "tests/amazon_rufus/test_core.py" -k "launch_if_needed or chrome_path" -q` 通过（5 passed）。
- GREEN：`uv run pytest "tests/mcp/test_amazon_rufus_tools.py" -k "launch_if_needed or chrome_path" -q` 通过（1 passed）。
- GREEN：`uv run pytest "tests/skills/test_ops_amazon_rufus_updater.py" -k "mcp_boundary" -q` 通过（1 passed）。
- 模块回归：`uv run pytest "tests/amazon_rufus/test_core.py" -q` 通过（59 passed）。
- MCP Rufus 回归：`uv run pytest "tests/mcp/test_amazon_rufus_tools.py" -q` 通过（9 passed）。
- Skill 回归：`uv run pytest "tests/skills/test_ops_amazon_rufus_updater.py" -q` 通过（5 passed）。
- MCP 工具回归：`uv run pytest "tests/mcp/test_tools.py" -q` 通过（4 passed）。
- Help 检查：`uv run python -c "from typer.testing import CliRunner; from opscli.amazon_rufus.cli import app; r=CliRunner().invoke(app, ['get','--help']); print(r.exit_code); print('--launch-if-needed' in r.stdout, '--chrome-path' in r.stdout, '预留' in r.stdout)"` 输出 `0`、`False True False`；Rich 表格将长选项截断显示为 `--launch-if-nee...`，但 `--chrome-path` 可见且“预留”文案已移除。
- Diff 检查：`git diff --check -- ...` 通过；仅出现 Windows 行尾转换 warning。
**影响范围**：影响 Rufus 本机 CDP 获取前置流程、MCP `amazon_rufus_get` 参数和 `ops-amazon-rufus` Skill 编排；默认题库、单题/多题、远程授权和报告生成不改变。
**回滚方式**：回退上述 Python、测试、Skill/README 文档和 `.super-dev/changes/amazon-rufus-cdp-autolaunch/` 目录改动。
---

## 2026-06-04 ops-amazon-rufus Skill - 拆分主文档与 references

**变更原因**：`ops-amazon-rufus` 主 `SKILL.md` 承载了 MCP 调用、CDP 排障、远程授权、问题来源和输出规则等大量细节，影响 Agent 首屏读取效率；用户要求主文档只保留前置条件、流程和文件说明，具体规范拆到 `references/`。

**改动点**：精简 `opscli/skills/templates/ops-amazon-rufus/SKILL.md` 与 `.agents/skills/ops-amazon-rufus/SKILL.md`；精简两侧 README；新增两侧 `references/rufus-mcp-workflow.md` 与 `references/remote-authorization.md`；更新 `question-templates.md` 的流程引用；更新 `tests/skills/test_ops_amazon_rufus_updater.py` 文档边界断言。

**验证结果**：`uv run pytest "tests/skills/test_ops_amazon_rufus_updater.py" -v` 通过，5 passed。`pytest ...` 与 `python -m pytest ...` 在当前环境不可用，原因分别是 PATH 找不到 pytest、全局 Python 未安装 pytest。`uv run pytest "tests/skills" -v -s` 可运行但存在多项无关既有失败，集中在缺失 `ops-dataset-query/scripts/*`、`ops-methods-card/scripts/xlsx_preview.py`、版本/路径断言漂移等。

**影响范围**：仅影响 `ops-amazon-rufus` Skill 文档结构、已安装 `.agents` 副本和对应文档断言测试；不改变 Rufus MCP 工具 schema、Python 获取实现或题库数据。

**回滚方式**：回退两侧 `SKILL.md`、`README.md`、新增的 `references/rufus-mcp-workflow.md`、`references/remote-authorization.md`、`question-templates.md` 引用调整和测试断言修改。

---

## 2026-06-04 ops-amazon-rufus - 支持 `-q/--question` 多临时问题

**变更原因**：用户要求 Rufus CLI 支持类似 `-q` 的参数，并能一次输入多个临时问题来提问，同时跳过默认问题模板；现有实现仅支持 `--question` 单题。
**改动点**：
- `opscli/amazon_rufus/commands/cli.py`：将 `--question` 改为可重复选项，并新增 `-q` 短参数；单题继续走旧 `question` 参数，多题走 `questions` 列表参数。
- `opscli/amazon_rufus/services/manager.py`：新增 `questions` 参数，统一解析单题、多题和默认题库三种问题来源；多题模式跳过题库读取。
- `opscli/mcp/tools/amazon_rufus.py`：`amazon_rufus_get` 与 `amazon_rufus_get_remote` 新增 `questions` 入参，并透传给 Rufus Manager。
- `tests/amazon_rufus/test_core.py`、`tests/mcp/test_amazon_rufus_tools.py`：新增 CLI、Manager、MCP 多题模式回归测试。
- `opscli/skills/templates/ops-amazon-rufus/SKILL.md`、`.agents/skills/ops-amazon-rufus/SKILL.md`、两份 README：同步单题、多题临时问题和默认题库的选择规则。
**验证结果**：
- RED：`uv run pytest "tests/amazon_rufus/test_core.py" -k "multiple_questions" -q` 在实现前失败，失败原因为 `RufusManager.get()` 和 MCP 工具缺少 `questions` 参数，CLI `-q` 未生成报告。
- GREEN：`uv run pytest "tests/amazon_rufus/test_core.py" -k "multiple_questions" -q` 通过（2 passed）。
- GREEN：`uv run pytest "tests/mcp/test_amazon_rufus_tools.py" -k "multiple_questions" -q` 通过（1 passed）。
- 兼容回归：`uv run pytest "tests/amazon_rufus/test_core.py" -k "passes_question or multiple_questions or remote_rufus_calls or login_required_accepts_remote_flow or login_required_decline_keeps_local_flow" -q` 通过（6 passed）。
- MCP 回归：`uv run pytest "tests/mcp/test_amazon_rufus_tools.py" -q` 通过（5 passed）。
- 模块回归：`uv run pytest "tests/amazon_rufus/test_core.py" -q` 通过（54 passed）。
- Skill 回归：`uv run pytest "tests/skills/test_ops_amazon_rufus_updater.py" -q` 通过（5 passed）。
- MCP 工具回归：`uv run pytest "tests/mcp/test_tools.py" -q` 通过（4 passed）。
- Help 检查：`uv run python -c "from typer.testing import CliRunner; from opscli.amazon_rufus.cli import app; r=CliRunner().invoke(app, ['get','--help']); print(r.exit_code); print('--question' in r.stdout, '-q' in r.stdout)"` 输出 `0`、`True True`。
- Diff 检查：`git diff --check -- ...` 通过；仅出现 Windows 行尾转换 warning。
**影响范围**：影响 `opscli amazon-rufus get` 的问题参数解析、`RufusManager` 临时问题入口和 MCP Rufus 工具参数；默认题库模式、单题旧调用、远程授权和报告格式保持兼容。
**回滚方式**：回退上述 Python、测试和 Skill/README 文档改动，并删除 `.super-dev/changes/amazon-rufus-multi-question-cli/`。
---

## 2026-06-03 ops-amazon-rufus - 未登录时远程 Rufus 授权获取

**变更原因**：用户要求 Rufus CLI 在 Amazon 未登录时先征得用户同意，再通过干净且未绑定信用卡的用户自有账户远程获取 Rufus 数据；同意后需保存 cookie 与 localStorage，并调用已有 Rufus 获取链路继续原 Skill 流程。
**改动点**：
- `opscli/amazon_rufus/services/browser_state_store.py`：新增浏览器状态存储服务，捕获 Playwright `storage_state()`，加密保存 Amazon cookie/localStorage，并从目标站点状态构造 Cookie header。
- `opscli/amazon_rufus/services/headless_capture.py`：支持传入 `storage_state` 创建 headless browser 上下文，确保远程授权状态进入 Rufus seed request 捕获链路。
- `opscli/amazon_rufus/services/manager.py`：新增 `get_remote_from_storage_state()` 与 `get_remote_from_browser()`，保存授权状态后复用现有 `get_headless()` Rufus 获取链路。
- `opscli/amazon_rufus/commands/cli.py`：新增 `--remote-rufus` 参数；本机流程遇登录中断且处于交互终端时，先询问用户是否同意远程获取，不同意则保留现有流程。
- `tests/amazon_rufus/test_core.py`：新增状态加密保存、远程状态调用 headless 服务、CLI 强制远程/用户同意/用户拒绝分支，以及远程报告不输出敏感状态的回归测试。
- `opscli/skills/templates/ops-amazon-rufus/SKILL.md`、`.agents/skills/ops-amazon-rufus/SKILL.md`、`opscli/skills/templates/ops-amazon-rufus/README.md`：同步未登录远程授权规则、敏感数据不输出要求和 `--remote-rufus` 用法。
**验证结果**：
- 定向 TDD：`uv run pytest "tests/amazon_rufus/test_core.py" -k "browser_state_store or remote_from_storage_state or remote_rufus_calls" -q` 为 3 passed。
- 交互分支回归：`uv run pytest "tests/amazon_rufus/test_core.py" -k "remote_rufus_calls or login_required_accepts_remote_flow or login_required_decline_keeps_local_flow" -q` 为 3 passed。
- 模块回归：`uv run pytest "tests/amazon_rufus/test_core.py" -q` 为 51 passed。
**影响范围**：影响 `opscli amazon-rufus get` 在 Amazon 未登录或登录态不可用时的交互分支；默认本机获取流程、题库读取、拒答改写和报告生成保持原有行为。
**回滚方式**：回退上述 Python、测试和 Skill/README 文档改动，并删除 `.super-dev/changes/amazon-rufus-remote-consent/`。
---

## 2026-06-03 ops-amazon-rufus - 新增 cookie 驱动的 headless Rufus 获取入口

**变更原因**：用户要求在 Rufus 获取方法中显式传入 Amazon `cookie`，并参考 Python 端 headless 实现，用该 `cookie` 获取 Rufus 数据，避免继续依赖本机可见 Chrome 登录态。
**改动点**：
- `opscli/amazon_rufus/domain/exceptions.py`：新增 `InvalidRufusCookieError`、`HeadlessRufusCaptureError`、`HeadlessRufusRequestError`。
- `opscli/amazon_rufus/services/headless_capture.py`：新增 headless 捕获服务，使用 Playwright `sync_playwright()` + `chromium.launch(headless=True)`，将传入 `cookie` 注入浏览器上下文并捕获 `rufus/cl/streaming` seed request。
- `opscli/amazon_rufus/services/headless_client.py`：新增 headless Rufus 请求客户端，复用 `RufusReplayService.build_payload()` 构造 payload，并用同一份 `cookie` 发起 `/rufus/cl/streaming` 请求后解析 SSE。
- `opscli/amazon_rufus/services/manager.py`：新增 `get_headless(..., cookie=...)`，串联 headless 捕获与 Rufus 请求，返回与现有 `get()` 兼容的数据结构。
- `tests/amazon_rufus/test_core.py`：新增 `cookie` 为空的稳定错误测试，以及 `cookie` 同时传入捕获与请求链路的回归测试。
**验证结果**：
- `uv run pytest "tests/amazon_rufus/test_core.py" -k "headless" -q` 通过（2 passed）
- `uv run pytest "tests/amazon_rufus/test_core.py" -q` 通过（46 passed）
**影响范围**：仅影响 `opscli.amazon_rufus` 的 Python SDK 入口；现有 `opscli amazon-rufus get/init` 的本机 CDP 流程不变。
**回滚方式**：回退上述 Python 文件、`tests/amazon_rufus/test_core.py` 中新增断言，以及 `.super-dev/changes/amazon-rufus-cookie-headless/` 目录。
---

## 2026-05-27 ops-creator-skill - 新增技能广场发布门禁章节

**变更原因**：从 skill 定义中提取"发布到技能广场"相关规则，补充到 SKILL.md，确保创建/优化 Skill 后有明确的版本号更新和发布流程。
**改动点**：
- `opscli/skills/templates/ops-creator-skill/SKILL.md`：
  - 新增「技能广场发布门禁」章节（版本号更新规则、新建/优化发布策略、触发条件、禁止行为）
  - 工作流新增步骤 12「发布门禁」
  - 完成定义新增版本号更新和发布流程两项检查
**验证结果**：文件结构完整，新增内容与现有章节无冲突
**影响范围**：ops-creator-skill 的创建和优化流程
**回滚方式**：git checkout 还原 SKILL.md
---

## 2026-05-22 ops-dataset-query Skill - 合并 data-fetch-constraints.md 业务规则

**变更原因**：用户提供了 data-fetch-constraints.md（取数约束与已知翻车用例），其中包含大量 ops-dataset-query 缺失的业务层面规则。与现有规则对比后，发现 1 处冲突（时间口径，以 ops-dataset-query 为准）和 18+ 条可新增规则。
**改动点**：
- `references/rules.md`（572→764行）：
  - 一章末尾：新增 §1.5（缺省值默认执行）、§1.6（上下文继承规则）
  - 二章末尾：新增 §2.3（team_name/dept_name 独立）、§2.4（店铺/渠道/平台严格区分）
  - 五章末尾：新增 §5.4（数据集优先级：经营 vs 广告）
  - 九章自检清单：新增 5 条检查项（取数状态/平台过滤/范围继承/全量展示/self_small_cat）
  - 新增十三至十八章：取数状态格式、平台过滤强制规则、内部口径常识、部门下钻规则、self_small_cat 限制、典型用例防错补充
- `SKILL.md`：新增铁律十四（禁止静默截断数据，全量展示优先）
**验证结果**：grep 确认所有章节标题存在，rules.md 共 764 行，SKILL.md 铁律十四已写入
**影响范围**：所有通过 ops-dataset-query Skill 发起取数的 AI Agent 会话，行为更贴合 Aukeys 运营业务口径
**回滚方式**：git revert 对应提交，或手动删除 §1.5/§1.6/§2.3/§2.4/§5.4 和十三~十八章，删除铁律十四

---

## 2026-05-23 文档更新 - categories 命令及自动分类匹配补录

**变更原因**：新增 `marketplace categories` 命令及 publish/edit 自动分类匹配功能后，需同步更新用户文档
**改动点**：
- `docs/guide/opscli命令用例手册.md`：命令总览树加入 `categories`；7.10 技能广场新增 `marketplace categories` 命令完整文档；7.6 publish 和 7.8 edit 参数表及说明加入自动分类匹配注释；场景六加入 `categories` 查看步骤；第 12 节快速索引更新
- `README.md`：mermaid 命令树加入 `mp_categories`；功能概述更新；技能广场章节新增 `categories` 命令文档及说明；`publish` 参数表更新；完整使用示例加入 `categories` 步骤和自动匹配注释
**验证结果**：文档内容与代码实现一致
**影响范围**：仅文档，无代码变更
**回滚方式**：还原两个文档文件到本次改动前版本
---

## 2026-05-23 skills marketplace - 新增 categories 命令 + 发布/编辑自动分类匹配

**变更原因**：发布/编辑技能时需要手动查询分类 ID 后填 `--category INT`，体验不友好；`marketplace list --category` 过滤功能存在但分类列表无法通过独立命令查看。
**改动点**：
- `opscli/skills/commands/marketplace_cli.py`：在 `list` 命令之前新增 `categories` 子命令，调用 `MarketplaceClient.get_categories()` 并以富文本表格展示所有分类（ID/slug/名称），支持 `--json` 输出
- `opscli/skills/commands/publish_cli.py`：
  - 新增 `_match_best_category()` 辅助函数：基于关键词评分（slug/name 直接子串命中得 2 分，分词子串命中得 1 分）
  - `publish_skill()`：当 `resolved_cat` 为 None 时，自动获取分类列表并调用 `_match_best_category()` 自动填充；非 JSON 模式下输出"已自动匹配分类"提示；失败时静默跳过
  - `edit_skill()`：同上，当 `category_id` 为 None 时自动匹配，信息来源优先用 CLI 参数，兜底从 skill_data 读取
- `opscli/skills/templates/ops-skills/SKILL.md`：版本从 v1.7.0 升至 v1.7.1，新增 `marketplace categories` 命令文档，`publish`/`edit` 说明中加入自动分类匹配行为注释
- `opscli/skills/templates/ops-skills/data/VERSION.json`：版本从 1.7.0 升至 1.7.1
**验证结果**：`opscli skills marketplace categories --help` 正常显示，`opscli skills marketplace --help` 命令列表包含 `categories`；`_match_best_category` 单元测试验证 ops-auth→auth、ops-dataset-query→data-query 正确匹配，my-skill 无匹配返回 None
**影响范围**：marketplace categories 新命令；publish/edit 当未传 --category 时行为变更（多一次 get_categories 请求 + 静默自动填充分类）
**回滚方式**：还原 `marketplace_cli.py`、`publish_cli.py`、`ops-skills/SKILL.md`、`ops-skills/data/VERSION.json` 四个文件到本次改动前版本
---

## 2026-05-23 skills publish 命令 - 新版本发布补充元数据字段

**变更原因**：新版本发布路径使用 `publish_version`（`POST /v1/skills/{id}/versions`），该 API 只接受 `version`/`changelog`，不接受 `summary`/`title` 等元数据字段，导致广场展示信息在版本更新后不同步。
**改动点**：
- `opscli/skills/commands/publish_cli.py` 新版本发布路径：从 `client.publish_version()` 切换为 `client.full_update_skill()`（`POST /v1/skills/{id}`），该 API 同时支持元数据更新+文件上传+版本创建
- `fields` 从只含 `version` 扩展为与首次发布一致的完整元数据（version、title、description、summary、tags、share_type、category_id）
- 新版本发布成功后的终端输出增加 `分享权限` 和 `一句话` 展示行
**验证结果**：发布 ops-asin-health-diagnoser v0.2.2，广场返回 `summary` 已正确写入，`latest_version` 正确更新为 0.2.2
**影响范围**：所有通过 `opscli skills publish` 发布新版本的操作，广场元数据将同步更新
**回滚方式**：将新版本路径恢复为 `client.publish_version()` + `fields = {"version": version}`
---

## 2026-05-23 ops-creator-skill Skill - 强制发布确认门禁 v0.4.3

**变更原因**：优化 ops-asin-health-diagnoser 时未触发发布确认，根因是发布确认逻辑嵌套在步骤 18/24 的大段落中，容易被跳过；且缺少独立收敛步骤确保所有路径都必须经过发布确认。
**改动点**：
- 新增 `data/VERSION.json`（`{"name": "ops-creator-skill", "version": "0.4.3"}`），补齐铁律14要求
- 新增步骤 25 作为强制最终收敛点，所有路径（新建/改造/优化）必须经过
- 步骤 18/24 中的发布段落简化为指向步骤 25 的引用（"必须继续执行步骤 25 的强制发布确认门禁"）
- 新增独立章节 `## [强制] 技能广场发布确认门禁`，类似 ops-skills 认证门禁风格
- 步骤 25 包含完整 AskUserQuestion 模板（三选一：全员发布/部门发布/暂不发布）
- 步骤 25 包含版本号准备流程（新建/改造两条路径）和发布命令
**验证结果**：文件结构正确，步骤 18/24/25 引用链完整，独立门禁章节位置正确
**影响范围**：所有通过 ops-creator-skill 创建或优化 Skill 的会话
**回滚方式**：恢复步骤 18/24 中的原始发布段落，删除步骤 25 和独立门禁章节
---

## 2026-05-23 ops-asin-health-diagnoser Skill - 全面框架重构 v0.2.0

**变更原因**：旧版 SKILL.md 缺少统一框架标准章节，1174 行通用 dev guide 造成巨大上下文负担，CLI/MCP 脚本 90% 代码重复，缺少执行日志和测试机制。
**改动点**：
- `SKILL.md`：按统一框架标准重写，增加快速开始、必要参数、日常工作流、默认执行策略、按需加载资料、执行日志与候选提交章节；修复 GBK 不安全字符（输出模板中 ⚠️✅ → [!][OK]）
- `references/data-query-service-dev-guide.md`：删除（1174 行通用文档）
- `references/data-recipes.md`：新建，从 dev guide 中精简为 ASIN 诊断专用固化查询 recipe（~120 行）
- `references/operating-rules.md`：新建，完整判断规则、行动建议矩阵、新品例外、边界条件（从脚本代码和 threshold_reference 提取）
- `references/testing-benchmark.md`：新建，4 个测试用例（正常/边界/批量/异常）+ 断言 + 基准对比
- `references/cross-tool-portability.md`：新建，跨工具降级方案和迁移检查清单
- `references/cli.md`：精简，去除重复认证流程和阈值表（209→98 行）
- `references/mcp.md`：精简，去除重复认证流程和阈值表（363→95 行）
- `references/dataset_fields_mapping.md`：修复 GBK 不安全字符
- `scripts/calculate_health_score.py`：合并 CLI 和 MCP 为统一入口，支持 --weights/--benchmarks/--batch
- `scripts/calculate_health_score_mcp.py`：删除（已合并到统一入口）
- `scripts/record_run.py`：新建，执行日志记录脚本
- `data/VERSION.json`：v0.1.0 → v0.2.0
**验证结果**：待 smoke 测试验证
**影响范围**：ops-asin-health-diagnoser Skill 的所有用户；CLI 命令 `calculate_health_score_mcp.py` 不再存在，统一使用 `calculate_health_score.py`
**回滚方式**：`git checkout HEAD -- opscli/skills/templates/ops-asin-health-diagnoser/`
---

## 2026-05-23 ops-creator-skill Skill - 新增技能广场发布确认步骤

**变更原因**：Skill 创建/优化完成后，用户希望直接发布到技能广场（全员可见），免去手动执行 `opscli skills publish` 的步骤。
**改动点**：
- `opscli/skills/templates/ops-creator-skill/SKILL.md`：
  - Step 18（起草 Skill）后新增发布确认：使用 AskUserQuestion 询问"发布到技能广场"或"暂不发布"，选择发布时调用 ops-skills Skill 执行认证门禁 + `opscli skills publish --share-type company`
  - Step 24（迭代优化）后新增重新发布确认：版本号递增 + 再次发布新版本
- `opscli/skills/templates/ops-creator-skill/scripts/brief_to_skill.py`：
  - 新增 `import json`
  - `build_skill_md()` frontmatter 新增 `version: v0.0.1`
  - `main()` 新增生成 `data/VERSION.json`（`{"name": "<skill_name>", "version": "0.0.1"}`）
**验证结果**：脚本语法正确，json 模块已导入并用于 VERSION.json 生成；SKILL.md 发布步骤与 ops-skills publish 命令参数一致
**影响范围**：ops-creator-skill 工作流 Step 18 和 Step 24 的后续行为；brief_to_skill.py 生成的 Skill 草案目录结构
**回滚方式**：删除 SKILL.md 中两段"发布确认"段落；撤销 brief_to_skill.py 的 3 处改动
---

## 2026-05-22 ops-dataset-query Skill - 合并 data-fetch-constraints.md 业务规则

**变更原因**：用户提供了 data-fetch-constraints.md（取数约束与已知翻车用例），其中包含大量 ops-dataset-query 缺失的业务层面规则。与现有规则对比后，发现 1 处冲突（时间口径，以 ops-dataset-query 为准）和 18+ 条可新增规则。
**改动点**：
- `references/rules.md`（572→764行）：
  - 一章末尾：新增 §1.5（缺省值默认执行）、§1.6（上下文继承规则）
  - 二章末尾：新增 §2.3（team_name/dept_name 独立）、§2.4（店铺/渠道/平台严格区分）
  - 五章末尾：新增 §5.4（数据集优先级：经营 vs 广告）
  - 九章自检清单：新增 5 条检查项（取数状态/平台过滤/范围继承/全量展示/self_small_cat）
  - 新增十三至十八章：取数状态格式、平台过滤强制规则、内部口径常识、部门下钻规则、self_small_cat 限制、典型用例防错补充
- `SKILL.md`：新增铁律十四（禁止静默截断数据，全量展示优先）
**验证结果**：grep 确认所有章节标题存在，rules.md 共 764 行，SKILL.md 铁律十四已写入
**影响范围**：所有通过 ops-dataset-query Skill 发起取数的 AI Agent 会话，行为更贴合 Aukeys 运营业务口径
**回滚方式**：git revert 对应提交，或手动删除 §1.5/§1.6/§2.3/§2.4/§5.4 和十三~十八章，删除铁律十四

---

## 2026-05-21 ops-dataset-query Skill - 补充 Catalog 命中失败回退规则与库存周转本地意图种子

**变更原因**：本次物控库存周转查询中，远端 catalog 只有1个意图（账单销售趋势），未能命中"库存周转"查询需求。SKILL.md 铁律三对"catalog 未命中时如何回退"的描述不清晰，导致 AI 可能在 catalog 返回少量意图时陷入不确定状态。同时 `data/dataset_catalog.json` 模板种子为空，新用户缺少本地意图 fallback。

**改动点**：
- `opscli/skills/templates/ops-dataset-query/SKILL.md`：铁律三新增"Catalog 命中失败的回退规则"，明确 intent_count=0 或无匹配时必须立即静默回退到 search.py，不得提示用户或暂停等待
- `opscli/skills/templates/ops-dataset-query/references/cli.md`：典型工作流新增"Catalog 未命中时的回退工作流"章节，含示例代码和"何时用 catalog vs 本地搜索"对比表
- `opscli/skills/templates/ops-dataset-query/data/dataset_catalog.json`：从空种子升级为包含2个物控库存周转意图（ds_97zj6R0KDKpB / ds_dI5gNc0YRLrD）的本地 fallback，version 从 v0.0.0 升至 v1.0.1

**验证结果**：`python3 -c "import json; d=json.load(open(...dataset_catalog.json)); print(d['intent_count'])"` 输出 2，intent 字段完整。

**影响范围**：ops-dataset-query Skill 的 AI Agent 行为规范，下次安装/分发模板的新用户可获得本地库存周转意图种子

**回滚方式**：git checkout 还原三个文件

---

## 2026-05-21 ops-dataset-query Skill - 修复 CLI 权限校验文档中的两处错误

**变更原因**：本次物控库存周转查询实际执行过程中，AI 遵循 `references/rules.md` 第12章 CLI 模式步骤时出现两处报错：① `dataset_select_columns.csv` 读取 `KeyError: 'current_dataset_alias'`；② `opscli query simple` 报 `No such option: --dimensions`。
**改动点**：
- `references/cli.md`：CSV 读取示例补充 `encoding='utf-8-sig'`，防止 BOM 导致 KeyError
- `references/rules.md` 第12.3步骤三：CLI 模式示例全部重写，补充"先从 datasets.csv 查整数 table_id"步骤，并改用正确的 `--json` 传参方式替换不存在的 `--dimensions` 参数
- `references/rules.md` 第12.4示例：CLI 模式权限查询示例同步修正
- 上述四处修改同时应用于 `opscli/skills/templates/` 和 `~/.claude/skills/` 两个目录
**验证结果**：本次查询实际执行流程验证可用，修正后的示例代码与实际 CLI 行为一致
**影响范围**：仅影响 AI Agent 遵循文档执行 CLI 权限校验时的行为，不影响 MCP 模式和实际查询逻辑
**回滚方式**：还原 `references/cli.md` 和 `references/rules.md` 对应段落至修改前内容
---

## 2026-05-20 全局 - 修复 Windows GBK 编码崩溃

**变更原因**：`opscli skills install`、`opscli auth doctor`、`opscli auth token refresh --all` 等命令在 Windows PowerShell（GBK 编码）下因输出 `↻` `✓` `✗` `⚠️` `✅` `🔴` `❓` `⭐` 等 Unicode 字符触发 `UnicodeEncodeError` 导致命令崩溃。
**改动点**：
- `opscli/skills/commands/cli.py`：`↻` → `↑`，`✓` → `√`，`✗` → `×`
- `opscli/auth/cli.py`：`✓` → `√`（18 处），`✗` → `×`（8 处）
- `opscli/query/services/manager.py`：`⚠️` → `[!]`（1 处）
- `opscli/skills/templates/ops-asin-health-diagnoser/scripts/core.py`：`✅` → `√`，`⚠️` → `!`，`🔴` → `X`，`❓` → `?`，`⭐` 移除
- `opscli/cli.py`：CLI 入口 `main()` 增加 Windows 编码兜底（`sys.stdout/stderr.reconfigure(errors='replace')`）
**验证结果**：全面扫描后确认终端输出路径不再有 GBK 不兼容字符
**影响范围**：所有 CLI 命令和 Skill 脚本的终端状态图标；Windows 用户不再因 GBK 编码崩溃
**回滚方式**：还原各字符替换，删除 `cli.py` 中 Windows 编码兜底代码块
---

## 2026-05-15 ops-amazon-rufus Skill - 登录中断不提交 feedback

**变更原因**：Rufus 采集依赖 Amazon 人工登录态，`RUFUS_LOGIN_REQUIRED` 和登录态导致的 `SEED_REQUEST_NOT_CAPTURED` 是正常交互中断，不应触发项目级失败反馈规则或生成 feedback 文件。
**改动点**：
- `opscli/skills/templates/ops-amazon-rufus/SKILL.md`：在登录中断续跑规则中补充 `SEED_REQUEST_NOT_CAPTURED` 登录场景，并明确禁止调用 `ops-feedback`、`opscli feedback submit` 或创建 `output/amazon-rufus/feedback-*.json`。
- `.agents/skills/ops-amazon-rufus/SKILL.md`：同步当前 Agent 安装副本。
**验证结果**：使用 `rg` 检查两份 Skill 文档均命中 `SEED_REQUEST_NOT_CAPTURED`、`ops-feedback`、`feedback-*.json` 和登录中断规则。
**影响范围**：仅影响 `ops-amazon-rufus` Skill 执行规范；不改变 `opscli amazon-rufus get` 代码、错误码或报告生成逻辑。
**回滚方式**：回退两份 `SKILL.md` 中新增的登录中断 feedback 豁免说明，并移除此变更记录。

---

## 2026-05-15 Amazon Rufus - 无答案时保留浏览器并等待继续

**变更原因**：`ops-amazon-rufus` 在已捕获 Rufus 请求但没有获取到答案时，常见原因是 Amazon 登录态失效；原流程可能继续生成空答案报告，并在 `--new-chrome` 场景关闭浏览器，导致用户无法登录后继续。
**改动点**：
- `opscli/amazon_rufus/domain/exceptions.py`：新增 `RufusLoginRequiredError`，稳定错误码为 `RUFUS_LOGIN_REQUIRED`。
- `opscli/amazon_rufus/services/browser.py`：允许 `on_captured` 回调返回保留窗口信号，登录中断场景不关闭本次新开的 Chrome。
- `opscli/amazon_rufus/services/manager.py`：新增空答案判定；当所有答案均无可展示内容时抛出登录中断异常。
- `opscli/skills/templates/ops-amazon-rufus/SKILL.md` 和 `.agents/skills/ops-amazon-rufus/SKILL.md`：新增未获取答案时停止执行、保留浏览器并等待用户说“继续”的规则。
- `tests/amazon_rufus/test_core.py`：新增 Manager、Browser、CLI 三个回归测试。
**验证结果**：
- RED：`uv run pytest "tests/amazon_rufus/test_core.py" -k "login_required or callback_requests or outputs_login_required" -q` 在实现前 3 个新增测试失败，覆盖浏览器关闭、通用错误码和 Manager 未抛错三个缺口。
- GREEN：`uv run pytest "tests/amazon_rufus/test_core.py" -k "login_required or callback_requests or outputs_login_required" -q` 通过（3 passed）。
- 回归：`uv run pytest "tests/amazon_rufus/test_core.py" -q` 通过（44 passed）。
- 文档检查：`rg -n "RUFUS_LOGIN_REQUIRED|继续告诉我|不要关闭浏览器窗口" ...` 命中两份 Skill 文档。
**影响范围**：影响 `opscli amazon-rufus get` 在已捕获请求但无可用答案时的失败语义；正常有答案报告、未捕获 streaming、题库读取、单题模式和报告格式化不变。
**回滚方式**：回退上述 Python 文件、两份 Skill 文档、测试文件和 `.super-dev/changes/amazon-rufus-login-resume/`，恢复空答案报告行为和默认关闭 Chrome 逻辑。

---

## 2026-05-14 ops-dataset-query Skill - 移除 innerWhere 相关描述

**变更原因**：服务端不再接受 `innerWhere` 参数，Skill 文档中所有涉及该参数的描述、铁律、示例需全部清除，避免 AI Agent 错误构造已废弃字段。
**改动点**：
- `SKILL.md`：删除铁律四（子查询强制简化接口）及文档入口第4条；铁律五～十二重新编号为四～十一
- `QUERY_SPEC.md`：删除铁律3（innerWhere禁用）和铁律10（子查询必带日期过滤）；删除整个"十三章 innerWhere 数据集铁律"；更新查询工具选择决策树、query_simple 描述、错误处理表；章节重新编号（原十四～二十→十三～十九）
- `references/simple-query-guide.md`：删除 intro 中的 innerWhere；删除整个"子查询数据集注意事项"节；更新 filters 映射表和错误处理表
- `references/cli.md` / `references/mcp.md`：删除文档入口第5条、使用原则中的禁用场景条目、文档引用顺序第4条
- `references/cli-simple-guide.md` / `references/mcp-simple-guide.md`：更新命令/Tool 说明，删除强制禁用声明
- `references/cli-advanced-guide.md` / `references/mcp-advanced-guide.md`：删除顶部及工作流中的【强制禁用】声明
- `references/query-patterns.md`：更新参考章节表（移除 innerWhere 行）
- `references/data-query-service-dev-guide.md`：删除 payload 完整结构中的 `innerWhere` 字段；重写 3.3 子查询类型节（移除 innerWhere 层级说明和完整示例）；重写 3.4 对比总结表；重写 10.2 PHP 示例代码；删除 10.3 日期条件处理中的 innerWhere 注释
**验证结果**：对所有 .md 文件执行 grep innerWhere，结果为空，全部清除
**影响范围**：ops-dataset-query Skill 文档层，不影响运行时查询逻辑；服务端已不接受 innerWhere 参数，文档与后端行为对齐
**回滚方式**：git checkout 还原 opscli/skills/templates/ops-dataset-query/ 目录下相关文件

---

## 2026-05-14 ops-auth Skill - 移除 polaris 相关内容

**变更原因**：正式发版中 polaris 系统已通过 polaris_enabled=false 禁用，Skill 文档中的 polaris 相关示例和说明不再适用，需同步清理避免误导 AI Agent。
**改动点**：
- `opscli/skills/templates/ops-auth/references/cli.md`：删除内置系统表格的 polaris 行、token get/check 示例、doctor 输出示例、token status 输出示例、system list 示例、system remove 说明、Python SDK 高级示例；config.ini 示例移除 polaris 地址配置
- `opscli/skills/templates/ops-auth/references/mcp.md`：删除内置系统表格的 polaris 行、auth_get_token 参数说明、auth_system_remove 说明、auth_doctor 返回示例；config.ini 示例移除 polaris 地址配置
**验证结果**：两个文件中 polaris 相关内容已全部清除（仅保留 polarisUserToken cookie 名称，该名称为技术实现细节非系统引用）
**影响范围**：ops-auth Skill 文档层，不影响运行时逻辑
**回滚方式**：git checkout 还原两个文件
## 2026-05-15 ops-amazon-rufus Skill - 增强 listing 语义触发

**变更原因**：用户使用“listing”“listing 分析”“listing 优化”等自然语言表达 Rufus 商品页分析意图时，原 Skill 描述未覆盖该触发语义，可能导致 Agent 未加载 `ops-amazon-rufus`。
**改动点**：
- `opscli/skills/templates/ops-amazon-rufus/SKILL.md`：frontmatter `description` 增加 Amazon Listing/listing 商品页触发语义，并新增“触发范围”章节。
- `.agents/skills/ops-amazon-rufus/SKILL.md`：同步当前仓库 Agent 安装副本。
- `tests/skills/test_manager.py`：新增测试，防止 listing 触发词与 `ops-amazon-listing-analysis` 边界说明丢失。
- `tests/skills/test_manager.py`：将多运行时安装路径断言改为 `Path(...).as_posix()` 后再匹配，避免 Windows 路径分隔符导致定向验证失败。

**验证结果**：TDD RED：新增测试在实现前失败，失败原因为缺少 `listing` 触发内容；GREEN：`uv run pytest "tests/skills/test_manager.py::test_ops_amazon_rufus_skill_mentions_listing_trigger_scope" -v` 通过；定向回归 `uv run pytest "tests/skills/test_manager.py" "tests/skills/test_cli.py" -v` 通过（21 passed）；`rg` 命中两份 `SKILL.md` 的 listing 触发词与边界说明；`git diff --check` 通过（仅行尾转换 warning）。
**影响范围**：仅影响 `ops-amazon-rufus` Skill 自动触发说明和测试；不改变 Rufus CLI、题库、浏览器采集、Replay、Parser 或报告输出运行链路。
**回滚方式**：恢复两份 `SKILL.md` 的原 frontmatter 与正文，删除 `test_ops_amazon_rufus_skill_mentions_listing_trigger_scope` 测试。

---

## 2026-05-14 auth/config.py - 新增 polaris_enabled 配置参数

**变更原因**：正式发版中 polaris 系统暂时不参与授权请求和 Token 刷新，需通过配置参数控制，避免登录后预刷新和 refresh_all 触发 polaris 网络请求。
**改动点**：`opscli/auth/config.py`
**具体改动**：
- `DEFAULTS` 新增 `polaris_enabled: "false"` 键，**默认禁用**（正式发版）
- `get_builtin_systems()` 重构为先构建 ops 条目，再根据 `polaris_enabled` 决定是否追加 polaris 条目
- 需要启用时在 `~/.config/opscli/config.ini [systems]` 写入 `polaris_enabled = true`

**验证结果**：改动逻辑正确，不影响 ops 系统任何行为；polaris_enabled=false 时 list_all()/refresh_all()/doctor 均不含 polaris
**影响范围**：仅影响 `get_builtin_systems()` 返回值，下游 SystemRegistry、TokenManager.refresh_all、CLI status/doctor 均自动生效
**回滚方式**：恢复 `get_builtin_systems()` 原始实现（无条件返回 ops+polaris），删除 `DEFAULTS` 中的 `polaris_enabled` 键

---

## 2026-05-14 QUERY_SPEC.md + SKILL.md - 补充 payload / execution_summary 完整字段

**变更原因**：原反馈示例中 `execution_summary` 结构过于简陋，缺少 `payload`、`failed_calls`、`successful_calls`、`final_resolution` 等关键字段，与后端 `dm_user_feedbacks` 表结构不匹配，导致反馈内容无法有效用于问题追踪和根因分析。
**改动点**：
- `opscli/skills/templates/ops-dataset-query/QUERY_SPEC.md`（第二十章 反馈提交参数规范）
- `opscli/skills/templates/ops-dataset-query/SKILL.md`（查询闭环章节 MCP/CLI 调用方式）

**具体改动**：
- 两个文件均将单一示例扩展为**成功场景 + 失败/降级场景**两个示例
- 新增 `payload` 字段（`{"actual": "...", "expected": "..."}`）
- `execution_summary` 补全为完整结构：`summary` / `failed_calls`（含 tool/reason/call_params/error_message/fix_suggestion）/ `successful_calls` / `final_resolution`
- 失败场景增加 `severity="medium"` 字段
- CLI 模式补充 `--payload` 和 `--execution-summary` 参数示例

**验证结果**：QUERY_SPEC.md 命中 25 处、SKILL.md 命中 17 处 payload/execution_summary 相关字段
**影响范围**：规范文档层，不影响运行时逻辑
**回滚方式**：恢复为原单一成功示例，移除 payload 字段和 failed_calls 结构

---

## 2026-05-14 skills/templates/ops-dataset-query/QUERY_SPEC.md - 新增查询闭环规则

**变更原因**：规范文档缺少 feedbackSubmit 闭环要求，需与 query.py 工具描述保持一致，同步更新 query_spec 工具名引用。
**改动点**：`opscli/skills/templates/ops-dataset-query/QUERY_SPEC.md`
**具体改动**：
- 文档头 + 页脚：`query_spec()` → `query_spec_must_read()`
- 第十七章自检清单末尾：追加 `□ 闭环：查询完成后是否已调用 feedbackSubmit 提交结果反馈？`
- 工作流 A/B/C/D：各追加 `步骤 5 feedbackSubmit 提交查询反馈`；工作流 A 额外包含三个参数说明（feedback_type / title / content）
- 新增第二十章「查询闭环强制规则」：包含铁律（后续 3 次工具调用内必须完成 feedbackSubmit）、5 步强制执行清单、反馈参数规范代码示例、违规后果表格、Post-Hook 自动触发规则说明

**验证结果**：grep 确认 feedbackSubmit 共 10 处、无旧名 `query_spec()` 残留、第二十章标题正常出现
**影响范围**：MCP 规范文档层，不影响运行时逻辑
**回滚方式**：删除第二十章，移除各工作流步骤 5，恢复自检清单最后一行，将工具名引用改回 `query_spec()`

---

## 2026-05-14 mcp/tools/query.py - query_spec 改名并重写描述

**变更原因**：原 `query_spec` 描述以"仅在未安装 Skill 时才需要调用"开头，导致 AI 将其归为"可选参考文档"而跳过，造成库存字段误聚合等已知风险。改名加入强制性词汇，重写描述编码检测逻辑。
**改动点**：`opscli/mcp/tools/query.py`
**具体改动**：
- 函数改名：`query_spec` → `query_spec_must_read`
- docstring 重写：删除"仅在未安装时调用"限定语；新增「调用前必须完成的检测步骤」章节（三步：调 skills_list 检测 → Skill 启用走 Skill → Skill 不存在或禁用必须调本工具）；新增「跳过规范的已知风险」章节（5 条具体后果）
- 模块顶部注释工具名同步更新
- `query_simple`/`query_run`/`query_build_and_run` 中对 `query_spec()` 的引用更新为 `query_spec_must_read()`
- `_ALL_TOOLS` 列表引用更新

**验证结果**：`grep query_spec opscli/mcp/tools/query.py` 无旧名残留
**影响范围**：MCP Server 对外暴露的工具名称变更，调用方需更新工具名
**回滚方式**：将函数名和所有引用改回 `query_spec`，恢复旧 docstring

---

## 2026-05-14 mcp/tools/query.py - 新增查询完成后调用 feedback_submit 提示

**变更原因**：AI 执行完查询后缺乏反馈机制，无法收集执行结果信息；通过在工具描述中加入强制提示，引导 AI 每次查询完成后都调用 feedback_submit MCP 工具。
**改动点**：`opscli/mcp/tools/query.py`
**具体改动**：
- `query_simple`、`query_run`、`query_build_and_run`、`query_chart` 的 docstring 末尾各新增「查询完成后必须执行」章节，说明每次执行完成后（无论成功或失败）必须调用 feedback_submit MCP 工具
- `query_spec_must_read` 的规范内容中新增「完整工作流说明」，明确标准流程：检测 Skill 状态 → 读取规范 → 执行查询 → 调用 feedback_submit 提交反馈

**验证结果**：grep 确认 5 处提示均已插入（query_spec_must_read 1 处 + 各执行工具 4 处）
**影响范围**：MCP 工具描述层，不影响运行时逻辑
**回滚方式**：删除各方法 docstring 中「查询完成后必须执行」和「完整工作流说明」段落

---

## 2026-05-13 mcp/tools/query.py - 优化 AI agent 查询前置检查引导

**变更原因**：AI agent 调用查询工具时，只有查询出错后才去读 query_spec 规范，未能提前检测 Skill 安装状态并按规范执行
**改动点**：`opscli/mcp/tools/query.py` 各查询工具的 docstring
**具体改动**：
- `query_spec` docstring：明确调用条件为"未安装 Skill 时使用"，并说明 AI agent 应先通过 `skills_status / skills_list` 检测安装状态再决定是否调用
- `query_simple`、`query_run`、`query_build_and_run`、`query_chart` docstring：将"首次使用提示"升级为"前置检查（必须执行）"，明确两步流程：先检测 Skill → 已安装读 Skill 目录文档，未安装调 query_spec()
- 同步更新模块顶部注释中 query_spec 的描述
**验证结果**：docstring 语义清晰，符合铁律要求，无运行时代码改动，无需测试
**影响范围**：MCP 工具描述（AI agent 决策路径），不影响实际查询逻辑
**回滚方式**：还原 query.py 对应 docstring 文本即可
---

## 2026-05-13 QUERY_SPEC.md - 更新 MCP 授权方式为 auth_mcp_login

**变更原因**：MCP 授权方式已从 Device Flow（需浏览器）升级为 `auth_mcp_login` 一步登录（HTTP/SSE 模式，全自动），文档未同步
**改动点**：`opscli/skills/templates/ops-dataset-query/QUERY_SPEC.md`
- 第一章铁律1：更新认证描述，注明 session_id 可自动加载
- 第二章：新增推荐方式 `auth_mcp_login`（一步登录），Device Flow 降为回退方式（仅 stdio 模式）；新增"自动加载本地凭证"说明
- 第四章 query_simple 参数表：session_id 由"必须"改为"可选，不传时自动加载"
- 第十四章错误处理：session 无效处理改为按模式分流（HTTP/SSE → auth_mcp_login；stdio → Device Flow）；auth_token_refresh 去掉 session_id 必传说明
- 第十七章自检清单：认证项改为"自动检查本地凭证"
- 第十八章工作流 A/B/C：认证步骤全部更新，query 调用注明 session_id 可不传
- query_build_and_run 示例：移除硬编码 session_id

**验证结果**：文档内容与 auth.py 的实现对齐，auth_mcp_login 为首推，Device Flow 为回退
**影响范围**：AI Agent 读取此规范文档时的授权行为
**回滚方式**：git checkout 还原该文件
---

## 2026-05-12 query_simple MCP 工具 - dimensions/metrics 兼容字符串格式

**变更原因**：上游 Agent 调用 `query_simple` MCP Tool 时传入字符串格式的 dimensions（`'dept_name'`）和 metrics（`'amount:SUM'`），但 Pydantic 模型定义为 `list[dict]`，导致校验失败报 `ValidationError`。

**改动点**：
- `opscli/mcp/tools/query.py`：
  - 新增 `_normalize_dimension()`：将字符串 `"dept_name:f_dept"` 转为 `{"field": "dept_name", "alias": "f_dept"}`
  - 新增 `_normalize_metric()`：将字符串 `"price:SUM:f_price"` 转为 `{"field": "price", "aggregation": "SUM", "alias": "f_price"}`
  - `query_simple` 的 `dimensions`/`metrics` 类型从 `list[dict]` 改为 `list[str | dict]`，传入后自动归一化
  - 更新 docstring 说明两种传入格式

**验证结果**：归一化函数单元测试通过（字符串/dict/多段格式全部正确）；57 个 query 测试全部通过；25 个 MCP 测试通过（2 个预存失败与本次无关）

**影响范围**：仅影响 `query_simple` MCP Tool 的 dimensions/metrics 参数格式兼容性，向后兼容（dict 格式继续正常工作）

**回滚方式**：恢复 `query_simple` 参数类型为 `list[dict]`，删除 `_normalize_dimension`/`_normalize_metric` 函数
---

## 2026-05-12 MCP 一步登录 - 新增 auth_mcp_login

**变更原因**：MCP 模式下旧登录流程需要浏览器介入和多次轮询，AI Agent 无法自主完成。利用 X-MCP-API-Key 已绑定用户身份，实现无浏览器一步登录。
**改动点**：
- 新增 `app/Http/Controllers/Api/McpAuthController.php`：`POST /v1/mcp/auth/login` 接口，联合校验 device_code + user_code + API Key，事务写入 session
- 修改 `routes/api.php`：在 `/v1/mcp` 公开路由组追加新路由，新增 `McpAuthController` import
- 新增 `database/migrations/2026_05_12_000001_add_agent_name_to_shared_login_sessions_table.php`：`shared_login_sessions` 表新增 `agent_name varchar(128) NULL` 字段
- 修改 `opscli/mcp/tools/auth.py`：新增 `auth_mcp_login(agent_name)` 函数；`_ALL_TOOLS` 移除 `auth_login_start`/`auth_login_poll`，加入 `auth_mcp_login`；更新模块 docstring
**验证结果**：`python3 -m py_compile opscli/mcp/tools/auth.py` 通过
**影响范围**：MCP 工具集登录入口变更；CLI `opscli auth login` 不受影响
**回滚方式**：删除 `McpAuthController.php`，回滚 `routes/api.php` import 和路由行，回滚 `_ALL_TOOLS` 改动，执行 migration rollback
---

## 2026-05-12 源码目录清理 - 删除 Cython 编译产物

**变更原因**：源码目录 `opscli/opscli/` 下残留了大量 Cython 编译生成的 `.c` 和 `.so` 文件，影响源码阅读和 git 状态。
**改动点**：删除了 `opscli/` 子目录下的所有 `.c`（75 个）和 `.so`（52 个）文件，共计 127 个编译产物。
**验证结果**：`find opscli -type f \( -name '*.c' -o -name '*.so' \)` 返回 0。
**影响范围**：不影响运行（项目以纯 Python 模式开发，`SKIP_CYTHON=1`），生产构建会重新生成。
**回滚方式**：通过 git checkout 恢复。
---

## 2026-05-12 ops-dataset-query rules - 新增库存查询默认不聚合规则

**变更原因**：用户要求增加一条规则，查询具体产品的库存相关字段时默认不聚合，直接查最新库存数据。
**改动点**：在 `opscli/skills/templates/ops-dataset-query/references/rules.md` 新增 Section 11「库存数据查询规则」，包含 11.1 指定产品的库存查询默认不聚合。
**验证结果**：文件已写入，规则内容完整。
**影响范围**：仅 ops-dataset-query Skill 的规则参考文档，不影响代码逻辑。
**回滚方式**：回退该文件的编辑即可。
---

## 2026-05-12 opscli query metadata - 优化为远端优先获取最新字段

**变更原因**：`opscli query metadata` 之前仅从本地缓存读取，未指定参数时返回所有字段（数据量大且不是用户需要的），指定参数时也没有获取远端最新数据。用户需要：(1) 无参数时只返回数据集列表；(2) 有参数时从远端拉取最新字段信息。

**改动点**：
- `opscli/query/transport/client.py`：新增 `fetch_query_metadata()` 方法，调用 `GET /v1/data-metrics/datasets/query-metadata` 获取远端最新 datasets + fields
- `opscli/query/services/manager.py`：重写 `metadata()` 方法
  - 无参数 → 仅返回本地数据集列表（`fields=[]`，`all_datasets=[...]`）
  - 有参数 → 优先调用 `fetch_query_metadata()` 远端获取，失败回退本地
- `opscli/query/commands/cli.py`：更新 hint 提示词，无参数时提示使用 --dataset/--table-id，远端失败时提示执行 upgrade
- `tests/query/test_client.py`：新增 `test_fetch_query_metadata_sends_get_request`
- `tests/query/test_manager.py`：新增 3 个 metadata 测试（无参数/远端成功/远端回退），所有 build 测试补充 fetch_query_metadata mock
- `tests/query/test_cli.py`：新增 2 个 CLI hint 测试，修复 DummyResult 缺少 source 属性

**验证结果**：55 个 query 测试全部通过（+5 个新增），全量 246 测试仅 2 个预存失败（ops-amazon-rufus / version_consistency）

**影响范围**：`opscli query metadata` 命令行为变更，`QueryManager.metadata()` 返回值结构不变（向后兼容 `QueryMetadataResult`），`build()` 内部调用 metadata 时也会触发远端请求（有本地回退兜底）

**回滚方式**：`git revert` 对应 commit，恢复 `metadata()` 为纯本地读取逻辑

---

## 2026-05-12 ops-dataset-query - scripts 重构瘦身，消除 ~950 行重复代码

**变更原因**：`chart_analyze.py`/`chart_analyze_mcp.py`（~700 行重复）和 `excel_export.py`/`excel_export_mcp.py`（~250 行重复）存在大量 CLI/MCP 双版本代码重复，维护成本和出错风险高。

**改动点**：
- 新建 `chart_analyze_core.py`（455 行）— 提取异常检测引擎（ROLE_PATTERNS、detect_field_role、build_alias_map、detect_anomalies_current/trend、generate_report 等）
- 新建 `excel_export_core.py`（298 行）— 提取 Excel 导出引擎（样式常量、_build_col_layout、_get_row_type、export_to_excel 等）
- `chart_analyze.py`：665→134 行，删除检测引擎代码，改为从 chart_analyze_core + chart_data_loader + chart_map_core 导入
- `chart_analyze_mcp.py`：660→171 行，同上，另删除私有 _check_mapping_hit/load_chart_data，改为从 core/chart_data_loader 导入
- `excel_export.py`：425→134 行，修复 load_chart_data 导入源（从 chart_analyze → chart_data_loader），导出逻辑改为从 excel_export_core 导入
- `excel_export_mcp.py`：370→137 行，删除私有 _load_chart_data_from_file/_check_mapping_hit，改为从共用模块导入

**验证结果**：10 个脚本 import 全部通过；4 个入口脚本 --help 正常；110 个 pytest 中 109 通过（1 个失败为 ops-amazon-rufus 远端 manifest 不可达，与本次无关）

**影响范围**：ops-dataset-query Skill 的 scripts/ 目录。CLI 和 MCP 模式的 chart_analyze、excel_export 功能行为不变。

**回滚方式**：git checkout 重构前 commit（bd18b88）即可还原

## 2026-05-09 ops-dataset-query - 精简 CSV 和 API 字段，减少 AI 上下文消耗

**变更原因**：`dataset_fields.csv`（19 字段）和 `datasets.csv`（10 字段）字段过多，浪费 AI 上下文 token；`/api/v1/data-metrics/datasets/query-metadata` API 响应也包含大量冗余字段。

**改动点**：

### 字段精简对照表

**dataset_fields.csv（19→10 字段）**：
- 保留：`dataset_alias`, `dataset_name`, `field_name`, `verbose_name`, `global_alias`, `field_type`, `summary_expression`, `detail_expression`, `description`, `remarks`（新增）
- 删除：`dataset_type`, `dataset_category`, `data_type`, `is_dttm`, `is_restricted`, `expression`, `expression_raw`, `formula_config`, `has_formula_config`, `keywords`

**datasets.csv（10→6 字段）**：
- 保留：`table_id`, `dataset_alias`, `dataset_name`, `inner_where_enabled`, `description`, `remarks`（新增）
- 删除：`dataset_type`, `dataset_category`, `data_source`, `main_dttm_col`, `cache_timeout`

### 修改的文件

1. **PHP 服务端** `DatasetSkillService.php`：
   - `createFieldExportResponseForUser()` CSV 表头 19→10 字段
   - `toFieldExportRow()` 输出行 19→10 字段
   - `createDatasetExportResponseForUser()` CSV 表头 10→6 字段
   - `toDatasetExportRow()` 输出行 10→6 字段
   - `buildQueryMetadataForUser()` 改用 `Arr::only()` 仅返回必要字段
   - `buildDatasets()` 将 `remarks` 从 description 回退逻辑拆为独立字段
   - `buildFields()` dimension 和 metric 行均增加独立 `remarks` 字段，description 不再回退到 remarks

2. **Python 客户端** `core.py`：
   - `load_local_index()` 移除 `data_type` 字段（仅存储从未有效读取）
   - `load_local_index()` dataset_index 和 field_index 均增加 `remarks` 字段

3. **CSV 占位文件**：
   - `data/dataset_fields.csv` 更新表头为 10 字段
   - `data/datasets.csv` 更新表头为 5 字段

**验证结果**：需发布新版本后通过 `opscli skills upgrade` 验证 CSV 下载和 API 响应

**影响范围**：ops-dataset-query Skill 的数据同步、搜索、查询全链路

**回滚方式**：恢复上述 5 个文件的旧字段列表

---

## 2026-05-11 methods-card - 新增方法卡 Skill 与分析工作流

**变更原因**：需要将 `methods card` Skill 从认证门禁扩展为可执行分析流程：用登录态获取方法卡列表/详情，结合本地 Excel 数据和方法卡规范生成 HTML 报告。

**改动点**：
- 新增 Super Dev 变更包 `.super-dev/changes/ops-methods-card/`
- 新增 `opscli/methods_card/` 模块，提供 `opscli methods-card list/detail`
- 在 `opscli/cli.py` 注册 `methods-card` 顶级命令
- 新增 `tests/skills/test_manager.py` 安装测试，锁定 `ops-methods-card` 模板必须能走现有安装链路
- 新增 `tests/methods_card/` 客户端和 CLI 测试
- 新增 `tests/skills/test_ops_methods_card_xlsx_preview.py`，锁定 Excel 预览脚本输出
- 新增 `opscli/skills/templates/ops-methods-card/SKILL.md` 和 `data/VERSION.json`
- 将方法卡静态说明移入 `opscli/skills/templates/ops-methods-card/references/`，并把输出示例 HTML 一并收口到 reference 层
- 新增 `references/执行流程.md`、`references/方法卡接口.md`
- 新增 `scripts/xlsx_preview.py`，用标准库解析本地 `.xlsx` 为 JSON 摘要
- `xlsx_preview.py` 显式使用 UTF-8 输出，避免 Windows 管道捕获中文路径时解码失败
- 更新 `opscli/skills/templates/manifest.json`，声明 `ops-methods-card` 但不纳入公开发版产物
- 更新 `SKILL.md`，补充认证、选卡、详情、Excel 读取和 HTML 保存流程
- 将 `SKILL.md` frontmatter `description` 改为中文，并明确 HTML 报告需参考 `references/卡片输出示例.html`
- `SkillsManager.install()` 安装模板时忽略 `__pycache__`、`*.pyc`、`*.pyo`，避免将本地验证缓存复制到项目 Skill

**验证结果**：
- RED：`.venv/Scripts/python.exe -m pytest tests/skills/test_manager.py::test_install_ops_methods_card_template -q` 因模板缺失失败
- GREEN：同一目标测试通过，`1 passed`
- MethodsCard RED：`tests/methods_card/*` 初次运行因 `opscli.methods_card` 模块缺失失败
- MethodsCard GREEN：`tests/methods_card/test_client.py tests/methods_card/test_cli.py` 通过，`5 passed`
- Excel 预览：`tests/skills/test_ops_methods_card_xlsx_preview.py` 通过，`1 passed`
- Skill 校验：设置 UTF-8 后 `quick_validate.py opscli/skills/templates/ops-methods-card` 通过
- Manifest 校验：`validate_release_manifest(Path("opscli/skills/templates"))` 输出 `OK`
- 模板发现：`SkillsManager().list_templates()` 可发现 `ops-methods-card`
- Diff 检查：`git diff --check` 退出码 0，仅有 CRLF 工作区提示
- 最终统一验证：目标 pytest `7 passed`；Skill 快速校验通过；manifest 校验输出 `OK`；`compileall` 通过；`git diff --check` 退出码 0
- 文档补充验证：中文 description 调整后，`quick_validate.py opscli/skills/templates/ops-methods-card` 通过；`git diff --check` 通过
- 项目安装验证：`opscli skills install ops-methods-card --skills-dir ".agents/skills"` 成功；`skills list --skills-dir ".agents/skills"` 可发现 `ops-methods-card`
- 已知环境噪音：`uv run pytest ...` 被 `uv.lock` 中 `playwright` 缺少 `source` 字段阻断；`.venv` 全量 `test_manager.py` 和 `test_packaging.py` 分别仍有既有 Windows 路径分隔断言失败

**影响范围**：新增只读 methods-card CLI；不影响 auth/query/amazon 业务逻辑。Skill 增加本地 Excel 预览和 HTML 报告生成流程。

**回滚方式**：删除 `.super-dev/changes/ops-methods-card/`、`opscli/methods_card/`、`tests/methods_card/`、`opscli/skills/templates/ops-methods-card/`，回退 `opscli/cli.py` 注册行和 `tests/skills/test_manager.py` 新增测试，并从 `manifest.json` 移除 `ops-methods-card`

---

## 2026-05-07 opscli - skills install 自动向编辑器配置文件注入反馈铁律

**变更原因**：用户期望 `opscli skills install` 安装 ops-feedback Skill 时，能自动在对应编辑器（Claude Code / Codex / OpenCode / OpenClaw）的配置文件中追加【铁律】工具调用失败自动反馈，实现零配置启用。

**改动点**：

### 1. 新增 RuleInjector 模块
- `opscli/skills/services/rule_injector.py` — 铁律注入器
  - `RuleInjector` 类：负责向编辑器配置文件追加铁律
  - 支持 runtime → 配置文件名映射（claude→CLAUDE.md，codex/opencode/openclaw→AGENTS.md）
  - 配置文件放在 **skills 目录的父目录**（与 skills 同级），如 `~/.claude/skills/` → `~/.claude/CLAUDE.md`
  - 幂等检测：通过 `RULE_MARKER` 注释避免重复注入
  - 铁律内容来源：优先读取 `ops-feedback/data/FEEDBACK_RULE.md`，文件不存在时回退内置硬编码
  - 未知 runtime / 自定义目录（--skills-dir）时**安全跳过**

### 2. 提取铁律内容到 Skill 模板
- `opscli/skills/templates/ops-feedback/data/FEEDBACK_RULE.md` — 独立铁律 Markdown 文件
  - 内容与 AGENTS.md 中的全局铁律保持一致
  - 作为 RuleInjector 的单一来源，后续更新只需改此文件

### 3. CLI 层统一注入铁律（重构）
- `opscli/skills/commands/cli.py`
  - 新增 `_inject_rules_for_installs()` 辅助函数：对安装结果按 `(runtime, skills_parent)` 去重后统一注入
  - 单 Skill 安装（`install_skill`）：安装成功后调用 `_inject_rules_for_installs(result.installs)`
  - 批量交互安装（`_install_interactive`）：收集所有 `all_installs`，循环结束后统一注入一次
  - 注入提示打印：`⚙ 已追加反馈铁律到 {path}`

### 4. 修改 SkillsManager（移除注入逻辑）
- `opscli/skills/services/manager.py`
  - 移除 `install()` 方法内部的 RuleInjector 调用
  - 保持 `SkillBatchInstallResult` 简洁，不再填充 `injected_configs`

### 5. 保留数据模型字段
- `opscli/skills/domain/models.py`
  - `SkillBatchInstallResult.injected_configs` 保留但不再由 manager 填充，供后续扩展使用

**验证结果**：
- Python 编译检查：rule_injector.py、manager.py、domain/models.py、commands/cli.py 全部通过
- RuleInjector 功能测试：
  - claude runtime → 生成 `~/.claude/CLAUDE.md`，包含铁律和 RULE_MARKER
  - codex runtime → 生成 `~/.codex/AGENTS.md`，包含铁律
  - opencode runtime → 生成 `AGENTS.md`
  - 未知 runtime → 安全返回 None
  - 幂等测试：同一目录第二次注入返回相同路径，不重复追加
  - 铁律内容测试：生成文件中包含 "工具调用失败自动反馈"
- CLI 层去重测试：3 个安装结果指向 2 个编辑器目录（2 个 claude + 1 个 codex），正确去重后只注入 2 次

**影响范围**：
- `opscli skills install` 现在会自动为检测到的编辑器注入反馈铁律
- 用户安装 ops-feedback 后，对应编辑器（Codex/Claude）会话中工具失败会自动触发反馈提交
- 不影响 --skills-dir 自定义目录安装场景
- Windows/macOS/Linux 跨平台兼容（使用 Path 对象，无硬编码路径分隔符）

**回滚方式**：
- 删除 RuleInjector 模块和 FEEDBACK_RULE.md
- 回退 manager.py 的 install 方法
- 回退 domain/models.py 和 commands/cli.py

---

## 2026-05-07 opscli - 增强 ops-feedback 自动触发机制

**变更原因**：用户期望 AI Agent（Codex）在调用 opscli 工具失败时能自动触发 ops-feedback Skill 提交反馈，无需等待用户指示。

**改动点**：

### 1. AGENTS.md 新增全局铁律
- 新增 【铁律】工具调用失败自动反馈
- 明确 Codex 在工具调用失败后必须立即调用 ops-feedback 提交结构化反馈
- 规定执行顺序（读取 SKILL.md → 构造 execution_summary → 调用 feedback_submit → 返回 feedback_uuid）
- 定义例外情况（认证类错误、用户主动取消、5 分钟内已提交过）

### 2. MCP helpers.py 增强 _err 响应
- `_err()` 增加可选参数：`tool`、`call_params`、`auto_feedback`
- 默认 `auto_feedback=True`，所有工具调用失败自动在响应中附加 `feedback` 草案字段
- 新增 `_draft_feedback()` 辅助函数，从异常上下文自动构造 feedback payload：
  - `feedback_type`: bug
  - `severity`: medium
  - `source`: mcp
  - `execution_summary`: 含 failed_calls（tool、call_params、error_message）
- 保持向后兼容：原有 `_err(exc)` 调用无需修改

### 3. ops-feedback SKILL.md 增加自动触发规则
- 新增 "自动触发规则（Agent 工具调用失败后）" 章节
- 明确触发条件（success=false、未捕获异常、非 0 退出码、特定错误码）
- 明确不触发情况（认证流程、KeyboardInterrupt、5 分钟内重复）
- 提供完整的触发流程（检查 feedback 字段 → 补充 title/content → 调用 feedback_submit → 返回 uuid）
- 提供 execution_summary 构造模板

### 4. ops-feedback references/mcp.md 增加自动触发示例
- 新增 "自动触发（Agent 工具调用失败后）" 章节
- 提供从错误响应提取 feedback 草案并提交的代码示例

### 5. 两份使用手册更新
- `opscli命令用例手册.md`：反馈模块增加自动触发规则说明
- `MCP工具使用手册.md`：反馈模块增加自动触发说明

**验证结果**：
- Python 编译检查：`helpers.py` 通过
- `_err` 向后兼容测试：原有 `_err(ValueError('测试'))` 正常返回且包含 feedback 字段
- `auto_feedback=False` 测试：认证类错误可关闭自动反馈
- `_err(tool='...', call_params={...})` 测试：正确构造包含 tool 和 call_params 的 feedback 草案
- 手册章节号连续验证：opscli命令用例手册.md（1-12）、MCP工具使用手册.md（1-11）

**影响范围**：
- 所有 MCP Tool 的错误响应现在默认包含 feedback 草案
- AGENTS.md 铁律对所有在 opscli 项目中工作的 Codex 会话生效
- ops-feedback Skill 增加自动触发语义，AI Agent 加载后会在工具失败后自动执行

**回滚方式**：
- AGENTS.md：删除新增铁律段落
- helpers.py：回退 `_err` 和 `_draft_feedback` 到原有实现
- SKILL.md：删除 "自动触发规则" 章节
- references/mcp.md：删除 "自动触发" 章节

---

## 2026-05-07 auth/cli - token status 增加 session_id 显示

**变更原因**：用户需要在 `opscli auth token status` 中看到 session_id，方便排查和 MCP 连接时确认当前会话。
**改动点**：`opscli/auth/cli.py` 的 `status()` 函数，在 email 和 session_expires_at 之间增加 `Session ID` 行输出。
**验证结果**：`session_id` 已在 `CredentialStore.load()` 返回数据中存在，直接读取即可。
**影响范围**：仅影响 `opscli auth token status` 的终端输出，增加一行信息。
**回滚方式**：删除新增的 `console.print(f"Session ID：{data.get('session_id', 'N/A')}")` 行。
---

## 2026-05-07 docs/guide — 更新 CLI 和 MCP 两份使用手册至 v0.0.35

**变更原因**：两份手册（`opscli命令用例手册.md` 和 `MCP工具使用手册.md`）停留在 v0.0.10，项目已迭代至 v0.0.35，缺少 seller-sprite 模块、mcp user 命令组、query catalog/simple 子命令、search/fetch MCP 工具等大量新增内容，需要全量更新以保持文档与代码一致。

**改动点**：

### opscli命令用例手册.md
1. 版本号从 `0.0.10` 更新为 `0.0.35`
2. 命令总览树新增 `seller-sprite`（含 account 子命令组）、`mcp user` 子命令组、`query catalog`/`query simple` 子命令
3. 新增第 6.2 节 `query catalog` 命令（读取业务语义索引）
4. 新增第 6.5 节 `query simple` 命令（基于 JSON 文件/字符串的简化查询）
5. 新增第 8 节 `seller-sprite` 模块完整文档（collect、frequency、keyword-mining、keyword-reverse、archive、login、login-status、schema、account save/list/delete，共 11 个子命令）
6. 新增第 9 节 `mcp` 管理模块（user list/add/remove/rotate，共 4 个子命令）
7. Skills 模板表从 4 个更新为 9 个
8. 新增组合用例：卖家精灵完整采集流程（10.5）、MCP 用户管理（10.6）
9. 快速索引表同步更新

### MCP工具使用手册.md
1. 版本号从 `0.0.10` 更新为 `0.0.35`
2. Tool 总览树新增 `query_catalog`、knowledge 分支（search/fetch）
3. 新增第 5.2 节 `query_catalog` 工具（读取业务语义索引）
4. 新增第 8 节 Knowledge 模块（ChatGPT/OpenAI 兼容的 `search` 和 `fetch` 工具，遵循 Company Knowledge 标准格式）
5. 新增组合用例：使用业务语义索引定位数据集（7.6）、使用 search/fetch 搜索数据集（7.7）
6. 认证状态速查表新增 `query_catalog`、`search`、`fetch` 三个工具
7. 快速索引表新增 `query_catalog`、`search`、`fetch` 映射

**验证结果**：文档变更，无代码修改，无需测试
**影响范围**：两份使用指南文档，不影响代码功能
**回滚方式**：git checkout -- `docs/guide/MCP工具使用手册.md` `docs/guide/opscli命令用例手册.md`
---

## 2026-05-07 ops-dataset-query 文档 — 补充 payload 互斥与 select 结构说明

**变更原因**：AI 在实际调用中频繁出现两类错误：(1) `opscli query simple` 同时传 `--payload` 和 `--json` 导致 CLI 报错；(2) 手写 `query run` payload 使用 `global_alias` 作为 key 而非 `expr`/`alias`，导致服务端 422 校验失败
**改动点**：
1. `references/cli.md` — `opscli query simple` 章节增加 `--payload`/`--json` 互斥警告框和错误示例
2. `references/cli.md` — `opscli query run` 章节增加 `query.select` 必填字段说明（`expr` + `alias`），含正确和错误对比示例
3. `references/mcp.md` — `query_run` 章节增加同样的 `select` 结构要求说明
**验证结果**：文档变更，无代码修改，无需测试
**影响范围**：ops-dataset-query Skill 的 CLI 和 MCP 参考文档
**回滚方式**：git revert 对应 commit
---

## 2026-05-07 MCP query/search — 4 项调用异常修复

**变更原因**：基于实际调用记录分析，发现 4 个影响数据查询体验的问题：query_simple 因透传 skills_dir 导致 TypeError；search 工具多词搜索命中率极低；where_conditions 格式文档缺失导致 AI 连续试错；CLI 优先级提示不够强
**改动点**：
1. `opscli/mcp/tools/query.py` — query_simple 调用 build_simple_and_run 时剔除 skills_dir 参数（build_simple 不接受此参数）
2. `opscli/mcp/tools/chatgpt.py` — search 工具新增 _tokenize_query 分词函数，_score_dataset_match / _score_field_match 支持多 token 逐词匹配累加分数
3. `opscli/mcp/tools/query.py` — query_build 和 query_build_and_run 的 docstring 补充 where_conditions 格式说明（field|operator|value_json）和示例
4. `opscli/skills/templates/ops-dataset-query/SKILL.md` — 运行模式判断增加"opscli 项目目录下必须用 CLI"的强制规则
**验证结果**：146 个测试通过（1 个已有的认证依赖测试失败，与本次无关）；多词搜索验证 "Amazon 销售额 广告花费" 可匹配到 verbose_name 含"广告花费"的字段（分数 50，原来为 0）
**影响范围**：MCP query_simple / search / query_build_and_run 工具；ops-dataset-query SKILL.md
**回滚方式**：git revert 对应 commit
---

## 2026-04-30 ops-dataset-query - P0/P1 修复 + 搜索空结果强制升级

**变更原因**：ops-dataset-query Skill 存在 10 项问题（P0-P3），包括 __pycache__ 泄漏、版本号不统一、where 字段名错误、函数重复定义、文档重复、搜索空结果无升级兜底等。用户反馈搜索"广告"返回空 `[]` 后 AI 直接放弃，未触发 upgrade。

**改动点**：
1. P0-1: 新增 `.gitignore`（__pycache__/*.pyc/*.pyo/.DS_Store）
2. P0-2: SKILL.md 版本号改为 `see data/VERSION.json`，cli.md/mcp.md 移除硬编码版本
3. P0-3: `query_mcp.py` 修复 `"logic": "AND"` → `"operator": "AND"`
4. P1-1: 8 个脚本的重复函数（discover_data_dir/load_local_index/resolve_dataset_alias/resolve_field_alias/try_upgrade/check_mapping_hit）统一提取到 `core.py`
5. P1-2: 新建 `references/query-patterns.md`（225行），cli.md 和 mcp.md 的重复高级计算章节改为引用（净减 ~290 行）
6. P2: SKILL.md/cli.md/mcp.md 增加"搜索结果为空时必须先 upgrade 再重试"的强制规则和示例

**验证结果**：8 个脚本 `import` 全部通过，无循环依赖
**影响范围**：ops-dataset-query Skill 的所有脚本和参考文档
**回滚方式**：`git checkout -- opscli/skills/templates/ops-dataset-query/`

---

## 2026-04-29 opscli - 实现 Skill 委托模式，防止 AI 猜测字段名

**变更原因**：测试调用记录显示，AI 在执行数据集查询时经常直接猜测字段名（如 `ds_pdTYjvLRCadv.asin`），导致 `INVALID_PAYLOAD` 错误。需要显式声明业务逻辑层 Skill 应将数据查询工作委托给 `ops-dataset-query` Skill，由其负责字段发现、metadata 验证和 payload 构造。

**改动点**：
- 为 9 个数据查询类 Skill 的 `SKILL.md` 添加"## 技能委托声明"部分
  - ops-asin-health-diagnoser（之前已完成）
  - ops-competitive-intelligence-analyst
  - ops-cross-border-product-selector
  - ops-advertising-efficiency-optimizer
  - ops-inventory-health-monitor
  - ops-product-attribute-analyzer
  - ops-perspective-builder
  - ops-profit-structure-analyzer
  - ops-refund-priority-matrix
- 每个委托声明包含：
  - 责任边界表（数据查询层 → ops-dataset-query，业务逻辑层 → 当前 Skill）
  - 委托触发规则表（5 场景，标注 ✅ 必须委托 / ❌ 可直接执行）
  - 委托调用方式示例（→ 调用 / ← 返回）
  - 反例警告（禁止直接猜测字段名）
- 插入位置统一为"阅读入口"和"使用原则"之间

**验证结果**：
- `grep -l "## 技能委托声明" opscli/skills/templates/ops-*/SKILL.md | wc -l` 返回 9
- 所有 9 个数据查询类 Skill 已包含完整委托声明

**影响范围**：
- AI Agent 在调用这些 Skill 时，会优先切换到 ops-dataset-query 进行字段发现
- 减少 INVALID_PAYLOAD 错误，避免额外的往返修复
- 不影响 CLI 模式用户直接使用 opscli query 命令

**回滚方式**：
- 删除各 SKILL.md 中"## 技能委托声明"部分（从 `---` 到下一个 `---`）

---

## 2026-04-27 opscli - 新增 chart_analyze_mcp.py

**变更原因**：为 ops-dataset-query Skill 新增 MCP 无状态模式的图表异常检测脚本，原 `chart_analyze.py` 依赖 `opscli` CLI（subprocess），无法在纯 MCP 环境中使用。

**改动点**：
- 新增 `opscli/skills/templates/ops-dataset-query/scripts/chart_analyze_mcp.py`
- 移除所有 `subprocess` 调用 `opscli` 的逻辑
- 数据获取改为纯文件输入（`--input` / `--dc-input`），由 MCP Agent 预先通过 `query_chart` / `query_build_and_run` Tool 获取后传入
- 移除自动 `upgrade` 兜底，改为返回错误并提示调用 MCP `skills_upgrade`
- 文件头部添加详细 MCP 调用指南注释（含前置 session 检查、Tool 调用示例、dataComparison 用法）
- 核心异常检测逻辑（5 类规则）与 `chart_analyze.py` 完全一致

**验证结果**：`python -m py_compile` 语法检查通过

**影响范围**：不影响现有 `chart_analyze.py`，为 MCP 环境提供独立入口

**回滚方式**：删除 `chart_analyze_mcp.py` 即可

---

## 2026-04-27 opscli - 新增 chart_map_mcp.py / excel_export_mcp.py / query_mcp.py / updater_mcp.py

**变更原因**：为 ops-dataset-query Skill 的 4 个核心脚本创建 MCP 无状态模式版本，原脚本均依赖 opscli CLI（subprocess 或直接导入内部模块），无法在纯 MCP 环境中使用。

### chart_map_mcp.py
- 新增 `opscli/skills/templates/ops-dataset-query/scripts/chart_map_mcp.py`
- 移除 `subprocess` 调用 `opscli query chart`（原 `--uuid`/`--run` 参数）
- 移除 `_try_upgrade()` 自动升级逻辑，映射失败时提示调用 MCP `skills_upgrade`
- 数据入口改为纯 `--input` 文件（由 MCP `query_chart` 获取后保存）
- 保留核心映射函数：`discover_data_dir`、`load_local_index`、`map_chart_queries`、`map_query_results`

### excel_export_mcp.py
- 新增 `opscli/skills/templates/ops-dataset-query/scripts/excel_export_mcp.py`
- 不再从 `chart_analyze.py` 导入 CLI 函数（`_check_mapping_hit`、`_try_upgrade`、`load_chart_data`）
- 自行实现文件版 `load_chart_data()` 和 `_check_mapping_hit()`
- 移除 `--uuid` 和 `--no-auto-upgrade` 参数
- 保留 Excel 导出核心逻辑：样式、行列类型判断、百分比列识别、列宽自适应

### query_mcp.py
- 新增 `opscli/skills/templates/ops-dataset-query/scripts/query_mcp.py`
- 原 `query.py` 为纯 opscli 转发脚本（`subprocess` 调用 CLI），MCP 模式下无直接价值
- 改造为**本地 Payload 构造器**：使用本地 CSV 索引实现字段别名解析（`global_alias > field_name > verbose_name`），构造标准 query payload JSON
- 支持 `build` 子命令（dimensions/metrics/where/order_by/limit/offset/data_comparison）和 `metadata` 子命令
- 输出 payload JSON 文件，供 MCP `query_run` Tool 使用
- 实现字段歧义自动消歧（`_pick_primary_field`，优先选取原始字段）

### updater_mcp.py
- 新增 `opscli/skills/templates/ops-dataset-query/scripts/updater_mcp.py`
- 移除对 `opscli.skills.models.SkillRecord` 和 `opscli.skills.updater.SkillsUpdater` 的依赖
- 改为仅检查本地 `VERSION.json` 和数据文件（`datasets.csv`、`dataset_fields.csv`、`query_metadata.json`）完整性的轻量脚本
- 更新操作提示通过 MCP `skills_upgrade` Tool 执行

**验证结果**：`python -m py_compile` 语法检查全部通过（4/4）

**影响范围**：不影响现有 CLI 版本脚本，为 MCP 环境提供独立入口

**回滚方式**：删除 4 个 `*_mcp.py` 文件即可

---

## 2026-04-27 opscli - 更新 SKILL_MCP.md 文档

**变更原因**：将新增的 5 个 MCP 版本脚本（`query_mcp.py`、`chart_map_mcp.py`、`chart_analyze_mcp.py`、`excel_export_mcp.py`、`updater_mcp.py`）的调用方式及用法补充到 SKILL_MCP.md 中，方便 MCP Agent 查阅。

**改动点**：
- 在 `opscli/skills/templates/ops-dataset-query/SKILL_MCP.md` 的"辅助脚本"章节中新增"MCP 环境辅助脚本"小节
- 每个脚本包含：功能说明、用法示例、输入来源（对应哪个 MCP Tool）、输出格式
- `query_mcp.py` 单独说明与 `query_run` Tool 的配合使用流程
- `chart_analyze_mcp.py` 包含 5 类异常检测规则速查表
- `excel_export_mcp.py` 包含格式规范说明

**影响范围**：仅文档更新，不影响代码

**回滚方式**：回退 SKILL_MCP.md 修改即可

---

## 2026-04-27 opscli - 新增 ops-skills/SKILL_MCP.md

**变更原因**：`ops-skills` 虽然不需要 `*_mcp.py` 脚本（核心功能本身就是 MCP Tool），但缺少 MCP 模式下的使用文档，导致 MCP Agent 无法了解 `skills_list`、`skills_install`、`skills_status`、`skills_upgrade` 四个 Tool 的参数格式和返回结构。

**改动点**：
- 新增 `opscli/skills/templates/ops-skills/SKILL_MCP.md`
- 包含完整的 4 个 MCP Tool 参数表：
  - `skills_list`：本地扫描，无需认证
  - `skills_status`：含远端版本对比
  - `skills_install`：纯本地模板安装
  - `skills_upgrade`：仅支持 `ops-dataset-query` 远端升级
- 提供典型工作流（全新环境初始化、日常版本维护、指定路径安装、强制重置）
- 明确认证说明：`skills_list`/`skills_install` 纯本地操作无需认证；`skills_status`/`skills_upgrade` 远端调用由服务器端内部处理

**影响范围**：仅文档新增，不影响代码

**回滚方式**：删除 SKILL_MCP.md 即可

---

## 2026-04-27 opscli - 新增 MCP 工具使用手册

**变更原因**：CLI 命令用例手册 (`opscli命令用例手册.md`) 无法直接指导 MCP 环境下的 Tool 调用，需要一份对应的 MCP Tool 使用手册，覆盖全部 4 个模块（auth / amazon / query / skills）共 24+ 个 Tool 的参数、返回结构和示例。

**改动点**：
- 新增 `docs/guide/MCP工具使用手册.md`
- 结构与 CLI 手册一一对应，但使用 Python 函数调用风格展示参数
- 每个 Tool 包含：参数表、返回示例、调用示例
- 包含认证状态速查表（哪些 Tool 需要认证、认证方式）
- 包含 CLI → MCP Tool 的映射对照表（快速索引）
- 覆盖 CLI 手册中所有 8 个常见组合用例的 MCP 版本

**影响范围**：仅文档新增，不影响代码

**回滚方式**：删除 `docs/guide/MCP工具使用手册.md` 即可

---

## 2026-04-29 opscli/skills - Skills 深度审查修复（16 项）

**变更原因**：对已开发完成的 9 个 Skills 进行全面深度审查，发现 7 项必须修复问题 + 6 项建议修复 + 3 项可选优化，逐一修复确保代码质量和安全性。

**改动点**：

### 🔴 必须修复（7 项）
1. **permission 格式错误**：5 个 reference 文件中 `"permission": ["{permission}"]` 改为 `"permission": "{permission}"`（字符串而非数组）
   - `ops-competitive-intelligence-analyst/reference/dataset_fields_mapping.md`
   - `ops-refund-priority-matrix/reference/dataset_fields_mapping.md`
   - `ops-perspective-builder/reference/dataset_fields_mapping.md`
   - `ops-profit-structure-analyzer/reference/dataset_fields_mapping.md`
   - `ops-cross-border-product-selector/reference/dataset_fields_mapping.md`
2. **透视模板缺失**：`build_perspective_config.py` 补充 4 个缺失模板（`ad_type_comparison`、`device_traffic`、`promotion_effectiveness`、`inventory_structure`）及对应触发词
3. **四行动策略硬编码**：`competitive_analysis.py` 的 `analyze_four_actions()` 将硬编码的保温杯建议改为基于品类数据和定位分析动态生成
4. **毛利润可能为负**：`analyze_cost_structure.py` 的 `gross_profit = 1.0 - total_cost` 改为 `max(0.0, min(1.0, 1.0 - total_cost))`
5. **重复 import**：`calculate_roas_acos.py` 删除 `if __name__` 块中重复的 `from typing import Optional`
6. **预估成本硬编码**：`product_selector.py` 的 `price * 0.35` 改为可配置参数 `DEFAULT_COST_RATIO` + 支持 `item.estimated_cost` 和 `internal_capability.cost_ratio`

### 🟡 建议修复（6 项）
7. **字段映射声明**：`ops-asin-health-diagnoser/SKILL.md` 阈值表添加 `sell_qty_days → inventory_days` 字段映射说明
8. **参数类型标注错误**：`product_selector.py` 的 `classify_quadrant` 参数 `sentiment_score` 从 `Optional[str]` 改为 `Optional[float]`
9. **硬编码日期**：`generate_replenishment_plan.py` 新增 `reference_date` 参数，默认 `datetime.now()`，支持测试和回测
10. **description 混合语言**：`ops-profit-structure-analyzer` 和 `ops-refund-priority-matrix` 的 frontmatter description 改为纯英文
11. **错误输出方向**：`calculate_health_score.py` 错误信息同时输出到 stdout 和 stderr
12. **SKILL.md 标题风格**：统一 3 个标题为 `# 英文标题` + 中文副标题格式

### 新增铁律
13. **CLAUDE.md 新增【铁律18】**：代码修改后必须更新变更记录文件 `docs/change-log-pending.md`

**验证结果**：所有 14 个脚本通过 `echo '{}' | python script.py` 基础测试，关键脚本（health_score、cost_structure、roas_acos、perspective_builder、competitive_analysis、product_selector）通过正常数据测试

**影响范围**：仅影响 Skills 模板的脚本和文档，不影响 opscli 核心功能（auth/query/mcp）

**回滚方式**：`git checkout -- opscli/skills/templates/ CLAUDE.md docs/change-log-pending.md`

---

## 2026-04-29 CLAUDE.md - 整合 Andrej Karpathy 编码行为准则为铁律19-22

**变更原因**：将 https://github.com/forrestchang/andrej-karpathy-skills/blob/main/CLAUDE.md 中 4 条编码行为准则翻译为中文，以【铁律19~22】形式追加到项目 CLAUDE.md 的铁律章节，与项目现有铁律风格保持一致。

**改动点**：
- CLAUDE.md 新增 4 条铁律：
  - 【铁律19】编码前先思考，不假设、不掩盖困惑（原文：Think Before Coding）
  - 【铁律20】极简优先，只写解决问题所需的最少代码（原文：Simplicity First）
  - 【铁律21】精确变更，只改必须改的（原文：Surgical Changes）
  - 【铁律22】目标导向执行，定义成功标准并验证闭环（原文：Goal-Driven Execution）
- 原则：忠于原文核心精神，中文表达贴合项目铁律风格（禁止行为列表 + 判断标准）

**验证结果**：4 条铁律内容对照原文无遗漏，中文表达通顺

**影响范围**：仅影响 CLAUDE.md 文档，不影响代码

**回滚方式**：删除 CLAUDE.md 中【铁律19】至【铁律22】段落

---

## 2026-04-29 auto-scheduler + opscli - 图表查询接口增加过滤字段及新增 chart-doc 指令

**变更原因**：
1. 服务端 `latest-request-data` 接口需要返回当前图表数据集支持的过滤条件字段，供 opscli 侧了解可用 WHERE 条件
2. opscli 侧需要在图表查询结果中透传过滤字段信息
3. 新增 `opscli query chart-doc` 指令，支持通过 chart_uuid 自动生成完整 API 调用 Markdown 文档

**改动点**：

### 服务端（auto-scheduler）
- 修改 `vendor/aukey/data-metrics/src/Http/Controllers/CliQueryApiController.php`
  - 引入 `Aukey\DataMetrics\Models\SelectColumnRelation`
  - `latestRequestData` 方法新增逻辑：通过 `query.from.alias` → `dm_tables.dataset_alias` → `dm_select_column_relations.dataset_alias` 查询启用的过滤字段
  - 返回结构扩展：每个 query item 新增 `filterable_fields` 字段（含 `column_name`、`verbose_name`、`source_column_name`）
  - 按 `dataset_alias` 缓存避免重复查询

### opscli 侧
- 修改 `opscli/query/services/manager.py`
  - `run_chart_queries` 方法透传 `filterable_fields` 和 `query_structure` 到每个 query 结果中
  - 新增 `generate_chart_doc(chart_uuid)` 方法：生成完整 Markdown 文档，含数据集概览、过滤字段表、查询结构说明、API 调用顺序、Payload 示例、WHERE 条件构建指南
  - 示例中敏感字段（`table`/`permission`）使用占位符，不返回 `userEmail`
- 修改 `opscli/query/commands/cli.py`
  - 新增 `chart-doc` 子命令：`opscli query chart-doc --uuid <chart_uuid> [--output <file>] [--pretty]`
  - 支持将 Markdown 文档直接写入文件

**验证结果**：
- `python -m py_compile opscli/query/services/manager.py opscli/query/commands/cli.py` 语法检查通过
- 服务端 PHP 文件未引入语法错误（新增 import + 扩展已有循环逻辑）

**影响范围**：
- 服务端 `latest-request-data` 接口返回结构向后兼容扩展（新增字段）
- opscli `query chart` 和 `query chart-run` 返回的每个 query 中新增 `filterable_fields` 和 `query_structure`
- 新增 `query chart-doc` 命令，不影响现有命令

**回滚方式**：
- 服务端：回退 `CliQueryApiController.php` 的 `latestRequestData` 方法修改
- opscli：回退 `manager.py` 中 `run_chart_queries` 和 `generate_chart_doc`，回退 `cli.py` 中 `chart_doc` 命令

---

## 2026-04-29 query - 优化 chart-doc 生成文档结构

**变更原因**：生成的文档存在三个缺陷：可过滤字段在多 Query 时重复渲染浪费 token；7.1 字段映射表列数达 8 列宽表 AI 不友好；缺少字段命名约定说明导致 AI 无法处理边界场景
**改动点**：
1. `opscli/query/services/manager.py - generate_chart_doc`：
   - §2 新增"字段命名约定"小节（§2.2），说明 query_alias / global_alias / origin_name / expr 的格式规律、生成方式和使用场景，及公式字段边界说明
   - §7.1 输出字段映射由 1 张 8 列宽表拆分为 2 张 4 列表（表A字段语义 + 表B字段引用），以 field_name 作连接键，expr 列去掉并在表B注释中说明
   - §7.3 可过滤字段新增去重逻辑：对比当前 Query 与所属数据集（§5.2）的 filterable_fields 集合，完全相同时只输出一行引用语句，不同才完整渲染
2. `tests/query/test_manager.py`：更新两个受影响的测试断言匹配新双表格式和去重引用格式
**验证结果**：pytest tests/query/ 39 passed
**影响范围**：opscli query chart-doc 命令输出的 Markdown 文档结构；不影响 API 调用逻辑
**回滚方式**：git revert 此次改动，恢复 manager.py 和 test_manager.py 对应段落
---

## 2026-05-07 opscli + data-metrics - 新增用户反馈模块（ops-feedback）

**变更原因**：用户需要一套完整的用户反馈收集机制，覆盖 CLI、MCP 和 Skill 三层。特别是 Skill/CLI/MCP 执行失败后，必须能沉淀结构化复盘信息（工具、调用参数、报错信息、原因、修复建议），保存到 polaris_ops_metrics.dm_user_feedbacks 表。

**改动点**：

### 服务端（auto-scheduler/vendor/aukey/data-metrics）
1. 新增迁移 `src/database/migrations/2026_05_07_000002_create_dm_user_feedbacks_table.php`：创建 `dm_user_feedbacks` 表，含 feedback_uuid、source、feedback_type、severity、title、content、payload、context、execution_summary、failed_call_count、attachments、status、user_id 等字段及 5 个索引
2. 新增 ORM `src/Models/UserFeedback.php`：继承 BaseModel， casts JSON 字段，提供 `toApiArray()` 方法
3. 新增 Service `src/Services/UserFeedbackService.php`：`submitForUser()` 自动计算 failed_call_count，从 UserOrm 取 email；`findByUuidForUser()` 按用户隔离查询
4. 新增 Controller `src/Http/Controllers/UserFeedbackApiController.php`：POST submit + GET detail，含完整 Validator 校验（feedback_type/severity/source 枚举、title<=200、failed_calls.*.tool/error_message 必填）
5. 修改 `src/Http/routes.php`：在 `api/v1/data-metrics` JWT 认证组注册 feedback 路由（避开 RoutePermission 中间件）

### opscli 侧
1. 新增 `opscli/feedback/` 完整模块：
   - `domain/models.py` — FEEDBACK_TYPES、SEVERITIES、SOURCES、FEEDBACK_SCHEMA
   - `domain/exceptions.py` — FeedbackError / InvalidPayloadError / RemoteHttpError / RemoteBusinessError / BadRemoteJsonError
   - `transport/client.py` — FeedbackClient，封装 submit/detail 的 HTTP 请求和认证
   - `services/manager.py` — FeedbackManager，负责 payload 构建、字段校验、execution_summary.failed_calls 边界检查
   - `commands/cli.py` — `feedback schema/submit/detail` 三个子命令，支持 --file/--payload-file/--context-file/--execution-summary-file/--attachments-file 文件输入方式
   - `cli.py` — 兼容导出
2. 修改 `opscli/cli.py`：注册 `feedback_app`
3. 新增 MCP 工具 `opscli/mcp/tools/feedback.py`：`feedback_submit` + `feedback_detail`，支持 session_id/jwt 认证透传
4. 修改 `opscli/mcp/server.py`：导入并注册 `_feedback_tools`

### Skill 模板
新增 `opscli/skills/templates/ops-feedback/`：
- `SKILL.md` — 运行模式判断、提交前强制总结规范（failed_calls 必须含 tool/call_params/error_message/reason/fix_suggestion）
- `references/cli.md` — CLI 提交/查询/schema 示例
- `references/mcp.md` — MCP Tool 调用示例
- `data/VERSION.json` — v1.0.0

**验证结果**：
- PHP 语法检查：迁移、Model、Service、Controller、routes 全部 `No syntax errors detected`
- Python 编译检查：`opscli/feedback/`、`opscli/mcp/tools/feedback.py`、`opscli/cli.py`、`opscli/mcp/server.py` 全部通过
- CLI 功能验证（Typer CliRunner）：
  - `feedback schema --pretty` 正常输出 schema
  - `feedback --help` 显示 schema/submit/detail 三个命令
  - `feedback submit --type bug --title t` 正确拦截“缺少 content”
  - `feedback submit --type invalid --title t --content c` 正确拦截“feedback_type 必须是...”
  - `feedback submit --file feedback.json --pretty` 文件提交模式正常构造 payload（服务端未部署返回 404，属于预期）
  - `feedback detail --uuid ''` 正确拦截“feedback_uuid 不能为空”
- FeedbackManager 边界校验：超长 title（201 字符）拦截、failed_calls 缺少 tool/error_message 拦截、空 failed_calls 正常通过
- MCP 工具注册验证：`register(mock_mcp)` 后 `await mock_mcp.list_tools()` 成功列出 `feedback_submit`、`feedback_detail`
- 服务端迁移状态：`php artisan migrate:status` 正确识别 `2026_05_07_000002_create_dm_user_feedbacks_table` 为 Pending

**影响范围**：
- 新增独立 feedback 领域，不影响现有 auth/query/amazon/skills/mcp 功能
- 服务端新增一张表和一组接口，仅用于反馈收集
- Skill 层新增 ops-feedback 模板，供 AI Agent 使用

**回滚方式**：
- 服务端：删除 migration + Model + Service + Controller，回退 routes.php
- opscli：删除 `opscli/feedback/` 目录、`opscli/mcp/tools/feedback.py`，回退 `opscli/cli.py` 和 `opscli/mcp/server.py` 的导入/注册行
- Skill：删除 `opscli/skills/templates/ops-feedback/`

---

## 2026-04-29 skills/templates - 精简所有 Skill 的 references 文档

**变更原因**：`data-query-service-dev-guide.md`（1173行）在 9 个业务 Skill 中存在完全相同的 10 份副本，占每个 Skill 文档总量的 60-75%；其中大量章节（多次查询、MOY/ACC/PPT、缓存、PHP 伪代码）对 Skill 执行无用，造成 AI 上下文浪费和维护困难

**改动点**：
1. 新建 `query-essential-guide.md`（149行）：从完整 dev-guide 中提取 Skill 真正需要的内容（WHERE 操作符、SELECT 格式、日期规范、dataComparison、错误码），复制到 9 个业务 Skill 的 references/
2. 删除 9 个业务 Skill 中的 `data-query-service-dev-guide.md`，保留 `ops-dataset-query/references/` 中的唯一完整版
3. 精简 `ops-asin-health-diagnoser/references/dataset_fields_mapping.md`（134行→65行）：去掉静态 payload 模板，保留数据集索引 + 核心字段业务语义 + chart-doc 使用指引
4. 更新 9 个 Skill 的 `SKILL.md`、`references/cli.md`、`references/mcp.md` 中的文件名引用（data-query-service-dev-guide → query-essential-guide）

**验证结果**：
- dev-guide 残留检查通过（9 个业务 Skill 均已删除）
- query-essential-guide 分布：9 个 Skill 均已到位
- 各 Skill 文档总行数：平均从 ~1800 行降至 ~737 行，减少约 59%

**影响范围**：所有业务类 Skill 的 references 目录结构；ops-dataset-query 不受影响
**回滚方式**：从 ops-dataset-query/references/data-query-service-dev-guide.md 重新 cp 到各 Skill，删除 query-essential-guide.md，恢复文件名引用
---

## 2026-05-09 MCP context - 修复 SSE 模式下 API Key 丢失导致凭证跨会话不可见

**变更原因**：MCP SSE 模式下，ASGI 中间件设置的 `mcp_request_ctx` contextvar 在 SSE 长连接→anyio task group→tool handler 的传播链中丢失，导致 `get_current_api_key()` 返回 None，凭证写入 Keychain 而非 API Key 隔离目录，后续会话无法发现已保存的凭证。

**改动点**：
- `opscli/mcp/context.py`：`get_current_api_key()`、`get_current_user_id()`、`get_current_user_email()` 增加降级路径，当自定义 `mcp_request_ctx` 为 None 时，从 MCP 框架的 `request_ctx`（在 `_handle_request` 中可靠设置）读取 POST 请求 scope 中的值

**验证结果**：`tests/mcp/test_context.py` 全部通过；语法编译通过

**影响范围**：仅影响 MCP SSE 模式下的 API Key 获取路径，CLI 模式不受影响

**回滚方式**：移除 `context.py` 中的降级读取逻辑和 `_get_scope_from_mcp_request_ctx()` 辅助函数

---

## 2026-05-09 auth device_flow - 修复 ChatGPT 轮询卡死问题

**变更原因**：ChatGPT 使用 `auth_login_poll` 时，若后端返回非 200（如 WAF 拦截 "Unusual activity has been detected"），`poll_once` 调用 `raise_for_status()` 抛出通用异常，MCP tool 返回模糊错误信息，ChatGPT 持续重试导致轮询卡死。

**改动点**：
1. `opscli/auth/core/device_flow.py`：
   - `poll_once` 捕获 `httpx.TimeoutException` 和 `httpx.ConnectError`，返回结构化错误 dict
   - 非 200 响应不再 `raise_for_status()`，改为返回含 `retryable` 标志的错误 dict（429/5xx 可重试，其余不可重试）
   - 新增 `_extract_error_message()` 静态方法，解析 JSON/text/HTML 格式的错误消息
2. `opscli/mcp/tools/auth.py`：
   - `auth_login_poll` 处理 `status: "error"` 结果时直接透传（含 `retryable` 标志）
   - 更新 docstring 文档所有 status 值和 `retryable` 语义

**验证结果**：`tests/auth/test_device_flow.py` 8 passed；`tests/mcp/test_tools.py` 3 passed；语法编译通过

**影响范围**：仅影响 `auth_login_poll` MCP tool 和 `DeviceFlow.poll_once` 方法的错误处理路径，正常授权流程不变

**回滚方式**：回退 `device_flow.py` 的 `poll_once` 方法（恢复 `raise_for_status()`），回退 `auth.py` 的 `auth_login_poll`（移除 error 状态透传）

---

## 2026-05-11 mcp auth - 优化 ChatGPT 授权轮询超时

**变更原因**：ChatGPT 通过远程 MCP 调用 `auth_login_poll` 时存在外层工具超时，原实现单次后端轮询和 API Key 远程校验都可能各自等待 10 秒，导致工具尚未返回就被 ChatGPT 判定超时。

**改动点**：`opscli/mcp/tools/auth.py` 将 `auth_login_poll` 默认超时降为 5 秒，并通过 `asyncio.to_thread()` 执行同步 `poll_once`，避免阻塞 MCP 事件循环；同文件为 auth 工具补齐 `ToolAnnotations`。`opscli/mcp/auth_middleware.py` 为远程 API Key 校验增加 60 秒短缓存，并将单次校验超时降为 3 秒。

**验证结果**：已执行 `.venv/bin/python -m pytest tests/auth/test_device_flow.py tests/mcp/test_tools.py tests/mcp/test_auth_middleware.py tests/mcp/test_multi_user_isolation.py -v`，15 passed。

**影响范围**：影响远程 MCP HTTP/SSE 模式下 auth 工具调用，尤其是 ChatGPT 授权轮询链路；CLI 登录流程不受影响。

**回滚方式**：回退 `opscli/mcp/tools/auth.py` 中 `auth_login_poll` 的默认超时、`asyncio.to_thread()` 调用和 annotations 注册；回退 `opscli/mcp/auth_middleware.py` 中的校验缓存与超时常量。
## 2026-05-14 Amazon Rufus - 补齐 get 单题 question 参数

**变更原因**：`ops-amazon-rufus` Skill/README 已说明 `opscli amazon-rufus get --question` 单题模式，但 CLI 与 Manager 未实现该参数，导致 Agent 按文档调用时报 `No such option: --question`。

**改动点**：
- `opscli/amazon_rufus/commands/cli.py`：为 `get` 命令增加 `--question` 参数，并透传到 `RufusManager.get`
- `opscli/amazon_rufus/services/manager.py`：新增单题模式问题解析，传入 `question` 时跳过题库读取；未传时保留默认题库模式
- `opscli/amazon_rufus/domain/exceptions.py`：新增 `InvalidQuestionError`，用于空白问题的稳定错误码
- `tests/amazon_rufus/test_core.py`：补充 CLI 参数透传、单题跳过题库、空白问题拒绝的回归测试

**验证结果**：
- 定向 TDD 验证：`uv run pytest "tests/amazon_rufus/test_core.py" -k "question_to_manager or single_question_without_loading_bank or rejects_blank_question" -q` 为 3 passed
- 完整 Amazon Rufus 测试：`uv run pytest "tests/amazon_rufus/test_core.py" -q` 为 41 passed
- CLI 参数验证：`uv run --extra amazon opscli amazon-rufus get --help` 已展示 `--question`

**影响范围**：仅影响 `opscli amazon-rufus get` 的问题来源选择；未传 `--question` 时继续读取本地题库。

**回滚方式**：回退上述 4 个文件中本次新增的 `question` 参数、`_resolve_questions` 分支、`InvalidQuestionError` 和对应测试。

---

## 2026-05-14 ops-amazon-rufus Skill - 增加拒答后中文改写规则

**变更原因**：`ops-amazon-rufus` 已要求拒答后改写并重试，但未明确约束重试问题语言，可能在英文原问题或英文站点场景下生成英文改写问题。

**改动点**：
- `.agents/skills/ops-amazon-rufus/SKILL.md`：在拒答处理规则中增加“改写后的问题必须使用中文”。
- `opscli/skills/templates/ops-amazon-rufus/SKILL.md`：同步模板级 Skill 规则，保证后续安装/升级后仍保留约束。
- `opscli/skills/templates/ops-amazon-rufus/README.md`：同步拒答处理说明与流程图文案。
- `.super-dev/changes/amazon-rufus-question-refusal-routing/`：补充 proposal 与 tasks 中的中文改写约束。

**验证结果**：
- 静态红测确认变更前 skill 文档未包含中文改写约束。
- 静态绿测通过：项目级 skill、模板 skill、README、proposal 和 tasks 均已覆盖中文改写规则。

**影响范围**：仅影响 `ops-amazon-rufus` Skill 执行规范和模板文档；不改变 `opscli amazon-rufus get` 的代码行为。

**回滚方式**：回退上述 5 个文件中新增的中文改写规则文本，并恢复 README 流程图节点文案。

---

## 2026-05-15 ops-methods-card Skill - 同步项目级 Skill 模板资源

**变更原因**：项目级 `.agents/skills/ops-methods-card` 与 `opscli/skills/templates/ops-methods-card` 模板目录不一致，缺少最新方法卡参数说明和 Amazon 广告诊断子 Skill 资源。

**改动点**：同步项目级 `ops-methods-card` 的 `SKILL.md`、`references/method-card-parameter-guide.md` 和 `amazon-ads-diagnosis/` 子 Skill 资源；保留项目级旧参考文件与示例 Excel，避免删除历史上下文。

**验证结果**：`PYTHONUTF8=1 python C:/Users/A/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/ops-methods-card` 通过；`amazon-ads-diagnosis` 子 Skill 校验通过；`uv run pytest tests/skills/test_ops_methods_card_skill_contract.py tests/skills/test_ops_methods_card_xlsx_preview.py -q` 为 4 passed。

**影响范围**：仅影响项目级 Agent Skill 的 methods card 使用说明、参考资料和 Amazon 广告诊断辅助资源；不改变 `opscli` 运行时代码。

**回滚方式**：回退 `.agents/skills/ops-methods-card/SKILL.md`，删除本次新增的 `.agents/skills/ops-methods-card/references/method-card-parameter-guide.md` 和 `.agents/skills/ops-methods-card/amazon-ads-diagnosis/`。

---

## 2026-05-30 skills/templates/ops-dataset-query - 首次发布到技能广场

**变更原因**：用户要求将 ops-dataset-query Skill 发布到技能广场供全员使用
**改动点**：
- `opscli/skills/templates/ops-dataset-query/data/VERSION.json`：版本从 `v0.0.1`（占位符）同步为 `1.0.2`（无 v 前缀，符合铁律）
- `opscli/skills/templates/ops-dataset-query/SKILL.md` frontmatter：`version: 1.0.2` → `version: v1.0.2`（加 v 前缀，符合铁律）
**验证结果**：`opscli skills publish --share-type company` 发布成功，标识符 `zhangpeiliang@ops-dataset-query`，版本 1.0.2，分类"数据查询"
**影响范围**：技能广场全员可见，安装命令 `opscli skills install zhangpeiliang@ops-dataset-query`
**回滚方式**：`opscli skills unpublish zhangpeiliang@ops-dataset-query`
## 2026-06-06 Amazon Rufus - 登录页监听与 streaming seed 捕获

**变更原因**：Cookie mock 能保存本地状态，但真实 Amazon 页面仍可能未触发 Rufus streaming。登录恢复需要由 CLI 实时监听用户打开的 Amazon 页面，自动检测登录完成，并捕获 `/rufus/cl/streaming` 的 curl 等价请求材料，减少 Agent 等待“已登录”确认和手动 `save-state` 的不稳定性。

**改动点**：新增 `opscli amazon-rufus watch-login <ASIN> <COUNTRY> --launch-if-needed`；`BrowserAttachService` 新增 CDP 登录页监听和 request 捕获；`RufusBrowserStateStore.save()` 支持加密保存 streaming seed、脱敏 headers 与 payload template；`RufusBackendSecretProvider` 可读取已保存 seed；`RufusManager.get_backend()` 对同 ASIN/国家复用本地 seed，避免重复 headless 捕获；同步 Skill、README、reference、安装后 next_steps 和 Super Dev 架构/tasks。

**验证结果**：RED 阶段新增测试失败于缺少 `seed_request` 保存参数、`RufusManager.watch_login()` 和 CLI `watch-login`；GREEN 阶段 `python -m pytest tests/amazon_rufus/test_core.py -q` 为 61 passed。后续会继续跑 MCP、Skill 和安装流程回归。

**影响范围**：影响 Rufus CLI 登录恢复、Rufus 本地加密状态结构、后端 secret provider 和 Skill 登录恢复编排；不改变 `amazon_rufus_get` MCP schema，不在 MCP 参数、报告、feedback 或 CLI 成功输出中暴露 cookie、headers、payload_template、request body 或完整 curl。

**回滚方式**：回退 `opscli/amazon_rufus/services/browser.py`、`browser_state_store.py`、`backend_secret.py`、`manager.py`、`commands/cli.py` 的 watch-login 与 streaming seed 相关改动；回退 Rufus Skill 文档、安装 next_steps、Super Dev 文档/tasks 和新增测试。

---

## 2026-06-06 Amazon Rufus - 保存 curl_data 并由 MCP 后端优先复用

**变更原因**：参考 `extension/python/app/contexts/rufus/application/account_runner.py` 后，Rufus 后端请求应直接复用浏览器 streaming 请求等价结构：`url`、`headers`、`cookies`、`payload_template`。仅保存拆散的 streaming seed 字段会增加 provider 与 MCP 请求路径的转换成本，也不利于对齐参考实现。

**改动点**：`RufusBrowserStateStore.save()` 捕获 streaming request 后新增加密 `curl_data` 字段，结构对齐 `ParsedCurlRufusRequest.to_dict()`；`RufusBackendSecretProvider` 优先读取 `curl_data`，旧字段和 `storage_state` 派生作为兼容 fallback；`HeadlessRufusClient` 使用保存的 url/headers/cookies/payload_template 请求 Rufus；`RufusReplayService.build_payload()` 对齐参考 payload builder，基于模板深拷贝并覆盖 question、ASIN 和 detail URL 相关 pageContext 字段；同步 Rufus Skill reference、Super Dev 文档和测试。

**验证结果**：RED 阶段新增/调整测试失败于缺少 `curl_data`；GREEN 阶段 `python -m pytest tests/amazon_rufus/test_core.py -q` 为 61 passed。后续会继续跑 MCP、Skill 和安装流程回归。

**影响范围**：影响 Rufus 本地加密状态结构、provider 读取优先级、MCP 后端请求材料来源和 payload 构造；不改变 `amazon_rufus_get` MCP schema，不在 CLI/MCP/报告/feedback 中输出 cookie、headers、payload_template、curl_data 或完整 curl。

**回滚方式**：回退 `browser_state_store.py` 中 `curl_data` 写入、`backend_secret.py` 中 `curl_data` 优先读取、`replay.py`/`headless_client.py` payload 构造调整，以及相关文档和测试。

---

## 2026-06-08 Amazon Rufus - 登录恢复登录态判断优化

**变更原因**：`watch-login` 原先依赖 `#nav-link-accountList-nav-line-1` / `#nav-link-accountList .nav-line-1` 判断 Amazon 登录态，这些元素在当前 Amazon 页面不稳定，可能导致用户登录后仍无法自动打开商品页捕获 Rufus streaming 请求。
**改动点**：`tests/amazon_rufus/test_core.py` 新增 `#nav-tools` 文案、`sso-state-main` / `at-main` Cookie key 和 i18n 未登录提示回归测试；`opscli/amazon_rufus/services/browser.py` 改为通过 `#nav-tools` 顶部工具区文本或指定登录态 Cookie key 判定登录成功，Cookie 判断只读取 name，不读取 value。
**验证结果**：RED 阶段 `uv run pytest "tests/amazon_rufus/test_core.py" -k "login_detection_uses_nav_tools or login_detection_uses_amazon_login_cookie_names or signed_out_markers_cover_i18n" -q` 已按预期失败；GREEN 阶段同命令为 3 passed；定向回归 `uv run pytest "tests/amazon_rufus/test_core.py" -k "watch_login or login_detection or signed_out_markers" -q` 为 6 passed；Skill 文档回归 `uv run pytest "tests/skills/test_ops_amazon_rufus_updater.py" -q` 为 7 passed；MCP Rufus 回归 `uv run pytest "tests/mcp/test_amazon_rufus_tools.py" -q` 为 6 passed；Rufus core 全量 `uv run pytest "tests/amazon_rufus/test_core.py" -q` 为 75 passed。
**影响范围**：影响 `opscli amazon-rufus watch-login` 登录完成检测和后续商品页自动打开；不改变 MCP schema、Rufus streaming 请求构造、报告格式或 Cookie 值输出策略。
**回滚方式**：回退 `opscli/amazon_rufus/services/browser.py` 中登录态判断 helper，删除本次新增的登录判断测试，并恢复 Skill 文档中的旧登录恢复说明。

---

## 2026-06-06 Amazon Rufus - CLI 手动登录态导入底层能力

**变更原因**：Rufus Skill 需要把登录态读写能力收敛到 opscli，MCP 只保留 headless Rufus 获取能力。后续已确认该类手动导入能力只能作为 CLI/服务层调试能力，不能出现在 MCP 或 Skill 的默认流程中。

**改动点**：新增 `RufusCookieParser` 将 Cookie header 转换为最小 Playwright `storage_state`；`RufusManager` 新增手动保存与状态摘要能力；CLI 提供对应调试入口；补充 Rufus、MCP、Skill 契约测试。当前清理轮已移除模板 Skill、`.agents` 已安装 Skill 和安装后提示中的该类入口指引。

**验证结果**：RED 阶段 `tests/amazon_rufus/test_core.py` 新增 cookie 相关测试失败于缺少 parser、Manager 方法和 CLI 子命令；GREEN 阶段 `python -m pytest tests/amazon_rufus/test_core.py -k "cookie_parser or save_cookie or cookie_status or backend_secret_provider_reads_cookie_saved_state or cli_cookie" -q` 为 5 passed；`tests/mcp/test_amazon_rufus_tools.py -k "tool_schema_excludes" -q` 为 1 passed；`tests/skills/test_ops_amazon_rufus_updater.py -k "template_uses_mcp_boundary" -q` 为 1 passed。

**影响范围**：影响 `opscli amazon-rufus` CLI 状态管理能力、Rufus 本地加密状态保存、Rufus Skill 文档和相关测试；不改变 `amazon_rufus_get` MCP schema，不在 MCP 参数或报告中暴露 cookie。

**回滚方式**：删除 `opscli/amazon_rufus/services/cookie_parser.py`；回退 `opscli/amazon_rufus/services/manager.py`、`opscli/amazon_rufus/commands/cli.py`、Super Dev 变更目录和新增测试中的手动登录态导入相关改动。

---

## 2026-06-06 Amazon Rufus - headless 捕获等待延迟 Rufus 请求

**变更原因**：真实 `amazon_rufus_get` 复现时，即使本地 Cookie 状态可读取，headless 商品页也可能在 `domcontentloaded` 后延迟触发 Rufus 请求；原实现只固定等待最多 1 秒，容易过早判定 `RUFUS_HEADLESS_CAPTURE_ERROR`。

**改动点**：`tests/amazon_rufus/test_core.py` 新增延迟 Rufus request 的回归测试；`opscli/amazon_rufus/services/headless_capture.py` 在页面加载后优先使用 Playwright `wait_for_event("request", predicate=...)` 等待 `/rufus/cl/streaming`，单页等待受剩余预算和 30 秒上限约束，保留原有页面重开重试逻辑。

**验证结果**：RED 阶段 `python -m pytest tests/amazon_rufus/test_core.py -k "waits_for_delayed_rufus_request" -q` 失败于旧实现回退固定等待；GREEN 阶段 `python -m pytest tests/amazon_rufus/test_core.py -k "headless_capture" -q` 为 6 passed；`python -m pytest tests/amazon_rufus/test_core.py -k "cookie_parser or save_cookie or cookie_status or backend_secret_provider_reads_cookie_saved_state or cli_cookie" -q` 为 5 passed。

**影响范围**：仅影响 Rufus headless 捕获等待策略；不改变 MCP 参数、CLI 参数、报告格式、Cookie 保存格式或 Rufus SSE 请求构造。

**回滚方式**：回退 `headless_capture.py` 中 `wait_for_event` 等待逻辑，删除 `test_headless_capture_waits_for_delayed_rufus_request`。

---

## 2026-06-05 Amazon Rufus - headless 页面重开重试

**变更原因**：Rufus MCP headless 捕获偶发返回 `RUFUS_HEADLESS_CAPTURE_ERROR`，根因是 Amazon 商品页首轮未触发 `/rufus/cl/streaming` 时当前实现只打开一次页面，没有内部重试。

**改动点**：
- `tests/amazon_rufus/test_core.py`：新增页面首次未触发 Rufus 请求时重开页面并最终捕获成功、持续未触发时最多重试 3 次的回归测试。
- `opscli/amazon_rufus/services/headless_capture.py`：新增 headless 商品页重开重试逻辑，首次失败后最多重试 3 次，并复用同一个 browser context。

**验证结果**：
- RED：`uv run pytest "tests/amazon_rufus/test_core.py" -k "reopens_page_after_transient_miss" -v` 失败于当前实现只打开一次页面。
- GREEN：`uv run pytest "tests/amazon_rufus/test_core.py" -k "reopens_page_after_transient_miss" -v` 为 1 passed。
- 定向：`uv run pytest "tests/amazon_rufus/test_core.py" -k "headless_capture" -v` 为 5 passed。
- MCP：`uv run pytest "tests/mcp/test_amazon_rufus_tools.py" -v` 为 9 passed。
- 回归：`uv run pytest "tests/amazon_rufus/test_core.py" -v` 为 67 passed。

**影响范围**：仅影响 Rufus headless 捕获阶段；不改变 MCP 工具参数、远程授权流程、Rufus 请求构造、SSE 解析和报告输出。

**回滚方式**：回退 `headless_capture.py` 中页面重开 helper 和常量，删除 `test_headless_capture_reopens_page_after_transient_miss` 与 `test_headless_capture_stops_after_three_page_retries` 测试。

---

## 2026-06-05 ops-amazon-rufus Skill - 补充 MCP 工具不可见兼容入口

**变更原因**：当前 Skill 默认要求宿主可见 `amazon_rufus_*` MCP 工具；当宿主未暴露 Rufus MCP 工具时缺少可执行兜底路径，容易把工具不可见误判为 Rufus 授权失败。

**改动点**：更新 `opscli/skills/templates/ops-amazon-rufus` 与 `.agents/skills/ops-amazon-rufus` 的 `SKILL.md`、`README.md`、`references/rufus-mcp-workflow.md`，新增“宿主未暴露 MCP 工具时使用 `opscli amazon-rufus` 本机 CDP 兼容入口”的分流规则；同步更新 `tests/skills/test_ops_amazon_rufus_updater.py` 的文档契约断言。

**验证结果**：`uv run pytest "tests/skills/test_ops_amazon_rufus_updater.py" -q` 为 5 passed。

**影响范围**：仅影响 `ops-amazon-rufus` Skill 文档、已安装 Skill 副本和 Skill 文档契约测试；不改变 Rufus MCP 默认 headless 获取实现。

**回滚方式**：回退上述 Skill 文档中的 MCP 工具不可见兼容入口段落，并恢复 `tests/skills/test_ops_amazon_rufus_updater.py` 中对 `opscli amazon-rufus get` 的旧断言。

---

## 2026-06-05 ops-amazon-rufus Skill - 补充 headless 捕获失败登录恢复流程

**变更原因**：MCP 获取 Rufus 时返回 `RUFUS_HEADLESS_CAPTURE_ERROR` 后，Skill 只有错误识别但缺少恢复路径，Agent 容易把它误判为 MCP 工具不可见或 CDP 连接问题。

**改动点**：更新 `opscli/skills/templates/ops-amazon-rufus` 与 `.agents/skills/ops-amazon-rufus` 的 `SKILL.md`、`README.md`、`references/rufus-mcp-workflow.md`、`references/remote-authorization.md`，新增 headless 捕获失败恢复流程：先通过 CDP 登录窗口刷新目标国家站点浏览器状态，用户确认已登录后按原问题来源调用 `amazon_rufus_get_remote(..., allow_capture_browser_state=True)` 或重试原 CLI 兼容入口；同步更新 Super Dev 输出文档和 Skill 契约测试。

**验证结果**：`uv run pytest "tests/skills/test_ops_amazon_rufus_updater.py" -q` 为 5 passed。

**影响范围**：仅影响 `ops-amazon-rufus` Skill 文档、已安装 Skill 副本、Super Dev 文档和 Skill 文档契约测试；不改变 MCP 工具参数、Rufus headless 获取实现或 CLI 实现。

**回滚方式**：回退上述 Skill 文档和 `output/ops-amazon-rufus-*.md` 中关于 `RUFUS_HEADLESS_CAPTURE_ERROR` 登录恢复的新增段落，并移除 `tests/skills/test_ops_amazon_rufus_updater.py` 中新增的恢复流程断言。

---
## 2026-06-09 Amazon Rufus Skill - MCP-only 运行链路

**变更原因**：用户要求 `ops-amazon-rufus` Skill 使用 MCP 后不再通过 opscli CLI 处理授权、登录态采集、恢复或获取，运行期全程走 MCP Tool，并在 MCP 鉴权失败时通过 MCP auth 工具处理。

**改动点**：`opscli/mcp/tools/amazon_rufus.py` 新增 `amazon_rufus_remote_consent_status`、`amazon_rufus_remote_consent_set`、`amazon_rufus_login_status`、`amazon_rufus_watch_login`、`amazon_rufus_logout` 及脱敏响应；更新 `opscli/skills/templates/ops-amazon-rufus` 与 `.agents/skills/ops-amazon-rufus` 的 Skill 文档和 workflow，删除运行期 CLI fallback；更新 `opscli/skills/commands/cli.py` 安装后引导；补充 MCP 工具、Skill 文档和安装引导测试；新增 Super Dev MCP-only 文档和变更任务。

**验证结果**：`python -m py_compile opscli/mcp/tools/amazon_rufus.py` 通过；`uv run pytest tests/mcp/test_amazon_rufus_tools.py tests/skills/test_cli.py tests/skills/test_ops_amazon_rufus_updater.py -q` 为 34 passed；`uv run pytest tests/amazon_rufus/test_transport.py tests/amazon_rufus/test_core.py -q` 为 91 passed。

**影响范围**：影响 Rufus MCP Tool 暴露面、`ops-amazon-rufus` Skill 编排文档、安装后提示和相关测试；不删除现有 Rufus CLI 命令，不改变 `amazon_rufus_get` 的敏感字段过滤和报告输出契约。

**回滚方式**：回退 `opscli/mcp/tools/amazon_rufus.py` 中新增 MCP wrapper 和注册项，恢复 `ops-amazon-rufus` Skill 文档、安装后引导和测试断言到 CLI fallback 版本，删除 `.super-dev/changes/amazon-rufus-mcp-only-flow` 与 `output/rufus-mcp-only-flow-*` 文档。

---

## 2026-06-10 Amazon Rufus MCP - 标准架构收敛

**变更原因**：Rufus MCP 已完成 MCP-only，但 `opscli/mcp/tools/amazon_rufus.py` 仍承担 manager 工厂、remote-consent store 工厂、报告写入和响应 allowlist 等适配职责。为对齐 Keepa、SellerSprite、Query 等 MCP 工具的薄 Tool 层架构，需要将 MCP-facing 编排下沉到 Rufus service 层。

**改动点**：新增 `opscli/amazon_rufus/domain/mcp_models.py`，定义 `RufusGetRequest`、`RufusWatchLoginRequest`、`RufusRemoteConsentRequest` 和 `RufusMcpResult`；新增 `opscli/amazon_rufus/services/mcp_manager.py`，集中处理 MCP 凭证目录、`AuthClient`/`RufusTransportClient`/`RufusManager`/`RemoteConsentStore` 创建、报告写入和 MCP-safe 脱敏响应；精简 `opscli/mcp/tools/amazon_rufus.py`，Tool 函数只构造 request、调用 `RufusMcpManager` 并返回 `_ok/_err`；新增 `tests/amazon_rufus/test_mcp_manager.py`，调整 `tests/mcp/test_amazon_rufus_tools.py` 聚焦 Tool 注册、schema 和参数转发；新增 Super Dev 标准架构文档和 change 任务。

**验证结果**：`uv run pytest tests/amazon_rufus/test_mcp_manager.py -q` 为 9 passed；`uv run pytest tests/mcp/test_amazon_rufus_tools.py -q` 为 14 passed；`uv run pytest tests/amazon_rufus/test_transport.py -q` 为 8 passed；`uv run pytest tests/skills/test_ops_amazon_rufus_updater.py -q` 为 8 passed。

**影响范围**：影响 Rufus MCP Tool 内部实现边界和测试分层；不改变现有 MCP Tool 名称、参数 schema、Skill MCP-only 流程、Rufus 报告格式、OPS 平台 Cookie API 契约或 CLI 可用性。MCP 成功响应仍不暴露 cookie、headers、payload、storage_state、seed request、upload_payload 或平台 Cookie content。

**回滚方式**：回退 `opscli/amazon_rufus/domain/mcp_models.py`、`opscli/amazon_rufus/services/mcp_manager.py`、`opscli/mcp/tools/amazon_rufus.py` 和相关测试改动，恢复 Tool 层直接调用 `RufusManager`、`RemoteConsentStore` 与 `AnswerReportWriter` 的旧结构，并删除 `.super-dev/changes/amazon-rufus-mcp-standard-architecture` 与 `output/rufus-mcp-standard-architecture-*` 文档。

---

## 2026-06-10 Amazon Rufus - cURL 命令态登录状态

**变更原因**：Rufus 后端请求状态原来保存为内部 `curl_data` 对象，并兼容旧 `storage_state` fallback；用户要求改为接近浏览器 Copy-as-cURL 的 cURL 命令格式，并移除旧结构解析兼容。

**改动点**：`RufusBrowserStateStore` 将 streaming 请求材料保存为 `version=2` 和浏览器 cURL 命令态；`RufusBackendSecretProvider` 只解析新 `curl` 字段；`RufusManager.login_status()` 改为基于 cURL 可解析性判断 `can_get_backend`，并删除旧 streaming request helper；`RufusMcpManager` 将 `curl` 加入敏感字段拦截；同步更新 Rufus Skill 文档、Super Dev 文档和相关测试。

**验证结果**：RED：新增目标测试先失败于缺少 `version/curl`、旧 `curl_data` 仍可读取、旧 `storage_state` 仍判定 ready、MCP 脱敏未拦截 `curl`、`RufusSecret` 仍暴露 `curl_data` 属性；GREEN：`uv run pytest "tests/amazon_rufus/test_core.py" -v` 为 85 passed；`uv run pytest "tests/amazon_rufus/test_mcp_manager.py" "tests/mcp/test_amazon_rufus_tools.py" "tests/skills/test_ops_amazon_rufus_updater.py" -v` 为 31 passed；`uv run python -m py_compile "opscli/amazon_rufus/services/browser_state_store.py" "opscli/amazon_rufus/services/backend_secret.py" "opscli/amazon_rufus/services/manager.py" "opscli/amazon_rufus/services/mcp_manager.py"` 通过；固定字符串检查确认旧解析 helper 和旧字段 fallback 无命中。

**影响范围**：影响 Rufus 登录态保存结构、后端凭证读取、登录态状态判断和 Skill 文档说明。旧 `curl_data` 或仅 `storage_state` 的平台 Cookie content 会被视为不可用，需要重新执行登录采集或重新保存 Copy-as-cURL；CLI/MCP/报告仍不输出 cookie、headers、payload、storage_state、seed request、平台 Cookie content 或 cURL 命令。

**回滚方式**：回退 `browser_state_store.py`、`backend_secret.py`、`manager.py`、`mcp_manager.py`、Rufus Skill 文档、Super Dev change 文档和相关测试改动，恢复 `curl_data` 对象保存与旧 `storage_state` fallback 解析。

---
## 2026-06-08 西柚 - 接入运营后台凭据服务

**变更原因**：正式环境不能依赖 `.env` 或本地 `credential.json` 保存西柚 token/cookie，需要从运营后台统一读取最新凭据，并支持补登成功后清理进程缓存。
**改动点**：新增 `opscli/xiyou/credential_service.py`，增加 `OPSCLI_XIYOU_CREDENTIAL_LATEST_URL`、`OPSCLI_XIYOU_CREDENTIAL_API_KEY`、`OPSCLI_XIYOU_CREDENTIAL_CACHE_TTL_SECONDS` 配置；`XiyouCredentialProvider` 调整为“配置 latest URL 则只远程拉取并进程内缓存，未配置 latest 才读取 `.env` / 环境变量 `OPSCLI_XIYOU_AUTHORIZATION`、`OPSCLI_XIYOU_COOKIE`”；删除 MCP/HTTP 本地补登入口 `/xiyou/credential/update` 的正常链路，只保留 `/internal/xiyou/credential/updated` 回调清缓存；新增 `opscli/xiyou/docs/后端服务.md` 给后端对接。
**验证结果**：已运行 `python -m pytest tests/xiyou -q -p no:cacheprovider`，结果 `61 passed, 1 warning`。
**影响范围**：西柚凭据读取、MCP/HTTP 模式下西柚任务启动前的 token 获取、补登成功后的缓存刷新。
**回滚方式**：移除新增配置和 `credential_service.py`，恢复 `XiyouCredentialProvider` 只读取本地 `.env`，删除新增回调路由和后端服务文档。
---
## 2026-06-11 skills - manifest 补齐 8 个未声明的 Skill 模板目录

**变更原因**：Skill 发版检查（`validate_release_manifest`）报错"模板目录未在 manifest 声明"，`opscli/skills/templates/` 下 8 个新模板目录未在 `manifest.json` 中登记。
**改动点**：在 `opscli/skills/templates/manifest.json` 的 `skills` 末尾追加 `ops-feed-task`、`ops-shopify-delete`、`ops-shopify-inventory`、`ops-shopify-price`、`ops-shopify-query`、`ops-shopify-status`、`ops-sif`、`ops-xiyou` 共 8 个条目，四个发版开关（source/wheel/binary/binary_full）全部为 false，tier 设为 internal。
**验证结果**：`validate_release_manifest()` 返回空（通过）；`pytest tests/skills/test_packaging.py -q -s` 6 passed；目录与 manifest 双向对比无缺失无多余。
**影响范围**：仅影响 Skill 发版打包白名单，新增条目均为 false，不改变任何现有发版产物内容。
**回滚方式**：从 `manifest.json` 中删除上述 8 个新增条目。
---
## 2026-06-12 skills - ops-dataset-query 移除 catalog intents 意图匹配

**变更原因**：后台暂未配置 catalog intents，远端意图匹配（`query_catalog` / `query_intent_match` / `opscli query intent`）无数据可用，强制要求先调用会导致流程空转。本版将数据集确定流程改为：本地意图路由（route_intent.py）→ 本地关键词搜索（search.py）→ MCP 模式用 query_metadata() 列表筛选。
**改动点**：仅修改 ops-dataset-query Skill 模板文档，未改任何 Python 代码：
- `SKILL.md`：铁律三改为"本地意图路由"，删除铁律三-A（Intent 约束优先）和铁律三-B（Catalog 回退链）的远端部分；标准工作流去除 query_intent_match 步骤
- `QUERY_SPEC.md`：删除铁律 5 / 10-A 的 catalog 依赖，删除 query_catalog / query_intent_match 工具章节，工作流 B 改为 query_metadata() 列表筛选，自检清单去除 Intent 约束项
- `references/cli.md`：删除 `opscli query catalog` / `opscli query intent` 命令章节，改为 route_intent.py 本地意图路由；典型工作流同步更新
- `references/mcp.md`：删除 query_catalog / query_intent_match Tool 索引，字段存在性检查第 0 步改为 query_metadata() 列表筛选
- `references/mcp-simple-guide.md`：删除 query_catalog / query_intent_match 参数说明章节
- `references/rules.md`：第八章改为本地意图匹配规则，数据来源去除 dataset_catalog.json
- `references/simple-query-guide.md` / `references/ask-user-question-guide.md`：去除 catalog 字样引用
**验证结果**：`grep -rn -i "catalog|query_intent_match|opscli query intent|intent_constraints"` 在 Skill 模板所有 .md 中零残留；本地路由脚本 route_intent.py 与 intent_taxonomy.yml 数据文件保持不变，本地意图路由能力保留。
**影响范围**：仅影响 AI Agent 阅读 ops-dataset-query Skill 后的数据集确定流程；MCP Server 端 query_catalog / query_intent_match 工具代码未删除，后台配置 intents 后可恢复文档。
**回滚方式**：git checkout 恢复 opscli/skills/templates/ops-dataset-query/ 下的 SKILL.md、QUERY_SPEC.md 和 references/ 各文件。
---
## 2026-06-12 mcp - MCP 工具按用户角色权限动态过滤

**变更原因**：此前任何用户连接 MCP Server 后默认可见/可用全部 60+ 工具。需求改为白名单制：由 OPS 后端按用户角色（运营系统角色 sys_roles + BI 角色 Doris mv_user_role）计算可用工具，opscli 在 list_tools 阶段过滤无权限工具（减少 AI 上下文开销）并在 call_tool 时拦截越权调用。
**改动点**：
- 新增 `opscli/mcp/permissions.py`：`ToolPermissionMiddleware`（fastmcp Middleware，on_list_tools 过滤 + on_call_tool 拦截）、`BASE_AUTH_TOOLS` 基础白名单（14 个 auth_* 工具，与后端 McpToolPermissionService::BASE_AUTH_TOOLS 双端一致）、`_resolve_allowed_tools()` 三模式自探测（HTTP 远程校验模式读上下文 allowed_tools / 固定 Key 模式或旧后端全量放行 / stdio 模式按本地 session 调 GET /v1/mcp/allowed-tools，缓存 300s，404 放行、401 仅基础工具、网络异常 stale-while-error 或 fail-closed）
- `opscli/mcp/auth_middleware.py`：verify-key 响应中的 allowed_tools 注入 scope 和 contextvar
- `opscli/mcp/server.py`：注册 `mcp.add_middleware(ToolPermissionMiddleware())`
- `opscli/mcp/tools/auth.py`：auth_mcp_login / auth_login_poll / auth_logout 成功路径调用 invalidate_stdio_cache()
- 后端配套（auto-scheduler）：新增 mcp_modules / mcp_tools / mcp_role_permissions 三表（ops_sys 库）+ McpToolPermissionService + verify-key 返回 allowed_tools + GET /v1/mcp/allowed-tools 端点
**验证结果**：新增 `tests/mcp/test_tool_permissions.py` 15 个测试全部通过；tests/mcp/ 81 passed（5 个失败经 git stash 对比确认为历史遗留）；后端 tinker 验证三种授权情形（无绑定=14 基础工具/整模块=25/单工具=26）；curl 验证 verify-key 带 allowed_tools 字段、allowed-tools 端点 200/401 两条路径。
**影响范围**：HTTP/SSE 远程校验模式和 stdio 模式的工具可见性按角色过滤；固定 API Key 单用户模式和旧后端全量放行不受影响（兼容语义：响应无 allowed_tools 字段=放行）。
**回滚方式**：opscli 端删除 server.py 中 add_middleware 一行即恢复全量；后端回滚迁移 `php artisan migrate:rollback --path=database/migrations/2026_06_12_000001_create_mcp_tool_permission_tables.php`。
---
## 2026-06-12 mcp - MCP 工具清单启动自动上报后端（替代人工维护）

**变更原因**：MCP 工具清单此前由管理后台人工维护，新增工具需手工录入且显示名/说明为空。改为 MCP Server 启动时自动上报清单，描述自动取自代码 docstring。
**改动点**：
- 新增 `opscli/mcp/tool_catalog.py`：`record_tool()` 注册时采集元数据（工具名优先取 name= 覆盖、模块取函数 __module__ 末段、描述取注册参数或 docstring 首行）；`sync_catalog_async()` HTTP/SSE 模式启动时守护线程 POST /v1/mcp/sync-tools（同步地址与 --auth-verify-url 同源，否则从 config.ini 推导；404/网络异常静默不影响启动）
- `opscli/mcp/server.py`：`_TelemetryMcpProxy.tool()` 注册包裹时调用 record_tool；run() HTTP 分支启动时调用 sync_catalog_async
- 后端（auto-scheduler）：新增 `McpToolSyncController::sync` + 路由 POST /v1/mcp/sync-tools。同步语义：只增不删（新模块/工具自动入库启用，缺失工具不自动停用），已有工具仅刷新 description 和 module_id，label/is_active 人工字段不覆盖
- 管理页（auto-scheduler_debug mcp-tool-permissions.blade.php）：工具表格改 table-layout:fixed 固定列宽（22/12/42/7/17%），超长省略+title 提示
- 数据修正：停用种子中 4 个代码注释未注册的预留工具（auth_login_start/auth_login_poll/auth_system_add/auth_system_remove）
**验证结果**：新增 `tests/mcp/test_tool_catalog.py` 6 个测试通过（chatgpt 无前缀工具归属、seller_sprite 多段前缀、404/网络异常容错）；tests/mcp/ 87 passed（5 失败为历史遗留）；真实启动 E2E：清空 keepa_run 描述 → 启动服务 → 描述自动回填 docstring 首行；浏览器确认页面列宽对齐、53 个工具说明已自动填充。
**影响范围**：HTTP/SSE 模式启动多一次后台上报（守护线程，失败仅日志）；stdio 模式不上报；管理后台 CRUD 保留可继续手动微调。
**回滚方式**：opscli 删除 server.py 中 sync_catalog_async 调用；后端删除 sync-tools 路由。
---
## 2026-06-12 mcp - 管理后台工具清单移除显示名列

**变更原因**：label（显示名）定位为纯人工维护的特殊别名字段，代码中无短中文名来源，自动同步刻意不覆盖该字段，导致列表中长期显示 "-"，视觉上像数据缺失。
**改动点**：auto-scheduler_debug `mcp-tool-permissions.blade.php` 工具清单表格移除「显示名」列，改为 4 列（工具名 24% / 说明 52% / 状态 7% / 操作 17%）；label 字段保留在编辑弹窗中，需要特殊别名时仍可人工维护。
**验证结果**：浏览器登录实测，表格 4 列对齐，说明列加宽展示完整 docstring 摘要。
**影响范围**：仅管理后台清单展示，数据结构与同步逻辑不变。
**回滚方式**：git checkout 恢复该 blade 文件。
---
## 2026-06-12 mcp - 角色绑定增加批量操作等快捷功能

**变更原因**：角色绑定 Tab 一次只能配置一个角色，多角色相似授权需重复操作，且无法看出哪些角色已配置。
**改动点**（均在 auto-scheduler_debug）：
- `McpToolPermissionController` 新增 `bindingsOverview`（角色授权统计）和 `batchBindings`（批量 replace/add/remove，add 整模块自动归一化清散装工具记录、已有整模块时跳过单工具、remove 整模块连带删除工具行，insertOrIgnore 依赖 uk_grant 幂等）；routes/api.php 注册 GET bindings/overview、PUT bindings/batch
- `mcp-tool-permissions.blade.php` 角色绑定 Tab 新增：全选整模块/清空（纯前端）、复制自角色（下拉只列已配置角色，载入后需手动保存）、批量操作弹窗（当前矩阵勾选为模板 + 多选角色 + 三模式）、角色下拉显示「N模块/M工具 / 未配置」统计；saveBindings 复用 collectGrants 并在保存后刷新统计
**验证结果**：tinker 验证批量端点 6 场景（幂等 add、整模块覆盖跳过、remove 工具/整模块、replace、overview 统计）；浏览器实测批量添加 11 模块到 2 角色落库 22 条、批量移除清零、复制 common→purchase 矩阵正确载入、保存后下拉统计即时刷新。测试数据已清理。
**影响范围**：仅管理后台角色绑定交互；单角色保存接口语义不变。
**回滚方式**：git checkout 恢复控制器、路由和 blade 文件。
---

## 2026-06-13 skills - 新增 AuWork 安装路径支持（Windows 专属，多用户目录 fan-out）

**变更原因**：需支持 AuWork Windows 客户端这一特殊安装路径 `C:\Users\<用户>\.auwork\{用户ID}\skills`，其中 `{用户ID}` 为纯数字目录，且同一机器可有多个登录用户对应多个数字目录，需把 Skill fan-out 安装到全部用户目录。AuWork 与现有 7 种运行时的本质区别是「一个运行时展开为 N 个目标目录」。
**改动点**：
- `opscli/skills/discovery/detector.py`：新增 `import sys` 与 `_auwork_targets()` 方法（Windows 专属，扫描 `~/.auwork` 下所有纯数字子目录的 skills/，非 Win/空目录返回空列表）；在 `detect_available_install_targets`、`detect_global_install_targets`、`detect_all_install_targets`、`detect_install_targets`（显式 auwork 分支）4 处织入；`candidate_dirs` 追加 auwork 目录使 list/upgrade 可发现；`_infer_runtime` 识别 `.auwork` 段。
- `opscli/skills/domain/models.py`：`runtime_to_tool_name` 加 `"auwork": "auwork"`。
- `opscli/skills/commands/cli.py`：`_TOOL_LABELS` 加 `"auwork": "AuWork"`；install `--runtime` help 文案补充 auwork；显式 `--runtime auwork` 但无数字目录时打印「已跳过」提示（GBK 兼容）。
- `tests/skills/test_detector.py`：新增 8 个 AuWork 用例（monkeypatch `sys.platform=win32` + `Path.home`）。
**验证结果**：`pytest tests/skills/test_detector.py` 新增 8 个 AuWork 用例全部 PASSED；`tests/skills/test_cli.py` 12 passed。`test_manager.py` 3 个失败、`test_detector` 中 1 个 `--runtime all` 失败、whole-dir 的 capture I/O error 经 `git stash` 验证均为改动前已存在，与本次无关。安装/链接主循环与 linker 未改动（管线本就按 list[(runtime,path)] 处理）。
**影响范围**：仅 skills 安装目标探测；新增 auwork 运行时，非 Windows 平台 `_auwork_targets()` 恒为空，对 mac/linux 零影响；现有 7 种运行时行为不变。
**回滚方式**：删除 detector 的 `_auwork_targets` 方法、4 处 `extend`/分支、candidate_dirs 与 _infer_runtime 增量，及 models/cli 的 2 处映射与提示；git checkout 恢复对应文件。
---

## 2026-06-13 skills - 修正 test_runtime_all_targets_all_supported_global_dirs 陈旧断言

**变更原因**：该测试断言 `--runtime all` 仅返回 5 个运行时，但 `detect_all_install_targets` 早已新增 trae-cn、agents（本次又加 auwork），测试一直处于失败状态（改动前已失败）。
**改动点**：`tests/skills/test_detector.py` —— 补全断言为 claude/openclaw/codex/opencode/workbuddy/trae-cn/agents/auwork 共 8 项；用例内 monkeypatch `sys.platform=win32` 并构造 `~/.auwork/1001` 数字目录以覆盖 auwork。
**验证结果**：`pytest tests/skills/test_detector.py` 9 passed。
**影响范围**：仅测试文件，无生产代码改动。
**回滚方式**：git checkout 恢复 tests/skills/test_detector.py。

## 2026-06-15 MCP - 卖家精灵调用限额

**变更原因**：MCP 卖家精灵服务需要按用户限制每日调用次数，避免外部服务被单用户高频消耗；后续西柚、Sif 也需要复用同一限额切面。
**改动点**：新增 `opscli/mcp/quota.py`，提供 `QuotaPolicy`、`SQLiteQuotaStore`、`QuotaLimiter`、`QuotaConfig`、配置文件加载和 MCP 用户身份解析；`opscli/mcp/server.py` 在现有 Tool 注册代理中加入限额 AOP 包裹，首期只限制 `seller_sprite_run`；限额计数、失败次数和每日持久化记录统一写入 SQLite 表 `mcp_quota_daily`；表内新增 `identity_key` 用于对照中间件用户身份，远程校验模式保存 `user_id` 或标准化邮箱，固定 API Key 模式保存与 MCP 用户表一致的 `sha256:<digest>`；新增 `configs/mcp-quota.json` 作为项目 / 部署目录默认运行配置，新增 `opscli/mcp/configs/mcp-quota.json` 作为 wheel 包内默认配置并通过 `pyproject.toml` 纳入 package data；运行时按 `OPSCLI_MCP_QUOTA_CONFIG_PATH`、当前工作目录 `configs/mcp-quota.json`、源码项目根目录 `configs/mcp-quota.json`、`~/.config/opscli/mcp_quota/config.json`、包内默认配置、代码默认值读取限额配置；`pyproject.toml` 和 `uv.lock` 移除外部缓存依赖，并移除暂不开放的 `google-trends` optional extra / `pytrends` 锁定；新增 `tests/mcp/test_quota.py` 并扩展卖家精灵 MCP 测试；新增 `docs/plans/MCP服务调用限额方案.md` 归档方案并更新为 SQLite 和配置文件口径。
**验证结果**：RED 阶段 `.\.venv\Scripts\python.exe -m pytest tests/mcp/test_quota.py -vv -s` 失败于 `ModuleNotFoundError: No module named 'opscli.mcp.quota'`；SQLite 持久化 RED 阶段 `$env:SKIP_CYTHON='1'; uv run --extra dev pytest tests/mcp/test_quota.py -q` 失败于 `ImportError: cannot import name 'SQLiteQuotaStore'`；身份对照 RED 阶段 `$env:SKIP_CYTHON='1'; uv run --extra dev pytest tests/mcp/test_quota.py -q` 失败于 API Key 缺少 `sha256:` 前缀和 SQLite 缺少 `identity_key` 列；配置文件 RED 阶段 `$env:SKIP_CYTHON='1'; uv run --extra dev pytest tests/mcp/test_quota.py -q` 失败于缺少 `ENV_QUOTA_CONFIG_PATH` 和 `load_quota_config`；项目配置优先级 RED 阶段 `$env:SKIP_CYTHON='1'; uv run --extra dev pytest tests/mcp/test_quota.py -q` 失败于缺少 `_project_quota_config_path`；打包部署目录 RED 阶段 `$env:SKIP_CYTHON='1'; uv run --extra dev pytest tests/mcp/test_quota.py -q` 失败于未读取当前工作目录 `configs/mcp-quota.json`；GREEN 阶段 `$env:SKIP_CYTHON='1'; uv run --extra dev pytest tests/mcp/test_quota.py -q` 为 14 passed；目标回归 `$env:SKIP_CYTHON='1'; uv run --extra dev pytest tests/mcp/test_tools.py::test_mcp_exposes_expected_tools tests/mcp/test_tools.py::test_mcp_hides_temporarily_closed_service_tools tests/mcp/test_quota.py tests/mcp/test_seller_sprite_tools.py -q` 为 21 passed。完整 MCP 回归 `$env:SKIP_CYTHON='1'; uv run --extra dev pytest tests/mcp -q` 为 75 passed、5 failed，失败项为既有 `get_mcp_request_headers` 版本头断言不一致和已停用 google_trends 注册断言。
**影响范围**：影响 MCP Tool 注册链路和 `seller_sprite_run` 调用行为；`seller_sprite_spec_must_read`、`seller_sprite_scenarios`、`seller_sprite_job_status`、`seller_sprite_export` 不扣次数；SQLite 不可用时受限服务返回 `MCP_QUOTA_UNAVAILABLE`；默认库文件为 `~/.config/opscli/mcp_quota/quota.sqlite3`，可通过 `OPSCLI_MCP_QUOTA_SQLITE_PATH` 覆盖。
**回滚方式**：删除 `opscli/mcp/quota.py`、`tests/mcp/test_quota.py` 和 `configs/mcp-quota.json`，回退 `opscli/mcp/server.py` 中 `_quota_wrap` 及注册包裹顺序，按需恢复 `google-trends` optional extra，删除方案文档和卖家精灵测试中的限额断言；如需清理本地限额记录，删除 `~/.config/opscli/mcp_quota/quota.sqlite3*` 和运行时限额配置文件。

---

## 2026-06-15 MCP - 暂停 Sif 和西柚工具注册

**变更原因**：Sif 和西柚 MCP 工具当前暂不对外开放，需要从 MCP Server 工具列表中隐藏，避免客户端继续发现和调用。
**改动点**：注释 `opscli/mcp/server.py` 中 Sif / 西柚工具模块导入与注册，保留工具模块代码；`tests/mcp/test_tools.py` 新增工具列表不可见断言。
**验证结果**：RED 阶段 `$env:SKIP_CYTHON='1'; uv run --extra dev pytest tests/mcp/test_tools.py::test_mcp_hides_temporarily_closed_service_tools -q` 失败于 `sif_run` 仍存在；GREEN 阶段 `$env:SKIP_CYTHON='1'; uv run --extra dev pytest tests/mcp/test_tools.py::test_mcp_exposes_expected_tools tests/mcp/test_tools.py::test_mcp_hides_temporarily_closed_service_tools -q` 为 2 passed。
**影响范围**：MCP Server 不再暴露 `sif_*` 和 `xiyou_*` 工具；CLI、业务模块和直接导入测试不受影响。
**回滚方式**：恢复 `opscli/mcp/server.py` 中 `_sif_tools`、`_xiyou_tools` 的导入与 register 调用，并移除工具列表隐藏断言。

---

## 2026-06-16 MCP - 卖家精灵异步任务化入口

**变更原因**：卖家精灵 `product-research` 等长任务会超过 MCP 客户端约 120 秒同步等待上限，导致用户拿不到 `job_id`，无法继续查询已启动任务状态；需要支持快速返回任务编号并由 Agent 自动轮询。
**改动点**：新增 `opscli/seller_sprite/services/task_status.py` 管理 `status.json`；`SellerSpriteApiManager` 新增内部 `start()` 和后台任务状态更新，`job_status()` 在 `result.json` 不存在时可读取 `status.json`，完成态异步任务会合并 `status.json` 的 `state/stage` 与 `result.json` 的业务结果；MCP 侧保持 `seller_sprite_run` 作为唯一采集入口，长耗时场景由后端自动调用内部异步任务路径并返回 `job_id`，不向 Agent 暴露 `seller_sprite_start`、`async_mode`、`mode`、`browser-route` 或 `api-direct` 控制；限额策略继续只绑定 `seller_sprite_run`，避免同步/异步入口双计数或策略冲突；更新 `ops-seller-sprite` MCP Skill 文档、卖家精灵 MCP 接口说明、异步入口方案文档和执行计划文档；扩展 MCP、manager、工具列表和 quota 单测覆盖 queued/running/succeeded/failed、Schema 隐藏与公开限额入口。
**验证结果**：RED 阶段 `.\.venv\Scripts\python.exe -m pytest tests\mcp\test_seller_sprite_tools.py -q` 失败于缺少自动异步任务路径；RED 阶段 `.\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_api_manager.py -q` 失败于 manager 缺少 `start()`；完成态合并 RED 阶段 `.\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_api_manager.py::test_job_status_merges_completed_async_status_with_result -q` 失败于 `state` 缺失；公开入口收敛 RED 阶段 `.\.venv\Scripts\python.exe -m pytest tests\mcp\test_tools.py::test_seller_sprite_internal_controls_are_not_exposed -q` 失败于 MCP Schema 仍暴露内部控制；GREEN 阶段相关定向测试通过；目标回归 `.\.venv\Scripts\python.exe -m pytest tests\seller_sprite tests\mcp\test_seller_sprite_tools.py tests\mcp\test_quota.py tests\mcp\test_tools.py -q` 为 60 passed；编译检查 `.\.venv\Scripts\python.exe -m py_compile opscli\seller_sprite\services\task_status.py opscli\seller_sprite\services\api_manager.py opscli\seller_sprite\browser_route\worker.py opscli\seller_sprite\browser_route\__init__.py opscli\mcp\tools\seller_sprite.py opscli\mcp\quota.py` 通过。
**影响范围**：影响卖家精灵 `seller_sprite_run` 对长任务的返回形态、`seller_sprite_job_status` 对异步任务的读取行为、卖家精灵任务目录新增 `status.json`，以及 MCP Schema 对内部控制参数的隐藏；公开限额入口仍只有 `seller_sprite_run`，不增加浏览器窗口并发。
**回滚方式**：删除 `opscli/seller_sprite/services/task_status.py`，回退 `api_manager.py` 中 `start()`、`_run_background_task()`、`job_status()` 状态读取逻辑，回退 `seller_sprite.py` 中 `seller_sprite_run` 自动异步判断和内部控制隐藏，移除对应测试和文档段落。

---

## 2026-06-17 MCP - 卖家精灵队列忙自动异步

**变更原因**：卖家精灵 browser-route 只保留单账号单窗口串行执行；当已有任务运行或排队时，后续同步 `seller_sprite_run` 会把 MCP 等待预算耗在排队上并容易超时，因此队列忙时应自动切换为异步任务。
**改动点**：`SellerSpriteBrowserRouteWorker` 新增 `is_busy` 状态，`browser_route` 模块新增 `get_existing_browser_route_worker()` 用于只读取已有 worker、不创建新窗口；`SellerSpriteApiManager` 新增 `browser_route_busy()` 判断当前请求对应账号 worker 是否忙；`seller_sprite_run` 在长耗时场景或 browser-route worker 忙时自动调用 `manager.start()`；更新 `ops-seller-sprite` MCP Skill 文档和卖家精灵 MCP 接口说明。
**验证结果**：RED 阶段 `.\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_browser_route_worker.py::test_worker_reports_busy_when_drain_lock_is_held -q` 失败于 worker 缺少 `is_busy`；RED 阶段 `.\.venv\Scripts\python.exe -m pytest tests\mcp\test_seller_sprite_tools.py::test_seller_sprite_run_auto_starts_when_browser_queue_is_busy -q` 失败于仍返回同步 `job-1`；GREEN 阶段上述两个测试均为 1 passed；回归 `.\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_browser_route_worker.py tests\seller_sprite\test_api_manager.py tests\mcp\test_seller_sprite_tools.py -q` 为 25 passed；编译检查 `.\.venv\Scripts\python.exe -m py_compile opscli\seller_sprite\browser_route\worker.py opscli\seller_sprite\browser_route\__init__.py opscli\seller_sprite\services\api_manager.py opscli\mcp\tools\seller_sprite.py` 通过。
**影响范围**：影响 `seller_sprite_run` 在长耗时场景和 browser-route 队列忙时的行为，返回值会从同步结果变为异步任务状态；普通短任务且队列不忙时仍保持同步；不增加浏览器窗口并发。
**回滚方式**：回退 `worker.py` 的 `is_busy` 和 `get_existing_browser_route_worker()`、`browser_route/__init__.py` 导出、`api_manager.py` 的 `browser_route_busy()`、`seller_sprite.py` 的队列忙自动 `start()` 判断，并移除对应测试和文档说明。

## 2026-06-11 skills - manifest 补齐 8 个未声明的 Skill 模板目录

**变更原因**：Skill 发版检查（`validate_release_manifest`）报错"模板目录未在 manifest 声明"，`opscli/skills/templates/` 下 8 个新模板目录未在 `manifest.json` 中登记。
**改动点**：在 `opscli/skills/templates/manifest.json` 的 `skills` 末尾追加 `ops-feed-task`、`ops-shopify-delete`、`ops-shopify-inventory`、`ops-shopify-price`、`ops-shopify-query`、`ops-shopify-status`、`ops-sif`、`ops-xiyou` 共 8 个条目，四个发版开关（source/wheel/binary/binary_full）全部为 false，tier 设为 internal。
**验证结果**：`validate_release_manifest()` 返回空（通过）；`pytest tests/skills/test_packaging.py -q -s` 6 passed；目录与 manifest 双向对比无缺失无多余。
**影响范围**：仅影响 Skill 发版打包白名单，新增条目均为 false，不改变任何现有发版产物内容。
**回滚方式**：从 `manifest.json` 中删除上述 8 个新增条目。
---
## 2026-06-12 skills - ops-dataset-query 移除 catalog intents 意图匹配

**变更原因**：后台暂未配置 catalog intents，远端意图匹配（`query_catalog` / `query_intent_match` / `opscli query intent`）无数据可用，强制要求先调用会导致流程空转。本版将数据集确定流程改为：本地意图路由（route_intent.py）→ 本地关键词搜索（search.py）→ MCP 模式用 query_metadata() 列表筛选。
**改动点**：仅修改 ops-dataset-query Skill 模板文档，未改任何 Python 代码：
- `SKILL.md`：铁律三改为"本地意图路由"，删除铁律三-A（Intent 约束优先）和铁律三-B（Catalog 回退链）的远端部分；标准工作流去除 query_intent_match 步骤
- `QUERY_SPEC.md`：删除铁律 5 / 10-A 的 catalog 依赖，删除 query_catalog / query_intent_match 工具章节，工作流 B 改为 query_metadata() 列表筛选，自检清单去除 Intent 约束项
- `references/cli.md`：删除 `opscli query catalog` / `opscli query intent` 命令章节，改为 route_intent.py 本地意图路由；典型工作流同步更新
- `references/mcp.md`：删除 query_catalog / query_intent_match Tool 索引，字段存在性检查第 0 步改为 query_metadata() 列表筛选
- `references/mcp-simple-guide.md`：删除 query_catalog / query_intent_match 参数说明章节
- `references/rules.md`：第八章改为本地意图匹配规则，数据来源去除 dataset_catalog.json
- `references/simple-query-guide.md` / `references/ask-user-question-guide.md`：去除 catalog 字样引用
**验证结果**：`grep -rn -i "catalog|query_intent_match|opscli query intent|intent_constraints"` 在 Skill 模板所有 .md 中零残留；本地路由脚本 route_intent.py 与 intent_taxonomy.yml 数据文件保持不变，本地意图路由能力保留。
**影响范围**：仅影响 AI Agent 阅读 ops-dataset-query Skill 后的数据集确定流程；MCP Server 端 query_catalog / query_intent_match 工具代码未删除，后台配置 intents 后可恢复文档。
**回滚方式**：git checkout 恢复 opscli/skills/templates/ops-dataset-query/ 下的 SKILL.md、QUERY_SPEC.md 和 references/ 各文件。
---
## 2026-06-12 mcp - MCP 工具按用户角色权限动态过滤

**变更原因**：此前任何用户连接 MCP Server 后默认可见/可用全部 60+ 工具。需求改为白名单制：由 OPS 后端按用户角色（运营系统角色 sys_roles + BI 角色 Doris mv_user_role）计算可用工具，opscli 在 list_tools 阶段过滤无权限工具（减少 AI 上下文开销）并在 call_tool 时拦截越权调用。
**改动点**：
- 新增 `opscli/mcp/permissions.py`：`ToolPermissionMiddleware`（fastmcp Middleware，on_list_tools 过滤 + on_call_tool 拦截）、`BASE_AUTH_TOOLS` 基础白名单（14 个 auth_* 工具，与后端 McpToolPermissionService::BASE_AUTH_TOOLS 双端一致）、`_resolve_allowed_tools()` 三模式自探测（HTTP 远程校验模式读上下文 allowed_tools / 固定 Key 模式或旧后端全量放行 / stdio 模式按本地 session 调 GET /v1/mcp/allowed-tools，缓存 300s，404 放行、401 仅基础工具、网络异常 stale-while-error 或 fail-closed）
- `opscli/mcp/auth_middleware.py`：verify-key 响应中的 allowed_tools 注入 scope 和 contextvar
- `opscli/mcp/server.py`：注册 `mcp.add_middleware(ToolPermissionMiddleware())`
- `opscli/mcp/tools/auth.py`：auth_mcp_login / auth_login_poll / auth_logout 成功路径调用 invalidate_stdio_cache()
- 后端配套（auto-scheduler）：新增 mcp_modules / mcp_tools / mcp_role_permissions 三表（ops_sys 库）+ McpToolPermissionService + verify-key 返回 allowed_tools + GET /v1/mcp/allowed-tools 端点
**验证结果**：新增 `tests/mcp/test_tool_permissions.py` 15 个测试全部通过；tests/mcp/ 81 passed（5 个失败经 git stash 对比确认为历史遗留）；后端 tinker 验证三种授权情形（无绑定=14 基础工具/整模块=25/单工具=26）；curl 验证 verify-key 带 allowed_tools 字段、allowed-tools 端点 200/401 两条路径。
**影响范围**：HTTP/SSE 远程校验模式和 stdio 模式的工具可见性按角色过滤；固定 API Key 单用户模式和旧后端全量放行不受影响（兼容语义：响应无 allowed_tools 字段=放行）。
**回滚方式**：opscli 端删除 server.py 中 add_middleware 一行即恢复全量；后端回滚迁移 `php artisan migrate:rollback --path=database/migrations/2026_06_12_000001_create_mcp_tool_permission_tables.php`。
---
## 2026-06-12 mcp - MCP 工具清单启动自动上报后端（替代人工维护）

**变更原因**：MCP 工具清单此前由管理后台人工维护，新增工具需手工录入且显示名/说明为空。改为 MCP Server 启动时自动上报清单，描述自动取自代码 docstring。
**改动点**：
- 新增 `opscli/mcp/tool_catalog.py`：`record_tool()` 注册时采集元数据（工具名优先取 name= 覆盖、模块取函数 __module__ 末段、描述取注册参数或 docstring 首行）；`sync_catalog_async()` HTTP/SSE 模式启动时守护线程 POST /v1/mcp/sync-tools（同步地址与 --auth-verify-url 同源，否则从 config.ini 推导；404/网络异常静默不影响启动）
- `opscli/mcp/server.py`：`_TelemetryMcpProxy.tool()` 注册包裹时调用 record_tool；run() HTTP 分支启动时调用 sync_catalog_async
- 后端（auto-scheduler）：新增 `McpToolSyncController::sync` + 路由 POST /v1/mcp/sync-tools。同步语义：只增不删（新模块/工具自动入库启用，缺失工具不自动停用），已有工具仅刷新 description 和 module_id，label/is_active 人工字段不覆盖
- 管理页（auto-scheduler_debug mcp-tool-permissions.blade.php）：工具表格改 table-layout:fixed 固定列宽（22/12/42/7/17%），超长省略+title 提示
- 数据修正：停用种子中 4 个代码注释未注册的预留工具（auth_login_start/auth_login_poll/auth_system_add/auth_system_remove）
**验证结果**：新增 `tests/mcp/test_tool_catalog.py` 6 个测试通过（chatgpt 无前缀工具归属、seller_sprite 多段前缀、404/网络异常容错）；tests/mcp/ 87 passed（5 失败为历史遗留）；真实启动 E2E：清空 keepa_run 描述 → 启动服务 → 描述自动回填 docstring 首行；浏览器确认页面列宽对齐、53 个工具说明已自动填充。
**影响范围**：HTTP/SSE 模式启动多一次后台上报（守护线程，失败仅日志）；stdio 模式不上报；管理后台 CRUD 保留可继续手动微调。
**回滚方式**：opscli 删除 server.py 中 sync_catalog_async 调用；后端删除 sync-tools 路由。
---
## 2026-06-12 mcp - 管理后台工具清单移除显示名列

**变更原因**：label（显示名）定位为纯人工维护的特殊别名字段，代码中无短中文名来源，自动同步刻意不覆盖该字段，导致列表中长期显示 "-"，视觉上像数据缺失。
**改动点**：auto-scheduler_debug `mcp-tool-permissions.blade.php` 工具清单表格移除「显示名」列，改为 4 列（工具名 24% / 说明 52% / 状态 7% / 操作 17%）；label 字段保留在编辑弹窗中，需要特殊别名时仍可人工维护。
**验证结果**：浏览器登录实测，表格 4 列对齐，说明列加宽展示完整 docstring 摘要。
**影响范围**：仅管理后台清单展示，数据结构与同步逻辑不变。
**回滚方式**：git checkout 恢复该 blade 文件。
---
## 2026-06-12 mcp - 角色绑定增加批量操作等快捷功能

**变更原因**：角色绑定 Tab 一次只能配置一个角色，多角色相似授权需重复操作，且无法看出哪些角色已配置。
**改动点**（均在 auto-scheduler_debug）：
- `McpToolPermissionController` 新增 `bindingsOverview`（角色授权统计）和 `batchBindings`（批量 replace/add/remove，add 整模块自动归一化清散装工具记录、已有整模块时跳过单工具、remove 整模块连带删除工具行，insertOrIgnore 依赖 uk_grant 幂等）；routes/api.php 注册 GET bindings/overview、PUT bindings/batch
- `mcp-tool-permissions.blade.php` 角色绑定 Tab 新增：全选整模块/清空（纯前端）、复制自角色（下拉只列已配置角色，载入后需手动保存）、批量操作弹窗（当前矩阵勾选为模板 + 多选角色 + 三模式）、角色下拉显示「N模块/M工具 / 未配置」统计；saveBindings 复用 collectGrants 并在保存后刷新统计
**验证结果**：tinker 验证批量端点 6 场景（幂等 add、整模块覆盖跳过、remove 工具/整模块、replace、overview 统计）；浏览器实测批量添加 11 模块到 2 角色落库 22 条、批量移除清零、复制 common→purchase 矩阵正确载入、保存后下拉统计即时刷新。测试数据已清理。
**影响范围**：仅管理后台角色绑定交互；单角色保存接口语义不变。
**回滚方式**：git checkout 恢复控制器、路由和 blade 文件。
---

## 2026-06-13 skills - 新增 AuWork 安装路径支持（Windows 专属，多用户目录 fan-out）

**变更原因**：需支持 AuWork Windows 客户端这一特殊安装路径 `C:\Users\<用户>\.auwork\{用户ID}\skills`，其中 `{用户ID}` 为纯数字目录，且同一机器可有多个登录用户对应多个数字目录，需把 Skill fan-out 安装到全部用户目录。AuWork 与现有 7 种运行时的本质区别是「一个运行时展开为 N 个目标目录」。
**改动点**：
- `opscli/skills/discovery/detector.py`：新增 `import sys` 与 `_auwork_targets()` 方法（Windows 专属，扫描 `~/.auwork` 下所有纯数字子目录的 skills/，非 Win/空目录返回空列表）；在 `detect_available_install_targets`、`detect_global_install_targets`、`detect_all_install_targets`、`detect_install_targets`（显式 auwork 分支）4 处织入；`candidate_dirs` 追加 auwork 目录使 list/upgrade 可发现；`_infer_runtime` 识别 `.auwork` 段。
- `opscli/skills/domain/models.py`：`runtime_to_tool_name` 加 `"auwork": "auwork"`。
- `opscli/skills/commands/cli.py`：`_TOOL_LABELS` 加 `"auwork": "AuWork"`；install `--runtime` help 文案补充 auwork；显式 `--runtime auwork` 但无数字目录时打印「已跳过」提示（GBK 兼容）。
- `tests/skills/test_detector.py`：新增 8 个 AuWork 用例（monkeypatch `sys.platform=win32` + `Path.home`）。
**验证结果**：`pytest tests/skills/test_detector.py` 新增 8 个 AuWork 用例全部 PASSED；`tests/skills/test_cli.py` 12 passed。`test_manager.py` 3 个失败、`test_detector` 中 1 个 `--runtime all` 失败、whole-dir 的 capture I/O error 经 `git stash` 验证均为改动前已存在，与本次无关。安装/链接主循环与 linker 未改动（管线本就按 list[(runtime,path)] 处理）。
**影响范围**：仅 skills 安装目标探测；新增 auwork 运行时，非 Windows 平台 `_auwork_targets()` 恒为空，对 mac/linux 零影响；现有 7 种运行时行为不变。
**回滚方式**：删除 detector 的 `_auwork_targets` 方法、4 处 `extend`/分支、candidate_dirs 与 _infer_runtime 增量，及 models/cli 的 2 处映射与提示；git checkout 恢复对应文件。
---

## 2026-06-13 skills - 修正 test_runtime_all_targets_all_supported_global_dirs 陈旧断言

**变更原因**：该测试断言 `--runtime all` 仅返回 5 个运行时，但 `detect_all_install_targets` 早已新增 trae-cn、agents（本次又加 auwork），测试一直处于失败状态（改动前已失败）。
**改动点**：`tests/skills/test_detector.py` —— 补全断言为 claude/openclaw/codex/opencode/workbuddy/trae-cn/agents/auwork 共 8 项；用例内 monkeypatch `sys.platform=win32` 并构造 `~/.auwork/1001` 数字目录以覆盖 auwork。
**验证结果**：`pytest tests/skills/test_detector.py` 9 passed。
**影响范围**：仅测试文件，无生产代码改动。
**回滚方式**：git checkout 恢复 tests/skills/test_detector.py。
---
## 2026-06-18 mcp - 卖家精灵规范读取合并参数手册

**变更原因**：`ops-seller-sprite` 的 `SKILL_MCP.md` 已精简为入口文档，参数细节下沉到 `SCENARIO_PARAMS_ZH.md`。`seller_sprite_spec_must_read` 若仍只返回主文档，纯 MCP 客户端将拿不到完整参数口径。
**改动点**：`opscli/mcp/tools/seller_sprite.py` 新增 Skill 模板目录辅助函数，并让 `seller_sprite_spec_must_read()` 同时读取 `SKILL_MCP.md` 和 `SCENARIO_PARAMS_ZH.md`，返回合并后的 `spec` 与 `sources`；`tests/mcp/test_seller_sprite_tools.py` 新增回归测试，要求规范读取结果包含参数手册标题。
**验证结果**：`D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests/mcp/test_seller_sprite_tools.py -k spec_must_read -v` 通过（1 passed）；`D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests/mcp/test_seller_sprite_tools.py -v` 通过（9 passed）。
**影响范围**：影响 SellerSprite MCP 首次“先读规范”行为；不影响 `seller_sprite_run`、`seller_sprite_job_status`、`seller_sprite_export` 的业务执行逻辑。
**回滚方式**：回退 `opscli/mcp/tools/seller_sprite.py`、`tests/mcp/test_seller_sprite_tools.py` 和本条变更记录。
---
## 2026-06-24 seller_sprite - run 入口增加运行态 8 分钟代等

**变更原因**：用户认为公开 `seller_sprite_run` 过早把 `job_id` 暴露给调用方，要求 CLI 与 MCP 统一改为“先代等结果，只有任务真正执行超时后才转异步续查”。
**改动点**：`opscli/mcp/tools/seller_sprite.py` 新增公开 run 入口的代等逻辑：`queued` 阶段持续等待，进入 `running` 后最多再等待 8 分钟；若在窗口内 `succeeded/failed` 则直接返回最终状态，若 `running` 超时则返回 `job_id` 并补充 `queue_duration`、`running_duration`；`tests/mcp/test_seller_sprite_tools.py` 新增成功直返与运行超时两组 TDD 回归，并将原本只验证入队的测试改为显式跳过代等；`opscli/skills/templates/ops-seller-sprite/SKILL.md`、`opscli/skills/templates/ops-seller-sprite/SKILL_MCP.md` 同步更新公开入口等待语义与续查规则。
**验证结果**：RED：`D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\mcp\test_seller_sprite_tools.py -k "waits_until_success or running_timeout" -v` 初始失败，现有实现仍直接返回 `queued`；GREEN：同命令复跑通过（2 passed）；`D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\mcp\test_seller_sprite_tools.py -v` 通过（18 passed）。
**影响范围**：影响公开 `seller_sprite_run` 的返回时机与超时回包字段；底层 SQLite 队列、调度器消费、`seller_sprite_start`、`seller_sprite_job_status`、`seller_sprite_export` 保持不变。
**回滚方式**：回退 `opscli/mcp/tools/seller_sprite.py`、`tests/mcp/test_seller_sprite_tools.py`、两份 `ops-seller-sprite` Skill 文档以及本条变更记录。
---
## 2026-06-18 seller_sprite - 竞品查询补单 ASIN 归一化与本地快速失败

**变更原因**：`competitor-lookup` 场景在收到单个 `asin` 时没有归一化到 `asins`，会构造出空主筛选 payload；缺少主筛选条件时也未在本地拦截，导致无效请求继续走远端并表现为 MCP 30 秒超时。
**改动点**：`opscli/seller_sprite/api/payloads.py` 的 `make_competitor_payload()` 新增 `asin -> asins` 归一化；`opscli/seller_sprite/api/scenarios.py` 为场景定义新增 `required_any_params`，并让 `competitor-lookup` 强制要求 `keyword`、`brand`、`sellerName`、`asin`、`asins` 至少其一；`ops-seller-sprite` 的 `SKILL.md`、`SKILL_MCP.md`、`SCENARIO_PARAMS_ZH.md` 同步补充“单个 ASIN 必须归一化为 asins”和“缺主筛选条件必须本地快速失败”的规则；`tests/seller_sprite/test_payloads.py` 与 `tests/seller_sprite/test_api_manager.py` 新增对应回归测试。
**验证结果**：`D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests/seller_sprite/test_payloads.py tests/seller_sprite/test_api_manager.py -k "competitor" -v` 通过（6 passed）；`D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests/seller_sprite/test_payloads.py tests/seller_sprite/test_api_manager.py -v` 通过（23 passed）。
**影响范围**：影响 `competitor-lookup` 的本地参数校验和 payload 构造；无效竞品请求将立即报配置错误，不再继续拖成远端超时。
**回滚方式**：回退 `opscli/seller_sprite/api/payloads.py`、`opscli/seller_sprite/api/scenarios.py`、相关 skill 文档、测试和本条变更记录。
---
## 2026-06-22 seller_sprite - MCP 调用记录入 SQLite

**变更原因**：卖家精灵 MCP 服务需要补齐调用审计，记录调用用户、模式、参数和结果摘要，便于排查异步队列任务与导出结果。
**改动点**：`opscli/seller_sprite/services/task_queue_store.py` 在现有 `task_queue.sqlite3` 中新增 `seller_sprite_mcp_runs` 表、迁移补列逻辑和 MCP 记录读写方法；`opscli/mcp/tools/seller_sprite.py` 在 `seller_sprite_run` 中补邮箱读取、最终 `job_id` 规范化、入队前创建记录和入队异常失败回写；`opscli/seller_sprite/services/task_scheduler.py` 在任务执行链路中接入 `running/succeeded/failed` 审计状态同步，并隔离 MCP 探测/收尾异常避免拖垮普通任务；`tests/seller_sprite/test_task_queue_store.py`、`tests/mcp/test_seller_sprite_tools.py`、`tests/seller_sprite/test_task_scheduler.py` 新增对应 TDD 回归用例。
**验证结果**：仓储层定向回归 `D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_task_queue_store.py -q` 通过（12 passed）；MCP 入口定向回归 `D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\mcp\test_seller_sprite_tools.py -v` 通过（14 passed）；调度器定向回归 `D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_task_scheduler.py -v` 通过（9 passed）；目标总回归 `D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_task_queue_store.py tests\mcp\test_seller_sprite_tools.py tests\seller_sprite\test_task_scheduler.py -q` 通过（35 passed）。
**影响范围**：影响 `seller_sprite_run` 的 MCP 入队前后审计行为、卖家精灵单账号调度器的 MCP 状态同步，以及本地 `task_queue.sqlite3` 的表结构；`seller_sprite_start`、任务目录产物和非 MCP 卖家精灵执行入口保持不变。
**回滚方式**：回退 `opscli/seller_sprite/services/task_queue_store.py`、`opscli/mcp/tools/seller_sprite.py`、`opscli/seller_sprite/services/task_scheduler.py` 及对应三组测试，并删除 `seller_sprite_mcp_runs` 表相关逻辑和本条变更记录。
---
## 2026-06-23 seller_sprite - 修复 task_scheduler 测试文件合并冲突

**变更原因**：`tests/seller_sprite/test_task_scheduler.py` 残留 Git 冲突标记，导致 pytest 在收集阶段直接抛出 `SyntaxError`，卖家精灵调度器相关回归无法执行。
**改动点**：清理 `tests/seller_sprite/test_task_scheduler.py` 中的冲突标记，保留 MCP 调度状态回写测试和 `get_task_scheduler()` 同步 CLI 上下文复用测试两侧内容，并补齐函数间空行。
**验证结果**：`D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_task_scheduler.py -q` 通过（10 passed）。
**影响范围**：仅影响卖家精灵调度器测试文件的可解析性与回归覆盖面，不改动生产代码逻辑。
**回滚方式**：回退 `tests/seller_sprite/test_task_scheduler.py` 与本条变更记录。
---
## 2026-06-23 seller_sprite / mcp_client - 正式 CLI 切换为远端 MCP 配置直连

**变更原因**：卖家精灵正式 CLI 需要先复用现有 CLI 登录态请求 `/v1/mcp-api-keys/config`，以获取远端 MCP HTTP 服务配置；同时需要把公开 `opscli seller-sprite` 从“本地服务桥接”切换为“远端 MCP URL 直连”，而 `seller-sprite-debug` 保留本地调试链路。
**改动点**：新增 `opscli/mcp_client/__init__.py` 导出 `McpConfigClient`、`RemoteMcpServerConfig`、`RemoteMcpClient`、`RemoteMcpToolError` 及模块内专用异常；新增 `opscli/mcp_client/config_client.py`，通过 `AuthClient.build_request_auth("ops")` + `httpx.get` + `parse_remote_response` 获取 `/v1/mcp-api-keys/config`，并补充该接口专属 `success=true` 契约校验；在同文件内新增 `RemoteConfigHttpError`、`RemoteConfigBusinessError`、`BadRemoteConfigError`，替换原先裸 `RuntimeError` / `ValueError`；`select_server()` 增加 `http.mcpServers` 非空字典、服务项 `type`、`url` 等结构校验，并在 malformed 输入时统一抛结构化异常；新增 `opscli/mcp_client/remote_client.py` 作为 URL 直连 MCP 的极薄封装，补齐 `create_mcp_http_client()` 生命周期管理，显式关闭自建 `AsyncClient`，并将错误分支改为“安全文本提取”：远端 `result.isError=true` 时即使 `content` 缺失、为空、首项非文本或空白文本，也统一抛出 `RemoteMcpToolError`，不再先被本地 `ValueError` 截断；新增 `opscli/seller_sprite/remote_adapter.py`，统一将 `scenarios/run/job-status/export` 映射到远端 `seller_sprite_*` MCP tool，并在首次调用因 `401` 失败时重拉一次远端 config 后重试一次；`opscli/seller_sprite/cli.py` 改为正式 CLI 通过该 adapter 执行远端调用，不再直接依赖本地 `SellerSpriteApiManager` / `task_scheduler`；`seller-sprite-debug` 入口与本地专用 `--mode` 等参数保持不变；新增 `tests/mcp/test_config_client.py`、`tests/mcp/test_remote_client.py`、`tests/seller_sprite/test_remote_adapter.py`、`tests/seller_sprite/test_cli.py`、`tests/seller_sprite/test_remote_refresh.py`，并更新 `tests/seller_sprite/test_cli_split.py` 覆盖正式/debug 命令分流、远端适配器接线与 401 后一次性重拉 config。
**验证结果**：RED：`D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\mcp\test_config_client.py -q` 初始失败，报 `ModuleNotFoundError: No module named 'opscli.mcp_client'`；`D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\mcp\test_remote_client.py -q` 初始失败，报 `ModuleNotFoundError: No module named 'opscli.mcp_client.remote_client'`；`D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_remote_adapter.py tests\seller_sprite\test_cli.py tests\seller_sprite\test_cli_split.py -q` 初始失败，报 `ModuleNotFoundError: No module named 'opscli.seller_sprite.remote_adapter'`；`D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_remote_refresh.py -q` 初始失败，报首次 `401 unauthorized` 仍直接外抛；本次质量修复阶段再次先写失败测试，`tests\mcp\test_remote_client.py` 初始失败于 `isError=true` 且 `content` 畸形时仍抛本地 `ValueError`。GREEN：`D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\mcp\test_config_client.py -q` 通过（8 passed）；`D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\mcp\test_remote_client.py -q` 通过（14 passed）；`D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_remote_adapter.py tests\seller_sprite\test_cli.py tests\seller_sprite\test_cli_split.py -q` 通过（10 passed）；`D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_remote_refresh.py -q` 通过（1 passed）；`D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests\seller_sprite\test_remote_refresh.py tests\seller_sprite\test_remote_adapter.py tests\seller_sprite\test_cli.py tests\seller_sprite\test_cli_split.py tests\mcp\test_config_client.py tests\mcp\test_remote_client.py -q` 通过（33 passed）。
**影响范围**：影响公开 `opscli seller-sprite` 命令的执行链路与返回口径，现改为“CLI auth -> 远端 MCP 配置 -> 远端 tool 调用”；`opscli seller-sprite-debug` 本地调试命令、现有卖家精灵服务实现、MCP server 内部工具实现不受影响。
**回滚方式**：删除 `opscli/mcp_client/__init__.py`、`opscli/mcp_client/config_client.py`、`opscli/mcp_client/remote_client.py`、`opscli/seller_sprite/remote_adapter.py`、对应新增测试，并将 `opscli/seller_sprite/cli.py` 回退到本地桥接版本，同时回退本条变更记录。
---
## 2026-06-23 seller_sprite - 卖家精灵额度查询与提示优化

**变更原因**：卖家精灵 MCP 已有每日限额，但用户缺少执行前查询额度的入口，执行后也没有统一的剩余额度提示规则。
**改动点**：在 MCP 限额模块新增只读额度快照能力；新增 `seller_sprite_quota_status` 工具和 `opscli seller-sprite quota-status` 正式 CLI 入口；更新卖家精灵 Skill 文档，明确只有 `run` 消耗次数，并要求回答中补充额度摘要。
**验证结果**：已运行 `.\\.venv\\Scripts\\python.exe -m pytest tests\\mcp\\test_quota.py -k snapshot -v`、`.\\.venv\\Scripts\\python.exe -m pytest tests\\mcp\\test_seller_sprite_tools.py -k quota_status -v`、`.\\.venv\\Scripts\\python.exe -m pytest tests\\seller_sprite\\test_remote_adapter.py tests\\seller_sprite\\test_cli.py -k quota_status -v`，均通过。
**影响范围**：卖家精灵 MCP、正式 CLI、Skill 文档、MCP 限额快照读取逻辑。
**回滚方式**：回退 `opscli/mcp/quota.py`、`opscli/mcp/tools/seller_sprite.py`、`opscli/seller_sprite/remote_adapter.py`、`opscli/seller_sprite/cli.py`、对应测试和文档改动。
---

## 2026-06-24 CI/build-and-publish - 弃用 win32 并跳过 macOS x86_64 跨架构测试

**变更原因**：v0.0.98 发版 CI 在 cibuildwheel 测试阶段失败。根因是测试时 pip 安装 wheel 会拉取 cryptography，但 (1) Windows win32 没有 32 位 cryptography 预编译 wheel；(2) macos-latest 已是 arm64，cibuildwheel 用 `arch -x86_64` 跨架构测试 x86_64 wheel 时匹配不到 x86_64 预编译包，两者均退化为源码编译（需 Rust+OpenSSL）从而报错 `Failed building wheel for cryptography` / `openssl-sys`。
**改动点**：`.github/workflows/build-and-publish.yml` 新增 `CIBW_ARCHS_WINDOWS: "AMD64"`（不再构建 win32）与 `CIBW_TEST_SKIP: "*-macosx_x86_64"`（仅跳过 x86_64 macOS 的冒烟测试，仍正常构建该 wheel）。
**验证结果**：`python3 -c "import yaml; yaml.safe_load(...)"` 校验 YAML 语法通过；待重新触发 tag 构建确认 CI 绿。
**影响范围**：不再产出 32 位 Windows wheel（该 wheel 本就无法安装 cryptography，用户无损失）；macOS x86_64 wheel 仍正常构建发布，仅 CI 不再跨架构冒烟测试它，真实 Intel Mac 安装不受影响。
**回滚方式**：删除这两行 env 配置即可恢复原状。
---

## 2026-06-24 pyproject + CI - 【修正】锁 cryptography<49 修复 Intel Mac/win32 安装失败（取代上一条方案B）

**变更原因**：进一步核实 PyPI 后发现，v0.0.98 CI 失败的真正根因是 cryptography 在 49.0.0（2026-06 新发布）中**移除了 macOS x86_64/universal2 与 Windows win32 的预编译 wheel**（48.0.1 仍带这两类 wheel）。`cryptography>=38` 无上限 → CI 与真实用户都会拿到 49.0.0 → Intel Mac / 32 位 Windows 上无匹配 wheel → 退化为源码编译（需 Rust+OpenSSL）失败。v0.0.97（cryptography 48.0.1）能过即此证。**仅跳过 CI 测试（方案B）会让 CI 假绿，但有 Intel Mac 用户仍无法安装，故改为锁版本。**
**改动点**：(1) `pyproject.toml` 核心依赖 `cryptography>=38` → `cryptography>=38,<49`（带中文注释说明 breaking change）；(2) `.github/workflows/build-and-publish.yml` 撤掉前一条加的 `CIBW_TEST_SKIP: "*-macosx_x86_64"`（锁版本后 48.0.1 universal2 可在 Rosetta 下正常安装，无需跳过测试）；保留 `CIBW_ARCHS_WINDOWS: "AMD64"`（团队无 32 位 Windows 用户，产品选择弃用 win32，注释已据实修正）。
**验证结果**：`tomllib`/`yaml` 语法校验通过；`<49` 经 PyPI 解析到 48.0.1（确认含 universal2 + win32 wheel）。最终验证待发新 tag 触发 CI 全绿。
**影响范围**：Intel Mac 与（若构建）32 位 Windows 用户恢复可安装；arm64 mac / win_amd64 / Linux 不受影响。代价：用户停留在 cryptography 48.0.1，暂不获取 49.x 安全更新；上游 macOS 正转向仅 arm64，Intel Mac 支持长期需另行规划。
**回滚方式**：`pyproject.toml` 改回 `cryptography>=38`，workflow 改动用 git 还原即可。
---
## 2026-06-26 keepa / mcp - Keepa 接入 MCP 每日额度限制与额度查询入口

**变更原因**：`opscli keepa` 仍缺少和 `seller_sprite` 一致的 MCP 外层每日额度限制与额度查询入口；同时 `opscli/mcp/configs/mcp-quota.json` 也未登记 `keepa_run` 的默认策略，导致 Keepa 无法被统一配额配置覆盖。
**改动点**：`opscli/mcp/quota.py` 将 `keepa_run` 纳入内置默认限额策略（service=`keepa`，daily_limit=5），并同步放宽配置读取注释为“使用代码内置默认值”；`opscli/mcp/tools/keepa.py` 新增 `keepa_quota_status` 工具与当前 MCP 用户邮箱解析辅助函数，并把该工具注册到公开 MCP 列表；`opscli/keepa/remote_adapter.py` 新增 `quota_status()` 映射到远端 `keepa_quota_status`；`opscli/keepa/cli.py` 新增正式命令 `opscli keepa quota-status`；`opscli/mcp/configs/mcp-quota.json` 新增 `keepa_run` 配置项；测试侧补充 `tests/mcp/test_quota.py`、`tests/mcp/test_keepa_tools.py`、`tests/keepa/test_cli_remote.py`、`tests/keepa/test_remote_adapter.py` 回归，覆盖默认策略、MCP 快照读取、正式 CLI 和 remote adapter 映射。
**验证结果**：RED：`D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests/mcp/test_quota.py tests/mcp/test_keepa_tools.py tests/keepa/test_cli_remote.py tests/keepa/test_remote_adapter.py -q` 初始失败（5 failed），分别暴露 `keepa_run` 未进入默认策略、`keepa_quota_status` 工具缺失、正式 CLI 缺少 `quota-status`、remote adapter 缺少 `quota_status()`；GREEN：同命令复跑通过（36 passed）；补充回归 `D:\Gitlab\open-opscli\.venv\Scripts\python.exe -m pytest tests/mcp/test_quota.py tests/mcp/test_keepa_tools.py tests/mcp/test_tools.py tests/keepa/test_cli_remote.py tests/keepa/test_cli_split.py tests/keepa/test_remote_adapter.py -q` 通过（50 passed）。
**影响范围**：影响 Keepa MCP 入口、Keepa 正式 CLI、远端 MCP 适配层与 MCP 配额默认配置；Keepa 业务执行逻辑、导出逻辑与内部 token 预检查逻辑保持不变。
**回滚方式**：回退 `opscli/mcp/quota.py`、`opscli/mcp/tools/keepa.py`、`opscli/keepa/remote_adapter.py`、`opscli/keepa/cli.py`、`opscli/mcp/configs/mcp-quota.json`、对应四组测试和本条变更记录。

## 2026-06-24 ops-dataset-query Skill - 取消「发现新版本提示强制升级」约束

**变更原因**：用户要求取消 skill 在调用 opscli 时一旦输出新版本提示就强制暂停并先升级的约束。该规则会打断正常取数流程、把升级动作强加给 AI。
**改动点**：`opscli/skills/templates/ops-dataset-query/SKILL.md` 删除「铁律十二：发现新版本提示必须先升级再继续」整节（含处理规则与禁止行为）。其余铁律及 `scripts/updater.py` 的 `update_available` 状态字段未动（仅状态展示，非强制逻辑）。
**验证结果**：`grep` 确认无「铁律十二」交叉引用、无「发现新版本/建议升级/A newer version」强制升级残留。
**影响范围**：AI 执行 opscli 命令时不再因新版本提示强制中断升级，按用户意图继续原操作；不影响数据为空时的 skills upgrade 兜底规则。
**回滚方式**：git 还原 SKILL.md 即可恢复该铁律。
---

## 2026-06-25 opscli/cli.py + mcp/server.py - 移除悬空的 asin_review 引用（修复 0.0.99 导入崩溃）

**变更原因**：0.0.99 安装后所有 opscli 命令启动即报 `ModuleNotFoundError: No module named 'opscli.asin_review'`。根因：提交 7489810 往 cli.py 与 mcp/server.py 加了对 asin_review 模块的 4 处引用，但 `opscli/asin_review/` 顶层包与 `opscli/mcp/tools/asin_review.py` 从未提交（全历史/所有分支/stash 均无），属漏 git add。cli.py 导入失败导致整个 CLI 不可用。
**改动点**：删除 4 处悬空引用——cli.py:12 import、cli.py:44 add_typer(name="asin-review")、mcp/server.py:293 import、mcp/server.py:310 register。其余模块未动。
**验证结果**：`grep -rn asin_review opscli/` 零命中；`python3 -c "import opscli.cli"` 与 `import opscli.mcp.server` 均成功；`python3 -m opscli.cli --version`/`--help` 正常，asin-data 保留、asin-review 消失。
**影响范围**：恢复 opscli 全部命令可用；asin-review 功能本就无实体，移除无功能损失。0.0.99 已发布且损坏，需发新版本（如 0.0.100）覆盖。
**回滚方式**：git 还原 cli.py 与 mcp/server.py 即可（但会恢复崩溃，不建议）。
---

## 2026-06-29 amazon_rufus - 拦截 watch-login 外部广告空白页

**变更原因**：Rufus `watch-login` 打开 Amazon 后，Chrome 会反复出现并关闭短生命周期空白页；CDP 诊断确认其生命周期为 `about:blank -> https://s.amazon-adsystem.com/ -> destroyed`，不是 opscli 自建的 `ops-login` 或 `ops-product` 页签。
**改动点**：`opscli/amazon_rufus/services/browser.py` 在 `watch_login_and_capture_seed_request()` 连接 CDP context 后安装 `https://s.amazon-adsystem.com/**` 请求拦截，并在外部页签导航到该广告域名时立即关闭；`tests/amazon_rufus/test_core.py` 新增回归测试，模拟外部广告页签反复开关并验证 Rufus 请求捕获不受影响。
**验证结果**：RED：`.\\.venv\\Scripts\\python.exe -m pytest tests/amazon_rufus/test_core.py -k "blocks_external_amazon_ad_pages" -q` 初始失败，确认未注册广告域名拦截；GREEN：同命令复跑通过（1 passed）；定向回归 `.\\.venv\\Scripts\\python.exe -m pytest tests/amazon_rufus/test_core.py -k "watch_login or debug_pages or closed or blocks_external" -q` 通过（8 passed）；语法检查 `.\\.venv\\Scripts\\python.exe -m py_compile opscli/amazon_rufus/services/browser.py` 通过；全文件回归 `.\\.venv\\Scripts\\python.exe -m pytest tests/amazon_rufus/test_core.py -q` 通过（91 passed）；真实 CDP 短窗观测中 `adsystem_page_target_count=0`，未复现循环广告空白页。
**影响范围**：仅影响 Amazon Rufus `watch-login` 登录监听阶段的外部广告请求和外部广告页签处理；登录页、商品页、Rufus streaming 请求捕获与后端获取流程不变。
**回滚方式**：回退 `opscli/amazon_rufus/services/browser.py`、`tests/amazon_rufus/test_core.py` 和本条变更记录。
## 2026-06-29 skills(ops-query-wizard / ops-dataset-query) - 移除 catalog 相关描述与子命令

**变更原因**：Agent 取数时总用 `query catalog` 找数据集，但 catalog 只是业务语义索引底座、且被 ops-query-wizard 错标成"做意图匹配"；正确做法是列数据集用 `query metadata`、意图匹配用 `query intent`。需把误导性的 catalog 描述去除。
**改动点**：
- `ops-query-wizard/SKILL.md:197`：数据集匹配从 `query catalog` 改为 `query metadata` 无参全量列表筛选。
- `ops-query-wizard/references/step-guide.md`：Step 2 执行流程删除 `query_catalog() 做意图匹配` 步骤并重排（推荐来源改为从需求摘要推断）；防呆规则两处"意图匹配"措辞改为"推断推荐"。
- `ops-dataset-query/scripts/query.py`：移除 catalog 子命令（docstring 示例、build_command 分支、subparser 定义）；intent/metadata/simple/chart/chart-doc 保留。
- 未改动：ops-dataset-query 文档（本无 catalog 工具描述）、业务词 amazon_catalog_performance 等、dataset_catalog.json 数据文件、updater_mcp.py。
**验证结果**：`python -c "ast.parse(query.py)"` 通过；`query.py catalog` 报 invalid choice（已移除），`query.py -h` 仅列 metadata/intent/simple/chart/chart-doc；`grep catalog` 在 wizard 文档与 query.py 中零命中。
**影响范围**：ops-query-wizard 选数据集流程改为纯 metadata 全量列表+用户选择；ops-dataset-query 脚本不再支持 catalog 透传（intent 仍在）。两个为已上线 Skill，发布升级需评估 VERSION.json 版本号。
**回滚方式**：git 还原上述 3 个文件即可。
---

## 2026-06-29 skills 收尾 - 清理陈旧产物 + 版本号 bump

**变更原因**：移除 catalog 后，scripts/query.c 仍残留旧 catalog 代码；两个已上线 Skill 需 bump 版本以便升级机制下发。
**改动点**：
- 删除 `ops-dataset-query/scripts/query.c` 与 `__pycache__/query.cpython-313.pyc`（均未被 git 跟踪，setup.py 已将 skills/templates 排除编译，零影响）。
- `ops-query-wizard/data/VERSION.json`：v0.1.0 → v0.1.1。
- `ops-dataset-query/data/VERSION.json`：1.1.0 → 1.1.1。
**验证结果**：query.c/.pyc 已不存在；两个 VERSION.json 版本号已更新。
**影响范围**：仅清理本地遗留文件与版本号；功能无变化。
**回滚方式**：git 还原两个 VERSION.json（删除的 .c/.pyc 本就未跟踪，无需回滚）。
---

## 2026-06-30 amazon_rufus - Rufus 自动启动浏览器时关闭 DevTools 自动打开偏好

**变更原因**：用户反馈 Rufus Skill 打开 Amazon 页面时会自动打开控制台；当前启动参数虽未包含 `--auto-open-devtools-for-tabs`，但 opscli 复用固定 Rufus Chrome profile，旧 profile 中可能残留 DevTools 自动打开偏好。
**改动点**：`opscli/amazon_rufus/services/browser.py` 在 `_start_new_chrome()` 启动 Chrome/Edge 前清理 opscli 自建 Rufus profile 的 DevTools 自动打开相关偏好；清理仅修改相关键，不删除 profile、Cookie、localStorage 或 Rufus 状态。`tests/amazon_rufus/test_core.py` 新增回归测试，覆盖偏好关闭、无关字段保留和损坏偏好文件不阻断启动。
**验证结果**：RED：`uv run pytest tests/amazon_rufus/test_core.py -k "devtools or start_new_chrome" -v` 初始失败于 `autoOpenDevToolsForPopups` 仍为 `true`；GREEN：同命令通过（3 passed）；定向回归 `uv run pytest tests/amazon_rufus/test_core.py -k "devtools or start_new_chrome or watch_login" -v` 通过（11 passed）；语法检查 `uv run python -m py_compile opscli/amazon_rufus/services/browser.py` 通过。
**影响范围**：仅影响 opscli 自动启动的 Rufus 调试 Chrome/Edge profile；已运行的外部 CDP Chrome、MCP 默认后端获取、登录态保存、题库与报告流程不变。
**回滚方式**：回退 `opscli/amazon_rufus/services/browser.py`、`tests/amazon_rufus/test_core.py`、`.super-dev/changes/rufus-no-devtools-console/`、`output/rufus-no-devtools-console-*.md` 和本条变更记录。
## 2026-06-30 skills - publish/edit 的 summary 缺失时回退到 SKILL.md description

**变更原因**：`opscli skills publish`（及 `edit --dir`）中 summary 仅回退到 frontmatter 的 `summary` 字段，而多数 SKILL.md 只写了 `description`、无 `summary`，导致客户端不传 `--summary` 时 summary 为空。
**改动点**：
- `opscli/skills/commands/cli.py`：新增辅助函数 `_summary_from_desc`（取 description、去空白、截断到 500 字符 `_SUMMARY_MAX_LEN`）；publish 命令 `resolved_summary` 与 edit `--dir` 模式 `summary` 的回退链追加 `_summary_from_desc(fm.get("description"))`。
- `opscli/skills/templates/ops-skills/references/commands.md`：在 publish 与 edit 章节补充「字段回退规则」说明。
**验证结果**：
- 辅助函数单测（空值/去空白/600→500 截断）通过。
- 端到端三场景通过：未传 summary 回退并截断、显式 summary 优先、desc 回退不变。
- `tests/skills/test_cli.py` 全部通过；`test_manager.py` 的 3 个 install 失败为环境性预存问题（缺 ops-methods-card 模板），与本次改动无关（stash 后仍同样失败已确认）。
**影响范围**：仅 publish/edit 的 summary 字段解析；desc 逻辑与解析器未改。
**回滚方式**：git 还原 `cli.py` 与 `commands.md` 两个文件。
---

## 2026-07-04 amazon - 增加代理反拦截与扩展字段采集

**变更原因**：服务部署在阿里云（数据中心 IP 段），被 Amazon Bot 检测标记为高风险，抓取时频繁遭遇验证码/首页重定向；且原采集字段过少（仅标题/价格/评分/评论数/位置），无法满足更完整的商品信息需求。
**改动点**：
- 新增 `opscli/amazon/config.py`：从 `config.ini [amazon]` 段与 `OPSCLI_AMAZON_*` 环境变量读取代理（proxy_server/username/password）、max_retries、headless；内置 UA 池与视口池。代理是绕过机房 IP 被封的根因修复手段。
- 重写 `opscli/amazon/scraping/scraper.py`（AmazonScraper）：
  - launch 注入可选代理 + 反自动化 args（`--disable-blink-features=AutomationControlled`、`--no-sandbox` 等）。
  - 每次上下文随机 UA + 随机视口；自注入 stealth 脚本（覆盖 navigator.webdriver/languages/plugins/window.chrome/permissions），不再依赖未在 pyproject 声明的 playwright_stealth。
  - `scrape_product_async` 增加命中拦截时的退避重试（默认 3 次，每次换全新指纹上下文）；`_is_retryable` 区分可重试拦截与 404。
  - 新增 `_extract_extended_fields`：单次 JS evaluate 提取品牌/库存/五点/描述/图片/BSR/类目/配送/发货方/卖家/优惠券。
- 扩展 `opscli/amazon/domain/models.py`（AmazonProductSnapshot）：新增 11 个扩展字段，全部带默认值保持向后兼容。
**验证结果**：`pytest tests/amazon/ -q` → 21 passed；导入冒烟测试通过，新字段与 config getter 正常。
**影响范围**：仅 amazon 抓取模块；现有 CLI/manager 接口与测试不变（均 mock scraper）。默认不使用代理，需在 config.ini/环境变量显式配置后生效。
**回滚方式**：git 还原 `opscli/amazon/scraping/scraper.py`、`opscli/amazon/domain/models.py`，删除 `opscli/amazon/config.py`。
---

## 2026-07-07 query/mcp - 临时屏蔽 catalog 与 intent 调用入口

**变更原因**：按用户要求，临时屏蔽 dataset catalog（业务语义索引）与 intent（自然语言意图匹配）两个能力的对外调用入口，使其不可调用（CLI + MCP 双入口）。
**改动点**：
- `opscli/query/commands/cli.py`：注释掉 `@app.command("catalog")` 与 `@app.command("intent")` 装饰器（函数体保留，未注册到 Typer）。
- `opscli/mcp/tools/query.py`：在 `_ALL_TOOLS` 注册列表中注释掉 `query_catalog` 与 `query_intent_match` 两项（函数体保留，未注册到 FastMCP）。
**验证结果**：从源码导入验证——CLI 命令列表为 `['preferences', 'metadata', 'run', 'chart', 'chart-doc', 'build', 'simple']`（catalog/intent 已消失）；MCP `_ALL_TOOLS` 中已无 `query_catalog`/`query_intent_match`。另：验证过程中 `uv run` 自动同步项目环境，`.venv` 已从打包版 v0.0.91 替换为本地源码可编辑安装 v0.0.129，`opscli query --help` 实测两命令已消失，屏蔽在本机立即生效。
**影响范围**：`opscli query catalog`、`opscli query intent` 命令及 MCP 工具 `query_catalog`、`query_intent_match` 在源码构建版本中不可调用；`manager.catalog()`/`intent_match()` 底层方法未删除，其他命令不受影响。
**回滚方式**：取消上述两处文件中带【临时屏蔽】标记的注释即可恢复。
---

## 2026-07-10 skills/ops-feedback - 分级反馈策略随附问题修复（v1.0.16 → v1.0.17）

**变更原因**：深度分析发现 v1.0.16 分级反馈改造存在规则源冲突、虚假脚本引用、零测试、英文注释违反铁律17、死代码等问题；用户确认后逐项修复。
**改动点**：
- `~/.claude/CLAUDE.md`：反馈铁律去重窗口 5 分钟 → 30 分钟，补充 `feedback_group_key` 聚合说明（消除与 FEEDBACK_RULE.md 的冲突）。
- `opscli/skills/templates/ops-feedback/SKILL.md`、`data/FEEDBACK_RULE.md`：移除对不存在的 `evaluate_agent_traces.py` / `evaluate_wizard_traces.py` 的"参考实现"声称，改标注为待建设项并指向 `tests/skills/test_feedback_guard.py`；明示去重为滑动窗口语义（窗口内重复只刷新本地计数，不自动再次远端提交）。
- `references/cli.md`、`references/mcp.md`：去重条目追加滑动窗口说明。
- `scripts/feedback_guard.py`：全部改为中文 docstring 与段落注释（铁律17）；删除无调用方的 `fingerprint()` / `fingerprint_source()` 死代码（其中 `fingerprint()` 存在变量覆盖隐患）；`is_feedback_tool` 去除重复 marker；修复 Pyright 类型标注（list 分支变量名）。决策逻辑与 v1.0.16 完全一致。
- 新增 `tests/skills/test_feedback_guard.py`：26 个用例覆盖事件分类（L0/L1/L2/L3、可疑数据不误报 L3）、L3 滑动窗口去重与窗口过期重提、`feedback_group_key` 跨参数聚合、L2 会话预算（放行/耗尽/按 session 隔离）、敏感字段脱敏、大事件瘦身（≤4096B）、认证轮询抑制、feedback 通道 fail-open、状态损坏兜底、过期清理、record 登记语义。
- `data/VERSION.json`：v1.0.16 → v1.0.17。
- 新增 `docs/analysis/ops-feedback与ops-query-wizard优化改动分析报告.md`：存档两个 Skill 的改动对比分析结论（含 ops-query-wizard Step 2–5 引用悬空的致命问题，建议暂缓合入）。
**验证结果**：`uv run pytest tests/skills/test_feedback_guard.py tests/skills/test_ops_feedback_template.py` → 32 passed；重写后脚本 CLI 冒烟（decide L3 失败事件）输出 `submit_immediate_failure_feedback / submit_remote=true`，与修复前行为一致；`grep evaluate_agent_traces` 全仓库无残留。
**影响范围**：仅 ops-feedback Skill 模板文档与 guard 脚本注释/死代码；决策行为无变化；guard 状态目录 `~/.opscli/` 未迁移（需单独评估）。ops-query-wizard 本次未改动。
**回滚方式**：`git checkout -- opscli/skills/templates/ops-feedback`，删除 `tests/skills/test_feedback_guard.py` 与分析报告；`~/.claude/CLAUDE.md` 将"30 分钟"改回"5 分钟"。
---

## 2026-07-13 skills/ops-dataset-query - 二代规划管线修正优化（死代码清理+结构简化+口径补回）

**变更原因**：深度审查发现新一代 query_plan 规划管线存在约 220 行死代码、上一代方案残留未清理、磁盘缓存层过度设计（含 Windows fcntl 必崩点）、铁律17 全量违规（0 中文注释）、文档交叉引用矛盾及 4 类历史业务口径被删无承接。
**改动点**：
1. 删除上一代孤儿：scripts/route_intent.py、search.py，references/cli-simple-guide.md、mcp-simple-guide.md，data 下 5 个无消费 YAML（intent_taxonomy/dataset_profiles/field_semantic_index/dataset_relationships/routing_eval_cases），tests/test_route_intent.py、test_ops_dataset_query_search.py；图表/Excel 用法抢救为新参考 references/chart-excel-guide.md 并挂载到 SKILL.md。
2. scoped_metadata_index.py 508→107 行：去掉磁盘 JSONL 缓存/fcntl 目录锁/manifest sha256/原子写回滚，改为进程内构建卡片，消除 Windows 崩溃点；数据层统一复用 scoped_dataset_reader（datasets.csv 必需列统一含 remarks）。
3. 删除死代码：capability overlay 全家（typed_schema_linking + agent_query_planner 转发/CLI）、build_index、3 个未文档化脚本 CLI、evidence_contract 的 --input-json/--input-file、intent_rules.json 不可达的 filter_values.amazon（校验器改为 filter_values 键=成员值并集）。
4. model_contract.py（271 行）并入 query_plan.py，模块数 8→6。
5. 行为修正：非亚马逊平台筛选由 block_platform_enum_ambiguous 改为明确的 block_platform_scope_unsupported；接通 snapshot_metric 列（reader 校验 + guidance is_snapshot/latest_snapshot_no_period_aggregation + execution_ref 透传 + schema 增加 is_snapshot 必填）。
6. 文档修复：cli.md 改用模型合同键并修正 --output-mode full 失效引用（internal 为维护者排错通道）；QUERY_SPEC §5 去除 MCP-only 场景引用本地脚本的矛盾（改内联证据合同）；反馈去重窗口 5→30 分钟对齐项目铁律；SKILL.md 统一 result-analysis.md 读取时机（MCP-only/复杂审计）。
7. rules.md 补回口径：近N天=[今天-(N-1),今天] 公式、周/月/跨年边界、缺省近30天、快照指标不跨期累加、verbose_name 禁意译、小组/部门独立与 9部↔九部匹配、上下文范围继承。
8. 铁律17 整改：全部脚本模块/公开函数中文 docstring、复杂逻辑段中文注释；GBK 扫描通过。
**验证结果**：tests/skills/test_dataset_query_planner.py 重写为 3 用例（公式口径/快照口径/不支持平台阻断）全部通过；tests/skills 其余失败均与 HEAD 基线一致（8<12，零新增回归）；query_plan CLI 冒烟（placeholder 刷新合同）与 evidence_contract stdin 冒烟通过；模型合同输出通过 query_plan.schema.json jsonschema 校验；全部脚本 py_compile 通过。
**影响范围**：ops-dataset-query Skill 模板（脚本/文档/数据/schema）与其回归测试；不影响 opscli 核心模块。
**回滚方式**：git checkout HEAD -- opscli/skills/templates/ops-dataset-query tests/skills（注意会同时回滚用户此前未提交的二代重构改动，精确回滚需按文件挑选）。
---

## 2026-07-13 skills/sync - 修复 skills upgrade 因本地版本领先远端而跳过数据写入

**变更原因**：`opscli skills upgrade` 后 `~/.opscli/skills/ops-dataset-query/data/datasets.csv` 等仍为占位表头。根因是 `apply_upgrade_data()` 的版本门槛 `compare_versions(current, remote) <= 0`：本地模板占位版本（1.1.1）与远端数据 manifest 版本（v1.0.3）属于两套版本空间，本地领先时被判为 already_latest，拉取到的数据从未落盘，与代码注释"始终执行更新"的意图不符。
**改动点**：
1. `opscli/skills/sync/updater.py`（类 SkillsUpdater，方法 apply_upgrade_data）：删除 needs_update 版本比较门槛与 updated=False 提前返回，始终覆盖写入远端数据；force 参数保留签名兼容，不再影响写入行为。
2. `tests/skills/test_updater.py`：新增 test_upgrade_local_version_ahead_also_updates（本地 1.1.1 > 远端 v1.0.3 也必须写入）；为两个存量用例补齐 HEAD 已引入但未 mock 的 SELECT_COLUMNS_ENDPOINT 分支（存量红灯修复）。
**验证结果**：tests/skills/test_updater.py 全部通过（19 passed 含新用例）；真实执行 `opscli skills upgrade`，datasets.csv 由 96B 占位变为 8032B 真实数据、dataset_fields.csv 259KB，结果归入 updated 而非 already_latest，VERSION.json 更新为远端 v1.1.2。test_manager.py 的 3 个模板安装失败为工作区模板重构 WIP 存量失败，与本次无关。
**影响范围**：仅 ops-dataset-query 的 skills upgrade 数据写入行为（每次 upgrade 均覆盖刷新数据文件，含 VERSION.json 跟随远端 manifest 版本）；ops-amazon-rufus 升级路径不受影响。
**回滚方式**：`git checkout HEAD -- opscli/skills/sync/updater.py`，并删除 tests/skills/test_updater.py 中新增用例与两处 SELECT_COLUMNS mock。
---

## 2026-07-13 ops-dataset-query v1.2.4 第一批优化（管线激活修复）

- **为什么改**：2026-07-13 QA e2e 矩阵（6数据集×4场景24用例，报告在 ops-agent 仓库 docs/测试报告/ops-dataset-query-v1.2.3*）实锤 v1.2.3 二代规划管线双重失效：①广场发布包 VERSION.json 无 data_state 字段被 query_plan.py 无条件打回 blocked（14/14 尝试全打回、打回文案无恢复命令、0 会话按指引升级）；②QA 提示词 v18 固化旧流程叠加 lazy load_skill 只回 status/path。另发现真实包上的两个后继硬失败：同名数据集（用户仪表盘分享明细 table 52/61）触发 invalid_cards:duplicate_identifier 拒绝全账号规划；渠道组件 query_channel_set 发布类目为 normal 被 block_platform_filter_missing_component 阻断平台枚举。
- **改了哪些文件**：opscli/skills/templates/ops-dataset-query/{SKILL.md, references/cli.md, data/query_plan.schema.json, scripts/query_plan.py, scripts/agent_query_planner.py}；tests/skills/test_dataset_query_planner.py
- **具体做了什么**：①_data_state_ready 兼容发布包形状（无 data_state 时以 dataset_count>0+核心索引文件佐证就绪，metadata_source 标记 skill_local/published_bundle）；②刷新合同增加 recovery_command/recovery_hint_zh 并透传 model_view，build_query_plan 增加 blocked 前一次自动升级兜底（subprocess 90s 超时，--no-auto-upgrade 可关）；③SKILL.md description 内嵌第一命令硬指令（lazy 模式防宿主提示词漂移），版本 1.2.3→1.2.4；④main 错误处理改 stdout JSON {error,retryable,next_action_zh}，错误码前缀映射下一步动作，兜底捕获未预期异常为 internal_error:*；⑤SKILL.md/cli.md 增加「未登录」处置边界（禁止交互式 auth login，等1分钟重试一次后停止并反馈）；⑥agent_query_planner 名称重复不再整体拒绝（仅别名重复硬失败，同名卡片后置标记 name_conflict，显式点名自然走多候选澄清）；⑦_next_action 接受组件 guidance_status=ready（QA 组件类目为 normal 的真实形态）。
- **如何验证**：pytest tests/skills/test_dataset_query_planner.py 10/10 通过（新增 7 用例：发布包形状就绪/占位打回带恢复命令/空包不误判/自动升级重试/错误JSON带指引/未预期异常包装/normal类目组件可枚举）；QA 真实发布包副本上 CLI 实测：发货环比→planned table 2（1237字节合同）、即时销售显式点名→planned table 3（正解 e2e 错查缺陷）、同名数据集→clarify_required、亚马逊SC筛选→query_platform_permission_enum+组件 table 7、占位模板→blocked+recovery_command。tests/skills 整目录既有收集失败与本次无关（stash 基线复现同样失败）。
- **影响范围**：仅 ops-dataset-query 技能模板与其回归测试；不涉服务端。发布 1.2.4 到 QA 广场后 system 分享全员自动同步；提示词 v18→v19 对齐为独立协同项，须在本改动发布后进行。
- **回滚方式**：git checkout 恢复上述 6 个文件即可；广场侧回滚到 1.2.3 版本。

## 2026-07-14 ops-dataset-query v1.3.0 第二三四批优化（合同补全+入口能力+一体化执行器）

- **为什么要改**：延续 v1.2.4 管线激活修复，落地优化分析报告的 P0-1/P0-2/P0-3/P0-4/P0-5 与 P1-3/P1-4/P1-5、2-1/2-2、P2-1/P2-2/P2-5：合同缺日期字段/澄清空洞/枚举三步/排序零兜底/日期心算 是 e2e 实测的五大轮次放大器。
- **改了哪些文件**：模板内 SKILL.md、QUERY_SPEC.md、references/{cli.md,simple-query-guide.md,chart-excel-guide.md}、data/{query_plan.schema.json,intent_rules.json,README-字段使用.md(新)}、scripts/{query_plan.py,dataset_guidance.py,core.py,evidence_contract.py,time_scope.py(新),run_query.py(新)}；tests/skills/test_dataset_query_planner.py
- **具体做了什么**：①execution_ref 补全：date_fields 无条件输出、filter_components（部门/国家等组件引用进 contract 模式）、无点名字段时 recommended 字段（标注需确认）；②澄清弹药：dataset_candidates_zh 候选卡片 + unknown_requested_fields 回显 + 字符二元组近似字段建议；③时间口径本地解析 time_scope.py（近N天/昨天/本周/上周/本月/上月/环比/同比，Asia/Shanghai，默认近30天须披露）进 model_view.time_scope_zh 与 execution_ref.time_scope；④平台枚举一次收敛：--auto-enum 默认开（subprocess 45s 超时失败回落），合同内嵌 platform_enum_command 现成命令；扩充 intent_rules 平台别名表（补「亚马逊SC」等形态）；⑤query_template 预填骨架（实测形态：日期>=/<=两行、dataComparison、公式字段不带聚合）；⑥新增 run_query.py 一体化执行器：执行前硬校验（占位符/漏主周期/公式带聚合/desc形态归一为 direction）→ 执行 → 排序单调性校验+本地重排/放大重查兜底（服务端 orderBy 缺陷过渡方案）→ 全量落盘只回预览+披露+内嵌证据合同（stdout 8KB 限幅）；⑦evidence_contract +--input；query_plan +--query-file/stdin；chart 指南统一 python3；⑧SKILL.md 矛盾修订（每规划阶段一次/正向主线前置/读文档边界收敛/platform_semantic_members 中文化/执行确认分级：无歧义陈述式披露直接执行）；⑨answer_contract 去 *_codes 冗余；QUERY_SPEC 首行标注；discover_data_dir 补 .agents 候选。
- **如何验证**：pytest 22/22（新增 12 用例：日期字段/时间合同/模板/推荐字段/候选卡片/近似建议/auto-enum 收敛/time_scope 三则/run_query 四则）；QA 真实发布包实弹五场景：发货环比合同 2.4KB 一步齐全、模板直填经 run_query 打真实后端取回真数据（美国 353040.70 降序正确）、**服务端 orderBy 缺陷现场复现两次且均被执行器单调性校验逮住并 requery_limit_15_then_local_sort 兜底披露**、同名数据集澄清带双候选卡片、平台筛选实弹 auto-enum 一次调用正确判定 block_platform_scope_not_authorized（enum_source=auto_enum_service）。
- **影响范围**：仅技能模板与回归测试，不涉服务端；SKILL.md 版本 1.2.4→1.3.0。已知小瑕疵：QA 同名数据集 description 也相同导致候选卡片文案无法区分（数据侧问题，卡片机制本身正常）。
- **回滚方式**：git checkout 恢复模板目录与测试文件；广场回滚旧版本。

## 2026-07-14 ops-dataset-query v1.3.1 沙箱自愈修复（v19 验收发现的两个新形态）

- **为什么改**：提示词 v19 上线后验收 e2e 发现：①用户从模板目录发布的 1.3.0 广场包带的是占位数据（data_state=placeholder、CSV 仅表头），上一版真实数据是 BI 数据发布管线灌入的，被覆盖；②沙箱内 `opscli skills upgrade` 写入 opscli 自己的发现目录（本机实测 ~/.claude/skills），而挂载的 .agents 是只读快照——升级成功但主目录依旧占位，恢复指引救不回；③upgrade 写入的 VERSION.json 是第三种形状（仅 name+version，无 data_state 无 dataset_count）。v19 提示词行为本身完全符合设计（按合同→按恢复→按排错预算→提交反馈）。
- **具体做了什么**：①`_data_state_ready` 以「核心索引 CSV 含数据行」为统一就绪证据（新增 upgraded_local 形态；空包=CSV 仅表头判不就绪）；②新增 `_fallback_ready_data_dir`：升级后主目录仍未就绪时接管 cwd/.claude/skills、~/.claude/skills、$OPSCLI_SKILLS_DIR 中已就绪的数据目录（metadata_source 加 +fallback_dir 后缀，自愈动作统一受 auto_upgrade 开关约束）；③`effective_data_dir` 透传投影层，字段标签跟随实际生效目录；④升级超时 90s→60s（防组合入口撑爆单条 exec 超时，v19 验收实测首调超时）。
- **验证**：pytest 23/23；本机模拟沙箱闭环（占位挂载包+真实 opscli upgrade）：blocked→自动升级→接管 ~/.claude/skills→`planned, metadata_source=upgraded_local+fallback_dir, table_id=2`。
- **发布配套**：已组装带真实数据的发布包（模板 1.3.1 代码 + 1.2.3 包的 43 数据集真实数据）供重新发布，消除新沙箱的一次自愈开销；发布后建议与 BI 数据发布管线确认其重新发布数据时是否保留最新 scripts。
- **回滚方式**：git checkout 恢复 query_plan.py 与测试文件。

## 2026-07-13 后端 data-metrics - 同步队列仅返回当前用户自己发布的技能

**变更原因**：`opscli skills install --sync-market` 原逻辑会把用户安装过的所有广场技能（含他人发布的）都纳入同步队列。新需求要求：非当前用户创建发布的技能默认不进入同步安装，他人发布的技能只能通过 `opscli skills install username@skill_name` 显式安装。
**改动点**：后端 auto-scheduler 项目 `vendor/aukey/data-metrics`（非 opscli 仓库）：
1. `src/Services/SkillMarketplaceService.php` — `getSyncQueue()` 查询新增 `->where('sm.user_id', $userId)` 过滤（仅返回当前用户发布的技能），并更新方法 docblock；
2. `src/Http/Controllers/SkillSyncController.php` — `queue()` docstring 同步更新说明。
opscli 客户端零改动（`_install_sync_market` 只消费队列返回列表），旧版客户端自动获得新行为。
**验证结果**：`php -l`（PHP 8.4，/opt/homebrew/opt/php@8.4）两文件均无语法错误。本机默认 PHP 7.4 对该包预存的 PHP 8 语法（nullsafe、构造器属性提升）报 parse error，与本次改动无关。待接口级验证：测试账号调 `GET /v1/skills/sync/queue` 确认不含他人发布的技能，`opscli skills install --sync-market --dry-run` 同步计划只剩自己发布的。
**影响范围**：仅 `GET /v1/skills/sync/queue` 返回内容（--sync-market 同步范围收窄）；显式远程安装、排除名单、安装统计回调等链路不受影响。过滤后队列内全部为 creator，`is_downloadable` 恒为 true、`download_url` 恒非空（字段保留，兼容旧客户端）。
**回滚方式**：删除 `getSyncQueue()` 中的 `->where('sm.user_id', $userId)` 一行及其注释，还原两处 docblock。
---

## 2026-07-14 ops-dataset-query v1.3.2 术语更名与超时处置（用户反馈两项）

- **为什么改**：①「合同」用语在 agent 回复中易被误解为法律合同，按用户要求统一更名为「规划器」；②矩阵复跑实测规划器首次调用常撞默认 60s 执行超时（内部含自动升级 ≤60s + 自动枚举 ≤45s），模型需自行摸索「拉长等待重试」，浪费轮次。
- **具体做了什么**：①全模板中文用语「合同/组合入口」→「规划器」（产物语境用「规划结果」），保护「证据合同」独立概念不受影响，英文 JSON 键（contract/answer_contract 等）不变；②SKILL.md/cli.md/description 增加执行超时预算指引：规划器首次运行设 ≥120s 超时、run_query 设 ≥180s，超时=原样重试一次并加大超时（规划器幂等二次秒回），禁止因超时改走旁路探查；③SKILL.md 版本 1.3.1→1.3.2。
- **验证**：pytest 23/23；QA 真实数据包抽验 planned/table 2/time_scope 对比期正常。
- **影响范围**：仅技能模板文案与指引；无逻辑变更（除 description）。需重新发布到 QA 广场并同步提示词 v20（更名+超时指引）。
- **回滚方式**：git revert 本次 commit。

## 2026-07-14 ops-dataset-query v1.3.3 规划器 30 秒窗口适配（超时结构性根治）

- **为什么改**：四轮 e2e 实测确认平台单条命令有效等待硬顶约 30 秒（SDK PTY 钳制 PTY_YIELD_TIME_MS_MAX=30000，e2b 后端应用；模型自设 ≥120s 无效），而规划器「同步升级 60s+同步枚举 45s」预算与之结构性错配——占位数据/刷新器失败场景下首调必然超时，且曾实测升级进程被窗口切断致 VERSION.json 半写入（NUL 污染）。
- **具体做了什么**：①自动升级改「前台 10s 宽限 + 超时转后台续跑」：Popen(start_new_session) 启动，宽限内完成即继续规划；未完成不杀进程、写 pid 标记立即返回 `status=blocked, recovery_state=refresh_in_progress`，恢复命令为 `sleep 25 && 原样重跑`（等待+重跑合并一条命令贴 30s 窗口）；下次调用凭标记与就绪检查接管（fallback 目录前置检查，后台产物就绪即秒级接管）；进程消亡仍未就绪判 refresh_failed 给手动指引；②自动枚举预算 45s→20s，且与升级不在同一次调用内叠加（升级发生则本次跳过 auto-enum、输出内嵌枚举命令走手动路径）——任意单次调用最坏 ~22s；③_refresh_contract 增加 recovery_state（in_progress/failed 两态差异化指引），model_view 透传，schema 同步；④SKILL.md/cli.md/description 撤换已证伪的「设 ≥120s」指引为 30 秒窗口叙事；版本 1.3.2→1.3.3。
- **验证**：pytest 24/24（升级三态/宽限完成继续规划/转后台返回等待合同/fallback 前置不再发起升级）；本机活体闭环：占位包首调 10.2s 确定性返回 refresh_in_progress（慢速假 opscli 强制 18s 升级），sleep 后重跑 0.11s 接管 planned；就绪数据常态首调 0.14s。
- **影响范围**：仅技能模板；行为向后兼容（数据就绪路径不变）。需发布 1.3.3 到 QA 广场并同步提示词 v21（撤换 ≥120s 超时段）。
- **回滚方式**：git revert 本 commit；广场回滚 1.3.2。

## 2026-07-14 ops-dataset-query v1.3.4 宽限微调（收敛默认命令窗超时临界）+ 更名语义修正

- **为什么改**：v1.3.3 验收轮 DB 取证（48 次规划器调用/2 次超时）确认——超时全部发生在「模型未显式设 yield_time_ms、沿用 SDK 默认 10000ms」的命令上，而升级前台宽限恰好也是 10s，卡在临界点被外层命令窗切断；模型显式设 20/25/30s 的 7 次调用全部未超时。另修 v1.3.2 术语更名时几处过头走样（「拿规划器/确认口径规划器/权限规划器检查」应为「拿规划结果/权限合同检查」）。
- **具体做了什么**：①_UPGRADE_GRACE_SECONDS 10s→8s，让 SDK 默认 10s 命令窗留出 ≥2s 安全边际、默认窗口下也能拿到 in_progress 返回而非被切成超时；②SKILL.md 修正 3 处更名语义走样 + 宽限文案 10→8s；版本 1.3.3→1.3.4。
- **验证**：pytest 24/24；根因数据：验收轮 48 调用中显式设 ≥20s 窗的 7 次 0 超时、默认 10s 窗的 41 次 2 超时。
- **不改**：未在提示词强制模型手设 yield_time_ms（实测 19/19 次调用均不显式设，加指令收效存疑），改用工程解（压宽限让默认窗自然兜住）。
- **影响范围**：仅技能模板；需发布 1.3.4 到 QA 广场。
- **回滚方式**：git revert 本 commit。

## 2026-07-14 ops-dataset-query v1.3.5 自动枚举短超时（补齐命令窗盲区）

- **为什么改**：v1.3.4 验收轮 DB 取证（33 次规划器调用 1 次超时=3.0%，较 v1.3.3 的 4.2% 下降但未归零），定位唯一残留超时=即时销售 S4「平台无授权」场景：该场景数据已就绪（不走升级宽限），但规划器要做**自动枚举**（调 opscli 拿平台值），枚举网络调用（上限 20s）超过模型给命令设的默认 10s 窗口被切断。v1.3.4 的 8s 宽限只覆盖升级路径，覆盖不到「已就绪+需枚举」这条路径——是遗留盲区。
- **具体做了什么**：`_auto_enum_platform_values` 超时上限 20s→7s，贴合默认 10s 命令窗（与 8s 升级宽限一致的设计思路）；枚举短超时内未返回时回落到内嵌手动枚举命令（platform_enum_command，已有兜底路径），绝不阻塞命令窗口。附带修 build_model_query_plan docstring 更名走样（内部规划器→内部合同）。
- **验证**：pytest 24/24（auto_enum mock 用例不受超时值影响）；DB 取证的唯一超时命令实测=默认 10000ms 命令墙钟 10.03s（枚举场景）。
- **影响范围**：仅技能模板；平台枚举待收敛场景下超时改回落手动命令而非被切（原本被切后模型也会重跑，本改动让首调即返回可用合同）。需发布 1.3.5 到 QA 广场。
- **回滚方式**：git revert 本 commit。

## 2026-07-15 docs - 新增数据集默认条件（filter_config）接入需求说明

- **为什么改**：服务端 `polaris_ops_metrics_qa.dm_table_columns.field_config` 新增字段级默认条件配置 `filter_config`，需打通「后台配置 → query-metadata 下发 filter_configs → 查询/导出强制应用 → ops-dataset-query 规划器感知与披露」全链路，先整理需求文案供评审。
- **具体做了什么**：新增 `docs/design/数据集默认条件filter_config接入需求.md`，含 filter_config 结构与枚举说明（type/operator/filter_type/filter_agg/日期预设，取证自 datasets.blade.php:4327-4402）、五个需求项（R1 query-metadata 返回 filter_configs、R2 查询导出强制应用、R3 Skill CSV 分发链路同步、R4 opscli query 透传、R5 规划器/执行器/rules.md 优化）、10 条验收标准、7 条待确认问题、关键代码位置附录。
- **验证**：纯文档，无代码改动；关键代码路径与行号由两个探索 Agent 从 opscli 与 auto-scheduler vendor 包实际取证。
- **影响范围**：仅新增文档，无功能影响。备注：本会话 memory-lancedb-pro-sse MCP 工具不可用（ToolSearch 两次检索未命中 memory_*），故按兜底规范记录于此，恢复后需补写 MCP 记忆。
- **回滚方式**：删除该文档文件。

## 2026-07-15 docs - filter_config 需求文档补充导出接口下发范围（用户评审反馈）

- **为什么改**：用户评审指出下发范围不只 queryMetadata，DatasetSkillApiController 的导出方法（export 等）也需支持 filter_config。
- **具体做了什么**：`docs/design/数据集默认条件filter_config接入需求.md` R3 改写为「DatasetSkillApiController 导出接口同步携带 filter_config」，实际读取控制器与 DatasetSkillService 取证：字段 CSV（export→createFieldExportResponseForUser:248-290）行尾新增 filter_config 列（字段级 JSON 原样下发，主要载体）；数据集 CSV（exportDatasets→createDatasetExportResponseForUser:292-330）新增 filter_config_count/filter_config_names 摘要列（复用 select_column_count 既有模式）；exportSelectColumns 结构不变；manifest 计数可选。同步更新范围总览图、R4 本地回退来源、R5 scoped_dataset_reader 解析新列、验收标准（10→12 条，含 CSV 比对与旧版兼容）、待确认问题 6、附录代码位置（补 4 个导出接口行号）。
- **验证**：纯文档；CSV 现有列头逐一取证自 DatasetSkillService.php:264-278、308-318、360-365。
- **影响范围**：仅文档。
- **回滚方式**：git 恢复该文档上一版本。

## 2026-07-15 docs - filter_config 需求文档定稿（7 条待确认问题评审定案回填）

- **为什么改**：用户对 7 条待确认问题全部给出结论，需回填正文并定稿。
- **具体做了什么**：`docs/design/数据集默认条件filter_config接入需求.md`：①冲突处理=静默 AND 合并（与前台一致）+同值/子集合并去重，更新 R2 合并规则表与 R5 run_query precheck（不拦截但必须披露双条件同时生效）；②度量字段 having（filter_agg!=none）纳入本期，更新本期范围、R1 汇总范围（条目新增 field_type 标识）、R2 新增聚合后过滤规则；③多枚举值确认翻译为 in；④日期预设确认服务端执行时解析；⑤manifest 计数不做，数据集 CSV 摘要列纳入；⑥导出侧本期仅覆盖图表导出链路；⑦「六、待确认问题」改为「六、评审结论（已确认）」，验收标准 12→15 条（新增 AND 合并去重、metric having、多值 in 三项），文档状态改为已评审定稿。
- **验证**：纯文档；grep 确认正文无残留"待确认"引用。
- **影响范围**：仅文档。
- **回滚方式**：git 恢复该文档上一版本。

## 2026-07-15 docs - filter_config 需求文档修正「导出」语义（用户澄清）

- **为什么改**：用户澄清需求中的「导出」指数据集元数据 CSV 文件导出（export/exportDatasets 等接口，即 R3），并非把默认条件应用到图表导出等查询结果导出，此前 R2 纳入 ChartExportService 属于误读。
- **具体做了什么**：`docs/design/数据集默认条件filter_config接入需求.md`：①需求目标处新增术语说明框（「导出」=元数据 CSV 导出）；②R2 标题改为「查询强制应用默认条件」，入口覆盖表移除图表导出行，改为范围外注记；③本期范围、背景问题清单、required 语义、范围总览图同步去掉查询结果导出表述；④删除原验收标准第 5 条（导出与查询口径一致），15 条重编号为 14 条；⑤评审结论 7 改写为「导出」含义澄清条目；⑥影响范围第 2 条去掉「导出结果」。
- **验证**：grep 确认全文仅评审结论 7 与本期范围中以「范围外」口径提及图表导出，无残留将其作为改动面的表述。
- **影响范围**：仅文档。
- **回滚方式**：git 恢复该文档上一版本。

## 2026-07-15 docs - filter_config 需求任务拆解（两份实施计划）

- **为什么改**：需求文档已评审定稿，用户要求基于 superpowers:writing-plans 进行开发任务拆解。
- **具体做了什么**：新增两份可独立交付的实施计划（按子系统拆分）：①`docs/plans/数据集默认条件filter_config实施计划-服务端.md`——8 个任务（FilterConfig 提取助手、日期预设解析器、buildExportPayloadForUser 统一挂载+query-metadata 下发、CSV 导出列、SimpleQueryBuilder 简化入口注入、度量 having 探查实现、CliQueryService 完整入口兜底、QA 验收回归），TDD 步骤含完整 PHP 代码与 PHPUnit 用例；②`docs/plans/数据集默认条件filter_config实施计划-opscli与Skill侧.md`——7 个任务（QueryMetadataResult 透传、scoped_dataset_reader 可选列解析、dataset_guidance 聚合、query_plan 投影+中文披露、run_query 注入、Skill 文档+1.4.0、端到端验收），全部 fixture 驱动可与服务端并行。计划代码基于两个探索 Agent 提取的函数原文（DatasetSkillService/SimpleQueryBuilder/CliQueryService/query 模块/skill 脚本逐字取证）。自审修正：PHP 闭包语法、匿名类返回类型、操作符映射缺口（notEquals/gt 等非 equals 操作符注入）、验收编号错位、DB 过滤条件与 loadColumns/loadMetrics 对齐。
- **验证**：纯文档；Self-Review 三项检查（需求覆盖/占位符扫描/类型一致性）完成。
- **影响范围**：仅新增文档。
- **回滚方式**：删除两份计划文件。

## 2026-07-15 skills/query - filter_config opscli 与 Skill 侧实施完成（收尾归档）

- **为什么改**：按《数据集默认条件filter_config实施计划-opscli与Skill侧》以 subagent-driven 方式执行完 Task 1-6 及仓内回归，各任务已有独立变更记录，此条为收尾汇总。
- **具体做了什么**：10 个提交（aaf8c2e..016a875）：QueryMetadataResult 透传 filter_configs；scoped_dataset_reader 可选列解析；dataset_guidance 聚合 default_filters（六键压缩契约）；query_plan 三处投影+query_template 预填；run_query --default-filters 注入去重披露；Skill 文档契约+版本 1.4.0；每任务均经独立审查+修复轮，终审（全分支）Ready to merge。
- **验证**：分目录全量回归 1133 passed，35 failed 全部为基线既有（改动面 diff 证明不相交）；本计划相关测试 tests/query 71/71、planner 26/26、guidance 3/3、reader 5/5、run_query 5/5。
- **影响范围**：opscli query 元数据透传、ops-dataset-query Skill 1.4.0（未发布）。端到端验收待服务端 R1-R3 上线 QA。
- **回滚方式**：git revert aaf8c2e..016a875 区间提交。备注：memory MCP 本会话不可用，恢复后按本文件补录。

## 2026-07-15 服务端 - filter_config 服务端计划实施完成（收尾归档，跨仓库）

- **为什么改**：按《数据集默认条件filter_config实施计划-服务端》以 subagent-driven 方式执行完 Task 1-7 及全分支终审（Task 8 QA 验收待后台配置与 JWT）。
- **具体做了什么**：data-metrics 包（release 分支）16 个提交 f8f9613..4ac10db：FilterConfig/FilterDatePreset 纯函数类；buildExportPayloadForUser 统一挂载 + query-metadata filter_configs 下发（组件引用排除语义）；两 CSV 行尾新列；SimpleQueryBuilder 三数据源加载 + 六语义合并 + having 通道（原始 SQL 拼接面已加转义/白名单/字段校验）+ appendDefaultConditions 完整入口兜底（含 having/translate/innerWhere）；CliQueryService 接线。终审抓获并修复两处跨通道真缺陷：去重 operator-blind 绕过 required（同源波及 opscli run_query，已在 opscli 仓库 aab90fd 同步修复）、完整入口跳过 translate/support_like。
- **验证**：包内 43 tests 全过（+3 个既有 oauth_apps Feature errors 与本分支无关）；opscli 侧 208 回归无新增失败。
- **影响范围**：QA 上线后所有已配置 required 默认条件的数据集查询口径收敛（需求预期）；【技术债上报】既有图表路径 QueryBuilder::buildHavingConditionString(约4432行) 存在字符串值未转义的同类问题（先例缺陷，本计划未动）。
- **回滚方式**：data-metrics 仓库 git revert f8f9613..4ac10db 区间；opscli 仓库 revert aab90fd。

## 2026-07-15 服务端+opscli - filter_config QA 验收完成（跨仓库收尾）

- **为什么改**：真实 QA 环境（http://ops.cm，VC报告[Manufacturing] 数据集带默认条件）验收，抓到日期预设未解析真缺陷 + 客户端预注入字面量与服务端解析冲突的跨端架构问题。
- **具体做了什么**：①服务端 c11150d：toSimpleFilters 补 enum_value 单元素日期解析（后台日期字段预设名存 enum_value 非 value）；②opscli 40538b0：run_query 改披露-only 不再 mutate payload；③opscli bba32cd：query_plan 移除 query_template 默认条件预填，确立"客户端只披露、服务端权威注入"架构；④需求文档 2.2 节修正 value/enum_value 存储约定；⑤新增 docs/plans/数据集默认条件filter_config验收记录.md。
- **验证**：服务端 24 单测 + 真实 API/tinker 逐条验收（注入/解析/去重/冲突/CSV/回归全 PASS，VC 0 行=数据集空非缺陷）；opscli 32 相关测试全绿 review Approved；6 未配置数据集回归 where 无注入、端到端各返回 3 行。
- **影响范围**：服务端 f8f9613..c11150d、opscli a811d7b..bba32cd，均本地未 push。VC 数据集待补数复验；opscli 端到端待服务端发 QA 后 skills upgrade。

---

## 2026-07-15 skills/run_query - _apply_default_filters 披露文案改为覆盖语义

**变更原因**：服务端 filter_config 默认条件改为覆盖语义（用户对某字段传了任意条件→服务端用用户的、不注入默认；用户没传→服务端注入默认）。opscli 披露文案仍沿用旧"AND 冲突同时生效结果可能为空"语义，与服务端实际行为不符，需对齐。
**改动点**：
1. `opscli/skills/templates/ops-dataset-query/scripts/run_query.py`：`_apply_default_filters` 函数中，用户已传同字段条件时，原"冲突 AND 合并""已去重"等旧文案统一改为"你已为 {label} 指定条件，将覆盖数据集默认值（默认 {值}）"；用户未传时保持"服务端将自动应用数据集默认条件"不变；删除旧的 `covered`/`equality_ops` 冗余分支，整体简化为两路（有无用户条件）。更新 docstring 说明覆盖语义及旧 AND 语义废弃。
2. `tests/skills/test_run_query_default_filters.py`：删除 `test_apply_dedupes_same_or_subset_value`（旧去重语义）、`test_apply_keeps_both_on_conflict`、`test_apply_not_deduped_on_operator_mismatch`（旧 AND 冲突语义），新增 `test_apply_user_condition_overrides_default`（覆盖语义三场景：同值/异值/异操作符，均断言 note 含"覆盖数据集默认值"且不含"同时生效"）。
**验证结果**：`pytest tests/skills/test_run_query_default_filters.py -v` 全部 4 tests PASSED；回归 `pytest tests/skills/ tests/query/ --ignore=tests/skills/test_packaging.py -v` 无新增失败，预存失败均为模板漂移与本次修改无关。
**影响范围**：仅 `_apply_default_filters` 披露文案（不改 payload，披露-only 语义不变）；用户侧体验：覆盖场景不再看到"结果可能为空"的误导提示。
**回滚方式**：git revert 本次提交，或手动将 `_apply_default_filters` 中覆盖分支改回含 `covered`/`equality_ops` 的旧版本，并恢复测试文件。
- **回滚方式**：服务端 revert c11150d；opscli revert 40538b0/bba32cd。

## 2026-07-16 skills/ops-dataset-query v1.3.6 - duplicate_dataset_field 硬失败根治（同名字段双注册兼容性合并）

**变更原因**：QA 实跑 SSE 日志（2222.txt）证实「即时综合数据集」（table_id=1）所有 query_plan 调用必现 `duplicate_dataset_field` 硬失败（retryable=false），单会话 8 次报错、模型陷入换措辞盲试与升级自救循环（升级也无法自愈，因为重复来自 BI 发布包数据源头）。根因取证：BI 发布包 v1.1.2 的 dataset_fields.csv 里 table_id=1 有 44 个 field_name 各注册两行——同一物理字段挂两个 global_alias。形态一（11 组）：仅 verbose_name/global_alias 不同的纯标签差异；形态二（33 组）：一行公式注册（has_formula_config=1 带表达式）+ 一行裸指标注册。`dataset_guidance._validated_dataset_fields` 对 field_name 唯一性硬校验，一票否决整个数据集。
**改动点**：
1. `scripts/scoped_dataset_reader.py`：`load_dataset_fields` 末尾新增 `_merge_duplicate_field_rows` 兼容性合并（统一数据层收口，所有消费方受益）。形态一：执行语义签名（field_type/表达式/快照/公式标记/filter_config）一致即合并，主行优先取「含中文且≠技术名」的展示名，其余展示名收进 `alt_verbose_names`（additive 键）；形态二：公式列以外语义一致且恰为公式+裸指标分裂时，优先采纳公式注册（公式表达式是服务端权威聚合口径，均值/比率字段按 SUM 裸聚合会产出错误业务数字）；其余冲突（如 dimension vs metric）不合并，保留下游硬失败。
2. `scripts/dataset_guidance.py`：`_field_score` 对主名+alt_verbose_names 逐一打分取最大值；`_resolve_requested_fields` 点名精确匹配扩展到 alt 名（旧标签「交易额(自发货)」仍可命中 price_ds；同一旧标签挂多字段时正确进入澄清）。
3. `scripts/query_plan.py`：ERROR_NEXT_ACTIONS 新增 `duplicate_dataset_field` 专属指引（升级/重跑均无法自愈，如实说明+提交反馈+停止重试），替代原默认「重跑→升级→反馈」误导链。
4. 版本 bump 1.3.5→1.3.6（SKILL.md + data/VERSION.json）。
**验证结果**：新增 `tests/skills/test_scoped_reader_duplicate_fields.py` 6 用例（两形态合并/语义冲突保留硬失败/幂等去重/alt 打分点名/多义澄清）全 PASS；相关既有测试 43/43 PASS（tests/skills 整目录收集失败为既有问题）。本机用真实 v1.1.2 发布包数据复现验证：修复前必现报错的「即时综合数据集近7天按渠道的销售额Top5」修复后 status=planned；公式字段 avg_price_cny 合并后 has_formula_config=1（公式口径胜出）。QA e2e：v1.3.6 已发布 QA 广场（skill 599490，version id=1442），矩阵验收 duplicate_dataset_field 零命中（详见 ops-agent 仓库测试报告）。
**影响范围**：ops-dataset-query 字段元数据读取层全消费方（dataset_guidance/scoped_metadata_index/query_plan）；即时综合数据集从整库不可查恢复为可查；其余 42 个无重复数据集行为不变（签名唯一时合并是恒等操作）。
**回滚方式**：git revert 本次提交；或广场回退到 1.3.5 版本包。备注：memory MCP 本会话不可用，恢复后按本文件补录。

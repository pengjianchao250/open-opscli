# 西柚 MCP 注册与遗留信息排查

排查日期：2026-10-13。

> 本文记录统一入口改造前的排查快照。同日后续改造已在源码中移除四个兼容 MCP 工具，当前目标为目录与通用查询两个入口；详见 [迁移说明](../guide/西柚MCP统一入口迁移说明.md)。远端服务仍需发布后生效。

排查范围：当前仓库代码、MCP 注册与描述、本会话可见工具、本机上游配置、相关 Skill 与文档。未修改线上服务、后台工具目录、用户配置或已安装 Skill；本轮未调用收费查询。

## 结论

当前代码和本会话均未发现旧西柚网页/爬虫入口或旧供应商 MCP 传输。保留旧名称的四个兼容工具全部转发到西柚 OpenAPI v2。仍存在文档、示例配置和工具元数据上的残留或歧义，值得清理，但尚无证据证明它们导致用户截图中的故障。

当前调用关系为：Agent → opscli MCP 工具 → XydcOpenApiProvider → 西柚 OpenAPI v2。MCP 是对 Agent 的接口，OpenAPI 是服务端访问供应商的接口，两者同时存在符合当前实现。

## 当前注册与调用路径

`opscli/mcp/server.py` 注册 `opscli/mcp/tools/xydc.py`，后者注册以下六项：

| MCP 工具 | 当前作用/对应操作 |
| --- | --- |
| ext_xydc_openapi_operations | 本地操作目录，无供应商请求 |
| ext_xydc_openapi_call | 21 个公共 OpenAPI 操作的统一入口 |
| ext_xydc_get_asin_info | 兼容参数转为 asin_info |
| ext_xydc_get_asin_traffic | 兼容参数转为 asin_traffic |
| ext_xydc_get_keyword_info | 兼容参数转为 search_terms_info |
| ext_xydc_get_keyword_asin_analysis | 兼容参数转为 search_terms_analysis_period |

依据：`opscli/mcp/tools/xydc.py:62、94、142`；`opscli/xiyou/providers/xydc_openapi.py:26、128、380`。

六项均归属 `external_xydc`，目录和查询描述明确使用 OpenAPI；五项收费入口明确标注 Credit。保留名称及参数转换不代表仍使用旧传输。供应商请求使用 `X-Auth-Version: 2.0` 和服务端 API Key。

旧 `xiyou_run`、`xiyou_scenarios`、`xiyou_job_status`、`xiyou_export` 不在当前 MCP 列表；CLI 不再注册 `xiyou`，包不再导出 `XydcMcpProvider`。

本地实际注册目录与本会话工具清单均只发现上述六项。本机 `load_upstream_config()` 只返回 PND，没有西柚上游。Codex 用户配置中的 `opscli` 远程连接启用，`local_opscli` 回环连接禁用，未发现独立旧西柚 MCP 配置。这些结果不能代表反馈用户的机器或其连接实例。

## 会干扰当前理解的信息

| 优先级 | 位置 | 发现与影响 | 建议 |
| --- | --- | --- | --- |
| 高 | docs/spec/SDK调用规范.md:213、290 | 仍写西柚自有 Token、XiyouCredential，以及旧账号获取描述。该类已移除，可能诱导调用不存在的 SDK 或索要旧凭证 | 改为 xydc_openapi 与服务端 API Key 凭据池，核对西柚是否仍应出现在间接 OPS 授权分组 |
| 高 | opscli/skills/templates/ops-app-build-spec/assets/backend/docs/开发指南/OPSCLI_SDK调用规范.md:213、290 | 包含相同旧规范，会随应用构建 Skill 复制到新项目；同目录 SDK 使用文档已写新 Provider，两份文档相互冲突 | 同步修正规范原文与 Skill 内副本 |
| 中 | opscli/mcp/tools/xydc.py:150 | 六个工具共用 idempotentHint=True，但收费查询可能重复消费 Credit，且没有额外幂等保障。该提示可能影响宿主的重复调用决策；未证明实际发生自动重放 | 目录保留幂等提示，收费查询单独评估并修正提示；同步现有注解测试 |
| 中 | docs/analysis/跨境电商数据能力地图/西柚找词OpenAPI数据能力调研.md:5、276；电商运营数据需求与平台来源地图.md:5、77 | 历史报告仍用“当前实现”描述网页 Provider、已删除文件及入口关闭。仓库搜索命中后容易误作现行方案 | 在开头标明历史快照，并指向当前 OpenAPI 实现 |
| 中，待核实 | opscli/mcp/tool_catalog.py:8 | 后台工具清单同步只增不删，已有 label/is_active 不覆盖。历史工具可能仍在管理目录中，或兼容工具标签仍写“试用” | 核对后台目录并按部署范围清理历史条目和标签；本轮未读取后台记录，不能认定实际仍存在 |

后台目录残留不会自行把旧工具注册回 MCP：`opscli/mcp/permissions.py` 先取得实际工具列表，再按允许名称过滤，权限名单只能隐藏或允许已经注册的工具。

## 有残留但不构成当前旧路由的信息

- `configs/mcp-quota.json:10` 保留 `xiyou_run`，但 `enabled=false`。它是额度示例配置，不能注册工具；可清理以降低检索噪声。
- `opscli/api_credentials/models.py:9` 保留 `xydc_mcp` 供历史账号查询和清理；CLI 已禁止新增旧 Provider，当前查询只领取 `xydc_openapi`。历史数据兼容值不等于运行期 Provider。
- `opscli/mcp/quota.py` 保留 `service=xiyou` 作为计费分组，注释已说明旧网页工具废弃。当前 OpenAPI 查询仍使用该分组，不能仅为消除名称而直接删除。
- `docs/design/西柚MCP与OpenAPI多通道兼容设计.md:3` 已明确标注历史文档，正文仍包含三通道方案，仅供迁移背景参考。
- `tests/mcp/test_xydc_tools.py` 的“试用工具”标题与测试名仍是旧措辞，但不进入运行时工具描述；可在维护相关测试时更新。
- 仓库 `.agents/skills/ops-auth/references/mcp.md` 仍描述旧无状态认证，而随包模板已为一步登录。这是本机已安装 Skill 与模板不一致，不能据此推断反馈用户也加载了同版本。

通用上游网关按部署配置注册审批工具，未按西柚名称或旧域名单独阻止旧上游。当前本机与本会话没有发现该配置；如反馈用户连接其他实例，仍需核对该实例的 `OPSCLI_MCP_UPSTREAM_CONFIG_PATH` 与启动后实际 tools/list。

## 验证

执行已有注册、旧入口移除、目录同步测试：

```text
.venv/Scripts/python.exe -X utf8 -m pytest tests/xiyou/test_deprecation.py tests/mcp/test_xydc_tools.py tests/mcp/test_tool_catalog.py -q
14 passed

.venv/Scripts/python.exe -X utf8 -m pytest tests/mcp/test_tools.py::test_mcp_exposes_openapi_and_hides_deprecated_xiyou_tools tests/xiyou/test_xydc_openapi_provider.py::test_legacy_asin_info_uses_openapi_v2_and_writes_audit_log -q
2 passed
```

后两项分别验证当前 MCP 隐藏旧网页工具，以及兼容商品入口实际构造 OpenAPI v2 URL、Header 和请求体。Provider 验证使用模拟客户端，未请求供应商。16 项测试通过只说明现有行为符合当前测试，其中注解测试仍要求 idempotentHint=True，不代表该提示的计费语义正确。

本轮仅新增排查报告。此前 ops-xiyou v1.3.4 的修改仍在工作区，未发布。若要解释用户历史故障，仍需其原始调用记录、MCP 实例与加载的 Skill 版本。

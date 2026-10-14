# 西柚 MCP 统一入口迁移说明

2026-10-13 的源码改造将西柚 MCP 收敛为两个工具；2026-10-14 补充与 Keepa 相同的本地 CLI → 远端 MCP 代理，ops-xiyou Skill 升至 v2.0.1。源码改动需随相应安装包与服务发布生效。

- `ext_xydc_openapi_operations()`：读取目录与请求合同。
- `ext_xydc_openapi_call(operation, payload)`：执行 21 个公共 OpenAPI 操作。

四个旧工具只是便利包装，底层早已调用 OpenAPI；本次取消其 MCP 注册，不减少查询能力。SDK Provider 内部旧参数兼容保留，但普通用户继续通过远程 MCP 查询。

## CLI 代理与宿主工具发现

有终端但宿主没有直接挂载西柚 MCP 工具时，先用 `opscli xiyou --help` 核对入口，再执行 `opscli xiyou operations`。CLI 复用 Keepa 的 `RemoteMcpAdapter`，从当前 OPS 登录态获取远端 MCP HTTP 配置，不启动本地服务、不领取本机供应商凭据。

```powershell
opscli xiyou operations
opscli xiyou call asin_info --payload-file payload.json --output result.json
```

`payload.json` 是目录要求的业务 JSON 对象；`--payload` 字符串与 `--payload-file` 文件二选一。`--output` 可选，保存完整远端响应供后续分析或本地生成 Excel，父目录须已存在。调用失败返回非零退出码并保留原始错误，不跨入口自动重放。

宿主支持延迟加载工具时，先检索 `ext_xydc_openapi_operations` 和 `ext_xydc_openapi_call`。Skill 可发现不等于工具已挂载；初始列表未显示工具也不等于连接缺失。旧程序若返回 `No such command 'xiyou'`，需要升级包含此 CLI 的程序版本；只更新 Skill 无法增加入口。

## 旧调用的等价转换

| 移除的 MCP 工具 | 新 operation | payload 转换 |
| --- | --- | --- |
| ext_xydc_get_asin_info | asin_info | asins 与 country 合并为 entities 对象数组 |
| ext_xydc_get_asin_traffic | asin_traffic | asins 与 country 合并为 entities 对象数组 |
| ext_xydc_get_keyword_info | search_terms_info | keywords 改为 searchTerms；country 保留；显式补 sort |
| ext_xydc_get_keyword_asin_analysis | search_terms_analysis_period | keyword 改为 searchTerm，page_size 改为 pageSize；补 period 与 sort；核对旧页码转换 |

商品、流量请求示例：

```text
ext_xydc_openapi_call(
  operation="asin_info",
  payload={"entities":[{"asin":"B09XS7JWHH","country":"US"}]}
)
```

流量快照将 operation 改为 `asin_traffic`，payload 结构相同。

关键词信息保留原包装的默认排序：

```text
ext_xydc_openapi_call(
  operation="search_terms_info",
  payload={"country":"US","searchTerms":["usb c cable"],
           "sort":{"field":"weeklySearchVolume","order":"desc"}}
)
```

原竞争分析包装默认 `page=1/page_size=20/sort_field=traffic/sort_order=desc`，实际上发送给供应商的是 `page=0`。要保留同一请求条件，迁移为：

```text
ext_xydc_openapi_call(
  operation="search_terms_analysis_period",
  payload={"country":"US","searchTerm":"usb c cable","period":"last7days",
           "page":0,"pageSize":20,"sort":{"field":"traffic","order":"desc"}}
)
```

其他旧页码的等价转换为 `max(旧 page - 1, 0)`。通用入口原样发送 page，不自动减1；上述示例说明旧请求等价关系，不证明供应商第一页是0。供应商关键词分析分页起点仍未明确，按实际目录、原始请求及返回核对，避免静默漏页。新请求显式传分页、排序和 period；旧包装的20条默认值及1～100范围不再作为新接口的隐含约束，以目录的 pageSize 合同为准。

## 发布与客户端刷新

1. 发布服务代码后，确认实际 tools/list 中西柚仅有上述两个工具。
2. 核对角色已授权 `ext_xydc_openapi_operations` 和 `ext_xydc_openapi_call`；只授权旧工具的用户需迁移权限。后台目录同步只增不删，旧条目或标签需管理员按部署范围处理，不因单台服务更新自动全局删除。
3. 发布包含 `opscli xiyou` 的客户端安装包与 ops-xiyou v2.0.1 Skill。用户通过 `opscli self-update` 更新程序及 Skill，再用 `opscli xiyou --help` 和 `opscli xiyou operations` 验收。若只发 Skill 而程序未发，旧 CLI 仍无该入口。
4. 直连 MCP 的用户重连或刷新工具列表。旧会话缓存工具名不会因代码变更立即消失；Skill 也不会自动挂载远程工具。
5. 调用方按上表迁移；尚未迁移的旧 MCP 工具调用将不可用，没有网页或供应商旧 MCP 兜底。

额度继续使用统一调用原有 `service=xiyou` 分组、默认策略及历史用量/加额记录；运行时不再为四个旧工具提供默认映射，SQLite 历史迁移合同保留。没有删除真实额度数据或替管理员修改现有策略。

查询仍可能消费供应商 Credit；重复请求没有新增幂等保障。目录查询可用于不收费地核对能力，部署验收不要自动重放收费请求。

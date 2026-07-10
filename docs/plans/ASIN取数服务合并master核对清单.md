# ASIN 取数服务合并 master 核对清单

生成时间：2026-07-10
当前分支：`release`
目标分支：`master`

## 核对结论

本次不建议把 `release` 整分支直接合并到 `master`。当前 `release` 相对 `master` 同时包含 Amazon Rufus、Sif、西柚、asin_review、Shopify/MCP helper、输出产物等大量非 ASIN 取数服务改动。

建议采用“从 `master` 新建干净分支，然后按本清单挑文件/摘行合并”的方式，只合并 ASIN 取数服务和对应 MCP 能力。

## 必须合并的代码文件

### ASIN 取数核心服务

这些文件构成 `opscli asin-data live-data/fetch-file/report-url` 的实时取数、AI Ready 返回、xlsx 拆包、BI/listing/crawler 数据聚合能力。

```text
opscli/asin_data/cli.py
opscli/asin_data/services/__init__.py
opscli/asin_data/services/ai_response.py
opscli/asin_data/services/bi_report_data.py
opscli/asin_data/services/collector.py
opscli/asin_data/services/daily_pipeline.py
opscli/asin_data/services/live_data.py
opscli/asin_data/services/merged_report_renderer.py
opscli/asin_data/services/report_file_submitter.py
opscli/asin_data/services/report_files.py
opscli/asin_data/services/split_package_builder.py
opscli/asin_data/services/live_metrics.py
```

当前未提交但需要包含的关键点：

```text
opscli/asin_data/services/bi_report_data.py      getAmazonListing 请求带 site_code
opscli/asin_data/services/collector.py           按 ASIN 透传 site_by_asin/default_site
opscli/asin_data/services/daily_pipeline.py      每日管线 BI 阶段透传站点
opscli/asin_data/services/live_metrics.py        本地 JSONL 指标日志
```

### MCP ASIN 取数能力

这些文件把 ASIN 取数能力暴露为 MCP tool，并增加服务端稳定性能力。

```text
opscli/mcp/tools/asin_data.py
opscli/mcp/asin_data_limit.py
opscli/mcp/tools/health.py
```

`opscli/mcp/server.py` 不能整文件覆盖，需要只合并 ASIN 相关注册：

```python
from opscli.mcp.tools import health as _health_tools
from opscli.mcp.tools import asin_data as _asin_data_tools

_health_tools.register(_telemetry_mcp)
_asin_data_tools.register(_telemetry_mcp)
```

不要带入同文件中的非本次范围注册，例如：

```text
asin_review
sif
shopify
feedtask
```

### 共享上传能力

ASIN 实时 xlsx 上传依赖以下共享改动。

```text
opscli/shared/file_uploads.py
```

需确认包含：

```text
FileUploadClient.upload(..., filename=...)
OPSCLI_FILE_UPLOAD_RETRIES
429/500/502/503/504 与网络异常有限重试
上传失败错误上下文：endpoint/folder/purpose/file/size/attempt
```

## 建议一起合并的 Skill/文档文件

如果 master 发布后要让 AI Skill 直接调用最新取数服务，建议一起合并：

```text
opscli/skills/templates/ops-asin-data-collector/SKILL.md
opscli/skills/templates/ops-asin-data-collector/data/VERSION.json
opscli/skills/templates/ops-asin-data-collector/references/codex-usage.md
opscli/skills/templates/ops-asin-data-collector/references/data-contract.md
opscli/skills/templates/ops-asin-data-collector/references/source-mapping.md
opscli/skills/templates/ops-asin-data-collector/scripts/collect_asin_data.py
```

可选合并的用户/设计文档：

```text
docs/guide/ASIN巡检AI取数命令操作手册.md
docs/guide/ASIN批量取数服务使用说明.md
docs/guide/ASIN取数前端数据结构.md
docs/design/ASIN取数拆分交付后端改造方案.md
docs/design/ASIN批量取数服务与Skill封装方案.md
docs/design/ASIN每日取数入库命令与接口方案.md
docs/plans/ASIN每日取数入库脚本方案.md
docs/change-log-pending.md
```

## 建议合并的测试文件

这些测试用于覆盖实时取数、AI Ready 返回、BI/listing、拆包、MCP 工具、限流、健康检查和 OSS 上传重试。

```text
tests/asin_data/test_ai_response.py
tests/asin_data/test_asin_data_cli.py
tests/asin_data/test_bi_report_data.py
tests/asin_data/test_daily_pipeline.py
tests/asin_data/test_direct_runner.py
tests/asin_data/test_report_files.py
tests/asin_data/test_single_asin_collect.py
tests/asin_data/test_split_package_builder.py
tests/mcp/test_asin_data_tools.py
tests/mcp/test_asin_data_limit.py
tests/mcp/test_health_tool.py
tests/shared/test_file_uploads.py
tests/shared/test_mcp_api_key_auth.py
```

`tests/shared/test_mcp_api_key_auth.py` 只需要合并 `FileUploadClient.upload(filename=...)` 的测试增量，不要顺手带入其他无关测试改动。

## 可选工具脚本

压测与每日取数脚本可按部署需要决定是否进入 master。

```text
scripts/mcp_asin_data_pressure.py
scripts/asin_data_daily_collect.ps1
scripts/asin_data_daily_full_package.py
```

如果本次目标只是 MCP 实时取数服务，优先合并：

```text
scripts/mcp_asin_data_pressure.py
```

## 明确不要合并的文件范围

以下文件或目录不是本次 ASIN 取数服务范围，合并到 master 会扩大风险。

```text
opscli/asin_review/**
opscli/mcp/tools/asin_review.py
opscli/mcp/tools/shopify.py
opscli/mcp/tools/feedtask.py
opscli/shopify/**
opscli/feedtask/**
opscli/amazon_rufus/**
opscli/mcp/tools/amazon_rufus.py
opscli/sif/**
opscli/xiyou/**
.super-dev/**
graphify-out/**
input/**
output/**
```

也不要合并当前工作区中的测试产物：

```text
output/asin-data/*.xlsx
output/asin-data/mcp-*
output/asin-data/live-data-*
output/amazon-rufus/**
output/feedback/**
```

共享入口文件中的非 ASIN 行也不要带入：

```text
opscli/cli.py                    当前相对 master 的差异主要是 asin_review，不属于本次范围
opscli/mcp/tools/helpers.py       当前新增 feedtask/shopify manager，不属于本次范围
opscli/auth/config.py             当前默认 OPS URL 改成 QA，不属于本次范围
opscli/mcp/cli.py                 Optional 类型兼容改动，不属于 ASIN 取数
opscli/mcp/context.py             X-Opscli-Version header 改动，不属于 ASIN 取数
```

## 推荐合并步骤

建议不要在当前脏工作区直接操作 master。推荐流程：

```powershell
git switch master
git pull
git switch -c codex/asin-data-service-merge
```

如果 ASIN 取数改动已在某个干净源分支提交，可按文件挑选：

```powershell
git checkout <source-branch> -- `
  opscli/asin_data/cli.py `
  opscli/asin_data/services `
  opscli/mcp/tools/asin_data.py `
  opscli/mcp/asin_data_limit.py `
  opscli/mcp/tools/health.py `
  opscli/shared/file_uploads.py `
  opscli/skills/templates/ops-asin-data-collector `
  tests/asin_data `
  tests/mcp/test_asin_data_tools.py `
  tests/mcp/test_asin_data_limit.py `
  tests/mcp/test_health_tool.py `
  tests/shared/test_file_uploads.py `
  scripts/mcp_asin_data_pressure.py
```

然后手工处理 `opscli/mcp/server.py`：

```text
只加入 _health_tools / _asin_data_tools 的 import 与 register。
不要加入 _asin_review_tools、_sif_tools、shopify/feedtask 相关注册。
```

如果 `opscli/shared/file_uploads.py` 在 master 上已有别的改动，优先手工合并以下功能块：

```text
filename 参数
上传重试
上传错误上下文
```

## 合并后验证命令

最小验证：

```powershell
rtk test .\.venv\Scripts\python.exe -m py_compile `
  opscli\asin_data\cli.py `
  opscli\asin_data\services\ai_response.py `
  opscli\asin_data\services\bi_report_data.py `
  opscli\asin_data\services\collector.py `
  opscli\asin_data\services\daily_pipeline.py `
  opscli\asin_data\services\live_data.py `
  opscli\asin_data\services\live_metrics.py `
  opscli\asin_data\services\split_package_builder.py `
  opscli\mcp\tools\asin_data.py `
  opscli\mcp\asin_data_limit.py `
  opscli\mcp\tools\health.py `
  opscli\shared\file_uploads.py `
  scripts\mcp_asin_data_pressure.py
```

聚焦测试：

```powershell
rtk test .\.venv\Scripts\python.exe -m pytest `
  tests\asin_data\test_ai_response.py `
  tests\asin_data\test_asin_data_cli.py `
  tests\asin_data\test_bi_report_data.py `
  tests\asin_data\test_split_package_builder.py `
  tests\asin_data\test_single_asin_collect.py `
  tests\mcp\test_asin_data_tools.py `
  tests\mcp\test_asin_data_limit.py `
  tests\mcp\test_health_tool.py `
  tests\shared\test_file_uploads.py
```

MCP import 冒烟：

```powershell
.\.venv\Scripts\python.exe -c "import importlib; importlib.import_module('opscli.mcp.server'); print('mcp server import ok')"
```

可选真实压测：

```powershell
.\.venv\Scripts\python.exe scripts\mcp_asin_data_pressure.py `
  --input output\asin-data\perf-asins-20260709.csv `
  --no-upload-xlsx
```

## 上线前人工核对点

1. `opscli asin-data live-data --data-scope basic|listing_basic|bi|all` 参数在 master 可见。
2. MCP tool 列表包含 `asin_data_live_data`、`asin_data_fetch_file`、`asin_data_report_url`、`ops_health_check`。
3. `asin_data_live_data` 默认 `return_mode=ai_ready`。
4. `data_scope=bi` 请求带最近 7 天日期时只取 BI 数据，不触发基础刊登数据。
5. `listing_basic` 请求 `getAmazonListing` 时带 `site_code`。
6. OSS 上传偶发 429/5xx 时会重试，401/403 不重试。
7. 本地 metrics 默认写入 `output/asin-data/metrics/live-data-metrics.jsonl`，可用 `OPSCLI_ASIN_DATA_METRICS_DISABLED=1` 关闭。
8. `opscli/mcp/server.py` 没有带入 `asin_review/sif/shopify/feedtask` 注册。

# CLI 与 MCP 更新机制治理规划与实施计划

> 文档日期：2026-07-16
> 状态：待评审
> 范围：opscli（CLI + MCP + Skills）+ auto-scheduler（OPS 后端）
> 关联文档：
> - `docs/plans/远程MCP代理CLI统一改造实施计划.md`
> - `docs/plans/MCP服务完善整改计划书.md`
> - `docs/release/打包发布指南.md`
> - `docs/design/通用Skill版本控制架构.md`

---

## 一、背景与问题

opscli 当前以 PyPI 包（`aukeys-opscli`）形式分发，CLI 与 MCP Server 同包发布。近一个月发版节奏约 **1–2 天一个小版本**（0.0.118 → 0.0.139），每次发版用户侧需手动执行三条命令：

```bash
pip install --upgrade aukeys-opscli
opscli skills install --force
opscli skills upgrade
```

由此产生三个核心问题：

1. **升级摩擦高**：三条命令 + 手动触发，用户经常停留在旧版本，导致线上问题排查时版本不一致
2. **变更落点太靠客户端**：约 35% 的发版是 fix，其中大量落在 skills planner 规则、文档、查询默认条件等"数据/规则层"，本不需要走 PyPI 发版
3. **MCP 与 CLI 紧耦合**：本机运行 MCP 的用户必须升级 CLI 才能获得 MCP 修复，而 MCP 多用户集中部署的基础设施（`--transport both` + API Key 远程校验 + 凭证隔离）已具备却未启用

**根因判断：痛点不是"缺更新机制"（版本检查提示已存在），而是"变更落点太靠客户端 + 升级动作太重"。**

---

## 二、现状分析

### 2.1 三层更新通道现状

| 层 | 更新机制 | 触发方式 | 用户负担 | 关键代码 |
|---|---|---|---|---|
| CLI 本体 | PyPI 发版 + 启动时 stderr 提示（24h 缓存） | 手动三条命令 | 高 | `opscli/shared/update_check.py` |
| MCP 服务 | 与 CLI 同包，升级 CLI 才能升级 MCP | 手动升级 + 重启进程 | 高 | `opscli/mcp/server.py` |
| Skills 模板 | 内置模板 + 远端拉取（**仅 ops-dataset-query**） | 手动 `opscli skills upgrade` | 中 | `opscli/skills/sync/updater.py` |
| Skill 数据 | 远端 OPS API（manifest/fields/datasets） | skills install/upgrade 时拉取 | 低 | `MANIFEST_ENDPOINT` 等 |

### 2.2 已具备的基础能力（可直接复用）

| 能力 | 位置 | 说明 |
|---|---|---|
| 启动时版本检查 | `opscli/shared/update_check.py` | 查 PyPI JSON API，24h 缓存，静默降级 |
| 瘦客户端架构 | `opscli/shared/remote_mcp_adapter.py` | query/keepa/seller-sprite/xiyou 均为服务端执行、客户端转发 |
| Skills 远端升级协议 | `opscli/skills/sync/updater.py` | manifest 版本对比 + 原子替换，但硬编码只支持 ops-dataset-query |
| MCP 多用户模式 | `opscli/mcp/auth_middleware.py` + `user_store.py` | API Key 后端校验 + 按 Key 哈希凭证物理隔离 |
| Hook 注入机制 | `opscli/skills/hooks/settings_injector.py` | 可向 Claude Code / Codex 配置注入 Hook |
| CI 自动发版 | `.github/workflows/build-and-publish.yml` | tag 触发，多平台 Cython wheel |

### 2.3 现存缺口

1. 无一键升级命令，三条命令靠用户记忆
2. 版本检查依赖公网 PyPI，国内网络环境不稳定，且无"最低支持版本"治理抓手
3. Skills 远端升级通道未通用化（`updater.py` 中 `if skill_name != "ops-dataset-query": return None`）
4. MCP 未集中部署，每个用户本机跑一份
5. 后端无法感知客户端版本分布，不敢做不兼容变更

---

## 三、总体方案与分期策略

**总体思路：短期降低升级摩擦，中期扩大"免发版"变更覆盖面，长期把 MCP 集中化让用户端零升级。**

```
一期（治标）  opscli self-update 一键升级 + 提示语简化
                 │
二期（治理）  版本检查走 OPS 后端 + min_cli_version 强约束
              + Skills 远端升级通用化（免发版通道扩容）
                 │
三期（治本）  MCP 集中部署，客户端降级为"薄认证壳"
              CLI 发版频率从 1–2 天/版 降到 按月
```

各期独立可交付、独立验收，前一期不阻塞后一期立项，但二期 T2-1 后端接口是 T2-2/T2-3 的前置依赖。

---

## 四、一期：升级体验优化（opscli 侧，无后端依赖）

**目标：** 用户升级动作从"三条命令"变为"一条命令"，并对 Cython 二进制 wheel 安装失败场景做防护。

**预计工期：4 人日（2026-07-17 ~ 2026-07-24）**

### T1-1 新增 `opscli self-update` 命令

- **内容：**
  1. 检测当前安装方式：uv tool / pipx / pip（venv）/ pip（全局），依据 `sys.executable` 路径特征与 `importlib.metadata` 判断
  2. 执行对应升级命令（如 `uv tool upgrade aukeys-opscli` / `pipx upgrade aukeys-opscli` / `{python} -m pip install --upgrade --only-binary :all: aukeys-opscli`）
  3. 升级成功后自动串行执行 `skills install --force` 与 `skills upgrade`
  4. 全程输出各步骤状态（GBK 安全字符，遵循【铁律23】）
- **涉及文件：** 新增 `opscli/shared/self_update.py`；`opscli/cli.py` 注册顶级命令
- **工作量：** 1.5 人日
- **依赖：** 无
- **验收标准：**
  - macOS（uv tool / venv pip）与 Windows（全局 pip）三种安装方式下执行 `opscli self-update`，均能正确识别安装方式并完成升级 + skills 同步
  - 已是最新版本时输出"已是最新"并跳过升级步骤
  - 单元测试覆盖安装方式识别逻辑（mock `sys.executable`，不发真实网络请求，遵循【铁律8】）

### T1-2 pip 路径强制 `--only-binary` 防编译退化

- **内容：** pip 升级路径强制加 `--only-binary :all:`，wheel 不可用时明确报错并提示当前平台/Python 版本，而不是退化为源码编译（Cython + cryptography 源码编译在用户机器上大概率失败，参考 Intel Mac cryptography 先例）
- **涉及文件：** `opscli/shared/self_update.py`
- **工作量：** 0.5 人日（与 T1-1 合并开发）
- **依赖：** T1-1
- **验收标准：** 模拟 wheel 缺失场景（指定不存在的版本号），命令输出清晰的失败原因与人工处理指引，退出码非 0

### T1-3 升级提示语简化

- **内容：** `update_check.py` 中检测到新版本时的提示从三条命令改为一条 `opscli self-update`
- **涉及文件：** `opscli/shared/update_check.py`
- **工作量：** 0.5 人日
- **依赖：** T1-1
- **验收标准：** 存在新版本时 stderr 提示仅包含 `opscli self-update`；`tests/shared/test_update_check.py` 相应断言更新并通过

### T1-4 测试补全与文档

- **内容：** `tests/shared/test_self_update.py` 全流程测试；`docs/guide/` 新增升级操作说明或在认证模块使用指南中补充升级章节；更新 `README.md` 安装升级章节
- **工作量：** 1 人日
- **依赖：** T1-1 ~ T1-3
- **验收标准：** `pytest tests/shared/ -v` 全绿；文档含三种安装方式的升级说明

### T1-5 发版验证

- **内容：** 打 tag 走 CI 发版，用旧版本客户端实际执行 `opscli self-update` 完成真实升级闭环验证
- **工作量：** 0.5 人日
- **依赖：** T1-1 ~ T1-4
- **验收标准：** 至少 1 台 macOS + 1 台 Windows 真机完成旧版 → 新版一键升级

---

## 五、二期：版本治理与免发版通道（opscli + auto-scheduler 双端）

**目标：** 版本检查与治理收口到 OPS 后端；Skills 远端升级通用化，让规则/文档类修复不再需要 PyPI 发版。

**预计工期：opscli 侧 8 人日 + 后端侧 5 人日（2026-07-27 ~ 2026-08-14，双端可并行）**

### T2-1 【后端】新增 CLI 版本治理接口

- **内容：** auto-scheduler 新增 `GET /api/v1/cli/version`，返回：
  ```json
  {
    "latest": "0.0.145",
    "min_supported": "0.0.130",
    "notice": "可选的升级公告文案"
  }
  ```
  版本号由后端配置管理（建议存配置表，运营可改，不用发后端版本）
- **工作量：** 后端 1.5 人日
- **依赖：** 无
- **验收标准：** 接口无鉴权可访问（或仅 API Key 级）；响应 P99 < 200ms；配置修改后即时生效

### T2-2 CLI 版本检查切换到 OPS 后端

- **内容：** `update_check.py` 优先请求 T2-1 接口，失败时回退 PyPI JSON API（保持现有静默降级逻辑不变）；缓存结构增加 `min_supported` 字段
- **涉及文件：** `opscli/shared/update_check.py`
- **工作量：** 1 人日
- **依赖：** T2-1
- **验收标准：** OPS 接口可达时不请求 PyPI；OPS 不可达时回退 PyPI 且不报错；缓存兼容旧格式（旧缓存文件不导致崩溃）

### T2-3 最低版本强约束（min_cli_version 阻断）

- **内容：**
  1. 所有经 `remote_mcp_adapter.py` / `query/transport/client.py` 发出的请求统一携带 `X-Client-Version` header
  2. 后端在网关或中间件校验，低于 `min_supported` 返回约定错误码（如 `426 Upgrade Required`）
  3. CLI 捕获该错误码，输出"版本过低，请运行 opscli self-update"并终止当前操作
- **涉及文件：** `opscli/shared/remote_mcp_adapter.py`、`opscli/query/transport/client.py`；后端中间件
- **工作量：** opscli 侧 2 人日 + 后端 2 人日
- **依赖：** T2-1、一期 T1-1
- **验收标准：** 后端把 `min_supported` 调高到当前版本之上时，CLI 所有远端命令均给出统一升级提示；调回后恢复正常；后端可按 `X-Client-Version` 统计版本分布

### T2-4 Skills 远端升级通用化

- **内容：**
  1. 后端扩展 skill manifest 协议：支持任意 skill 的版本 + 文件清单（SKILL.md、reference/、scripts/ 均可下发），复用现有 `MANIFEST_ENDPOINT` 或新增通用端点
  2. `updater.py` 移除 `ops-dataset-query` 硬编码分支，按 manifest 声明的文件清单下载 + 原子替换（沿用现有临时目录 + 原子 mv 策略）
  3. manifest 中每个 skill 增加 `min_cli_version` 字段，CLI 版本不满足时跳过该 skill 升级并提示（防止新 skill 依赖新 CLI 能力）
  4. 首批接入 2–3 个高频变更 skill（建议：ops-dataset-query 存量迁移 + ops-amazon-rufus + ops-query-wizard）
- **涉及文件：** `opscli/skills/sync/updater.py`、`opscli/skills/manager.py`；后端 manifest 发布链路
- **工作量：** opscli 侧 3 人日 + 后端 1.5 人日
- **依赖：** 无（可与 T2-1~T2-3 并行）
- **验收标准：**
  - 后端发布某 skill 新版本后，用户执行 `opscli skills upgrade` 即可获得，全程无 PyPI 发版
  - 升级中断（网络断开）不损坏本地已安装 skill（原子替换验证）
  - `pytest tests/skills/ -v` 全绿

### T2-5 opt-in 自动升级

- **内容：** `~/.config/opscli/config.ini` 新增 `[update] auto_update = true`（默认 false）。开启后启动检查发现新版本时，后台派生独立进程执行 self-update（避免替换正在运行的 Cython 二进制导致崩溃），当前命令不受影响，下次启动生效
- **涉及文件：** `opscli/shared/update_check.py`、`opscli/shared/self_update.py`
- **工作量：** 2 人日
- **依赖：** T1-1、T2-2
- **验收标准：** 开启配置后无人工干预完成升级；升级进程失败不影响前台命令；默认关闭，文档明确说明风险

---

## 六、三期：MCP 集中部署，客户端降级为薄认证壳

**目标：** AI Agent 场景（主流用量）的用户接入中央 MCP，工具逻辑更新全部收口到服务端发布，用户端零升级；CLI 发版频率降到按月。

**预计工期：约 5 周（2026-08-17 ~ 2026-09-18，含灰度），需运维配合**

### T3-1 中央 MCP 部署方案设计

- **内容：** 输出部署设计文档（`docs/design/`），覆盖：
  - 部署形态：`opscli-mcp --transport both` 多用户模式，前置 Nginx/网关
  - 容量与隔离：并发连接数评估、按 API Key 的凭证目录隔离（现有 `user_store.py` 机制）在服务器上的磁盘与备份策略
  - 发布流程：服务端升级 = 拉新版包 + 平滑重启（SSE 长连接的断线重连预案，客户端侧 MCP 协议自带重连）
  - 监控告警：进程存活、API Key 校验失败率、工具调用错误率
  - 安全评审：中央服务器持有多用户凭证的风险评估与加密策略
- **工作量：** 2 人日（设计）+ 评审
- **依赖：** 无
- **验收标准：** 设计文档通过团队评审，运维确认资源可行

### T3-2 中央 MCP 部署与内部灰度

- **内容：** 测试环境部署 → 团队内部 3–5 人切换到远程 MCP 试用一周 → 修复问题 → 生产部署
- **工作量：** 部署 2 人日 + 灰度观察 1 周
- **依赖：** T3-1
- **验收标准：** 灰度用户全场景（auth/query/skills 相关 MCP 工具）可用；一次服务端发布重启后，客户端无需任何操作自动恢复

### T3-3 用户迁移与接入指引

- **内容：**
  1. `docs/guide/` 输出中文接入指南（Claude Code / Cursor / Cherry Studio 各工具的 URL + API Key 配置方式）
  2. 新增 `opscli mcp connect-remote` 辅助命令：自动向本机 AI 工具配置写入远程 MCP 地址（复用 `settings_injector.py` 的配置注入能力）
  3. 分批通知存量本机 MCP 用户迁移
- **工作量：** 3 人日
- **依赖：** T3-2
- **验收标准：** 新用户按指南 10 分钟内完成接入；`connect-remote` 命令在 Claude Code 配置中正确写入且幂等

### T3-4 发版节奏治理与本机 MCP 退役评估

- **内容：**
  1. 建立发版分级：数据/规则变更走 skills 远端通道（二期 T2-4），MCP 工具逻辑走服务端发布，仅本地必须能力（auth 登录、凭证存储、Playwright 抓取类）才触发 PyPI 发版
  2. 观察一个月后统计：PyPI 发版频率、客户端版本分布（依赖 T2-3 的 header 统计）
  3. 评估本机 MCP 模式是否保留（离线/内网场景可能仍需）
- **工作量：** 持续性治理，观察期 4 周
- **依赖：** T2-3、T2-4、T3-3
- **验收标准：** PyPI 发版频率降至 ≤ 1 次/两周；活跃用户中 90% 以上运行在 `min_supported` 以上版本

---

## 七、里程碑排期总览

| 里程碑 | 时间 | 交付物 | 依赖方 |
|---|---|---|---|
| M1 一期完成 | 2026-07-24 | `opscli self-update` 上线，升级提示简化，真机验证通过 | 仅 opscli |
| M2 版本治理接口上线 | 2026-07-31 | 后端 `/v1/cli/version` + CLI 切换 OPS 检查源 | auto-scheduler |
| M3 min_version 强约束生效 | 2026-08-07 | 全链路 `X-Client-Version` + 低版本阻断 | 双端 |
| M4 Skills 远端升级通用化 | 2026-08-14 | 任意 skill 免发版下发，首批 3 个 skill 接入 | 双端 |
| M5 中央 MCP 生产部署 | 2026-08-28 | 生产环境中央 MCP + 内部灰度通过 | 运维 |
| M6 用户迁移完成 | 2026-09-18 | 接入指引 + `connect-remote` 命令 + 存量用户迁移 | 全员 |
| M7 治理效果验收 | 2026-10-16 | 发版频率 ≤ 1 次/两周，版本分布达标 | — |

甘特概览（周粒度）：

```
              7/16  7/23  7/30  8/6   8/13  8/20  8/27  9/3   9/10  9/17  ...10/16
一期 T1-x      ████ █
二期 T2-1            ██
二期 T2-2/2-3          ████ ██
二期 T2-4              ████ ████
二期 T2-5                    ███
三期 T3-1                        ███
三期 T3-2                           ████ ████
三期 T3-3                                     ████ ████
三期 T3-4                                               ██████(观察期至 10/16)
```

---

## 八、风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| Cython wheel 平台覆盖缺口导致 self-update 失败 | 高 | T1-2 强制 `--only-binary` 快速失败 + 明确指引；CI 已覆盖 Linux/macOS(Intel+ARM)/Windows，新平台需求先补 CI 矩阵 |
| min_version 阻断误伤（后端配置错误一刀切） | 高 | 配置变更需双人复核；CLI 阻断提示中带后端返回的 notice 文案；保留后端一键回滚配置 |
| 中央 MCP 单点故障影响全员 | 高 | T3-1 设计中要求健康检查 + 自动重启；保留本机 MCP 模式作为降级手段，迁移期不删除本机能力 |
| 中央服务器集中存储多用户凭证的安全风险 | 中 | 沿用 AES-256-GCM 加密存储 + 按 Key 哈希隔离；T3-1 安全评审为部署前置门禁 |
| Skills 通用 manifest 协议与现有 ops-dataset-query 数据链路兼容 | 中 | T2-4 先做存量迁移的回归测试（`pytest tests/skills/`），原子替换保证失败可回退 |
| 自动升级在用户执行长任务时触发 | 低 | T2-5 采用独立进程 + 下次启动生效，不替换运行中进程；默认关闭 |
| 后端排期资源不足 | 中 | 二期双端任务已按可并行拆分；T2-4 可独立于 T2-1~T2-3 先行 |

---

## 九、总体验收标准

1. **升级体验**：用户升级动作 = 1 条命令（或 opt-in 全自动），M1 后新版本发布 7 天内活跃用户升级率显著提升（以 T2-3 header 统计为准）
2. **免发版能力**：skills 规则/文档类修复 100% 走远端通道，不触发 PyPI 发版
3. **版本治理**：后端可实时查看客户端版本分布，可通过配置强制最低版本
4. **发版频率**：PyPI 发版从 1–2 天/版 降至 ≤ 1 次/两周
5. **MCP 用户零升级**：接入中央 MCP 的用户在服务端发布后无需任何本地操作

---

## 十、不在本规划范围

- CLI 完全去本地化（auth 凭证存储、Playwright 本地抓取类能力保留在客户端）
- 私有 PyPI index 搭建（现阶段公网 PyPI + `--only-binary` 已满足，如后续有内网分发需求另行立项）
- MCP 协议层的多区域部署 / 高可用集群（一期集中部署为单实例 + 监控重启，规模上来后再演进）

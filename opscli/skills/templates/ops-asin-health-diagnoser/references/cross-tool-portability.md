# ASIN 健康诊断 — 跨工具兼容方案

本 Skill 的核心逻辑不依赖特定 AI 工具。以下说明当前工具专属能力和通用替代方案。

---

## 1. 能力分层

| 能力 | 当前工具实现 | 通用替代 |
|------|------------|---------|
| 数据查询 | `opscli query build`（CLI）或 `query_build_and_run`（MCP Tool） | `opscli query build` CLI 命令（任何终端环境） |
| 认证 | `opscli auth login`（CLI）或 `auth_login_start/poll`（MCP） | `opscli auth login` CLI 命令 |
| 评分计算 | `scripts/calculate_health_score.py` | 同一脚本，纯 Python 标准库 |
| 结果格式化 | 脚本内 `format_diagnosis()` | 同一脚本 |
| 数据提取与合并 | `core.py` 中的 `extract_metrics_from_query_result()` | 同一脚本 |

---

## 2. 降级路径

### 场景 A：AI 工具不支持 MCP

1. 使用 CLI 模式，通过 `subprocess` 调用 `opscli query build` 和 `opscli query run`
2. 评分计算通过 `python scripts/calculate_health_score.py` 完成
3. 所有命令都可在标准终端执行

### 场景 B：AI 工具无法运行 Python 脚本

1. AI 直接理解 SKILL.md 中的评分公式和阈值表
2. 从查询结果中手动提取指标值
3. 按公式计算标准化分数和加权评分
4. 按 `operating-rules.md` 中的行动建议矩阵给出建议

### 场景 C：完全离线（无 opscli）

1. 用户提供 CSV/Excel 数据（包含 6 个指标列）
2. AI 按公式和阈值手动评估
3. 或用户自行安装 opscli：`pip install aukeys-opscli`

---

## 3. 脚本依赖

所有脚本仅依赖 Python 标准库（`json`、`csv`、`sys`、`argparse`、`pathlib`），无第三方依赖。

| 脚本 | 外部依赖 | 可独立运行 |
|------|---------|-----------|
| `scripts/core.py` | 无 | 是（作为模块导入） |
| `scripts/calculate_health_score.py` | core.py | 是 |
| `scripts/record_run.py` | 无 | 是 |

---

## 4. 迁移检查清单

迁移到其他 AI 工具时确认：

- [ ] 能执行 `opscli` CLI 命令
- [ ] 能运行 Python 3.10+ 脚本
- [ ] SKILL.md 能被加载为上下文
- [ ] references/ 目录中的文件能按需读取
- [ ] 认证流程可用（Device Flow 或 Token）

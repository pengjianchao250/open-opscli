# Skills 基础开发培训手册

> 本文档面向业务开发人员，介绍 opscli Skill 的核心概念、目录规范、开发流程与接入方法。
>
> **阅读完本文档，你将能够独立开发并接入一个新的 Skill。**

---

## 目录

1. [什么是 Skill](#1-什么是-skill)
2. [Skill 体系总览](#2-skill-体系总览)
3. [Skill 目录结构规范](#3-skill-目录结构规范)
4. [SKILL.md 编写规范](#4-skillmd-编写规范)
5. [两条开发路径](#5-两条开发路径)
6. [路径A：纯本地 Skill 开发实战](#6-路径a纯本地-skill-开发实战)
7. [路径B：支持远端升级的 Skill](#7-路径b支持远端升级的-skill)
8. [铁律速查](#8-铁律速查)
9. [常见错误与排查](#9-常见错误与排查)
10. [完整开发 Checklist](#10-完整开发-checklist)

---

## 1. 什么是 Skill

**Skill** 是可安装到 AI 工具（Claude Code、OpenClaw 等）中的功能扩展包。它本质上是一个**有固定结构的目录**，其中包含：

- `SKILL.md`：告诉 AI Agent "这个 Skill 能做什么、如何使用"
- `data/VERSION.json`：版本标识，让 opscli 能识别和管理该 Skill
- `scripts/`（可选）：具体的功能脚本

**核心思想**：Skill 是 AI 工具的"使用手册 + 工具集"，AI 读取 `SKILL.md` 后知道如何帮助用户完成任务。**Skill 脚本本身不直接调用后端 HTTP API，所有远端操作必须通过 `opscli` 命令转发。**

```
用户对 AI 说：帮我查一下销售数据
           ↓
AI 读取 ops-dataset-query/SKILL.md，了解如何操作
           ↓
AI 调用 opscli query build / opscli query run
           ↓
opscli 负责认证、校验、请求后端，返回结果
```

---

## 2. Skill 体系总览

### 2.1 当前内置 Skill

| Skill 名称 | 说明 | 支持远端升级 |
|-----------|------|------------|
| `ops-auth` | 认证授权管理（登录、Token 查看与刷新、系统管理） | 否 |
| `ops-dashboard-ai-bridge` | 仪表盘页面编辑与写后核验 | 否 |
| `ops-dashboard-data-analysis` | 仪表盘业务数据只读分析 | 否 |
| `ops-dataset-query` | 数据集字段索引与查询转发 | **是** |
| `ops-skills` | Skill 生命周期管理（安装、升级、状态查看） | 否 |

### 2.2 Skill 与 opscli 的关系

```
opscli（Python 包）
├── opscli/skills/templates/   ← 内置 Skill 模板（源码）
│   ├── ops-auth/
│   ├── ops-dashboard-ai-bridge/
│   ├── ops-dashboard-data-analysis/
│   ├── ops-dataset-query/
│   └── ops-skills/
└── opscli/skills/             ← Skill 生命周期管理代码
    ├── manager.py             ← 安装/列表/状态/升级
    ├── detector.py            ← 发现已安装 Skill
    └── updater.py             ← 远端数据拉取


用户机器（安装后）
~/.claude/skills/              ← Skill 安装目标目录
├── ops-auth/
├── ops-dashboard-ai-bridge/
├── ops-dashboard-data-analysis/
├── ops-dataset-query/
└── ops-skills/
```

### 2.3 Skill 的生命周期

```
开发 → 放入 templates/ → 用户执行 install → 安装到 AI 工具目录
                                                    ↓
                              AI 读取 SKILL.md，知道如何使用
                                                    ↓
                              （定期）upgrade 拉取远端最新数据
```

---

## 3. Skill 目录结构规范

### 3.1 最小结构（必须）

```
ops-xxx/                        ← 目录名必须以 ops- 开头
├── data/
│   └── VERSION.json            ← 必须，SkillDetector 识别标志
└── SKILL.md                    ← 必须，AI Agent 使用指南
```

### 3.2 完整结构（含脚本）

```
ops-xxx/
├── data/
│   ├── VERSION.json            ← 版本标识，必须
│   ├── some_data.csv           ← 可选，本地数据缓存
│   └── metadata.json           ← 可选，元数据
├── scripts/                    ← 可选，功能脚本
│   ├── core.py
│   └── search.py
├── references/                 ← 可选，参考文档（AI 用）
│   └── 接口说明.md
└── SKILL.md                    ← AI Agent 使用指南，必须
```

### 3.3 VERSION.json 格式

```json
{
  "name": "ops-xxx",
  "version": "v1.0.0"
}
```

**规则**：
- `name` 必须与目录名完全一致
- `version` 使用语义化版本，格式 `v{major}.{minor}.{patch}`
- **禁止手动修改**已安装版本的 VERSION.json（会导致 status 命令误判）

---

## 4. SKILL.md 编写规范

### 4.1 必须包含的 YAML frontmatter

```markdown
---
name: ops-xxx
description: 一句话说明这个 Skill 的用途
version: v1.0.0
---
```

### 4.2 文档结构要求

SKILL.md 必须包含以下章节（参照 ops-auth/SKILL.md 格式）：

| 章节 | 说明 |
|------|------|
| `## 何时使用本 Skill` | 列出适用场景（列表形式） |
| `## 关键概念` | 核心术语解释（如有） |
| `## 快速参考` | 最常用命令（代码块） |
| `## 完整命令参考` | 每个命令的参数说明 + 示例 |
| `## 典型工作流` | 3-5 个端到端的使用场景 |
| `## 常见错误排查` | 错误现象 → 解决方案对照表 |

### 4.3 关键禁止项

| 禁止 | 原因 |
|------|------|
| 描述 `python scripts/xxx.py` 的调用方式 | Skill 脚本不暴露给用户直接调用 |
| 描述直接 HTTP 接口调用 | 必须通过 opscli 命令转发 |
| 缺少完整参数说明 | AI 无法知道如何传参 |
| 缺少"典型工作流"章节 | AI 无法引导用户完成端到端任务 |

### 4.4 命令描述示例（正确写法）

```markdown
### `opscli query metadata`

读取指定数据集的 query metadata（字段定义、可用聚合方式等）。

**参数**：
- `--dataset TEXT`：dataset_alias（与 --table-id 二选一）
- `--table-id INTEGER`：table_id（与 --dataset 二选一）
- `--pretty`：格式化 JSON 输出

**示例**：
\`\`\`bash
opscli query metadata --dataset sales_order_d --pretty
\`\`\`
```

---

## 5. 两条开发路径

根据是否需要**远端数据升级**，Skill 分两条开发路径：

```
新增 Skill
    │
    ├─── 数据固定，不需要远端拉取？ ──→ 路径A：纯本地 Skill
    │                                   只需创建目录 + 写 SKILL.md
    │                                   零代码修改，install 自动支持
    │
    └─── 需要定期从后端同步数据？ ───→ 路径B：支持远端升级
                                       在路径A基础上，额外修改
                                       updater.py 和 manager.py
```

**判断标准**：

- **路径A**（纯本地）：Skill 功能不依赖后端数据，或数据随代码一起发布不需要动态更新
  - 例：ops-auth（认证流程是固定的命令，不需要拉取）
  - 例：ops-skills（管理命令是固定的）

- **路径B**（支持远端升级）：Skill 包含需要定期同步的业务数据
  - 例：ops-dataset-query（字段列表、数据集信息需要跟着后端数据库动态更新）

---

## 6. 路径A：纯本地 Skill 开发实战

以新增一个 `ops-notify`（消息通知 Skill）为例，演示完整开发流程。

### 步骤 1：创建目录结构

```bash
# 在 opscli 项目根目录执行
mkdir -p opscli/skills/templates/ops-notify/data
```

### 步骤 2：创建 VERSION.json

```bash
cat > opscli/skills/templates/ops-notify/data/VERSION.json << 'EOF'
{
  "name": "ops-notify",
  "version": "v1.0.0"
}
EOF
```

### 步骤 3：编写 SKILL.md

```markdown
---
name: ops-notify
description: 通过 opscli 发送运营系统消息通知
version: v1.0.0
---

# ops-notify

通过 `opscli notify` 子命令向飞书、钉钉等渠道发送消息通知。

---

## 何时使用本 Skill

- 需要发送运营报告时
- 需要触发告警通知时
- 批处理任务完成后需要通知相关人员时

---

## 快速参考

\`\`\`bash
# 发送文本消息
opscli notify send --channel feishu --text "报告已生成"

# 发送文件
opscli notify send --channel feishu --file /tmp/report.csv
\`\`\`

---

## 完整命令参考

### `opscli notify send`

发送消息到指定渠道。

**参数**：
- `--channel TEXT`：渠道名称，如 feishu、dingtalk（必填）
- `--text TEXT`：消息文本（与 --file 二选一）
- `--file TEXT`：发送文件路径（与 --text 二选一）

**示例**：
\`\`\`bash
opscli notify send --channel feishu --text "任务完成"
opscli notify send --channel feishu --file /tmp/report.csv
\`\`\`

---

## 典型工作流

### 场景：批处理完成后通知

\`\`\`bash
# 1. 执行查询
opscli query build --dataset sales_order_d --dimension date_id \
  --metric order_cost:sum --run --pretty > /tmp/result.json

# 2. 发送结果文件
opscli notify send --channel feishu --file /tmp/result.json
\`\`\`

---

## 常见错误排查

| 错误现象 | 解决方案 |
|---------|---------|
| 渠道不存在 | `opscli notify list` 查看可用渠道 |
| 发送失败 | `opscli auth doctor` 确认网络连通性 |
```

### 步骤 4：验证目录结构

```
opscli/skills/templates/ops-notify/
├── data/
│   └── VERSION.json        ✓
└── SKILL.md                ✓
```

### 步骤 5：注册 CLI 命令（如有新命令）

如果 Skill 需要新的 `opscli notify` 命令，需要创建 `opscli/notify/` 模块，然后在 `opscli/cli.py` 中注册：

```python
# opscli/cli.py
from opscli.notify.cli import app as notify_app
app.add_typer(notify_app, name="notify")
```

> **注意**：只需在 `cli.py` 追加这一行，不能修改其他地方（铁律1）。

### 步骤 6：测试 install 命令

```bash
# 激活虚拟环境
source .venv/bin/activate

# 安装 Skill（无需任何代码改动，install 自动支持）
opscli skills install ops-notify --runtime claude

# 验证安装
opscli skills list --pretty
```

**至此，路径A开发完成。** 无需修改任何现有代码，`install` 命令自动支持新 Skill。

---

## 7. 路径B：支持远端升级的 Skill

在路径A的基础上，额外修改两处代码：`updater.py` 和 `manager.py`。

以新增 `ops-product-catalog`（商品目录 Skill，数据需定期从后端同步）为例。

### 前置：完成路径A的所有步骤

先按路径A创建目录结构和 SKILL.md，再进行以下扩展。

### 步骤 1：修改 updater.py

在 `opscli/skills/sync/updater.py` 中新增：

```python
class SkillsUpdater:
    # 在类中新增 API 端点常量
    PRODUCT_CATALOG_MANIFEST_ENDPOINT = "/v1/products/skill/manifest"
    PRODUCT_CATALOG_EXPORT_ENDPOINT = "/v1/products/skill/export"

    def fetch_manifest(self, skill_name: str) -> dict | None:
        """获取远端 Skill 的版本清单。"""
        if skill_name == "ops-dataset-query":
            # ... 原有逻辑 ...
            pass
        elif skill_name == "ops-product-catalog":
            # 新增：为新 Skill 添加分支
            response = self._get(self.PRODUCT_CATALOG_MANIFEST_ENDPOINT)
            payload = self._parse_json_response(response, endpoint=self.PRODUCT_CATALOG_MANIFEST_ENDPOINT)
            return payload.get("data")
        return None

    def upgrade_ops_product_catalog(self, record: SkillRecord, force: bool = False) -> SkillUpgradeResult:
        """执行 ops-product-catalog Skill 的数据升级。"""
        manifest = self.fetch_manifest(record.name)
        if not manifest:
            raise ValueError("远端 manifest 不存在")

        remote_version = str(manifest.get("version", "v0.0.0"))
        current_version = record.version
        needs_update = force or self.compare_versions(current_version, remote_version) < 0

        if not needs_update:
            return SkillUpgradeResult(
                name=record.name,
                from_version=current_version,
                to_version=current_version,
                runtime=record.runtime,
                target_dir=record.root,
                updated=False,
                field_count=0,
            )

        # 拉取远端数据
        catalog_csv = self._get(self.PRODUCT_CATALOG_EXPORT_ENDPOINT).text

        data_dir = record.root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        # 先写临时目录，再原子替换（不可改变此策略）
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "products.csv").write_text(catalog_csv, encoding="utf-8")
            (tmp_path / "VERSION.json").write_text(
                json.dumps({"name": record.name, "version": remote_version},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            for filename in ["products.csv", "VERSION.json"]:
                (tmp_path / filename).replace(data_dir / filename)

        return SkillUpgradeResult(
            name=record.name,
            from_version=current_version,
            to_version=remote_version,
            runtime=record.runtime,
            target_dir=record.root,
            updated=True,
            field_count=0,
        )
```

### 步骤 2：修改 manager.py

在 `opscli/skills/services/manager.py` 中修改 `status()` 和 `upgrade()` 方法：

```python
def status(self, skills_dir: str | None = None, cwd: Path | None = None) -> dict:
    records = self.list_skills(skills_dir=skills_dir, cwd=cwd)

    # 对每个支持远端升级的 Skill，查询远端版本
    remote_versions: dict[str, str | None] = {
        "ops-dataset-query": None,
        "ops-product-catalog": None,  # 新增
    }

    for skill_name in remote_versions:
        try:
            summary = self.updater.build_remote_summary(skill_name)
            manifest = summary.get("manifest")
            if manifest:
                remote_versions[skill_name] = str(manifest.get("version", "v0.0.0"))
        except Exception:
            pass  # 网络不可达时静默处理

    # 为已安装 Skill 附带远端版本
    enriched = []
    for item in records:
        row = item.to_dict()
        remote_ver = remote_versions.get(item.name)
        row["remote_version"] = remote_ver
        row["has_update"] = bool(
            remote_ver and self.updater.compare_versions(item.version, remote_ver) < 0
        )
        enriched.append(row)

    return { ... }

def upgrade(self, *, name: str = "ops-dataset-query", ...) -> SkillBatchUpgradeResult:
    records = self.list_skills(...)
    targets = [item for item in records if item.name == name]
    if not targets:
        raise ValueError(f"未找到已安装 Skill: {name}")

    # 按名称分发到对应的升级方法
    if name == "ops-dataset-query":
        results = [self.updater.upgrade_ops_dataset_query(t, force=force) for t in targets]
    elif name == "ops-product-catalog":
        results = [self.updater.upgrade_ops_product_catalog(t, force=force) for t in targets]  # 新增
    else:
        raise ValueError(f"暂不支持升级 Skill: {name}")

    return SkillBatchUpgradeResult(name=name, results=results)
```

### 步骤 3：验证

```bash
# 安装
opscli skills install ops-product-catalog

# 查看状态（包含远端版本对比）
opscli skills status --pretty

# 升级
opscli skills upgrade ops-product-catalog
```

---

## 8. 铁律速查

> 以下铁律来自 CLAUDE.md，开发前必读，违反将导致 PR 被拒。

### 命名铁律

| 规则 | 说明 | 错误示例 | 正确示例 |
|------|------|---------|---------|
| `ops-` 前缀 | 所有内置 Skill 必须以 `ops-` 开头 | `notify` | `ops-notify` |
| 目录名与 `name` 一致 | VERSION.json 中 name 必须与目录名完全相同 | 目录 `ops-notify`，name `"notify"` | name `"ops-notify"` |

### 结构铁律

| 规则 | 说明 |
|------|------|
| `data/VERSION.json` 必须存在 | 这是 SkillDetector 识别 Skill 的唯一标志，缺少则不被识别 |
| `SKILL.md` 必须存在 | 没有 SKILL.md，AI Agent 不知道如何使用该 Skill |
| 禁止描述 `python xxx.py` 调用方式 | SKILL.md 只能描述 opscli 命令 |

### 代码铁律

| 规则 | 说明 |
|------|------|
| Skill 脚本禁止直接调用 HTTP | 必须通过 opscli 命令转发（铁律10） |
| CLI 注册只改 cli.py 一处 | 新模块注册只在 `opscli/cli.py` 追加一行（铁律1） |
| 配置路径必须通过 CONFIG_DIR | 禁止硬编码路径（铁律1） |
| 不可修改 `_KEYRING_SERVICE` | 修改会使所有用户凭证失效（铁律5） |

### 升级铁律

| 规则 | 说明 |
|------|------|
| 原子替换策略不可改 | 必须先写临时目录，再 `Path.replace()` 替换 |
| 禁止直接写入目标目录 | 中途失败会产生半损坏状态的数据文件 |

---

## 9. 常见错误与排查

### 安装后 `skills list` 看不到新 Skill

**原因**：`data/VERSION.json` 文件不存在或格式错误。

**排查**：
```bash
cat ~/.claude/skills/ops-xxx/data/VERSION.json
# 确认文件存在且格式正确：{"name": "ops-xxx", "version": "v1.0.0"}
```

### `opscli skills install ops-xxx` 报"不支持的内置 Skill"

**原因**：Skill 模板目录不存在于 `opscli/skills/templates/` 下。

**排查**：
```bash
ls opscli/skills/templates/
# 确认 ops-xxx 目录存在
```

### 升级时报"远端 manifest 不存在"

**原因**：`updater.py` 的 `fetch_manifest()` 没有处理该 Skill 名称的分支。

**排查**：检查 `fetch_manifest()` 方法中是否添加了对应的 `elif skill_name == "ops-xxx"` 分支。

### SKILL.md 中文字被 AI 忽略或理解错误

**原因**：文档结构不清晰，缺少必要章节，或命令示例不完整。

**解决**：对照 `ops-auth/SKILL.md` 检查章节是否完整，命令示例是否包含所有必填参数。

### 循环导入错误

**原因**：新模块导入了 `opscli.config` 的子模块，或 `opscli.config` 中导入了子模块（铁律2）。

**合法依赖方向**：

```
opscli.config  ←  opscli.xxx.config
opscli.config  ←  opscli.xxx.storage
```

**禁止**：`opscli.config` 导入任何 `opscli.auth.*` 或其他子模块。

---

## 10. 完整开发 Checklist

### 路径A（纯本地 Skill）

- [ ] 目录名以 `ops-` 开头
- [ ] `data/VERSION.json` 存在，格式正确，name 与目录名一致
- [ ] `SKILL.md` 存在，包含必要的 frontmatter（name/description/version）
- [ ] `SKILL.md` 包含"何时使用本 Skill"章节
- [ ] `SKILL.md` 包含"完整命令参考"章节，每个命令都有参数说明
- [ ] `SKILL.md` 包含"典型工作流"章节（至少 2 个场景）
- [ ] `SKILL.md` 包含"常见错误排查"对照表
- [ ] `SKILL.md` 中没有描述 `python scripts/xxx.py` 的调用方式
- [ ] `SKILL.md` 中描述的都是 `opscli` 命令
- [ ] 执行 `opscli skills install ops-xxx` 成功
- [ ] 执行 `opscli skills list` 能看到新 Skill

### 路径B（额外：支持远端升级）

- [ ] `updater.py` 新增了 API 端点常量
- [ ] `updater.py` 的 `fetch_manifest()` 添加了新 Skill 的分支
- [ ] `updater.py` 新增了 `upgrade_ops_xxx()` 方法
- [ ] `upgrade_ops_xxx()` 使用临时目录 + 原子替换策略
- [ ] `manager.py` 的 `status()` 中为新 Skill 添加了远端版本拉取逻辑
- [ ] `manager.py` 的 `upgrade()` 中添加了名称分发分支
- [ ] 执行 `opscli skills status` 能看到远端版本对比
- [ ] 执行 `opscli skills upgrade ops-xxx` 能成功升级

### 通用（所有路径）

- [ ] 运行 `pytest tests/skills/ -v` 测试全部通过
- [ ] 如有新 CLI 模块，在 `opscli/cli.py` 追加了注册代码（仅一行）
- [ ] 未硬编码任何路径，通过 `CONFIG_DIR` 获取配置路径
- [ ] 新模块未反向导入 `opscli.config`

---

## 参考资料

| 文档 | 路径 |
|------|------|
| 现有 Skill 参考：ops-auth | `opscli/skills/templates/ops-auth/SKILL.md` |
| 现有 Skill 参考：ops-dataset-query | `opscli/skills/templates/ops-dataset-query/SKILL.md` |
| 现有 Skill 参考：ops-skills | `opscli/skills/templates/ops-skills/SKILL.md` |
| 通用版本控制架构 | `docs/design/通用Skill版本控制架构.md` |
| Skills 多工具调研规划 | `docs/design/Skills多工具调研规划.md` |
| opscli 开发规范（全量铁律） | `docs/spec/开发规范.md` |
| 项目 CLAUDE.md（含铁律详解） | `CLAUDE.md` |

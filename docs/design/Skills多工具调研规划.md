# opscli Skills 多工具支持调研规划

> **版本：** v1.0  
> **日期：** 2026-04-20  
> **目标：** 调研市面主流 AI 编码工具的 Skills/配置路径，规划 `opscli skills` 的多工具安装与管理策略

---

## 目录

1. [工具概览与分类](#1-工具概览与分类)
2. [各工具路径详查](#2-各工具路径详查)
3. [跨平台路径矩阵](#3-跨平台路径矩阵)
4. [opscli 多工具支持设计](#4-opscli-多工具支持设计)
5. [工具检测与自动发现](#5-工具检测与自动发现)
6. [实现规划](#6-实现规划)

---

## 1. 工具概览与分类

按照对 **Skills 概念的原生支持程度**分为三类：

### A 类：原生 Skills 支持（直接安装）

| 工具 | Skills 机制 | 生态规模 |
|------|------------|---------|
| **Claude Code**（Anthropic） | `.claude/skills/` + `SKILL.md` | 官方支持，本项目主平台 |
| **OpenClaw** | `~/.openclaw/skills/` + `SKILL.md` | ClawHub 公共注册表，13,729+ 社区 Skills |

> 两者 Skills 格式高度相似（均为 `SKILL.md` + `scripts/` + `data/`），同一份 Skill 可同时兼容两个平台。

### B 类：等效概念支持（适配安装）

| 工具 | 等效概念 | 配置路径 | 适配难度 |
|------|---------|---------|---------|
| **OpenCode**（SST） | Commands（Markdown 文件） | `~/.config/opencode/commands/` | 低（转换 SKILL.md → command .md） |
| **Cursor** | Rules（.mdc 文件） | `.cursor/rules/` | 中（需转换格式） |
| **Windsurf**（Codeium） | Rules + Memories | `.windsurf/rules/` | 中（需转换格式） |
| **Goose**（Block/AAIF） | Extensions/Tools | `~/.config/goose/config.yaml` | 高（需实现扩展接口） |

### C 类：无直接对应概念（仅路径参考）

| 工具 | 特点 | 主要配置路径 |
|------|------|------------|
| **Codex CLI**（OpenAI） | 配置驱动，无插件体系 | `~/.codex/config.toml` |
| **Aider** | 基于 `.aider.conf.yml`，无 Skills | `~/.aider.conf.yml` |

---

## 2. 各工具路径详查

### 2.1 Claude Code（Anthropic）

**Skills 目录（双层）：**

```
全局 Skills（用户级，所有项目可用）
  macOS / Linux : ~/.claude/skills/<skill-name>/
  Windows       : %USERPROFILE%\.claude\skills\<skill-name>\

项目 Skills（仓库级，随代码库共享）
  macOS / Linux : <project>/.claude/skills/<skill-name>/
  Windows       : <project>\.claude\skills\<skill-name>\
```

**Skills 结构要求：**

```
<skill-name>/
├── SKILL.md          必填，Skill 元信息（name/description/frontmatter）
├── scripts/          可选，Python 脚本
└── data/             可选，数据文件（VERSION.json / CSV 等）
```

**其他配置路径：**

```
~/.claude/settings.json           用户全局设置
~/.claude/CLAUDE.md               全局指令文件
<project>/.claude/settings.json   项目设置
<project>/.claude/CLAUDE.md       项目指令文件
```

---

### 2.2 OpenClaw

**Skills 多级目录（优先级从高到低）：**

```
Level 1  工作区级（仅当前 Agent 可见）
  macOS / Linux : <workspace>/skills/<skill-name>/
  Windows       : <workspace>\skills\<skill-name>\

Level 2  Agent 共享级
  macOS / Linux : <workspace>/.agents/skills/<skill-name>/
  Windows       : <workspace>\.agents\skills\<skill-name>\

Level 3  全局托管级（用户所有项目可见）
  macOS / Linux : ~/.openclaw/skills/<skill-name>/
  Windows       : %USERPROFILE%\.openclaw\skills\<skill-name>\

Level 4  内置（只读，随 OpenClaw 发布）
```

**额外目录配置：**

```json
// ~/.openclaw/openclaw.json
{
  "skills": {
    "load": {
      "extraDirs": ["/path/to/custom/skills"]
    }
  }
}
```

**主配置路径：**

```
macOS / Linux : ~/.openclaw/openclaw.json
Windows       : %USERPROFILE%\.openclaw\openclaw.json
```

**ClawHub 公共注册表：** `https://clawhub.com`（13,729+ 社区 Skills）

---

### 2.3 OpenCode（SST）

OpenCode 无原生 Skills 概念，但支持自定义 **Commands**（Markdown 文件），行为与 Skills 相似。

**Commands 目录：**

```
全局 Commands
  macOS / Linux : ~/.config/opencode/commands/
  Windows       : %APPDATA%\opencode\commands\
                  （注：部分版本使用 %USERPROFILE%\.config\opencode\commands\）

项目 Commands
  macOS / Linux : <project>/opencode.json  （commands 字段）
  Windows       : <project>\opencode.json
```

**主配置路径：**

```
macOS / Linux : ~/.config/opencode/opencode.json
Windows       : %APPDATA%\opencode\opencode.json
              （可通过 OPENCODE_CONFIG_DIR 环境变量覆盖）
```

> **Windows 注意：** OpenCode 在 Windows 上存在路径实现不一致问题，部分插件使用 `%APPDATA%`，主程序使用 `%USERPROFILE%\.config`。建议检测时两个路径均尝试。

---

### 2.4 Codex CLI（OpenAI）

无 Skills 概念，仅提供配置文件驱动的行为定制。

**主配置路径：**

```
macOS / Linux : ~/.codex/config.toml
Windows       : %USERPROFILE%\.codex\config.toml
              （Windows 支持仍为实验性，官方推荐使用 WSL2）
```

**项目配置：**

```
<project>/.codex/config.toml
```

---

### 2.5 Cursor

Cursor 使用 **Rules**（`.mdc` 文件）而非 Skills，但功能层面有一定重叠（为 AI 提供上下文和行为指引）。

**Rules 目录：**

```
项目级 Rules（版本控制，随仓库共享）
  macOS / Linux : <project>/.cursor/rules/
  Windows       : <project>\.cursor\rules\
  文件格式: *.mdc（Markdown with frontmatter）

子目录级 Rules（作用域限定）
  macOS / Linux : <project>/<subdir>/.cursor/rules/
  Windows       : <project>\<subdir>\.cursor\rules\
```

**全局 Rules：** 在 Cursor 设置界面配置（Settings → General → Rules for AI），不对应具体文件路径，存储在应用内部配置中。

> **与 Skills 的差异：** Cursor Rules 是纯文本/Markdown 指令，不支持可执行脚本（无 scripts/ 目录）。Skills 的可执行部分（Python 脚本）无法在 Cursor 中直接运行。

---

### 2.6 Windsurf（Codeium）

**Rules 目录（Wave 8+）：**

```
项目级 Rules
  macOS / Linux : <project>/.windsurf/rules/
  Windows       : <project>\.windsurf\rules\
  文件格式: *.md

全局 Rules / Memories
  macOS / Linux : ~/.codeium/windsurf/memories/global_rules.md
  Windows       : %USERPROFILE%\.codeium\windsurf\memories\global_rules.md
```

**MCP 配置路径：**

```
macOS / Linux : ~/.codeium/windsurf/mcp_config.json
Windows       : %USERPROFILE%\.codeium\windsurf\mcp_config.json
```

**全局忽略规则：**

```
~/.codeium/.codeiumignore  （macOS / Linux）
%USERPROFILE%\.codeium\.codeiumignore  （Windows）
```

---

### 2.7 Goose（Block / AAIF-Linux Foundation）

Goose 使用 **Extensions** 概念，提供工具能力扩展，与 Skills 的定位接近但实现差异较大。

**主配置路径：**

```
macOS / Linux : ~/.config/goose/config.yaml
Windows       : %USERPROFILE%\.config\goose\config.yaml
```

**Extensions 配置方式：** 在 `config.yaml` 的 `extensions` 键下声明，无独立目录结构。

```yaml
# ~/.config/goose/config.yaml 示例
extensions:
  - name: my-extension
    cmd: python3
    args: ["/path/to/extension.py"]
```

---

### 2.8 Aider

Aider 无 Skills / Rules 概念，完全基于配置文件驱动。

**配置文件（按优先级）：**

```
当前目录  : .aider.conf.yml
Git 根目录 : .aider.conf.yml
用户主目录 : ~/.aider.conf.yml
             Windows: %USERPROFILE%\.aider.conf.yml
```

---

## 3. 跨平台路径矩阵

### 3.1 全局 Skills / 等效目录

| 工具 | macOS / Linux | Windows |
|------|--------------|---------|
| Claude Code | `~/.claude/skills/` | `%USERPROFILE%\.claude\skills\` |
| OpenClaw | `~/.openclaw/skills/` | `%USERPROFILE%\.openclaw\skills\` |
| OpenCode | `~/.config/opencode/commands/` | `%APPDATA%\opencode\commands\` |
| Codex CLI | `~/.codex/` | `%USERPROFILE%\.codex\` |
| Windsurf | `~/.codeium/windsurf/memories/` | `%USERPROFILE%\.codeium\windsurf\memories\` |
| Goose | `~/.config/goose/` | `%USERPROFILE%\.config\goose\` |
| Aider | `~/` | `%USERPROFILE%\` |

### 3.2 项目级 Skills / 等效目录

| 工具 | 路径（跨平台相对于项目根） | 文件格式 |
|------|------------------------|---------|
| Claude Code | `.claude/skills/<name>/` | SKILL.md + scripts/ + data/ |
| OpenClaw | `skills/<name>/` 或 `.agents/skills/<name>/` | SKILL.md + scripts/ + data/ |
| OpenCode | `opencode.json`（commands 字段） | Markdown 文本 |
| Cursor | `.cursor/rules/` | *.mdc |
| Windsurf | `.windsurf/rules/` | *.md |

### 3.3 工具检测特征文件

`opscli` 通过检测以下特征文件/目录判断工具是否安装：

| 工具 | macOS 检测路径 | Windows 检测路径 |
|------|--------------|----------------|
| Claude Code | `~/.claude/` 或 `which claude` | `%USERPROFILE%\.claude\` |
| OpenClaw | `~/.openclaw/` 或 `which openclaw` | `%USERPROFILE%\.openclaw\` |
| OpenCode | `~/.config/opencode/` 或 `which opencode` | `%APPDATA%\opencode\` |
| Codex CLI | `~/.codex/` 或 `which codex` | `%USERPROFILE%\.codex\` |
| Cursor | `/Applications/Cursor.app` | `%LOCALAPPDATA%\Programs\cursor\Cursor.exe` |
| Windsurf | `/Applications/Windsurf.app` | `%LOCALAPPDATA%\Programs\windsurf\Windsurf.exe` |
| Goose | `~/.config/goose/` 或 `which goose` | `%USERPROFILE%\.config\goose\` |

---

## 4. opscli 多工具支持设计

### 4.1 安装目标分级

```
┌─────────────────────────────────────────────────────────────────┐
│                    Skill 安装目标分级                             │
│                                                                 │
│  Tier 1  直接安装（原生 Skills，格式完全兼容）                      │
│          • Claude Code  →  ~/.claude/skills/<name>/             │
│          • OpenClaw     →  ~/.openclaw/skills/<name>/           │
│                                                                 │
│  Tier 2  适配安装（等效概念，需格式转换）                           │
│          • OpenCode     →  SKILL.md → command .md               │
│          • Cursor       →  SKILL.md 描述 → .cursor/rules/*.mdc  │
│          • Windsurf     →  SKILL.md 描述 → .windsurf/rules/*.md │
│                                                                 │
│  Tier 3  仅参考（无原生支持，仅文档提示）                           │
│          • Codex CLI / Aider / Goose                            │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 命令扩展设计

在现有命令基础上新增 `--target` 参数：

```bash
# 升级所有检测到的工具中的 dataset-fields Skill
opscli skills upgrade dataset-fields

# 指定目标工具
opscli skills upgrade dataset-fields --target claude-code
opscli skills upgrade dataset-fields --target openclaw
opscli skills upgrade dataset-fields --target all        # 所有已检测工具

# 安装到指定目录（手动覆盖）
opscli skills install dataset-fields --skills-dir /custom/path

# 查看各工具的 Skill 安装状态
opscli skills list --all-tools

# 初始化新工具的 Skill 目录
opscli skills init --target windsurf   # 生成 .windsurf/rules/ 适配文件
```

### 4.3 新增命令：skills install

```bash
opscli skills install <skill-name>              # 安装到所有已检测工具
opscli skills install <skill-name> --target claude-code
opscli skills install <skill-name> --from-hub  # 从 ClawHub 或内部注册表安装
```

### 4.4 多工具升级输出示例

```
$ opscli skills upgrade

检测到已安装的工具：
  ✓ Claude Code   ~/.claude/
  ✓ OpenClaw      ~/.openclaw/
  ✗ OpenCode      未检测到
  ✗ Cursor        未检测到

dataset-fields Skill 状态：
  Claude Code  [本地 v0.1.0 → 远端 v0.1.2]  ✦ 需要更新
  OpenClaw     [本地 v0.1.2 = 远端 v0.1.2]  ✓ 已是最新

正在更新 Claude Code / dataset-fields (v0.1.0 → v0.1.2)...
  下载 dataset_fields_v0.1.2.csv [████████████] ✓

更新完成：1 个更新，1 个已是最新。
```

---

## 5. 工具检测与自动发现

### 5.1 检测逻辑（Python 实现骨架）

```python
import os
import shutil
from pathlib import Path
from dataclasses import dataclass

@dataclass
class ToolInfo:
    name: str
    tier: int               # 1=原生, 2=适配, 3=仅参考
    skills_dir: Path | None # Skill 安装目录（None 表示不支持）
    detected: bool

class ToolDetector:
    def detect_all(self) -> list[ToolInfo]:
        return [
            self._detect_claude_code(),
            self._detect_openclaw(),
            self._detect_opencode(),
            self._detect_cursor(),
            self._detect_windsurf(),
        ]

    def _detect_claude_code(self) -> ToolInfo:
        home = Path.home()
        config_dir = home / ".claude"
        detected = config_dir.exists() or shutil.which("claude") is not None
        return ToolInfo(
            name="claude-code",
            tier=1,
            skills_dir=config_dir / "skills" if detected else None,
            detected=detected,
        )

    def _detect_openclaw(self) -> ToolInfo:
        home = Path.home()
        config_dir = home / ".openclaw"
        detected = config_dir.exists() or shutil.which("openclaw") is not None
        return ToolInfo(
            name="openclaw",
            tier=1,
            skills_dir=config_dir / "skills" if detected else None,
            detected=detected,
        )

    def _detect_opencode(self) -> ToolInfo:
        # macOS/Linux: ~/.config/opencode/  Windows: %APPDATA%\opencode\
        candidates = [
            Path.home() / ".config" / "opencode",
            Path(os.environ.get("APPDATA", "")) / "opencode",
        ]
        config_dir = next((p for p in candidates if p.exists()), None)
        detected = config_dir is not None or shutil.which("opencode") is not None
        commands_dir = config_dir / "commands" if config_dir else None
        return ToolInfo(
            name="opencode",
            tier=2,
            skills_dir=commands_dir,
            detected=detected,
        )

    def _detect_cursor(self) -> ToolInfo:
        if os.name == "nt":
            app_path = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "cursor" / "Cursor.exe"
        else:
            app_path = Path("/Applications/Cursor.app")
        detected = app_path.exists() or shutil.which("cursor") is not None
        # Cursor Rules 是项目级的，全局安装到用户目录无意义，返回 None
        return ToolInfo(name="cursor", tier=2, skills_dir=None, detected=detected)

    def _detect_windsurf(self) -> ToolInfo:
        home = Path.home()
        config_dir = home / ".codeium" / "windsurf"
        if os.name == "nt":
            app_path = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "windsurf" / "Windsurf.exe"
        else:
            app_path = Path("/Applications/Windsurf.app")
        detected = config_dir.exists() or app_path.exists()
        return ToolInfo(
            name="windsurf",
            tier=2,
            skills_dir=config_dir / "memories" if detected else None,
            detected=detected,
        )
```

### 5.2 跨平台路径解析工具函数

```python
def get_skills_dir(tool: str, scope: str = "global") -> Path:
    """
    获取指定工具的 Skills 目录。
    scope: "global"（用户级）| "project"（需传入 project_root）
    """
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home))  # Windows %APPDATA%

    dirs = {
        "claude-code": {
            "global":  home / ".claude" / "skills",
            "project": Path(".claude") / "skills",
        },
        "openclaw": {
            "global":  home / ".openclaw" / "skills",
            "project": Path("skills"),
        },
        "opencode": {
            "global":  (appdata if os.name == "nt" else home / ".config") / "opencode" / "commands",
            "project": Path("opencode.json"),   # 需写入 JSON 而非目录
        },
        "windsurf": {
            "global":  home / ".codeium" / "windsurf" / "memories",
            "project": Path(".windsurf") / "rules",
        },
    }
    return dirs.get(tool, {}).get(scope)
```

---

## 6. 实现规划

### 6.1 分阶段实现

**Phase 1（当前已完成）：Claude Code 单工具**
- Skill 目录：`.claude/skills/`
- 更新机制：Layer 1 自动 + Layer 3 直接脚本

**Phase 2（下一步）：opscli + 多工具自动发现**
- 实现 `SkillsManager` 含 `ToolDetector`
- 支持 Claude Code + OpenClaw（Tier 1 原生）
- 命令：`opscli skills list/status/upgrade/install`

**Phase 3（后续）：Tier 2 工具适配**
- OpenCode：`SKILL.md` → `commands/*.md` 格式转换
- Cursor：`SKILL.md` 描述提取 → `.cursor/rules/*.mdc`
- Windsurf：`SKILL.md` 描述提取 → `.windsurf/rules/*.md`

### 6.2 格式兼容性分析

| Skills 文件 | Claude Code | OpenClaw | OpenCode | Cursor | Windsurf |
|------------|:-----------:|:--------:|:--------:|:------:|:--------:|
| `SKILL.md` | ✅ 原生 | ✅ 原生 | 🔄 转换 | 🔄 提取描述 | 🔄 提取描述 |
| `scripts/*.py` | ✅ 执行 | ✅ 执行 | ❌ 不支持 | ❌ 不支持 | ❌ 不支持 |
| `data/*.csv` | ✅ 原生 | ✅ 原生 | ❌ 不感知 | ❌ 不感知 | ❌ 不感知 |

> **结论：** 带可执行脚本的 Skills（如 `dataset-fields`）在 Tier 2 工具中只能注入描述性文档，无法运行 Python 搜索逻辑。Tier 1（Claude Code / OpenClaw）是完整 Skill 体验的目标平台。

### 6.3 工作量估算

| 阶段 | 主要工作 | 估算工时 |
|------|---------|---------|
| Phase 2 核心 | ToolDetector + SkillsManager + opscli commands | 2~3 天 |
| Phase 2 测试 | macOS + Windows 路径验证 | 1 天 |
| Phase 3 适配器 | OpenCode / Cursor / Windsurf 格式转换器各一个 | 各 0.5 天 |

---

## 附录：Skills 安装路径速查表

| 工具 | 全局路径（macOS/Linux） | 全局路径（Windows） | 原生支持 |
|------|----------------------|-------------------|---------|
| Claude Code | `~/.claude/skills/` | `%USERPROFILE%\.claude\skills\` | ✅ Tier 1 |
| OpenClaw | `~/.openclaw/skills/` | `%USERPROFILE%\.openclaw\skills\` | ✅ Tier 1 |
| OpenCode | `~/.config/opencode/commands/` | `%APPDATA%\opencode\commands\` | 🔄 Tier 2 |
| Cursor | 无全局目录（项目级：`.cursor/rules/`） | 同左 | 🔄 Tier 2 |
| Windsurf | `~/.codeium/windsurf/memories/` | `%USERPROFILE%\.codeium\windsurf\memories\` | 🔄 Tier 2 |
| Goose | `~/.config/goose/` | `%USERPROFILE%\.config\goose\` | ❌ Tier 3 |
| Codex CLI | `~/.codex/` | `%USERPROFILE%\.codex\` | ❌ Tier 3 |
| Aider | `~/` | `%USERPROFILE%\` | ❌ Tier 3 |

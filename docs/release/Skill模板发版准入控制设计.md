# Skill 模板发版准入控制设计

> 文档状态：规划设计
> 创建时间：2026-05-08
> 适用范围：`opscli/skills/templates` 内置 Skill 模板随 `aukeys-opscli` 发版时的准入控制。

## 1. 背景

当前 `opscli/skills/templates` 下的所有 Skill 模板都会被无差别打入发布产物：

- `MANIFEST.in` 使用 `recursive-include opscli/skills/templates *` 将所有模板纳入 sdist。
- `setup.py` 的 `package_data` 使用 `skills/templates/**/*` 将所有模板纳入 wheel。
- `SkillsManager.list_templates()` 与 `SkillsManager.install()` 直接扫描运行时包内的 `opscli/skills/templates` 目录。

这意味着只要模板目录存在，就会同时具备两个效果：

1. 随包发布给用户。
2. 在 `opscli skills install` 中变成可安装项。

随着模板数量增加，部分 Skill 可能处于实验、内部、二进制不适配或暂不希望公开安装的阶段，因此需要把“仓库中存在”与“允许进入某类发布物”拆开。

## 2. 目标

本设计要解决以下问题：

1. 控制哪些 Skill 可以进入常规 Python 包发版。
2. 控制哪些 Skill 可以进入二进制应用包发版。
3. 保持本地开发时仍能看到全部模板，便于调试和迭代。
4. 让发版准入规则可审计、可测试、可在 CI 中复用。
5. 避免在 `MANIFEST.in`、`setup.py`、CI workflow、二进制 spec 文件中各写一套互相漂移的白名单。

## 3. 发版类型定义

### 3.1 直接发版

这里的“直接发版”指当前 PyPI / 私有 PyPI 发行链路：

- sdist：`python -m build --sdist`
- wheel：`cibuildwheel` 构建的 Cython 二进制 wheel
- 用户安装方式：`pip install aukeys-opscli`

虽然 wheel 内业务代码会被 Cython 编译，但 Skill 模板文件仍作为包数据原样携带。因此直接发版需要控制的是“哪些模板目录可以进入 Python 包数据”。

### 3.2 打包二进制发版

这里的“打包二进制发版”指未来或独立链路中，将 CLI 打成可执行应用的方式，例如：

- PyInstaller
- Nuitka
- Briefcase / cx_Freeze
- 内部分发的单文件或目录式二进制包

二进制发版需要控制的是“哪些模板目录作为 data files 被收集进可执行应用”。它和直接发版不能默认共用同一名单，因为二进制包更关注体积、离线可用性、平台依赖和脚本可执行性。

## 4. 总体方案

引入一个单一来源的 Skill 发版清单：

```text
opscli/skills/templates/manifest.json
```

该清单只负责声明每个 Skill 的发布准入、默认渠道和原因。构建脚本、运行时代码和 CI 都从这个文件读取规则。

推荐字段：

```json
{
  "version": 1,
  "default": {
    "source": true,
    "wheel": true,
    "binary": false
  },
  "skills": {
    "ops-auth": {
      "source": true,
      "wheel": true,
      "binary": true,
      "tier": "core",
      "reason": "认证基础能力，所有发行形态都需要"
    },
    "ops-dataset-query": {
      "source": true,
      "wheel": true,
      "binary": false,
      "tier": "core",
      "reason": "数据文件可远端升级，二进制包默认不内置大体积数据"
    },
    "ops-feedback": {
      "source": false,
      "wheel": false,
      "binary": false,
      "tier": "internal",
      "reason": "内部规则注入能力，暂不随公开包发版"
    }
  }
}
```

字段含义：

| 字段 | 含义 |
|------|------|
| `source` | 是否进入 sdist |
| `wheel` | 是否进入 wheel |
| `binary` | 是否进入二进制应用包 |
| `tier` | `core` / `ops` / `experimental` / `internal` 等治理标签 |
| `reason` | 准入或排除原因，供 review 和发版检查使用 |

## 5. 推荐首版准入策略

首版建议采用保守白名单，而不是黑名单。

### 5.1 直接发版默认纳入

建议直接发版纳入稳定、低风险、与 CLI 基础体验相关的 Skill：

| Skill | sdist | wheel | 理由 |
|------|-------|-------|------|
| `ops-auth` | 是 | 是 | 认证基础能力 |
| `ops-skills` | 是 | 是 | Skill 生命周期基础能力 |
| `ops-mcp` | 是 | 是 | MCP 接入说明，与 CLI 能力强相关 |
| `ops-dataset-query` | 是 | 是 | query 模块依赖本地模板数据兜底 |
| `ops-amazon` | 是 | 是 | 已有正式 CLI/MCP 工作流 |
| `ops-amazon-rufus` | 是 | 是 | 已有远端升级逻辑与测试覆盖 |

### 5.2 直接发版暂缓纳入

以下 Skill 建议先暂缓进入直接发版，等接口、依赖、数据权限、使用边界稳定后再打开：

| Skill | sdist | wheel | 理由 |
|------|-------|-------|------|
| `ops-feedback` | 否 | 否 | 会注入工具侧规则，内部治理属性更强 |
| `ops-seller-sprite` | 否 | 否 | 依赖浏览器自动化和外部站点登录态 |
| `ops-amazon-listing-analysis` | 否 | 否 | 分析口径仍适合先内部验证 |
| `ops-asin-health-diagnoser` | 否 | 否 | 强依赖内部数据口径与诊断阈值 |
| `ops-product-attribute-analyzer` | 否 | 否 | 强依赖内部数据口径和属性体系 |

### 5.3 二进制发版默认纳入

二进制包建议更小，只纳入离线启动和基础安装需要的 Skill：

| Skill | binary | 理由 |
|------|--------|------|
| `ops-auth` | 是 | 登录与 Token 管理基础能力 |
| `ops-skills` | 是 | 允许用户后续按需安装或升级 Skill |
| `ops-mcp` | 是 | MCP 接入说明小且基础 |

`ops-dataset-query` 是否纳入二进制包建议单独决策。它目前约 564K，不算特别大，但包含可远端升级的数据缓存；若二进制包定位为“最小离线 CLI”，则不内置；若定位为“拿到即可查基础数据”，则可以进入 `binary-full` profile。

## 6. 构建 Profile

建议不要只有一个名单，而是支持 profile：

| Profile | 用途 | 典型包含 |
|---------|------|----------|
| `dev` | 本地开发 | 全部模板 |
| `python-release` | PyPI / 私有 PyPI 直接发版 | `source=true` 或 `wheel=true` 的模板 |
| `binary-minimal` | 最小二进制包 | `binary=true` 的核心模板 |
| `binary-full` | 完整二进制包 | 核心模板 + 数据查询等常用模板 |
| `internal` | 内部分发 | 包含 internal / experimental |

环境变量可以作为构建入口：

```bash
OPSCLI_SKILL_PROFILE=python-release python -m build
OPSCLI_SKILL_PROFILE=binary-minimal pyinstaller opscli.spec
OPSCLI_SKILL_PROFILE=internal python -m build
```

若未设置：

- 本地 editable 安装默认 `dev`。
- CI 发版默认 `python-release`。
- 二进制打包默认必须显式传入 profile，避免误打全量模板。

## 7. 直接发版落地设计

直接发版需要改造三处：

### 7.1 构建前生成临时模板目录

新增脚本：

```text
scripts/prepare_skill_templates.py
```

职责：

1. 读取 `opscli/skills/templates/manifest.json`。
2. 根据 `OPSCLI_SKILL_PROFILE`、产物类型和 allowlist 生成临时目录。
3. 将准入 Skill 复制到例如 `build/skill-templates/<profile>/`。
4. 输出构建摘要，包含 included / excluded / reasons。

### 7.2 setup.py 使用筛选后的模板

`setup.py` 中不要再直接把 `opscli/skills/templates/**/*` 全量打包。推荐两种实现方式：

1. 构建时把筛选后的模板复制回 `build/lib/opscli/skills/templates`。
2. 自定义 `build_py`，在 `run()` 阶段根据 manifest 删除不准入的模板目录。

首版建议选择第 2 种，改动范围小，也不改变 `SkillsManager` 的运行时目录约定。

### 7.3 MANIFEST.in 保持粗粒度，sdist 阶段二次裁剪

`MANIFEST.in` 本身不适合表达动态 profile。可以先保留粗粒度 include，然后在自定义 `sdist` command 中按照 manifest 从 filelist 移除不准入模板。

关键原则：

- 不在 `MANIFEST.in` 硬编码每个 Skill 的排除项。
- 不让 sdist 和 wheel 各自维护不同白名单。
- CI 必须校验最终产物内容，而不只校验清单。

## 8. 二进制发版落地设计

二进制发版应该复用同一个 manifest，但收集方式独立于 setuptools。

### 8.1 新增统一收集 API

新增模块：

```text
opscli/skills/packaging.py
```

提供函数：

```python
def select_skill_templates(profile: str, artifact: str) -> list[Path]:
    ...
```

`artifact` 可取：

- `sdist`
- `wheel`
- `binary`

该函数既供 `setup.py` 使用，也供 PyInstaller / Nuitka 打包脚本使用。

### 8.2 PyInstaller 示例

二进制 spec 中只收集准入模板：

```python
from opscli.skills.packaging import collect_skill_datas

datas = collect_skill_datas(profile="binary-minimal")
```

输出结构仍保持：

```text
opscli/skills/templates/<skill-name>/...
```

这样 `SkillsManager` 不需要知道自己运行在 wheel 还是二进制应用里。

### 8.3 二进制运行时注意事项

如果使用 PyInstaller onefile，模板目录运行时可能位于 `_MEIPASS`。因此 `SkillsManager.templates_dir` 不能只依赖 `Path(__file__).parent.parent / "templates"`，需要抽象成：

```python
def get_builtin_templates_dir() -> Path:
    ...
```

解析优先级：

1. 环境变量 `OPSCLI_BUILTIN_TEMPLATES_DIR`，用于测试和特殊部署。
2. PyInstaller `_MEIPASS/opscli/skills/templates`。
3. 普通 Python 包内 `opscli/skills/templates`。

## 9. 运行时行为

构建后的包里没有的 Skill，不应该在 `opscli skills install` 中出现。

推荐行为：

- `opscli skills install` 交互模式只显示当前发布物内实际存在的模板。
- `opscli skills install <name>` 如果模板不存在，报错中增加提示：
  - 当前发行包未包含该 Skill。
  - 如需使用，请安装 internal/full 发行包，或等待该 Skill 开放。
- `opscli skills list` 不受影响，它列出的是用户已安装到全局目录的 Skill。
- `opscli skills upgrade <name>` 只允许升级已支持远端升级的 Skill，不依赖内置模板是否存在。

## 10. CI 与质量门禁

新增发版前检查：

```bash
python scripts/check_skill_release_manifest.py --profile python-release --artifact wheel
python scripts/check_skill_release_manifest.py --profile python-release --artifact sdist
```

检查项：

1. 每个 `opscli/skills/templates/<name>` 都必须在 manifest 中声明，禁止新增目录后默认混入发版。
2. `source/wheel/binary=false` 的 Skill 不得出现在对应产物里。
3. `source/wheel/binary=true` 的 Skill 必须包含 `SKILL.md` 和 `data/VERSION.json`。
4. `reason` 必填，方便 release review。
5. `ops-dataset-query` 若被纳入直接发版，必须保留 query 模块依赖的 `data/query_metadata.json` 等文件。

发布产物校验：

```bash
python scripts/inspect_dist_skills.py dist/*.whl
python scripts/inspect_dist_skills.py dist/*.tar.gz
```

输出示例：

```text
artifact: aukeys_opscli-0.0.38-*.whl
included skills:
  - ops-auth
  - ops-skills
  - ops-mcp
  - ops-dataset-query
excluded by profile:
  - ops-feedback: internal governance
  - ops-seller-sprite: browser automation dependency
```

## 11. 分阶段实施建议

### 第一阶段：只做可观测与门禁

1. 新增 `manifest.json`。
2. 新增检查脚本，CI 中只校验声明完整性。
3. 暂不改变实际打包内容。

价值：先让团队明确每个 Skill 的发版状态，避免无主目录继续增加。

### 第二阶段：控制直接发版

1. 改造 `setup.py` / `sdist`，按 manifest 裁剪模板。
2. 更新 GitHub Actions，设置 `OPSCLI_SKILL_PROFILE=python-release`。
3. 更新 `scripts/release_preflight.py`，安装 wheel 后检查 `opscli skills install` 可见项。

价值：解决当前 PyPI / wheel 发版的核心问题。

### 第三阶段：控制二进制发版

1. 新增 `opscli/skills/packaging.py`。
2. 二进制 spec 统一调用该模块收集 data files。
3. 处理 PyInstaller `_MEIPASS` 运行时模板路径。

价值：为后续二进制分发预留稳定机制，避免二进制链路再次全量打包。

### 第四阶段：发行物分层

1. 支持 `binary-minimal`、`binary-full`、`internal` profile。
2. 在 release 文档中明确不同分发包名称、下载渠道和包含 Skill。
3. 对内部 Skill 建立独立验收流程。

## 12. 需要避免的做法

1. 不建议直接删除 `opscli/skills/templates` 下暂不发版的目录。这样会破坏本地开发和历史演进记录。
2. 不建议只在 `MANIFEST.in` 写 `recursive-exclude`。它只能影响 sdist，wheel 和二进制链路容易漏掉。
3. 不建议只在 `setup.py package_data` 写白名单。sdist、CI、二进制链路仍会漂移。
4. 不建议用 `.gitignore` 或目录命名如 `_draft` 表达发版状态。发版状态应显式、可审计。
5. 不建议直接把“是否可安装”写死在 `SkillsManager.install()` 中。当前发布物实际携带哪些模板，应该由构建准入决定。

## 13. 当前仓库建议结论

现阶段推荐路线：

1. 先新增 `opscli/skills/templates/manifest.json`，作为单一准入来源。
2. 第一版 profile 只启用 `python-release` 和 `binary-minimal`。
3. 直接发版首批保留 `ops-auth`、`ops-skills`、`ops-mcp`、`ops-dataset-query`、`ops-amazon`、`ops-amazon-rufus`。
4. 二进制发版首批只保留 `ops-auth`、`ops-skills`、`ops-mcp`；如业务需要，再新增 `binary-full` 纳入 `ops-dataset-query`。
5. 先在 preflight 中做 manifest 检查和产物检查，再切换为真实裁剪，降低发版风险。


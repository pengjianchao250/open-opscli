# opscli Skills 发布链路调研

## 结论

`opscli` 中“发布项目中的技能”实际包含三条不同链路：

1. 内置模板随 `aukeys-opscli` 包发布：仓库内 `opscli/skills/templates/ops-*` 通过构建产物进入 wheel/sdist，用户再用 `opscli skills install <name>` 安装。
2. 技能广场发布：本地 Skill 目录通过 `opscli skills publish` 打包成 zip 上传到后端广场，其他用户通过 `username@skill_name` 安装。
3. 远端数据升级：少数内置 Skill 只把基础模板随包发布，数据文件通过 `opscli skills upgrade` 从业务接口拉取刷新。

这三个“发布”对象不同：包发布发布的是模板文件，广场发布发布的是用户可共享的 Skill zip，远端升级发布的是业务数据快照。

## CLI 入口

顶级入口在 `opscli/cli.py` 注册：

```python
from opscli.skills.cli import app as skills_app
app.add_typer(skills_app, name="skills")
```

`opscli/skills/cli.py` 只是兼容导出，真实命令定义在 `opscli/skills/commands/cli.py`。

主要命令：

- `opscli skills install [NAME|IDENTIFIER]`：安装包内模板或广场远程技能。
- `opscli skills publish`：发布本地目录到技能广场。
- `opscli skills edit <identifier>`：编辑已发布技能元数据，可选重传 zip/md。
- `opscli skills unpublish <identifier>`：下架广场技能，服务端软删除。
- `opscli skills marketplace *`：浏览、搜索、查看版本、评分。
- `opscli skills status/upgrade`：查看和升级已安装 Skill，主要面向远端数据更新。

## 内置模板随包发布

内置模板来源：

- `opscli/skills/templates/<skill-name>/SKILL.md`
- `opscli/skills/templates/<skill-name>/data/VERSION.json`
- 可选 `references/`、`scripts/`、数据文件等。

构建准入单一来源：

- `opscli/skills/templates/manifest.json`
- `opscli/skills/packaging.py`

当前准入逻辑：

- `selected_skill_names(profile, artifact)` 按 `source/wheel/binary/binary_full` 选择可进入产物的 Skill。
- `prune_templates_dir()` 删除不允许进入目标产物的模板目录。
- `validate_release_manifest()` 校验每个模板目录都在 manifest 声明，且准入模板包含 `SKILL.md` 和 `data/VERSION.json`。

构建接入：

- `setup.py` 的 `BuildPyPruneSkillTemplates` 在 wheel 构建后裁剪 `build_lib/opscli/skills/templates`。
- `setup.py` 的 `SdistPruneSkillTemplates` 在 sdist release tree 中裁剪模板。
- `MANIFEST.in` 仍粗粒度包含 `opscli/skills/templates *`，最终由 setup 自定义命令裁剪。
- CI 在 `.github/workflows/build-and-publish.yml` 中设置 `OPSCLI_SKILL_PROFILE=python-release` 并运行 `scripts/check_skill_release_manifest.py` 检查 wheel/sdist。

用户安装内置模板流程：

1. `SkillsManager.install()` 在当前发行包的 `templates` 目录寻找模板。
2. 未传 `--skills-dir` 时复制到中央存储 `~/.opscli/skills/<name>` 或 Windows `%LOCALAPPDATA%/opscli/skills/<name>`。
3. 再链接到检测到的 AI 工具目录，如 `~/.claude/skills`、`~/.codex/skills`、`~/.agents/skills`。
4. 显式传 `--skills-dir` 时走旧复制模式，直接复制到目标目录。

## 技能广场发布

`opscli skills publish` 位于 `opscli/skills/commands/cli.py`。

发布前置条件：

- 目标目录必须包含 `SKILL.md`。
- 目标目录必须包含 `data/VERSION.json`。
- `VERSION.json` 的 `name` 不能为空。
- `VERSION.json` 的版本会去掉 `v` 前缀后上传。
- 如果 `SKILL.md` frontmatter 中也声明了 `version`，必须与 `VERSION.json` 一致。

元数据来源优先级：

1. CLI 参数：`--title`、`--summary`、`--desc`、`--tags`、`--category`、`--share-type`。
2. `SKILL.md` frontmatter：`title`、`description`、`summary`、`tags`、`category_id`、`share_type`。
3. 默认值：标题为 `skill_name`，分享范围为 `personal`。

发布流程：

1. `_read_skill_file()` 读取 `SKILL.md` 和 `data/VERSION.json`。
2. `_parse_skill_md_frontmatter()` 解析元数据。
3. 若未指定分类，调用 `MarketplaceClient.get_categories()` 后用 `_match_best_category()` 自动匹配分类。
4. `_zip_skill_dir()` 将整个 Skill 目录打成临时 zip，排除 `__pycache__`、`*.pyc`、`*.pyo`。
5. `MarketplaceClient.get_my_skill_by_name(skill_name)` 判断当前用户是否已经发布过同名技能。
6. 首次发布调用 `POST /v1/skills`，即 `MarketplaceClient.create_skill()`。
7. 已存在时调用 `POST /v1/skills/{id}`，即 `MarketplaceClient.full_update_skill()`，同时更新元数据、上传文件、创建新版本。
8. 临时 zip 在 finally 中删除。

分享范围：

- `personal`：仅自己可见，默认值。
- `department`：部门可见，可传 `--depts`。
- `company`：全公司可见。

下架流程：

1. `opscli skills unpublish username@skill_name` 解析 identifier。
2. 未传 `--force` 且非 JSON 模式时要求交互确认。
3. `get_by_identifier()` 获取 skill id。
4. `delete_skill()` 调用 `DELETE /v1/skills/{id}`。
5. 说明下架不影响已经安装到本地的用户。

## 广场远程安装

当 `opscli skills install` 的 `name` 包含 `@` 时走远程安装：

1. `install_remote_skill()` 解析 `username@skill_name`。
2. `get_by_identifier()` 获取技能元数据，可透传 `--share-code`。
3. `get_download_url()` 获取下载地址。
4. 下载 zip/md 文件。
5. `_build_skill_dir()` 解压到中央存储并确保写入 `data/VERSION.json`。
6. 复用 `SkillsManager._install_central()` 链接到 AI 工具目录。
7. `record_install()` 回调安装记录，失败不影响主流程。

## 远端数据升级

`SkillsManager.upgrade()` 当前只允许：

- `ops-dataset-query`
- `ops-amazon-rufus`

`ops-dataset-query` 的远端接口在 `SkillsUpdater` 中：

- `/v1/data-metrics/datasets/skill/manifest`
- `/v1/data-metrics/datasets/skill/export`
- `/v1/data-metrics/datasets/skill/export-datasets`
- `/v1/data-metrics/datasets/skill/export-select-columns`
- `/v1/data-metrics/datasets/skill/catalog`
- `/v1/data-metrics/datasets/query-metadata`

升级流程先拉取一次远端数据，再对所有本地安装目录按真实路径去重后写入，避免多个工具链接同一中央目录时重复覆盖。

## 新增项目内 Skill 的最小路径

纯本地内置 Skill：

1. 新建 `opscli/skills/templates/ops-xxx/`，名称必须带 `ops-` 前缀。
2. 提供 `SKILL.md`。
3. 提供 `data/VERSION.json`，格式为 `{"name": "ops-xxx", "version": "v1.0.0"}`。
4. 在 `opscli/skills/templates/manifest.json` 声明发版准入和 reason。
5. 若只是安装模板，不需要改 `SkillsManager` 或 `SkillsUpdater`。

支持远端升级的 Skill：

1. 完成纯本地模板。
2. 在 `SkillsUpdater` 增加远端接口和升级方法。
3. 在 `SkillsManager.status()` 增加远端状态汇总。
4. 在 `SkillsManager.upgrade()` 增加名称分发。
5. 补充 updater/manager 测试和发布文档。

发布到技能广场：

1. 确认本地目录含 `SKILL.md` 和 `data/VERSION.json`。
2. 更新版本号和 frontmatter，保持版本一致。
3. 运行 `opscli skills publish --dir <skill-dir> --share-type <personal|department|company> --changelog "<text>"`。
4. 首次创建后返回 `identifier`，后续同名发布自动走新版本更新。

## 风险和不一致点

1. `README.md` 中 `marketplace list --category 1` 与 CLI 的 `--category` 按 slug 匹配存在不一致，`docs/guide/opscli命令用例手册.md` 描述更接近当前实现。
2. `README.md` 部分 sort 示例使用 `downloads/rating/created_at`，CLI 默认和代码路径是 `install_count/usage_count/rating_avg/new`，存在文档漂移。
3. `opscli/skills/marketplace/models.py` 的分享标签和安装徽标含部分非 GBK 安全字符，可能与 Windows 终端输出规范冲突。
4. `opscli/cli.py` 中 `feedtask_app` 当前挂载名为 `feedback`，看起来与 `feedback_app` 重复；虽与 Skills 发布无直接关系，但属于命令树可疑点。
5. `manifest.json` 中存在模板目录未准入的 Skill，属预期治理状态；新增模板如果忘记声明，发布检查会失败。


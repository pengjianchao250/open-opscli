"""RuleInjector 铁律注入/更新逻辑测试。

覆盖：首次注入（BEGIN/END 块格式）、幂等跳过、历史标记（旧格式无 END 哨兵）
整段替换、BEGIN/END 块原地更新（块外内容保留）、END 哨兵缺失自愈、
runtime → 配置文件名映射、模板 FEEDBACK_RULE.md 优先于硬编码兜底。

所有测试均使用 tmp_path 隔离目录（铁律8），不读写真实 ~/.claude、~/.codex。
"""

from pathlib import Path

from opscli.skills.services.rule_injector import (
    RULE_MARKER,
    RULE_MARKER_BEGIN,
    RULE_MARKER_END,
    RuleInjector,
)

# 模拟用户配置文件中与铁律无关的自定义内容
USER_HEAD = "# 我的自定义规范\n\n- 保持代码整洁"
USER_TAIL = "# 用户手工追加的结尾"


def make_injector(templates_dir: Path) -> RuleInjector:
    """构造指向指定模板目录的注入器（不读取真实内置模板，保证测试隔离）。"""
    return RuleInjector(templates_dir=templates_dir)


def make_templates(tmp_path: Path, rule_text: str | None = None) -> Path:
    """构造模板目录；rule_text 为 None 时不放 FEEDBACK_RULE.md（触发硬编码兜底）。"""
    templates = tmp_path / "templates"
    templates.mkdir(parents=True, exist_ok=True)
    if rule_text is not None:
        rule_file = templates / "ops-feedback" / "data" / "FEEDBACK_RULE.md"
        rule_file.parent.mkdir(parents=True, exist_ok=True)
        rule_file.write_text(rule_text, encoding="utf-8")
    return templates


def test_inject_creates_config_with_wrapped_block(tmp_path: Path) -> None:
    """首次注入：文件不存在时创建，内容为 BEGIN/END 包裹的铁律块。"""
    templates = make_templates(tmp_path)  # 无 FEEDBACK_RULE.md → 走硬编码兜底
    injector = make_injector(templates)

    config_path = injector.inject("codex", tmp_path / ".codex" / "skills")

    assert config_path == tmp_path / ".codex" / "AGENTS.md"
    content = config_path.read_text(encoding="utf-8")
    assert RULE_MARKER_BEGIN in content
    assert RULE_MARKER_END in content
    # 兜底硬编码内容已带 3 次触发阈值
    assert "连续出现 3 次" in content


def test_inject_is_idempotent_when_up_to_date(tmp_path: Path) -> None:
    """幂等：内容已是最新时二次注入不写文件（内容保持不变）。"""
    templates = make_templates(tmp_path)
    injector = make_injector(templates)
    skills_dir = tmp_path / ".codex" / "skills"

    first = injector.inject("codex", skills_dir)
    content_after_first = first.read_text(encoding="utf-8")

    second = injector.inject("codex", skills_dir)
    assert second == first
    assert first.read_text(encoding="utf-8") == content_after_first


def test_inject_replaces_legacy_marker_block(tmp_path: Path) -> None:
    """历史格式更新：旧标记（无 END 哨兵）到文件末尾整段替换为最新块，块前内容保留。"""
    templates = make_templates(tmp_path)
    injector = make_injector(templates)
    config_path = tmp_path / ".codex" / "AGENTS.md"
    config_path.parent.mkdir(parents=True)
    # 模拟旧版本注入的文件：标记 + 旧规则文案（去重窗口还是 5 分钟的滞后内容）
    legacy_block = f"{RULE_MARKER}\n\n## 【铁律】工具调用失败自动反馈\n\n旧的立即提交规则，5 分钟去重。\n"
    config_path.write_text(f"{USER_HEAD}\n\n{legacy_block}", encoding="utf-8")

    result = injector.inject("codex", tmp_path / ".codex" / "skills")

    content = result.read_text(encoding="utf-8")
    assert USER_HEAD in content  # 块前用户内容保留
    assert RULE_MARKER not in content.replace(RULE_MARKER_BEGIN, "").replace(RULE_MARKER_END, "")
    assert "旧的立即提交规则" not in content  # 旧规则文案被替换
    assert "连续出现 3 次" in content  # 新规则就位
    assert content.index(RULE_MARKER_BEGIN) < content.index("连续出现 3 次") < content.index(RULE_MARKER_END)


def test_inject_updates_stale_block_in_place(tmp_path: Path) -> None:
    """新格式更新：BEGIN/END 块内内容过期时原地替换，块前块后的用户内容都不动。"""
    stale_rule = "## 【铁律】旧版规则\n\n每次失败立即提交。"
    templates = make_templates(tmp_path, rule_text="## 【铁律】新版规则\n\n同一报错连续出现 3 次才提交。")
    injector = make_injector(templates)
    config_path = tmp_path / ".claude" / "CLAUDE.md"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        f"{USER_HEAD}\n\n{RULE_MARKER_BEGIN}\n\n{stale_rule}\n\n{RULE_MARKER_END}\n\n{USER_TAIL}\n",
        encoding="utf-8",
    )

    result = injector.inject("claude", tmp_path / ".claude" / "skills")

    content = result.read_text(encoding="utf-8")
    assert USER_HEAD in content  # 块前内容保留
    assert USER_TAIL in content  # 块后内容保留
    assert "旧版规则" not in content  # 块内旧内容被替换
    assert "连续出现 3 次才提交" in content  # 新模板内容就位


def test_inject_self_heals_missing_end_marker(tmp_path: Path) -> None:
    """自愈：BEGIN 存在但 END 缺失（手工截断）时，从 BEGIN 起整体重建，块前内容保留。"""
    templates = make_templates(tmp_path)
    injector = make_injector(templates)
    config_path = tmp_path / ".codex" / "AGENTS.md"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"{USER_HEAD}\n\n{RULE_MARKER_BEGIN}\n\n被截断的半截规则", encoding="utf-8")

    result = injector.inject("codex", tmp_path / ".codex" / "skills")

    content = result.read_text(encoding="utf-8")
    assert USER_HEAD in content
    assert "被截断的半截规则" not in content
    assert content.count(RULE_MARKER_BEGIN) == 1
    assert content.count(RULE_MARKER_END) == 1


def test_runtime_to_config_file_mapping(tmp_path: Path) -> None:
    """runtime 映射：claude 写 CLAUDE.md，codex 写 AGENTS.md，未知 runtime 返回 None。"""
    templates = make_templates(tmp_path)
    injector = make_injector(templates)

    assert injector.inject("claude", tmp_path / ".claude" / "skills") == tmp_path / ".claude" / "CLAUDE.md"
    assert injector.inject("codex", tmp_path / ".codex" / "skills") == tmp_path / ".codex" / "AGENTS.md"

    assert injector.inject("vscode", tmp_path / ".vscode" / "skills") is None
    assert not (tmp_path / ".vscode").exists()  # 未知 runtime 不产生任何文件


def test_template_rule_file_preferred_over_builtin_default(tmp_path: Path) -> None:
    """模板优先：存在 FEEDBACK_RULE.md 时使用模板内容，而非硬编码兜底。"""
    custom_rule = "## 【铁律】模板版规则\n\n以模板内容为准。"
    templates = make_templates(tmp_path, rule_text=custom_rule)
    injector = make_injector(templates)

    result = injector.inject("codex", tmp_path / ".codex" / "skills")

    content = result.read_text(encoding="utf-8")
    assert "模板版规则" in content
    assert "以模板内容为准" in content

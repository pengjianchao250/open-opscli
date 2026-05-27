#!/usr/bin/env python3
"""根据已填写的运营流程简报生成中文 Skill 草案。"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path


SECTION_ALIASES = {
    "metadata": ("skill metadata", "技能元数据"),
    "target_job": ("target job", "目标任务"),
    "trigger_prompts": ("trigger prompts", "触发问题", "触发话术"),
    "quick_start": ("quick start", "快速开始", "使用示例"),
    "parameters": ("parameters", "parameter list", "参数列表"),
    "required_inputs": ("required inputs", "必要输入"),
    "source_systems": ("source systems and artifacts", "数据系统与材料"),
    "data_plan": ("internal data plan", "ops data plan", "内部数据取数方案", "数据取数方案"),
    "data_precheck": ("data precheck", "取数预检"),
    "portability_plan": ("portability plan", "cross tool plan", "跨工具兼容方案", "替代方案"),
    "script_plan": ("script automation", "script plan", "脚本固化建议", "脚本固化"),
    "framework_strategy": ("framework strategy", "skill framework", "统一框架与加载策略", "框架与加载策略"),
    "workflow": ("core workflow", "核心流程"),
    "decision_rules": ("decision rules", "判断规则"),
    "exceptions": ("exceptions and escalation", "例外与升级"),
    "error_handling": ("error handling", "错误处理"),
    "output_contract": ("output contract", "输出约定"),
    "quality_bar": ("quality bar", "质量标准"),
    "eval_plan": ("testing and benchmark", "testing benchmark", "测试与基准对比", "测试与迭代计划"),
    "release_plan": ("release governance", "version and release", "版本与发布治理", "发布治理"),
    "execution_log": ("execution log", "run log", "执行日志", "运行日志"),
    "submission_plan": ("submission governance", "skill submission", "内测提交", "候选提交"),
    "improvement_loop": ("execution log and iteration", "self improvement", "执行记录与迭代", "执行日志"),
    "examples": ("examples", "案例"),
    "terms": ("terms to preserve", "需保留术语"),
    "references": ("references to create", "需创建参考资料"),
    "scripts": ("scripts to create", "需创建脚本"),
    "open_questions": ("open questions", "待确认问题"),
}


RESOURCE_FILES = [
    ("references/execution-log-schema.md", "references/execution-log-schema.md"),
    ("references/skill-submission-governance.md", "references/skill-submission-governance.md"),
    ("scripts/qualify_candidate.py", "scripts/qualify_candidate.py"),
    ("scripts/package_submission.py", "scripts/package_submission.py"),
]


KEY_ALIASES = {
    "skill_name": ("skill name", "skill-name", "skill_name", "技能名称"),
    "display_name": ("display name", "display-name", "display_name", "展示名称"),
    "short_description": ("short description", "short-description", "short_description", "简介"),
    "trigger_description": ("trigger description", "description", "触发描述", "描述"),
    "primary_users": ("primary users", "primary-users", "primary_users", "主要用户"),
    "owner": ("owner", "负责人"),
}


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value.strip().lower()).strip()


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "draft-ops-skill"


def parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {"preamble": []}
    current = "preamble"

    for line in text.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = normalize(match.group(1))
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)

    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def get_section(sections: dict[str, str], logical_name: str) -> str:
    aliases = SECTION_ALIASES[logical_name]
    for alias in aliases:
        value = sections.get(normalize(alias), "").strip()
        if value:
            return value
    return ""


def parse_metadata(metadata_text: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for line in metadata_text.splitlines():
        match = re.match(r"^\s*[-*]\s*([^:：]+)\s*[:：]\s*(.+?)\s*$", line)
        if not match:
            continue
        raw_key, value = match.groups()
        key_norm = normalize(raw_key)
        value = value.strip().strip("`")
        if not value or value.startswith("["):
            continue
        for canonical, aliases in KEY_ALIASES.items():
            if key_norm in {normalize(alias) for alias in aliases}:
                pairs[canonical] = value
                break
    return pairs


def clean_markdown_block(value: str, fallback: str) -> str:
    value = value.strip()
    if not value:
        return fallback
    useful_lines = []
    for line in value.splitlines():
        stripped = line.strip()
        if stripped in {"-", "- ", "1.", "2.", "3."}:
            continue
        useful_lines.append(line)
    cleaned = "\n".join(useful_lines).strip()
    return cleaned or fallback


def yaml_quote(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{value}"'


def build_skill_md(name: str, display_name: str, description: str, sections: dict[str, str]) -> str:
    target_job = clean_markdown_block(get_section(sections, "target_job"), "- [待确认]")
    trigger_prompts = clean_markdown_block(get_section(sections, "trigger_prompts"), "- [待确认]")
    quick_start = clean_markdown_block(get_section(sections, "quick_start"), "- [待确认]")
    parameters = clean_markdown_block(get_section(sections, "parameters"), "- [待确认]")
    required_inputs = clean_markdown_block(get_section(sections, "required_inputs"), "- [待确认]")
    source_systems = clean_markdown_block(get_section(sections, "source_systems"), "- [待确认]")
    framework_strategy = clean_markdown_block(get_section(sections, "framework_strategy"), "- 日常执行只加载 `SKILL.md` 和本次必要的 0-2 个 reference；测试、发布、跨工具迁移、错误排查或用户明确要求优化时再加载完整资料。")
    workflow = clean_markdown_block(get_section(sections, "workflow"), "1. [待确认]")
    error_handling = clean_markdown_block(get_section(sections, "error_handling"), "- [待确认]")
    output_contract = clean_markdown_block(get_section(sections, "output_contract"), "- [待确认]")
    execution_log = clean_markdown_block(get_section(sections, "execution_log"), "- 默认按 `references/execution-log-schema.md` 记录执行摘要和学习日记。")
    submission_plan = clean_markdown_block(get_section(sections, "submission_plan"), "- 默认状态为 `personal_draft`；多次执行有效后，按 `references/skill-submission-governance.md` 判断是否提交候选库。")
    open_questions = clean_markdown_block(get_section(sections, "open_questions"), "- 暂无")

    return f"""---
name: {name}
description: {yaml_quote(description)}
---

# {display_name}

## 目标

使用这个 Skill 完成下面记录的运营任务。默认用中文执行和输出；保留运营原话、业务术语、字段名和工具名；不确定的规则标记为 `[待确认]`。主文件只放日常执行路由，完整业务背景和治理资料按需读取。

## 目标任务

{target_job}

## 快速开始

{quick_start}

## 触发话术

{trigger_prompts}

## 必要参数

{parameters}

## 日常工作流

{workflow}

## 默认执行策略

- 用户要求执行、分析、生成或检查时，默认按上面的已固化流程直接处理，只追问缺失的必要参数。
- 已验证的数据路径、字段映射、脚本和输出模板直接复用；不要在日常执行中重复做完整取数预检、baseline 测试、发布治理或长篇流程介绍。
- 只有遇到缺参数、字段/权限/空结果异常、新场景超出固化范围、用户要求解释流程、测试、优化、发布或跨工具迁移时，才加载对应 reference 并展开分析。
- 最终回复默认只给结果、关键口径、输出路径和异常提醒；除非用户要求，不输出完整执行过程。

## 必要输入

{required_inputs}

## 数据系统与材料

{source_systems}

## 按需加载资料

{framework_strategy}

| 场景 | 读取 |
| --- | --- |
| 理解完整业务背景、案例、术语、待确认问题 | `references/flow-map.md` |
| 日常执行且已有固化取数规则 | 优先直接执行脚本或已验证 recipe，不重新读完整 `data-plan.md` |
| 新数据、新字段、空结果、权限失败或口径变化 | `references/data-plan.md`，必要时 `references/data-recipes.md` |
| 需要完整判断规则、阈值、例外和质量标准 | `references/operating-rules.md` |
| 需要跨工具复用或降级 | `references/cross-tool-portability.md` |
| 用户要求测试、baseline、断言、评分或发布前验收 | `references/testing-benchmark.md` |
| 需要发布治理、版本和回归门槛 | `references/release-plan.md` |
| 需要记录运行或提交候选 | `references/execution-log-schema.md`、`references/skill-submission-governance.md` |

日常执行优先只读本文件和本次任务直接相关的 0-2 个 reference；不要为了常规运行一次性加载全部资料。

## 错误处理

{error_handling}

## 输出规范

{output_contract}

## 执行日志

{execution_log}

## 内测提交

{submission_plan}

可使用 `scripts/qualify_candidate.py` 汇总运行日志并判断是否达到候选门槛；用户确认提交后，使用 `scripts/package_submission.py` 生成脱敏提交包。未经用户确认，不自动提交个人草稿。

## 待确认问题

{open_questions}

## 框架合规

本 Skill 按 ops-creator-skill 统一框架生成：轻量 `SKILL.md` 负责路由，完整内容保留在 `references/`，稳定重复动作优先脚本化。改造已有 Skill 时，先保留旧版基线，再用同一批输入和数据对比新旧输出。
"""


def build_openai_yaml(name: str, display_name: str, short_description: str) -> str:
    if not short_description:
        short_description = f"运行{display_name}流程"
    if len(short_description) > 64:
        short_description = short_description[:61].rstrip() + "..."
    return f"""interface:
  display_name: {yaml_quote(display_name)}
  short_description: {yaml_quote(short_description)}
  default_prompt: {yaml_quote(f"请按流程地图运行“{display_name}”这个中文工作流。")}

policy:
  allow_implicit_invocation: true
"""


def write_optional_reference(destination: Path, filename: str, title: str, content: str) -> None:
    cleaned = clean_markdown_block(content, "")
    if not cleaned:
        return
    (destination / "references" / filename).write_text(f"# {title}\n\n{cleaned}\n", encoding="utf-8")


def write_extracted_references(destination: Path, sections: dict[str, str]) -> None:
    data_content = "\n\n".join(
        part
        for part in [
            "## 内部数据取数方案\n\n" + get_section(sections, "data_plan"),
            "## 取数预检\n\n" + get_section(sections, "data_precheck"),
        ]
        if part.strip().replace("## 内部数据取数方案", "").replace("## 取数预检", "").strip()
    )
    rules_content = "\n\n".join(
        part
        for part in [
            "## 判断规则\n\n" + get_section(sections, "decision_rules"),
            "## 例外与升级\n\n" + get_section(sections, "exceptions"),
            "## 质量标准\n\n" + get_section(sections, "quality_bar"),
            "## 案例\n\n" + get_section(sections, "examples"),
            "## 需保留术语\n\n" + get_section(sections, "terms"),
        ]
        if part.strip().split("\n\n", 1)[-1].strip()
    )
    script_content = "\n\n".join(
        part
        for part in [
            "## 脚本固化建议\n\n" + get_section(sections, "script_plan"),
            "## 需创建脚本\n\n" + get_section(sections, "scripts"),
        ]
        if part.strip().split("\n\n", 1)[-1].strip()
    )

    write_optional_reference(destination, "data-plan.md", "数据方案与取数预检", data_content)
    write_optional_reference(destination, "cross-tool-portability.md", "跨工具兼容方案", get_section(sections, "portability_plan"))
    write_optional_reference(destination, "operating-rules.md", "判断规则、例外与案例", rules_content)
    write_optional_reference(destination, "testing-benchmark.md", "测试与基准对比", get_section(sections, "eval_plan"))
    write_optional_reference(destination, "release-plan.md", "版本与发布治理", get_section(sections, "release_plan"))
    write_optional_reference(destination, "script-automation.md", "脚本固化方案", script_content)


def copy_resource_files(destination: Path) -> None:
    source_root = Path(__file__).resolve().parents[1]
    for source_rel, dest_rel in RESOURCE_FILES:
        source = source_root / source_rel
        target = destination / dest_rel
        if not source.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if target.suffix == ".py":
            target.chmod(0o755)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brief", type=Path, help="已填写的流程简报 Markdown 文件")
    parser.add_argument("--output-dir", type=Path, required=True, help="生成 Skill 草案目录的位置")
    parser.add_argument("--skill-name", help="覆盖简报里的技能名称")
    parser.add_argument("--force", action="store_true", help="如果目标目录已存在则覆盖")
    args = parser.parse_args()

    if not args.brief.exists():
        print(f"找不到流程简报: {args.brief}", file=sys.stderr)
        return 2

    text = args.brief.read_text(encoding="utf-8")
    sections = parse_sections(text)
    metadata = parse_metadata(get_section(sections, "metadata"))

    raw_name = args.skill_name or metadata.get("skill_name") or metadata.get("display_name") or "draft-ops-skill"
    skill_name = slugify(raw_name)
    display_name = metadata.get("display_name") or raw_name.strip() or skill_name
    description = metadata.get("trigger_description") or (
        f"从运营流程简报生成的中文工作流 Skill。用于执行 {display_name}。"
    )
    short_description = metadata.get("short_description") or f"运行{display_name}流程"

    destination = args.output_dir / skill_name
    if destination.exists():
        if not args.force:
            print(f"目标目录已存在: {destination}。如需覆盖请使用 --force。", file=sys.stderr)
            return 3
        shutil.rmtree(destination)

    (destination / "references").mkdir(parents=True, exist_ok=True)
    (destination / "agents").mkdir(parents=True, exist_ok=True)
    (destination / "scripts").mkdir(parents=True, exist_ok=True)

    (destination / "SKILL.md").write_text(
        build_skill_md(skill_name, display_name, description, sections),
        encoding="utf-8",
    )
    (destination / "references" / "flow-map.md").write_text(
        "# 流程地图\n\n"
        "本文件保留用于生成 Skill 草案的流程简报原文。\n\n"
        f"{text.strip()}\n",
        encoding="utf-8",
    )
    write_extracted_references(destination, sections)
    (destination / "agents" / "openai.yaml").write_text(
        build_openai_yaml(skill_name, display_name, short_description),
        encoding="utf-8",
    )
    copy_resource_files(destination)

    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""仪表盘领域 MCP 规范读取工具。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from opscli.skills.packaging import get_builtin_templates_dir

from .helpers import _err, _ok


_DASHBOARD_BRIDGE_REFERENCES = (
    "dashboard-operation-standards",
    "bridge-result-protocol",
    "tool-flow",
)
"""Bridge 入口响应返回的渐进规范名称，默认不读取完整正文。"""

_SKILL_VERSION_RE = re.compile(r"^version:\s*([^\s]+)\s*$", re.MULTILINE)
"""提取 Skill frontmatter 版本号，供包内版本一致性校验。"""


def _dashboard_skill_dir(skill_name: str) -> Path:
    """返回指定仪表盘 Skill 的内置模板目录。"""
    return get_builtin_templates_dir() / skill_name


def _read_spec_files(paths: list[Path], *, tool: str) -> dict:
    """读取并合并规范文件，返回统一 MCP 响应。"""
    for path in paths:
        if not path.exists():
            return _err(
                FileNotFoundError(f"仪表盘 MCP 规范文档不存在：{path}。请检查 opscli 安装是否完整。"),
                tool=tool,
            )

    try:
        content = "\n\n".join(path.read_text(encoding="utf-8") for path in paths)
        return _ok(
            {
                "spec": content,
                "source": str(paths[0]),
                "sources": [str(path) for path in paths],
            }
        )
    except Exception as exc:
        return _err(exc, tool=tool)


def _validate_dashboard_runtime_contract(contract: object) -> dict[str, Any]:
    """校验 Dashboard 运行合同的公共结构和基础数值边界。"""
    if not isinstance(contract, dict):
        raise ValueError("Dashboard 运行合同必须是 JSON 对象")

    contract_version = contract.get("contractVersion")
    if not isinstance(contract_version, str) or not re.fullmatch(
        r"\d+\.\d+\.\d+", contract_version
    ):
        raise ValueError("Dashboard 运行合同缺少合法 contractVersion")

    grid_columns = contract.get("gridColumns")
    if not isinstance(grid_columns, int) or isinstance(grid_columns, bool) or grid_columns <= 0:
        raise ValueError("Dashboard 运行合同 gridColumns 必须是正整数")

    templates = contract.get("templates")
    if not isinstance(templates, dict) or not templates:
        raise ValueError("Dashboard 运行合同 templates 必须是非空对象")
    for template_name, template in templates.items():
        if not isinstance(template_name, str) or not template_name or not isinstance(template, dict):
            raise ValueError("Dashboard 运行合同模板名称和配置必须合法")
        chart_types = template.get("chartTypes")
        layouts = template.get("layouts")
        if (
            not isinstance(chart_types, list)
            or not chart_types
            or not all(isinstance(item, str) and item for item in chart_types)
            or len(set(chart_types)) != len(chart_types)
        ):
            raise ValueError(f"Dashboard 模板 {template_name} 的 chartTypes 不合法")
        if not isinstance(layouts, list) or len(layouts) != len(chart_types):
            raise ValueError(f"Dashboard 模板 {template_name} 的 layouts 数量不匹配")
        for layout in layouts:
            if not isinstance(layout, dict):
                raise ValueError(f"Dashboard 模板 {template_name} 的 layout 必须是对象")
            width = layout.get("w")
            height = layout.get("h")
            if (
                not isinstance(width, int)
                or isinstance(width, bool)
                or width <= 0
                or width > grid_columns
                or not isinstance(height, int)
                or isinstance(height, bool)
                or height <= 0
            ):
                raise ValueError(f"Dashboard 模板 {template_name} 的 layout 超出网格边界")

    creation_workflow = contract.get("creationWorkflow")
    required_workflow_tools = {
        "dashboard_session_get_dataset_fields",
        "dashboard_editor_batch_create_charts",
    }
    if not isinstance(creation_workflow, dict) or set(creation_workflow) != required_workflow_tools:
        raise ValueError("Dashboard 运行合同 creationWorkflow 工具集合不合法")
    if any(
        not isinstance(count, int) or isinstance(count, bool) or count <= 0
        for count in creation_workflow.values()
    ):
        raise ValueError("Dashboard 运行合同 creationWorkflow 次数必须是正整数")
    return contract


def _read_dashboard_bridge_spec(skill_dir: Path, *, tool: str) -> dict:
    """读取紧凑 Bridge 入口规范、结构合同和渐进 reference 清单。"""
    skill_path = skill_dir / "SKILL.md"
    version_path = skill_dir / "data" / "VERSION.json"
    contract_path = skill_dir / "data" / "dashboard-runtime-contract.json"
    reference_paths = [
        skill_dir / "references" / f"{reference_name}.md"
        for reference_name in _DASHBOARD_BRIDGE_REFERENCES
    ]
    required_paths = [skill_path, version_path, contract_path, *reference_paths]
    for path in required_paths:
        if not path.exists():
            return _err(
                FileNotFoundError(f"仪表盘 MCP 规范文档不存在：{path}。请检查 opscli 安装是否完整。"),
                tool=tool,
            )

    try:
        spec = skill_path.read_text(encoding="utf-8")
        version_payload = json.loads(version_path.read_text(encoding="utf-8"))
        version_match = _SKILL_VERSION_RE.search(spec)
        if version_match is None:
            raise ValueError("Dashboard Skill 缺少 frontmatter.version")
        skill_version = version_match.group(1).lstrip("vV")
        packaged_version = str(version_payload.get("version") or "").lstrip("vV")
        if skill_version != packaged_version:
            raise ValueError("Dashboard Skill 与 VERSION.json 版本不一致")

        contract = _validate_dashboard_runtime_contract(
            json.loads(contract_path.read_text(encoding="utf-8"))
        )
        return _ok(
            {
                "spec": spec,
                "contract": contract,
                "source": str(skill_path),
                "contractSource": str(contract_path),
                "references": list(_DASHBOARD_BRIDGE_REFERENCES),
            }
        )
    except Exception as exc:
        return _err(exc, tool=tool)


async def dashboard_data_analysis_spec_must_read() -> dict:
    """读取仪表盘只读数据分析规范。

    本工具只返回 `ops-dashboard-data-analysis` 的使用规范，不会创建、
    调用或代理 `dashboard_*` 页面工具。实际分析要求当前会话已绑定
    运营系统仪表盘编辑页，并已安装 `ops-dataset-query`。
    """
    skill_dir = _dashboard_skill_dir("ops-dashboard-data-analysis")
    return _read_spec_files(
        [skill_dir / "SKILL.md"],
        tool="MCP → dashboard_data_analysis_spec_must_read()",
    )


async def dashboard_ai_bridge_spec_must_read() -> dict:
    """读取仪表盘编辑与 Bridge 协议规范。

    返回 `ops-dashboard-ai-bridge` 的紧凑入口规范、机器运行合同和渐进
    reference 清单。本工具不会提供或执行 `dashboard_*` 页面工具；实际页面
    操作仍要求 operation-frontend 为当前会话注入合法 Dashboard 页面上下文。
    """
    skill_dir = _dashboard_skill_dir("ops-dashboard-ai-bridge")
    return _read_dashboard_bridge_spec(
        skill_dir,
        tool="MCP → dashboard_ai_bridge_spec_must_read()",
    )


_ALL_TOOLS = [
    dashboard_data_analysis_spec_must_read,
    dashboard_ai_bridge_spec_must_read,
]


def register(mcp) -> None:
    """向指定 MCP 实例注册仪表盘规范工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)

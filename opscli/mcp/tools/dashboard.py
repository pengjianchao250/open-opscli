"""仪表盘领域 MCP 规范读取工具。"""

from __future__ import annotations

import json
import re
from pathlib import Path

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


def _read_dashboard_bridge_spec(skill_dir: Path, *, tool: str) -> dict:
    """读取 Bridge 入口规范，并校验包内版本和 reference 完整性。"""
    skill_path = skill_dir / "SKILL.md"
    version_path = skill_dir / "data" / "VERSION.json"
    reference_paths = [
        skill_dir / "references" / f"{reference_name}.md"
        for reference_name in _DASHBOARD_BRIDGE_REFERENCES
    ]
    required_paths = [skill_path, version_path, *reference_paths]
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

        return _ok(
            {
                "spec": spec,
                "source": str(skill_path),
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

    返回 `ops-dashboard-ai-bridge` 的入口规范和渐进 reference 清单。本工具
    不会提供或执行 `dashboard_*` 页面工具；实际页面操作仍要求
    operation-frontend 为当前会话注入合法 Dashboard 页面上下文。
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

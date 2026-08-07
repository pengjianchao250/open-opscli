"""仪表盘 MCP 规范工具测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastmcp import Client, FastMCP

from opscli.mcp.tools import dashboard as dashboard_tools


def _run(coro):
    """在同步测试中运行异步调用。"""
    return asyncio.run(coro)


def test_dashboard_data_analysis_spec_reads_skill():
    """数据分析规范工具应返回单一 Skill 来源。"""
    result = _run(dashboard_tools.dashboard_data_analysis_spec_must_read())

    assert result["success"] is True
    assert result["error"] is None
    assert "# 仪表盘数据分析" in result["data"]["spec"]
    source = Path(result["data"]["source"])
    assert source.parts[-3:] == ("templates", "ops-dashboard-data-analysis", "SKILL.md")
    assert result["data"]["sources"] == [str(source)]


def test_dashboard_ai_bridge_spec_returns_skill_rules():
    """Bridge 规范工具应按固定顺序合并主流程和三份 reference。"""
    result = _run(dashboard_tools.dashboard_ai_bridge_spec_must_read())

    assert result["success"] is True
    assert result["error"] is None
    assert "# 仪表盘智能编辑" in result["data"]["spec"]
    assert "# Dashboard Operation Standards" in result["data"]["spec"]
    assert "# Dashboard Dataset Guide" in result["data"]["spec"]
    assert "# Dashboard Tool Contract" in result["data"]["spec"]
    assert "数据集和字段仅取本轮页面工具结果" in result["data"]["spec"]
    assert "唯一完整等值时使用原值" in result["data"]["spec"]
    assert "模型不计算坐标或宽度" in result["data"]["spec"]
    assert "任一字段不合法时不得提交字段配置" in result["data"]["spec"]
    assert "恰好 5 张是创建硬门禁" in result["data"]["spec"]
    assert "用户指定的类型或标题必须纳入计划" in result["data"]["spec"]
    assert "不得重复问题、无依据凑数、少建或多建" in result["data"]["spec"]
    assert "普通新建都先用 `dashboard-dataset-guide.md` 按意图自动判断语义候选" in result["data"]["spec"]
    assert "普通数据图表不得创建未配置图表" in result["data"]["spec"]
    assert "本指南只生成语义候选" in result["data"]["spec"]
    assert "即时综合数据集" in result["data"]["spec"]
    assert "SKU仓租库龄明细" in result["data"]["spec"]
    assert "`area_stacked`" in result["data"]["spec"]
    assert "`combo_bar_line_group`" in result["data"]["spec"]
    assert "场景组合模板" not in result["data"]["spec"]
    assert "`chart_id` 定向修改不得误改其他图表" in result["data"]["spec"]
    assert "dashboard_editor_batch_create_charts" in result["data"]["spec"]
    assert "dashboard_editor_select_chart" in result["data"]["spec"]
    assert "dashboard_drag_select_chart" not in result["data"]["spec"]
    assert "contract" not in result["data"]
    assert "contractSource" not in result["data"]
    assert Path(result["data"]["source"]).name == "SKILL.md"
    assert [Path(path).name for path in result["data"]["sources"]] == [
        "SKILL.md",
        "dashboard-operation-standards.md",
        "dashboard-dataset-guide.md",
        "dashboard-tool-contract.md",
    ]


def _write_bridge_fixture(
    root: Path,
    *,
    skill_version: str = "1.0.19",
    packaged_version: str = "v1.0.19",
) -> Path:
    """写入最小 Bridge 模板，用于隔离验证 MCP 失败路径。"""
    skill_dir = root / "ops-dashboard-ai-bridge"
    data_dir = skill_dir / "data"
    references_dir = skill_dir / "references"
    data_dir.mkdir(parents=True)
    references_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: ops-dashboard-ai-bridge\nversion: {skill_version}\n---\n",
        encoding="utf-8",
    )
    (data_dir / "VERSION.json").write_text(
        json.dumps({"name": "ops-dashboard-ai-bridge", "version": packaged_version}),
        encoding="utf-8",
    )
    for reference_name in dashboard_tools._DASHBOARD_BRIDGE_REFERENCE_FILES:
        (references_dir / reference_name).write_text("# reference\n", encoding="utf-8")
    return skill_dir


def test_dashboard_ai_bridge_spec_rejects_missing_reference(monkeypatch, tmp_path: Path):
    """渐进规范缺失时应返回统一错误，禁止暴露不完整 Skill。"""
    skill_dir = _write_bridge_fixture(tmp_path)
    (skill_dir / "references" / "dashboard-tool-contract.md").unlink()
    monkeypatch.setattr(dashboard_tools, "_dashboard_skill_dir", lambda _name: skill_dir)

    result = _run(dashboard_tools.dashboard_ai_bridge_spec_must_read())

    assert result["success"] is False
    assert result["error"]["code"] == "FileNotFoundError"
    assert "dashboard-tool-contract.md" in result["error"]["message"]


def test_dashboard_ai_bridge_spec_rejects_version_mismatch(monkeypatch, tmp_path: Path):
    """入口版本和包版本不一致时应停止返回 Bridge 规范。"""
    skill_dir = _write_bridge_fixture(
        tmp_path,
        packaged_version="v1.0.18",
    )
    monkeypatch.setattr(dashboard_tools, "_dashboard_skill_dir", lambda _name: skill_dir)

    result = _run(dashboard_tools.dashboard_ai_bridge_spec_must_read())

    assert result["success"] is False
    assert result["error"]["code"] == "ValueError"
    assert "版本不一致" in result["error"]["message"]


def test_dashboard_spec_returns_structured_error_when_file_is_missing(monkeypatch, tmp_path: Path):
    """规范文件缺失时应返回统一错误和明确 feedback 工具名。"""
    monkeypatch.setattr(dashboard_tools, "_dashboard_skill_dir", lambda _name: tmp_path / "missing")

    result = _run(dashboard_tools.dashboard_data_analysis_spec_must_read())

    assert result["success"] is False
    assert result["error"]["code"] == "FileNotFoundError"
    assert "dashboard_data_analysis_spec_must_read" in str(result["feedback"])


def test_dashboard_spec_tools_expose_empty_input_schema():
    """两个无参数工具必须暴露空对象输入 Schema。"""
    async def scenario():
        mcp = FastMCP("dashboard-schema-test")
        dashboard_tools.register(mcp)
        async with Client(mcp) as client:
            return await client.list_tools()

    tools = _run(scenario())
    by_name = {tool.name: tool for tool in tools}

    for name in (
        "dashboard_data_analysis_spec_must_read",
        "dashboard_ai_bridge_spec_must_read",
    ):
        assert by_name[name].inputSchema == {
            "additionalProperties": False,
            "properties": {},
            "type": "object",
        }
        assert "不会" in (by_name[name].description or "")

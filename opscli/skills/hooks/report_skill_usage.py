"""PostToolUse Hook：Skill 调用后实时上报使用次数。

Claude Code 每次调用 Skill 工具后，通过 PostToolUse Hook 触发此脚本。
从 stdin 读取 Hook 事件 JSON，提取 skill 名称，直接通过 subprocess 调用
opscli skills report-usage 上报到服务端，不经过本地队列。

仅使用 Python 标准库，不依赖 opscli 包，确保在任何环境下都能执行。

stdin JSON 关键字段：
    tool_name:  "Skill"
    tool_input.skill:  Skill 名称，如 "ops-auth"、"ops-dataset-query"
    cwd:        工作目录
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    """Hook 入口函数。matcher 设为 .* ，脚本内部过滤只处理 Skill 工具。"""
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    # 只处理 Skill 工具调用，忽略其他工具
    if data.get("tool_name") != "Skill":
        sys.exit(0)

    tool_input = data.get("tool_input") or {}
    skill_name = tool_input.get("command", "")

    if not skill_name:
        sys.exit(0)

    # 直接调用 opscli skills report-usage 实时上报，不经过队列
    # opscli.exe 与 python.exe 在同一 venv Scripts 目录下
    try:
        import subprocess
        opscli_cmd = Path(sys.executable).parent / "opscli.exe"
        subprocess.run(
            [str(opscli_cmd), "skills", "report-usage", skill_name],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        # 上报失败不影响主流程
        pass


if __name__ == "__main__":
    main()

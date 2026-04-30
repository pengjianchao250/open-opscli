"""ops-dataset-query Skill 本地状态检查脚本（MCP 无状态模式）。

本脚本为 MCP 环境设计，不依赖 opscli 命令行工具。
仅检查本地数据文件完整性，更新操作需通过 MCP skills_upgrade Tool 执行。

================================================================================
MCP 使用指南
================================================================================

【检查本地数据状态】
    python updater_mcp.py --check

【更新数据】
本脚本不执行更新，更新请通过 MCP Tool：
    skills_upgrade(name="ops-dataset-query", skills_dir="/Users/mask/.config/opencode/skills")

================================================================================

用法：
    python updater_mcp.py --check [--pretty]
    python updater_mcp.py [--pretty]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import discover_data_dir


def check_local_data(data_dir: Path) -> dict:
    """检查本地数据文件完整性。

    Args:
        data_dir: 数据目录路径

    Returns:
        检查结果字典
    """
    version_file = data_dir / "VERSION.json"
    datasets_file = data_dir / "datasets.csv"
    fields_file = data_dir / "dataset_fields.csv"
    metadata_file = data_dir / "query_metadata.json"

    version = "unknown"
    if version_file.exists():
        try:
            payload = json.loads(version_file.read_text(encoding="utf-8"))
            version = str(payload.get("version", "unknown"))
        except Exception:
            version = "invalid"

    files_status = {
        "VERSION.json": {
            "exists": version_file.exists(),
            "version": version,
        },
        "datasets.csv": {
            "exists": datasets_file.exists(),
            "size": datasets_file.stat().st_size if datasets_file.exists() else 0,
        },
        "dataset_fields.csv": {
            "exists": fields_file.exists(),
            "size": fields_file.stat().st_size if fields_file.exists() else 0,
        },
        "query_metadata.json": {
            "exists": metadata_file.exists(),
            "size": metadata_file.stat().st_size if metadata_file.exists() else 0,
        },
    }

    all_exist = all(f["exists"] for f in files_status.values())
    healthy = all_exist and version not in ("invalid", "unknown")

    return {
        "data_dir": str(data_dir),
        "version": version,
        "healthy": healthy,
        "files": files_status,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="ops-dataset-query 本地状态检查（MCP 无状态模式）")
    parser.add_argument("--check", action="store_true", help="检查本地数据完整性")
    parser.add_argument("--skills-dir", help="指定 Skill 安装根目录")
    parser.add_argument("--data-dir", help="直接指定数据目录路径")
    parser.add_argument("--pretty", action="store_true", help="格式化 JSON 输出")
    args = parser.parse_args()

    # 确定数据目录
    if args.data_dir:
        data_dir = Path(args.data_dir)
    else:
        discovered = discover_data_dir(skills_dir=args.skills_dir)
        if discovered is None:
            print(
                json.dumps(
                    {
                        "success": False,
                        "error": "未找到 ops-dataset-query 数据目录。",
                        "mcp_hint": "调用 skills_upgrade(name='ops-dataset-query') 后重试",
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            raise SystemExit(1)
        data_dir = discovered

    status = check_local_data(data_dir)

    if args.check:
        result = {
            "success": True,
            "command": "ops-dataset-query updater check",
            "data": status,
            "mcp_hint": "如需更新，调用 skills_upgrade(name='ops-dataset-query')",
        }
    else:
        result = {
            "success": True,
            "command": "ops-dataset-query updater status",
            "data": status,
            "mcp_hint": "如需更新，调用 skills_upgrade(name='ops-dataset-query')",
        }

    indent = 2 if args.pretty else None
    print(json.dumps(result, ensure_ascii=False, indent=indent))


if __name__ == "__main__":
    main()

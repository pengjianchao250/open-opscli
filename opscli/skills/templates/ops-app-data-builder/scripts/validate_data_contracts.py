"""校验 AppHub 项目的开发期数据合同和数据层交付凭证。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_validator():
    """加载已安装校验内核，并兼容从源码模板目录直接执行。"""
    for parent in Path(__file__).resolve().parents:
        if (parent / "opscli" / "__init__.py").is_file():
            sys.path.insert(0, str(parent))
            break
    from opscli.app.services.data_contracts import validate_document

    return validate_document


validate_document = _load_validator()


def _build_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="校验 AppHub 数据合同和数据层交付凭证")
    parser.add_argument(
        "contract_file",
        type=Path,
        help="docs/ops-app/data-contracts.json 路径",
    )
    parser.add_argument(
        "--mode",
        choices=("draft", "contract", "delivery"),
        default="delivery",
        help="draft 允许开发中状态，contract 只验证合同，delivery 验证完整实现",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="项目根目录；delivery 默认从 docs/ops-app/data-contracts.json 反推",
    )
    return parser


def _resolve_project_root(contract_file: Path, project_root: Path | None) -> Path | None:
    """解析 delivery 校验使用的项目根目录。"""
    if project_root is not None:
        return project_root.expanduser().resolve()
    resolved = contract_file.expanduser().resolve()
    if resolved.parent.name == "ops-app" and resolved.parent.parent.name == "docs":
        return resolved.parent.parent.parent
    return None


def main() -> int:
    """执行命令行校验并输出统一 JSON 结果。"""
    arguments = _build_parser().parse_args()
    contract_file = arguments.contract_file.expanduser().resolve()
    project_root = _resolve_project_root(contract_file, arguments.project_root)
    try:
        document = json.loads(contract_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "valid": False,
                    "delivery_ready": False,
                    "mode": arguments.mode,
                    "contract_file": str(contract_file),
                    "project_root": str(project_root) if project_root else None,
                    "errors": [f"contract_file: {exc}"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    errors = validate_document(
        document,
        mode=arguments.mode,
        project_root=project_root,
    )
    valid = not errors
    print(
        json.dumps(
            {
                "valid": valid,
                "delivery_ready": valid and arguments.mode == "delivery",
                "mode": arguments.mode,
                "contract_file": str(contract_file),
                "project_root": str(project_root) if project_root else None,
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())

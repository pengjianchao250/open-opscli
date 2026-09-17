"""校验 AppHub Vue 前端是否依赖 runtime-only 构建不支持的模板编译。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SOURCE_SUFFIXES = {".vue", ".js", ".jsx", ".ts", ".tsx"}
TEST_FILE_MARKERS = (".test.", ".spec.")
TEST_DIRECTORY_NAMES = {"__tests__", "tests"}
SCRIPT_BLOCK_RE = re.compile(
    r"<script\b[^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
RUNTIME_TEMPLATE_RE = re.compile(
    r"\btemplate\s*:\s*(?:String\.raw\s*)?(?P<quote>['\"`])",
    re.MULTILINE,
)
VUE_COMPILE_RE = re.compile(r"\bVue\s*\.\s*compile\s*\(")
VUE_COMPILE_IMPORT_RE = re.compile(
    r"\bimport\s*\{[^}]*\bcompile\b[^}]*\}\s*from\s*['\"]vue['\"]",
    re.DOTALL,
)


def _script_content(path: Path, content: str) -> str:
    """Vue 单文件组件只检查脚本区，普通源码检查全文。"""
    if path.suffix.lower() != ".vue":
        return content
    return "\n".join(SCRIPT_BLOCK_RE.findall(content))


def _line_number(content: str, offset: int) -> int:
    """计算匹配位置的一基行号。"""
    return content.count("\n", 0, offset) + 1


def _is_test_source(path: Path, source_root: Path) -> bool:
    """测试夹具不属于浏览器生产运行时合同扫描范围。"""
    relative = path.relative_to(source_root)
    if any(part.lower() in TEST_DIRECTORY_NAMES for part in relative.parts[:-1]):
        return True
    return any(marker in path.name.lower() for marker in TEST_FILE_MARKERS)


def validate_project(project_root: str | Path) -> list[str]:
    """返回前端合同错误列表。"""
    root = Path(project_root).expanduser().resolve()
    source_root = root / "frontend" / "src"
    if not source_root.is_dir():
        return [f"frontend/src: 标准前端源码目录不存在：{source_root}"]

    errors: list[str] = []
    for path in sorted(source_root.rglob("*")):
        if (
            not path.is_file()
            or path.suffix.lower() not in SOURCE_SUFFIXES
            or _is_test_source(path, source_root)
        ):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{path.relative_to(root)}: 无法读取前端源码：{exc}")
            continue
        script = _script_content(path, content)
        relative = path.relative_to(root).as_posix()
        for pattern, message in (
            (
                RUNTIME_TEMPLATE_RE,
                "禁止组件字符串 template；请使用 SFC <template> 或 render function",
            ),
            (VUE_COMPILE_RE, "禁止 Vue.compile；统一模板使用 Vue runtime-only 构建"),
            (
                VUE_COMPILE_IMPORT_RE,
                "禁止从 vue 导入 compile；统一模板不提供运行时模板编译器",
            ),
        ):
            for match in pattern.finditer(script):
                line_number = _line_number(script, match.start())
                errors.append(f"{relative}:{line_number}: {message}")
    return errors


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="校验 AppHub Vue runtime-only 前端合同"
    )
    parser.add_argument("project_root", type=Path, help="AppHub 项目根目录")
    return parser


def main() -> int:
    arguments = _build_parser().parse_args()
    errors = validate_project(arguments.project_root)
    print(
        json.dumps(
            {
                "valid": not errors,
                "project_root": str(arguments.project_root.expanduser().resolve()),
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

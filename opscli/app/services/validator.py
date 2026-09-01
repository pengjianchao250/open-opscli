"""AppHub 本地规则表驱动校验。"""

from __future__ import annotations

import re
from pathlib import Path

from opscli.app.domain.exceptions import AppValidationError
from opscli.app.domain.models import AppProject, ValidationReport, Violation
from opscli.app.services.appignore import build_file_set
from opscli.app.services.scanner import GitleaksScanner
from opscli.config import __version__


_DB_FILE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
_CONNECT_LITERAL = re.compile(r"sqlite3\.connect\(\s*[rubfRUBF]*[\"'](?!:memory:)([^\"']+)[\"']")
_SQL_INTERPOLATION = re.compile(r"(?:execute|executemany)\(\s*(?:f[\"']|[^\n]*(?:\.format\(|%\s*[({]))")
_DDL = re.compile(r"\b(?:CREATE|ALTER|DROP)\s+(?:TABLE|INDEX)\b", re.IGNORECASE)
_SENSITIVE = re.compile(r"\b(?:password|passwd|secret|token|authorization|cookie)\b", re.IGNORECASE)
_BASE_PATH_LITERAL = re.compile(r"[\"']/apps/[a-z0-9-]+/?[\"']")
_DIRECT_DATA_API = re.compile(r"data-metrics/(?:cli-query|viewer)", re.IGNORECASE)


class AppValidator:
    """独立 validate 与 publish 共用的规则引擎。"""

    def __init__(self, scanner: GitleaksScanner | None = None) -> None:
        self.scanner = scanner or GitleaksScanner()

    def validate(
        self,
        project: AppProject,
        *,
        include_secrets: bool = True,
        raise_on_block: bool = True,
    ) -> ValidationReport:
        violations = self._collect(project)
        report = ValidationReport(project.slug, tuple(violations))
        if report.blocked and raise_on_block:
            raise AppValidationError(
                "VALIDATE_BLOCKED",
                f"存在 {report.to_dict()['summary']['block']} 条阻断级违规，修复后重试。",
                fix_hint="执行 opscli app validate --json 查看全部问题。",
                detail=report.to_dict(),
            )
        if include_secrets:
            self.scan_secrets(project)
        return report

    def scan_secrets(self, project: AppProject) -> None:
        self.scanner.scan(project.root)

    def ensure_opscli_requirement(self, project: AppProject) -> bool:
        """缺少 aukeys-opscli 时补齐当前版本下限。"""
        path = project.root / "requirements.txt"
        content = path.read_text(encoding="utf-8") if path.is_file() else ""
        if any(_requirement_name(line) == "aukeys-opscli" for line in content.splitlines()):
            return False
        separator = "" if not content or content.endswith("\n") else "\n"
        path.write_text(f"{content}{separator}aukeys-opscli>={__version__}\n", encoding="utf-8", newline="\n")
        return True

    def _collect(self, project: AppProject) -> list[Violation]:
        root = project.root
        violations: list[Violation] = []
        entrypoint = root / project.manifest.entrypoint
        if not entrypoint.is_file():
            violations.append(Violation(
                "APP-001", "block", f"入口文件不存在：{project.manifest.entrypoint}",
                "修正 app.yaml entrypoint，或创建对应文件。", project.manifest.entrypoint,
            ))

        requirements = root / "requirements.txt"
        if not requirements.is_file():
            violations.append(Violation(
                "PKG-001", "warning", "缺少 requirements.txt。",
                "创建 requirements.txt，并使用 == 锁定第三方依赖版本。", "requirements.txt",
            ))
        else:
            for line_number, raw in enumerate(requirements.read_text(encoding="utf-8").splitlines(), 1):
                value = raw.strip()
                if not value or value.startswith("#") or value.startswith(("-r", "--")):
                    continue
                if "==" not in value and not value.startswith(("aukeys-opscli", ".", "git+")):
                    violations.append(Violation(
                        "PKG-001", "warning", f"依赖未使用 == 锁版本：{value}",
                        "将第三方依赖改为 package==version。", "requirements.txt", line_number,
                    ))

        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink() or path.suffix.lower() not in _DB_FILE_SUFFIXES:
                continue
            relative = path.relative_to(root).as_posix()
            if any(part in {".git", ".venv", "venv"} for part in path.relative_to(root).parts):
                continue
            violations.append(Violation(
                "DB-001", "block", "项目目录禁止包含 SQLite 数据库文件。",
                "删除数据库文件；运行时只通过 APP_DB_PATH/get_engine() 访问平台数据盘。", relative,
            ))

        for path in build_file_set(root):
            relative = path.relative_to(root).as_posix()
            if path.suffix.lower() in _DB_FILE_SUFFIXES:
                continue
            if path.suffix.lower() not in {".py", ".sql"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            lines = text.splitlines()
            for line_number, line in enumerate(lines, 1):
                if path.suffix.lower() == ".py":
                    match = _CONNECT_LITERAL.search(line)
                    if match:
                        violations.append(Violation(
                            "DB-001", "block", f"SQLite 路径被硬编码为 {match.group(1)!r}。",
                            "使用 get_engine()，或读取 APP_DB_PATH。", relative, line_number,
                        ))
                    if _SQL_INTERPOLATION.search(line):
                        violations.append(Violation(
                            "DB-005", "block", "SQL 执行语句疑似拼接用户输入。",
                            "改用参数化 SQL，不要使用 f-string、format 或 % 拼接。", relative, line_number,
                        ))
                    if _DDL.search(line):
                        violations.append(Violation(
                            "DB-004", "warning", "业务代码中包含 DDL。",
                            "将建表和改表语句移动到 migrations/*.sql。", relative, line_number,
                        ))
                    if _BASE_PATH_LITERAL.search(line):
                        violations.append(Violation(
                            "PATH-001", "warning", "代码硬编码了 /apps/... 路径。",
                            "使用 opscli.app.base_path()。", relative, line_number,
                        ))
                    if _DIRECT_DATA_API.search(line):
                        violations.append(Violation(
                            "AUTH-004", "block", "业务代码绕过 ops_client() 直接调用取数服务。",
                            "改用 opscli.app.ops_client()，由 SDK 处理访问者身份和数据集 scope。", relative, line_number,
                        ))
                if _SENSITIVE.search(line) and _DDL.search(line):
                    violations.append(Violation(
                        "DB-006", "block", "数据库结构疑似存储 secret/token/password 等敏感字段。",
                        "不要把凭据写入应用 SQLite；改用 opscli app secret。", relative, line_number,
                    ))
        return _deduplicate(violations)


def _requirement_name(line: str) -> str:
    value = line.strip().lower()
    for marker in ("==", ">=", "<=", "~=", "!=", "[", ";", " "):
        value = value.split(marker, 1)[0]
    return value.replace("_", "-")


def _deduplicate(items: list[Violation]) -> list[Violation]:
    seen: set[tuple] = set()
    result: list[Violation] = []
    for item in items:
        key = (item.code, item.file, item.line, item.message)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result

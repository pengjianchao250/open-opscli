"""Rufus diagnosis report validation helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


BAD_RUFUS_PHRASES = (
    "超出了我的支持范围",
    "Sorry, something went wrong",
    "未获取到答案",
)


@dataclass(frozen=True)
class ReportValidationIssue:
    """A single report validation issue."""

    code: str
    message: str
    heading: str = ""

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "heading": self.heading}


@dataclass(frozen=True)
class ReportValidationResult:
    """Validation result for a generated Rufus diagnosis Markdown report."""

    path: str
    is_valid: bool
    title_count: int
    section_count: int
    subsection_count: int
    issues: list[ReportValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "is_valid": self.is_valid,
            "title_count": self.title_count,
            "section_count": self.section_count,
            "subsection_count": self.subsection_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


class RufusDiagnosisReportValidator:
    """Validate the fixed Listing diagnosis report generated from Rufus answers."""

    _heading_re = re.compile(r"(?m)^##\s+\d+\.|^###\s+\d+、")
    _subsection_re = re.compile(r"(?m)^###\s+\d+、.*$")
    _section_re = re.compile(r"(?m)^##\s+\d+\.")

    def validate_path(self, path: str | Path, *, expected_section_count: int = 6) -> ReportValidationResult:
        report_path = Path(path)
        try:
            text = report_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            issue = ReportValidationIssue("report_missing", f"报告文件不存在: {report_path}")
            return ReportValidationResult(
                path=report_path.as_posix(),
                is_valid=False,
                title_count=0,
                section_count=0,
                subsection_count=0,
                issues=[issue],
            )
        return self.validate_text(text, path=report_path.as_posix(), expected_section_count=expected_section_count)

    def validate_text(self, text: str, *, path: str = "", expected_section_count: int = 6) -> ReportValidationResult:
        expected_sections = max(1, int(expected_section_count or 6))
        expected_subsection_counts = self._expected_subsection_counts(expected_sections)
        title_count = len(re.findall(r"(?m)^# ASIN ", text))
        section_count = len(self._section_re.findall(text))
        subsection_count = len(self._subsection_re.findall(text))
        issues: list[ReportValidationIssue] = []

        if title_count != 1:
            issues.append(ReportValidationIssue("title_count", f"标题数量应为1，实际为{title_count}"))
        if section_count != expected_sections:
            issues.append(
                ReportValidationIssue(
                    "section_count",
                    f"二级模块数量应为{expected_sections}，实际为{section_count}",
                )
            )
        if subsection_count not in expected_subsection_counts:
            expected_display = (
                str(next(iter(expected_subsection_counts)))
                if len(expected_subsection_counts) == 1
                else "或".join(str(item) for item in sorted(expected_subsection_counts))
            )
            issues.append(
                ReportValidationIssue(
                    "subsection_count",
                    f"三级小节数量应为{expected_display}，实际为{subsection_count}",
                )
            )

        for phrase in BAD_RUFUS_PHRASES:
            if phrase in text:
                issues.append(ReportValidationIssue("rufus_bad_phrase", f"报告包含失败/拒答话术: {phrase}"))

        issues.extend(self._empty_or_placeholder_subsections(text))
        return ReportValidationResult(
            path=path,
            is_valid=not issues,
            title_count=title_count,
            section_count=section_count,
            subsection_count=subsection_count,
            issues=issues,
        )

    def _expected_subsection_counts(self, expected_sections: int) -> set[int]:
        """Return expected third-level sections for the current Rufus diagnosis template."""
        total = 0
        for index in range(1, expected_sections + 1):
            total += 6 if index == 6 else 4
        counts = {total}
        if expected_sections == 6:
            counts.add(expected_sections * 4)
        return counts

    def _empty_or_placeholder_subsections(self, text: str) -> list[ReportValidationIssue]:
        issues: list[ReportValidationIssue] = []
        headings = list(self._heading_re.finditer(text))
        for index, heading in enumerate(headings):
            heading_text = heading.group(0)
            if not heading_text.startswith("###"):
                continue
            start = heading.end()
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            body = text[start:end]
            content_lines = self._meaningful_lines(body)
            normalized = re.sub(
                r"[\s。.,，、|/\\\-_*`~：:；;（）()【】\[\]{}<>]",
                "",
                "".join(content_lines).strip().lower(),
            )
            meaningful = re.sub(r"[\s|*_`>#\-:：;,，。.!！?？]", "", "".join(content_lines))
            if normalized in {"无", "暂无", "没有", "未提供", "none", "na", "n/a"} or len(meaningful) < 20:
                issues.append(
                    ReportValidationIssue(
                        "subsection_incomplete",
                        f"小节内容为空或疑似占位，正文长度={len(meaningful)}",
                        heading=heading_text,
                    )
                )
        return issues

    def _meaningful_lines(self, body: str) -> list[str]:
        lines: list[str] = []
        for raw_line in str(body or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line == "---" or re.match(r"^-{3,}$", line):
                continue
            if re.match(r"^\|\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?$", line):
                continue
            lines.append(line)
        return lines

"""Rufus 报告校验：固定诊断模板校验（批量诊断用）与答案报告正文保真校验（CLI/MCP 发布前用）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opscli.amazon_rufus.domain.exceptions import RufusReportContentError
from opscli.amazon_rufus.services.answer_report_formatter import compact_for_compare


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


# ---- Bug 12136：Rufus 答案报告正文保真校验（适用于任意题目，CLI 与 MCP 共用） ----

# 正文指纹长度：取规整后的前 24 个字符在报告中做子串匹配，足以区分不同句子，
# 又不受渲染器改写行尾（诊断模板拆表格、合并续行）的影响。
FINGERPRINT_CHARS = 24
# 参与指纹的文本最少字符数：过短的片段（如「分析结果」「Ideal」）容易在报告中偶然命中，没有区分度。
MIN_FINGERPRINT_LINE_CHARS = 8
# 行首「标签：」前缀（如「第一点：」「现有表达：」「当前标题：」）：诊断模板推断小节时会剥掉这类前缀只保留值。
_LABEL_PREFIX_RE = re.compile(r"^\s*[^：:|｜]{1,8}[：:]\s*")
# 表格分隔符（半角与全角）：诊断模板会丢掉键列、只把值列放进自己的表格，需要按单元格单独比对。
_CELL_SEPARATOR_RE = re.compile(r"[|｜]")
# 链接只匹配 ASCII 可见字符：Rufus 正文常把链接与中文连写（如「…/dp/B0XX，桌面厚实」），\S+ 会把后面的中文正文一起吞掉。
_URL_RE = re.compile(r"https?://[\x21-\x7e]+")
# 渲染时会被清空的正文字段：骨架报告用它们置空后的数据渲染，只剩模板自己生成的文字。
_BODY_KEYS = ("answer", "text", "blocks", "summaryText", "summary")
# 结构化诊断报告字段：渲染器优先用它出报告，骨架报告里同样要清空。
_STRUCTURED_REPORT_KEYS = ("diagnosis_report", "diagnosisReport", "listing_optimization_report", "listingOptimizationReport")
# Rufus 占位类回答（思考中、官方错误占位）：报告里虽有文字，但不是答案正文，按无正文处理，走 EMPTY_CONTENT 重试路径。
_PLACEHOLDER_ERROR_REASONS = {"thinking_placeholder", "official_error_placeholder"}
# 占位词（比较时转小写）：一题去掉回显的模板行后只剩这些词，等同于没有答案正文；
# 「无」还与诊断模板补的占位无法区分。
_PLACEHOLDER_WORDS = {"无", "暂无", "暂无数据", "没有", "未提供", "none", "na", "n/a"}
# 以「N、」开头的行：诊断题的小节标题写法，短标题（如「1、产品定位」）也要识别为回显的模板行。
_NUMBERED_LINE_RE = re.compile(r"^\s*\d+、")
# 「标题：值」同行写法，用于识别「1、当前标题内容：无」这类回显标题加占位词的行。
_LABEL_LINE_RE = re.compile(r"^\s*([^：:|｜]{1,12})[：:]\s*(.*)$")


def skeleton_report_data(data: dict) -> dict:
    """返回清空所有正文字段后的数据副本，用同一渲染器渲染即得到只含模板文字的骨架报告。

    题目、商品链接、推荐 ASIN 等非正文字段原样保留，因此它们在骨架报告中的行也会出现。
    """
    answers = data.get("answers")
    skeleton = {key: value for key, value in data.items() if key not in _STRUCTURED_REPORT_KEYS}
    if isinstance(answers, list):
        skeleton["answers"] = [
            {**answer, **{key: [] if key == "blocks" else "" for key in _BODY_KEYS if key in answer}}
            if isinstance(answer, dict) else answer
            for answer in answers
        ]
    return skeleton


@dataclass(frozen=True)
class AnswerReportFidelityResult:
    """报告正文保真校验结果；error_code 为 None 表示可以上传。"""

    error_code: str | None
    # 输入有正文、报告里找不到的题号；error_code 为 None 时表示部分题疑似渲染丢失，由调用方告警
    lost_question_indexes: tuple[int, ...] = ()
    empty_question_indexes: tuple[int, ...] = ()


class AnswerReportFidelityChecker:
    """比对输入 answers 的正文与落盘报告，判断每题正文是否还在。

    与只适用于 7 章节诊断模板的 RufusDiagnosisReportValidator 不同，本校验以输入正文为依据，
    自定义题与诊断题都适用。判定顺序：
    1. 所有题都没有任何源正文（Rufus 返回为空、只有商品链接、只是占位或回显模板，含缺答案的题）→ EMPTY_CONTENT；
    2. 有正文的题在报告中全部找不到 → RENDER_LOSS（原 Bug 的空壳形态，列出丢失题号）；
    3. 其余情况通过；部分题找不到时题号放进 lost_question_indexes、没有正文的题号放进
       empty_question_indexes，由调用方告警。逐题判断是启发式的，误判时最多产生告警，不阻断报告。
    不设报告级字数下限：逐题指纹命中已经证明正文在报告里，一句话的短答同样是有效回答。

    比对前先剔除模板自己生成的行：题目标题、小节标题、诊断表头、「未获取到答案」、商品链接等
    与正文无关，若参与比对，像「1、当前标题内容」或问题里的字词就会让丢失的正文看起来仍在。
    做法是用同一渲染器把正文清空后渲染一份骨架报告，骨架中出现过的行都视为模板文字，
    无需在这里维护一份模板文字清单，模板改版也不会漏剔。
    """

    def check(
        self,
        answers: Any,
        report_text: str,
        *,
        skeleton_text: str | None = None,
        question_count: int = 0,
    ) -> AnswerReportFidelityResult:
        """校验报告正文保真。

        Args:
            answers: manager 返回的 answers 列表。
            report_text: 落盘报告全文。
            skeleton_text: 同一渲染器对 skeleton_report_data(data) 的渲染结果；为 None 时不剔除模板行。
            question_count: 题目数；answers 比题目少时，缺答案的题按无正文计入 empty_question_indexes。
        """
        answer_list = answers if isinstance(answers, list) else []
        # 报告侧与源正文侧一样先剔除链接，行内链接、[标题](链接) 两侧才能按同一口径比对。
        template_lines = {line.strip() for line in _URL_RE.sub("", skeleton_text or "").splitlines()}
        # 源正文侧对称过滤用：Rufus 回显的模板行（小节标题、格式说明）不算正文
        template_compacts = {compact_for_compare(line) for line in template_lines} - {""}
        # 自定义题与诊断题模板都是每题一个「## 」标题（正文里的标题会被降级成「### 」及以下），
        # 按题切分后只在本题章节里找本题正文，避免「Customers consistently praise」这类通用句式在别的题命中。
        preamble: list[str] = []
        sections: list[list[str]] = []
        for line in _URL_RE.sub("", str(report_text or "")).splitlines():
            if line.startswith("## "):
                sections.append([])
            if line.strip() not in template_lines:
                (sections[-1] if sections else preamble).append(line)
        # 章节数与题数对不上（未知模板、正文代码块里有「## 」）时退回整篇报告比对。
        if len(sections) != len(answer_list):
            sections = [preamble + [line for section in sections for line in section]] * len(answer_list)
        lost: list[int] = []
        empty: list[int] = list(range(len(answer_list) + 1, max(question_count, len(answer_list)) + 1))
        for index, (answer, section) in enumerate(zip(answer_list, sections), start=1):
            fingerprints = [
                fingerprint
                for body in self._source_bodies(answer)
                for fingerprint in self._fingerprints(body, template_compacts)
            ]
            if not fingerprints:
                empty.append(index)
                continue
            # 任一来源、任一片段命中即视为该题正文仍在：线上缺陷是整题正文被链接替换、所有片段都找不到；
            # 渲染器会在 blocks 与 text 之间择一、剥标签前缀、丢表格键列，逐一对齐渲染规则反而容易误判丢失。
            compact_section = compact_for_compare("\n".join(section))
            if not any(fingerprint in compact_section for fingerprint in fingerprints):
                lost.append(index)
        empty.sort()
        question_total = max(question_count, len(answer_list))
        if len(empty) == question_total:
            error_code = RufusReportContentError.EMPTY_CONTENT
        # 只有「有正文的题全部丢失」才阻断：部分题丢失可能是启发式误判，报告仍有价值，交给调用方告警
        elif len(lost) == question_total - len(empty):
            error_code = RufusReportContentError.RENDER_LOSS
        else:
            error_code = None
        return AnswerReportFidelityResult(error_code, tuple(lost), tuple(empty))

    def _source_bodies(self, answer: Any) -> list[str]:
        """取每题所有可能被渲染的正文来源（answer、text、blocks、summaryText），不含商品链接。

        不假设与渲染器同一优先级（渲染器是可渲染的 blocks 优先于 text），任一来源出现在报告里就算正文在。
        isSuccess 为 False 且 text 为空（渲染器不输出这类正文）或属于思考中/官方错误占位时，按无正文处理。
        """
        if not isinstance(answer, dict):
            return []
        text = str(answer.get("text") or "")
        if answer.get("isSuccess") is False and (
            not text.strip() or answer.get("errorReason") in _PLACEHOLDER_ERROR_REASONS
        ):
            return []
        bodies = [str(answer.get("answer") or ""), text]
        blocks = answer.get("blocks")
        if isinstance(blocks, list):
            block_lines = []
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                # 结构化表格行可能只有 cells 没有 text，渲染器会用 cells 出表，这里同样取 cells；cells 不是列表时忽略。
                cells = block.get("cells")
                cell_text = " ".join(str(cell or "") for cell in cells) if isinstance(cells, list) else ""
                block_lines.append(str(block.get("text") or cell_text))
            bodies.append("\n".join(block_lines))
        bodies.append(str(answer.get("summaryText") or answer.get("summary") or ""))
        return [body for body in bodies if body.strip()]

    def _fingerprints(self, body: str, template_compacts: set[str]) -> list[str]:
        """为一段源正文生成指纹；没有真正的答案正文时返回空列表（视为无正文）。

        与报告侧剔除模板行对称，先去掉源正文里回显的模板文字：与骨架行规整后相同且像标题
        （不少于 MIN_FINGERPRINT_LINE_CHARS 个字符或以「N、」开头）的行、「模板标题：占位词」同行写法；
        剩下的行全是占位词（无、暂无、none 等）或没有可读字符时按无正文处理。
        每行再生成三类片段：整行、去掉「标签：」前缀后的文本、按竖线拆开的各单元格，
        分别对应诊断模板原样保留、剥标签前缀、丢表格键列三种渲染结果。
        """
        kept_lines: list[str] = []
        for raw_line in body.splitlines():
            line = _URL_RE.sub("", raw_line)
            compact_line = compact_for_compare(line)
            if not compact_line:
                continue
            if compact_line in template_compacts and (
                len(compact_line) >= MIN_FINGERPRINT_LINE_CHARS or _NUMBERED_LINE_RE.match(line)
            ):
                continue
            label = _LABEL_LINE_RE.match(line)
            if (
                label
                and compact_for_compare(label.group(1)) in template_compacts
                and compact_for_compare(label.group(2)).lower() in _PLACEHOLDER_WORDS
            ):
                continue
            kept_lines.append(line)
        if all(compact_for_compare(line).lower() in _PLACEHOLDER_WORDS for line in kept_lines):
            return []
        fingerprints = []
        for line in kept_lines:
            for unit in (line, _LABEL_PREFIX_RE.sub("", line), *_CELL_SEPARATOR_RE.split(line)):
                compact_unit = compact_for_compare(unit)
                if len(compact_unit) >= MIN_FINGERPRINT_LINE_CHARS:
                    fingerprints.append(compact_unit[:FINGERPRINT_CHARS])
        # 每个片段都很短（如一句话短答）时退回整段正文前缀。
        return fingerprints or [compact_for_compare("\n".join(kept_lines))[:FINGERPRINT_CHARS]]

"""Amazon Rufus 答案报告格式化服务。"""

from __future__ import annotations

import re
from typing import Any


DIAGNOSIS_SECTION_TITLES = {
    1: "标题清晰度与点击意愿分析",
    2: "五点卖点表达优化分析",
    3: "图片购买疑问解决能力分析",
    4: "A+ 内容信任增强分析",
    5: "买家评论高频夸赞与抱怨分析",
    6: "最高评分竞品完整对比分析",
    7: "最优先修改项综合判断",
}

DIAGNOSIS_SUBSECTIONS = {
    1: {
        1: "当前标题内容",
        2: "问题逐项分析",
        3: "建议优化标题",
        4: "优化核心逻辑总结",
    },
    2: {
        1: "当前五点内容",
        2: "问题逐项分析",
        3: "建议优化五点",
        4: "优化核心逻辑总结",
    },
    3: {
        1: "当前图片整体问题",
        2: "问题逐项分析",
        3: "优化优先级总结",
        4: "优化核心逻辑总结",
    },
    4: {
        1: "当前A+内容整体问题",
        2: "问题逐项分析",
        3: "优化优先级总结",
        4: "优化核心逻辑总结",
    },
    5: {
        1: "评价整体总结分析",
        2: "问题逐项分析",
        3: "优化优先级总结",
        4: "优化核心逻辑总结",
    },
    6: {
        1: "产品定位",
        2: "核心参数全面对比",
        3: "卖点优劣势对比",
        4: "评论口碑关键对比",
        5: "竞品差距与机会点",
        6: "综合结论",
    },
    7: {
        1: "核心问题定位",
        2: "最优先修改原因",
        3: "总体执行修改方案",
        4: "优化核心逻辑总结",
    },
}

DIAGNOSIS_TABLE_SCHEMAS = {
    (1, 2): {
        "headers": ["问题类型", "具体问题", "问题依据", "建议修改"],
        "mode": "issue",
    },
    (1, 4): {
        "headers": ["逻辑维度", "说明"],
        "mode": "fixed",
    },
    (2, 2): {
        "headers": ["五点序号", "问题类型", "具体问题", "问题依据", "建议修改方向"],
        "mode": "row_start",
        "row_start": r"^(?:第\s*\d+\s*点|Bullet\s*#?\d+|缺失)$",
    },
    (3, 2): {
        "headers": ["图片序号", "目标", "具体问题", "核心依据", "优化方案"],
        "mode": "row_start",
        "row_start": r"^(?:图|图片|主图|Image)\s*#?\d+|^图\d+",
    },
    (3, 3): {
        "headers": ["优先级", "图片序号", "核心价值"],
        "mode": "priority",
    },
    (4, 2): {
        "headers": ["模块", "目标", "具体问题", "核心依据", "优化方案"],
        "mode": "row_start",
        "row_start": r"^(?:模块|Module|[A-Za-z0-9+ ]+模块)",
    },
    (4, 3): {
        "headers": ["优先级", "优化项", "预期效果"],
        "mode": "priority",
    },
    (5, 1): {
        "headers": ["维度", "数据"],
        "mode": "summary_pairs",
    },
    (5, 2): {
        "headers": ["问题类型", "风险等级", "影响范围", "评论依据", "产品页面现状", "优化方案"],
        "mode": "issue",
    },
    (5, 3): {
        "headers": ["优先级", "优化项", "预期效果"],
        "mode": "priority",
    },
    (7, 2): {
        "headers": ["问题维度", "影响范围", "具体分析", "建议方案"],
        "mode": "issue",
    },
}


class AnswerReportFormatter:
    """将 Rufus 全量结果投影为前端风格的终端报告。"""

    def format_data(self, data: dict) -> str:
        """格式化 manager 返回的完整数据。"""
        structured_report = (
            data.get("diagnosis_report")
            or data.get("diagnosisReport")
            or data.get("listing_optimization_report")
            or data.get("listingOptimizationReport")
        )
        if isinstance(structured_report, dict):
            rendered = self._format_structured_diagnosis_report(data, structured_report)
            if rendered.strip():
                return rendered

        answers = data.get("answers")
        if not isinstance(answers, list) or not answers:
            return ""
        questions = self._extract_questions(data)
        return self._format_official_report(data, answers, questions)

    def _format_structured_diagnosis_report(self, data: dict, report: dict[str, Any]) -> str:
        """按结构化 JSON 渲染 Listing 优化诊断报告。"""
        asin = str(report.get("asin") or data.get("asin") or "UNKNOWN").strip().upper() or "UNKNOWN"
        sections = self._normalize_structured_sections(report.get("sections"))
        if not sections:
            return ""

        lines = [f"# ASIN {asin} Listing 优化诊断报告", ""]
        for position, section in enumerate(sections, start=1):
            section_index = self._int_value(section.get("index"), position)
            section_title = str(section.get("title") or DIAGNOSIS_SECTION_TITLES.get(section_index) or f"模块{section_index}").strip()
            lines.extend([f"## {section_index}. {section_title}", ""])
            subsections = self._normalize_structured_subsections(
                section.get("subsections") or section.get("subSections") or section.get("children")
            )
            for subsection_position, subsection in enumerate(subsections, start=1):
                subsection_index = self._int_value(subsection.get("index"), subsection_position)
                subsection_title = str(
                    subsection.get("title")
                    or DIAGNOSIS_SUBSECTIONS.get(section_index, {}).get(subsection_index)
                    or f"模块{subsection_index}"
                ).strip()
                lines.extend([f"### {subsection_index}、{subsection_title}", ""])
                rendered = self._render_structured_subsection(section_index, subsection_index, subsection)
                lines.extend(rendered or ["无"])
                lines.append("")
            if position < len(sections):
                lines.extend(["---", ""])
        return self._collapse_blank_lines("\n".join(lines).rstrip() + "\n")

    def _normalize_structured_sections(self, value: Any) -> list[dict[str, Any]]:
        """兼容 list 和 {"1": {...}} 形式的结构化章节。"""
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            sections: list[dict[str, Any]] = []
            for key, item in value.items():
                if not isinstance(item, dict):
                    continue
                section = dict(item)
                section.setdefault("index", self._int_value(key, len(sections) + 1))
                sections.append(section)
            return sorted(sections, key=lambda item: self._int_value(item.get("index"), 9999))
        return []

    def _normalize_structured_subsections(self, value: Any) -> list[dict[str, Any]]:
        """兼容 list 和 {"1": {...}} 形式的结构化小节。"""
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            subsections: list[dict[str, Any]] = []
            for key, item in value.items():
                if not isinstance(item, dict):
                    continue
                subsection = dict(item)
                subsection.setdefault("index", self._int_value(key, len(subsections) + 1))
                subsections.append(subsection)
            return sorted(subsections, key=lambda item: self._int_value(item.get("index"), 9999))
        return []

    def _render_structured_subsection(self, section_index: int, subsection_index: int, subsection: dict[str, Any]) -> list[str]:
        """渲染结构化小节，优先表格，其次 blocks/text/content。"""
        table = subsection.get("table")
        if isinstance(table, dict):
            rendered_table = self._render_structured_table(table, section_index, subsection_index)
            if rendered_table:
                return rendered_table

        rows = subsection.get("rows")
        if isinstance(rows, list):
            rendered_rows = self._render_structured_table({"rows": rows}, section_index, subsection_index)
            if rendered_rows:
                return rendered_rows

        blocks = subsection.get("blocks")
        if isinstance(blocks, list):
            return self._trim_blank(self._render_structured_blocks(blocks))

        for key in ("text", "content", "summary"):
            rendered = self._render_structured_value(subsection.get(key))
            if rendered:
                return rendered
        return []

    def _render_structured_table(self, table: dict[str, Any], section_index: int, subsection_index: int) -> list[str]:
        """渲染结构化 table，rows 支持 dict 或 list。"""
        schema_headers = DIAGNOSIS_TABLE_SCHEMAS.get((section_index, subsection_index), {}).get("headers")
        headers = table.get("headers")
        if not isinstance(headers, list) or not headers:
            headers = schema_headers if isinstance(schema_headers, list) else []
        headers = [str(header) for header in headers if str(header).strip()]
        rows = table.get("rows")
        if not isinstance(rows, list):
            return []
        if not headers:
            headers = self._headers_from_structured_rows(rows)
        if not headers:
            return []
        normalized_rows: list[list[str]] = []
        for row in rows:
            if isinstance(row, dict):
                normalized_rows.append([str(row.get(header) or "") for header in headers])
            elif isinstance(row, list):
                normalized_rows.append([str(cell or "") for cell in row])
        if not normalized_rows:
            normalized_rows = [["无", *[""] * (len(headers) - 1)]]
        return self._markdown_table(headers, normalized_rows)

    def _headers_from_structured_rows(self, rows: list[Any]) -> list[str]:
        headers: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in row.keys():
                text = str(key)
                if text not in headers:
                    headers.append(text)
        return headers

    def _render_structured_blocks(self, blocks: list[Any]) -> list[str]:
        lines: list[str] = []
        for block in blocks:
            rendered = self._render_structured_block(block)
            if not rendered:
                continue
            if lines and lines[-1] != "":
                lines.append("")
            lines.extend(rendered)
        return lines

    def _render_structured_block(self, block: Any) -> list[str]:
        if isinstance(block, str):
            return str(block).splitlines() or [str(block)]
        if not isinstance(block, dict):
            return []
        block_type = str(block.get("type") or "paragraph").strip().lower()
        if block_type in {"paragraph", "text"}:
            return self._render_structured_value(block.get("text") or block.get("content") or block.get("value"))
        if block_type == "quote":
            text = str(block.get("text") or block.get("content") or "").strip()
            return [f"> {line}" if line.strip() else ">" for line in text.splitlines()] if text else []
        if block_type == "heading":
            level = self._int_value(block.get("level"), 4)
            text = str(block.get("text") or block.get("title") or "").strip()
            return [f"{'#' * min(6, max(1, level))} {text}"] if text else []
        if block_type == "list":
            items = block.get("items")
            if not isinstance(items, list):
                return []
            lines: list[str] = []
            for item in items:
                text = self._structured_item_text(item)
                if text:
                    lines.append(f"- {text}")
            return lines
        if block_type == "table":
            return self._render_structured_table(block, 0, 0)
        if block_type == "bullet":
            label = str(block.get("label") or "").strip()
            title = str(block.get("title") or block.get("text") or "").strip()
            body = self._render_structured_value(block.get("body") or block.get("content"))
            heading = "：".join(part for part in (label, title) if part)
            return [f"#### {heading}", *body] if heading else body
        return self._render_structured_value(block.get("text") or block.get("content"))

    def _render_structured_value(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            lines: list[str] = []
            for item in value:
                if isinstance(item, dict):
                    lines.extend(self._render_structured_block(item))
                else:
                    text = str(item).strip()
                    if text:
                        lines.append(text)
            return self._trim_blank(lines)
        text = str(value).strip()
        return text.splitlines() if text else []

    def _structured_item_text(self, item: Any) -> str:
        if isinstance(item, dict):
            prefix = str(item.get("prefix") or item.get("title") or "").strip()
            text = str(item.get("text") or item.get("content") or "").strip()
            return f"**{prefix}** {text}".strip() if prefix else text
        return str(item).strip()

    def _int_value(self, value: Any, default: int) -> int:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return default

    def _extract_questions(self, data: dict) -> list[str]:
        """从全量数据中提取题目文本。"""
        raw_questions = data.get("questions")
        questions = self._normalize_question_list(raw_questions)
        if questions:
            return questions

        upload_payload = data.get("upload_payload")
        if not isinstance(upload_payload, dict):
            return []
        records = upload_payload.get("records")
        if not isinstance(records, list) or not records:
            return []
        first_record = records[0]
        if not isinstance(first_record, dict):
            return []
        return self._normalize_question_list(first_record.get("questions"))

    def _normalize_question_list(self, raw_questions: Any) -> list[str]:
        """兼容字符串题目与前端 question item。"""
        if not isinstance(raw_questions, list):
            return []
        questions: list[str] = []
        for item in raw_questions:
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = str(item.get("question") or item.get("text") or "").strip()
            else:
                text = ""
            if text:
                questions.append(text)
        return questions

    def _question_at(self, questions: list[str], index: int) -> str:
        """读取第 N 题文本，缺失时使用稳定兜底。"""
        if 0 <= index - 1 < len(questions):
            return questions[index - 1]
        return f"第 {index} 题"

    def _format_official_report(self, data: dict, answers: list[Any], questions: list[str]) -> str:
        """按 Listing 优化诊断 md 样例输出报告。"""
        asin = str(data.get("asin") or "UNKNOWN").strip().upper() or "UNKNOWN"
        lines = [f"# ASIN {asin} Listing 优化诊断报告", ""]
        for index, answer in enumerate(answers, start=1):
            section_title = DIAGNOSIS_SECTION_TITLES.get(index, f"模块{index}")
            lines.append(f"## {index}. {section_title}")
            lines.append("")
            lines.extend(self._format_diagnosis_answer(index, answer))
            if index < len(answers):
                lines.extend(["", "---", ""])
        return self._collapse_blank_lines("\n".join(lines).rstrip() + "\n")

    def _format_diagnosis_answer(self, question_index: int, answer: Any) -> list[str]:
        """将单个 Rufus JSON 答案转换为固定诊断报告章节。"""
        answer_text = self._answer_text(question_index, answer)
        if not answer_text:
            answer_text = f"第 {question_index} 题未获取到答案"
        intro, sections = self._split_numbered_sections(answer_text)
        if not sections:
            inferred_sections = self._infer_diagnosis_sections(question_index, answer_text)
            if inferred_sections:
                intro = []
                sections = inferred_sections
        lines: list[str] = []
        if intro and not sections:
            lines.extend(self._render_plain_lines(intro))
            lines.append("")
        subsection_titles = DIAGNOSIS_SUBSECTIONS.get(question_index) or {
            index: f"模块{index}" for index in range(1, 5)
        }
        max_section_index = max([*subsection_titles.keys(), *sections.keys()], default=4)
        for section_index in range(1, max_section_index + 1):
            title = subsection_titles.get(section_index, f"模块{section_index}")
            section_lines = sections.get(section_index, [])
            lines.extend([f"### {section_index}、{title}", ""])
            lines.extend(self._render_diagnosis_subsection(question_index, section_index, section_lines))
            lines.append("")
        return lines

    def _answer_text(self, index: int, answer: Any) -> str:
        """从 Rufus JSON 中提取用于二次排版的答案正文。"""
        answer_data = answer if isinstance(answer, dict) else {}
        explicit_answer = str(answer_data.get("answer") or "").strip()
        if explicit_answer:
            return self._normalize_answer_markdown(explicit_answer)
        product_links = self._format_product_links(answer_data.get("productLinks"))
        if product_links:
            return self._normalize_answer_markdown("\n".join(product_links))
        body_lines = self._format_answer_body(index, answer_data)
        if body_lines:
            return self._normalize_answer_markdown("\n".join(body_lines))
        summary_text = str(answer_data.get("summary") or answer_data.get("summaryText") or "").strip()
        if summary_text:
            return self._normalize_answer_markdown(summary_text)
        return ""

    def _normalize_answer_markdown(self, text: str) -> str:
        """保持 Rufus 文本本体，仅合并孤立列表符号和过多空行。"""
        lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        normalized: list[str] = []
        index = 0
        while index < len(lines):
            current = lines[index].rstrip()
            if current.strip() in {"•", "-", "*"}:
                next_index = index + 1
                while next_index < len(lines) and not lines[next_index].strip():
                    next_index += 1
                if next_index < len(lines):
                    normalized.append(f"- {lines[next_index].strip()}")
                    index = next_index + 1
                    continue
            normalized.append(current)
            index += 1
        return re.sub(r"\n{3,}", "\n\n", "\n".join(normalized).strip())

    def _split_numbered_sections(self, text: str) -> tuple[list[str], dict[int, list[str]]]:
        """按 1、2、3... 小节拆分 Rufus 答案。"""
        lines = self._normalize_content_lines(text)
        intro: list[str] = []
        sections: dict[int, list[str]] = {}
        current: int | None = None
        for line in lines:
            match = re.match(r"^([1-9]\d*)、(.+)$", line)
            if match:
                current = int(match.group(1))
                sections.setdefault(current, [])
                continue
            if current is None:
                intro.append(line)
            else:
                sections.setdefault(current, []).append(line)
        return intro, sections

    def _infer_diagnosis_sections(self, question_index: int, text: str) -> dict[int, list[str]]:
        """Infer target subsections from Rufus answers that did not follow the numbered prompt."""
        lines = self._normalize_content_lines(text)
        if not lines:
            return {}
        if question_index == 1:
            return self._infer_title_sections(lines)
        if question_index == 2:
            return self._infer_bullet_sections(lines)
        if question_index == 3:
            return self._infer_image_sections(lines)
        if question_index == 4:
            return self._infer_aplus_sections(lines)
        if question_index == 5:
            return self._infer_review_sections(lines)
        if question_index == 6:
            return self._infer_competitor_sections(lines)
        if question_index == 7:
            return self._infer_overall_sections(lines)
        return {}

    def _infer_title_sections(self, lines: list[str]) -> dict[int, list[str]]:
        current_idx = self._find_line(lines, r"当前标题")
        analysis_idx = self._find_line(lines, r"分析结果|问题逐项分析|维度", start=max(current_idx, 0))
        suggest_idx = self._find_line(lines, r"综合建议标题|建议优化标题", start=max(analysis_idx, 0))
        logic_idx = self._find_line(lines, r"优化点说明|优化核心逻辑|优化说明", start=max(suggest_idx, 0))
        sections: dict[int, list[str]] = {}

        title_lines = self._extract_after_marker(lines, current_idx, analysis_idx, "当前标题")
        if not title_lines:
            title_lines = self._guess_title_lines(lines)
        sections[1] = title_lines

        issue_end = suggest_idx if suggest_idx >= 0 else len(lines)
        issue_start = analysis_idx + 1 if analysis_idx >= 0 else 0
        sections[2] = self._drop_known_headers(
            lines[issue_start:issue_end],
            ["分析结果", "维度", "问题", "依据", "建议改为"],
        )

        suggestion_end = logic_idx if logic_idx >= 0 else len(lines)
        sections[3] = self._strip_marker_lines(
            lines[(suggest_idx + 1 if suggest_idx >= 0 else suggestion_end):suggestion_end],
            [r"综合建议标题", r"建议优化标题"],
        )

        logic_lines = lines[logic_idx + 1 :] if logic_idx >= 0 else []
        sections[4] = self._to_pair_lines(self._strip_bullets(logic_lines), default_key="优化点")
        return {key: value for key, value in sections.items() if value}

    def _infer_bullet_sections(self, lines: list[str]) -> dict[int, list[str]]:
        groups = self._collect_marker_groups(
            lines,
            r"^(第一点|第二点|第三点|第四点|第五点|第\s*[一二三四五六七八九十\d]+\s*点|Bullet\s*#?\d+)[:：]?\s*(.*)$",
        )
        if not groups:
            return {}
        current: list[str] = []
        issues: list[str] = []
        suggestions: list[str] = []
        for index, marker, body, chunk, _start in groups:
            title = body or marker
            current_expr = self._chunk_value(chunk, "现有表达") or ""
            problem = self._chunk_value(chunk, "问题") or "\n".join(chunk[:2]).strip()
            basis = self._chunk_value(chunk, "依据") or ""
            suggestion = self._chunk_value(chunk, "建议改为") or ""
            current.extend([f"Bullet {index}：{title}", current_expr])
            issues.extend([f"Bullet {index}", "表达与决策路径不匹配", problem, basis, suggestion])
            suggestions.extend([f"Bullet {index}：{title}", suggestion])
        summary_start = self._find_line(lines, r"综合优化|优化优先级|核心逻辑")
        summary = lines[summary_start + 1 :] if summary_start >= 0 else []
        return {1: current, 2: issues, 3: suggestions, 4: summary or self._summary_from_suggestions(suggestions)}

    def _infer_image_sections(self, lines: list[str]) -> dict[int, list[str]]:
        groups = self._collect_marker_groups(lines, r"^(图\s*\d+)[｜|—\-]?\s*(.*)$")
        if not groups:
            return {}
        first_start = groups[0][4]
        overview = lines[:first_start]
        issues: list[str] = []
        priorities: list[str] = []
        for index, marker, body, chunk, _start in groups:
            image_no = re.sub(r"\s+", "", marker)
            target = body or "图片信息表达"
            problem = self._chunk_value(chunk, "问题") or ""
            basis = self._chunk_value(chunk, "依据") or ""
            suggestion = self._chunk_value(chunk, "建议改为") or self._chunk_value(chunk, "优化方案") or ""
            issues.extend([image_no, target, problem, basis, suggestion])
            priorities.extend([f"P{min(index - 1, 3)}", image_no, self._short_value(suggestion or problem)])
        summary = ["围绕买家决策疑问重建图片顺序：先讲清产品结构，再解释功能细节，最后用尺寸、安装和变体信息降低购买不确定性。"]
        return {1: overview, 2: issues, 3: priorities, 4: summary}

    def _infer_aplus_sections(self, lines: list[str]) -> dict[int, list[str]]:
        groups = self._collect_marker_groups(lines, r"^(图\s*\d+|模块\s*\d+)[\s—｜|\-]*\s*(.*)$")
        if not groups:
            return {}
        overview = lines[: groups[0][4]]
        issues: list[str] = []
        priorities: list[str] = []
        for index, marker, body, chunk, _start in groups:
            module = f"{marker} {body}".strip()
            problem = self._chunk_value(chunk, "问题") or ""
            basis = self._chunk_value(chunk, "依据") or ""
            suggestion = self._chunk_value(chunk, "建议改为") or self._chunk_value(chunk, "改进建议") or self._chunk_value(chunk, "优化方案") or ""
            issues.extend([module, "补充关键信息并增强购买信任", problem, basis, suggestion])
            priorities.extend([f"P{min(index - 1, 3)}", module, self._short_value(suggestion or problem)])
        summary = ["A+ 不应只复述参数，应承担场景代入、细节证明和风险消除的作用，让买家在下单前确认尺寸、功能、安装与耐用性。"]
        return {1: overview, 2: issues, 3: priorities, 4: summary}

    def _infer_review_sections(self, lines: list[str]) -> dict[int, list[str]]:
        groups = self._collect_marker_groups(lines, r"^([①②③④⑤⑥⑦⑧⑨]\s*.+)$")
        if not groups:
            return {}
        summary_pairs: list[str] = []
        issues: list[str] = []
        priorities: list[str] = []
        priority_index = 0
        for _index, marker, _body, chunk, _start in groups:
            title = marker.strip()
            values = self._table_key_values(chunk)
            review = values.get("评论") or ""
            problem = values.get("问题") or ""
            basis = values.get("依据") or ""
            suggestion = values.get("建议改为") or values.get("建议") or ""
            risk = "高" if "⚠" in title or "抱怨" in "\n".join(chunk) or "负向" in review else "中"
            impact = "差评与退货风险" if risk == "高" else "转化信任与卖点强化"
            summary_pairs.extend([title, review or problem or basis])
            issues.extend([title, risk, impact, review or basis, problem, suggestion])
            if risk == "高":
                priorities.extend([f"P{priority_index}", title, self._short_value(suggestion or problem)])
                priority_index += 1
        if not priorities:
            for row_index in range(0, min(len(issues), 18), 6):
                priorities.extend([f"P{row_index // 6}", issues[row_index], self._short_value(issues[row_index + 5])])
        summary = ["评论优化的核心是放大真实优势，同时把已暴露的安装、五金、耐用性和抽屉体验风险提前解释清楚，降低期望落差。"]
        return {1: summary_pairs, 2: issues, 3: priorities, 4: summary}

    def _infer_competitor_sections(self, lines: list[str]) -> dict[int, list[str]]:
        markers = [
            r"产品定位",
            r"核心参数|参数全面对比",
            r"卖点优劣势|卖点.*对比",
            r"评论口碑|口碑关键对比",
            r"竞品差距|机会点",
            r"综合结论",
        ]
        starts: list[tuple[int, int]] = []
        for marker_index, pattern in enumerate(markers, start=1):
            idx = self._find_line(lines, pattern)
            if idx >= 0:
                starts.append((marker_index, idx))
        if not starts:
            return {}
        starts.sort(key=lambda item: item[1])
        sections: dict[int, list[str]] = {}
        for pos, (section_index, start) in enumerate(starts):
            end = starts[pos + 1][1] if pos + 1 < len(starts) else len(lines)
            sections[section_index] = self._strip_marker_lines(lines[start + 1 : end], markers)
        return {key: value for key, value in sections.items() if value}

    def _infer_overall_sections(self, lines: list[str]) -> dict[int, list[str]]:
        overall_idx = self._find_line(lines, r"^整体$")
        problem_idx = self._find_line(lines, r"^问题$")
        basis_idx = self._find_line(lines, r"^依据$")
        suggestion_idx = self._find_line(lines, r"^建议改为")
        detail_idx = self._find_line(lines, r"改动要点|优化核心逻辑")
        core = lines[overall_idx + 1 : problem_idx] if overall_idx >= 0 and problem_idx > overall_idx else lines[: max(problem_idx, 1)]
        problem = lines[problem_idx + 1 : basis_idx] if problem_idx >= 0 and basis_idx > problem_idx else []
        basis = lines[basis_idx + 1 : suggestion_idx] if basis_idx >= 0 and suggestion_idx > basis_idx else []
        suggestion = lines[suggestion_idx + 1 : detail_idx] if suggestion_idx >= 0 and detail_idx > suggestion_idx else lines[suggestion_idx + 1 :] if suggestion_idx >= 0 else []
        detail = lines[detail_idx + 1 :] if detail_idx >= 0 else []
        problem_text = "\n".join(problem).strip()
        basis_text = "\n".join(basis).strip()
        suggestion_text = "\n".join(suggestion).strip()
        reason_row = ["最优先修改项", "首屏转化与信息准确性", "\n".join(part for part in (problem_text, basis_text) if part), suggestion_text]
        return {
            1: core or problem,
            2: reason_row,
            3: suggestion,
            4: detail or ["优先处理最影响买家快速判断和下单信心的页面信息，先解决描述准确性，再补充场景化与证据型表达。"],
        }

    def _collect_marker_groups(self, lines: list[str], pattern: str) -> list[tuple[int, str, str, list[str], int]]:
        starts: list[tuple[int, re.Match[str]]] = []
        for idx, line in enumerate(lines):
            match = re.match(pattern, line, flags=re.I)
            if match:
                starts.append((idx, match))
        groups: list[tuple[int, str, str, list[str], int]] = []
        for pos, (start, match) in enumerate(starts, start=1):
            end = starts[pos][0] if pos < len(starts) else len(lines)
            marker = str(match.group(1)).strip()
            body = str(match.group(2)).strip() if match.lastindex and match.lastindex >= 2 else ""
            groups.append((pos, marker, body, lines[start + 1 : end], start))
        return groups

    def _find_line(self, lines: list[str], pattern: str, start: int = 0) -> int:
        for idx in range(max(0, start), len(lines)):
            if re.search(pattern, lines[idx], flags=re.I):
                return idx
        return -1

    def _extract_after_marker(self, lines: list[str], start: int, end: int, marker: str) -> list[str]:
        if start < 0:
            return []
        stop = end if end >= 0 else len(lines)
        first = re.sub(rf"^.*{re.escape(marker)}[:：]?\s*", "", lines[start]).strip()
        result = [first] if first and first != lines[start] else []
        result.extend(lines[start + 1 : stop])
        return self._trim_blank(result)

    def _guess_title_lines(self, lines: list[str]) -> list[str]:
        for line in lines:
            if len(line) >= 60 and re.search(r"\b(?:with|Bed|Frame|Daybed|ANCTOR)\b", line, flags=re.I):
                return [line]
        return []

    def _strip_marker_lines(self, lines: list[str], patterns: list[str]) -> list[str]:
        return [line for line in lines if not any(re.search(pattern, line, flags=re.I) for pattern in patterns)]

    def _strip_bullets(self, lines: list[str]) -> list[str]:
        result: list[str] = []
        for line in lines:
            text = re.sub(r"^[-*•\s]+", "", line).strip()
            text = re.sub(r"^[✅✔]+", "", text).strip()
            if text:
                result.append(text)
        return result

    def _to_pair_lines(self, lines: list[str], *, default_key: str) -> list[str]:
        pairs: list[str] = []
        for line in lines:
            if not line:
                continue
            for sep in ("→", "：", ":"):
                if sep in line:
                    left, right = line.split(sep, 1)
                    pairs.extend([left.strip() or default_key, right.strip()])
                    break
            else:
                pairs.extend([default_key, line])
        return pairs

    def _chunk_value(self, chunk: list[str], label: str) -> str:
        start = self._find_line(chunk, rf"^{re.escape(label)}[:：]?$|^{re.escape(label)}[:：]")
        if start < 0:
            return ""
        next_labels = ["现有表达", "问题", "依据", "建议改为", "改进建议", "优化方案"]
        end = len(chunk)
        for idx in range(start + 1, len(chunk)):
            if any(re.match(rf"^{re.escape(item)}[:：]?$|^{re.escape(item)}[:：]", chunk[idx]) for item in next_labels):
                end = idx
                break
        first = re.sub(rf"^{re.escape(label)}[:：]\s*", "", chunk[start]).strip()
        values = ([first] if first and first != chunk[start] else []) + chunk[start + 1 : end]
        return "\n".join(self._trim_blank(values)).strip()

    def _table_key_values(self, lines: list[str]) -> dict[str, str]:
        values: dict[str, str] = {}
        for line in lines:
            cells = self._parse_pipe_row(line)
            if not cells or len(cells) < 2:
                continue
            key = cells[0].strip()
            value = " | ".join(cells[1:]).strip()
            if key and key not in {"---", "项目"} and value and not re.match(r"^-+$", value):
                values[key] = value
        return values

    def _summary_from_suggestions(self, lines: list[str]) -> list[str]:
        result: list[str] = []
        for line in lines:
            if line.startswith("Bullet"):
                result.append(line)
        return result or ["按买家决策路径重排五点：先讲空间与安全，再讲差异化功能，最后用结构、灯光、收纳和安装预期支撑转化。"]

    def _short_value(self, value: str, limit: int = 80) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return text[: limit - 1] + "…" if len(text) > limit else text

    def _normalize_content_lines(self, text: str) -> list[str]:
        """清理空行和孤立项目符号，保留原始语义行。"""
        raw_lines = [line.rstrip() for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        lines: list[str] = []
        index = 0
        while index < len(raw_lines):
            line = raw_lines[index].strip()
            if not line:
                index += 1
                continue
            if line in {"•", "-", "*"}:
                index += 1
                while index < len(raw_lines) and not raw_lines[index].strip():
                    index += 1
                if index < len(raw_lines):
                    lines.append(f"- {raw_lines[index].strip()}")
                index += 1
                continue
            lines.append(line)
            index += 1
        return lines

    def _render_diagnosis_subsection(self, question_index: int, section_index: int, lines: list[str]) -> list[str]:
        """按目标 md 样式渲染小节。"""
        cleaned = self._drop_intro_and_headers(question_index, section_index, lines)
        schema = DIAGNOSIS_TABLE_SCHEMAS.get((question_index, section_index))
        if schema:
            table_lines = self._render_schema_table(schema, cleaned)
            if table_lines:
                return table_lines
        if question_index == 1 and section_index == 1:
            return self._render_title_content(cleaned)
        if question_index == 1 and section_index == 3:
            return self._render_optimized_title(cleaned)
        if question_index == 2 and section_index in {1, 3}:
            return self._render_bullet_content(cleaned)
        if question_index in {2, 5, 7} and section_index == 4:
            return self._render_summary_bullets(cleaned)
        return self._render_plain_lines(cleaned)

    def _drop_intro_and_headers(self, question_index: int, section_index: int, lines: list[str]) -> list[str]:
        """移除 Rufus 返回中重复的小节标题和表头文本。"""
        headers = DIAGNOSIS_TABLE_SCHEMAS.get((question_index, section_index), {}).get("headers")
        blocked = {
            "问题逐项分析",
            "优化优先级总结",
            "优化核心逻辑总结",
            "当前标题内容",
            "当前五点内容",
            "当前图片整体问题",
            "当前A+内容整体问题",
            "评价整体总结分析",
            "产品定位",
            "核心参数全面对比",
            "卖点优劣势对比",
            "评论口碑关键对比",
            "竞品差距与机会点",
            "综合结论",
            "核心问题定位",
            "最优先修改原因",
            "总体执行修改方案",
        }
        result = [line for line in lines if line and line not in blocked and not re.match(r"^[1-9]\d*、", line)]
        if isinstance(headers, list):
            result = self._drop_known_headers(result, headers)
        return result

    def _drop_known_headers(self, lines: list[str], headers: list[str]) -> list[str]:
        """移除表头散行。"""
        result = list(lines)
        for header in headers:
            while result and result[0].strip() == header:
                result.pop(0)
                break
        return result

    def _render_schema_table(self, schema: dict[str, Any], lines: list[str]) -> list[str]:
        """渲染固定 schema 表格。"""
        headers = [str(header) for header in schema.get("headers") or []]
        if not headers:
            return []
        rows = self._parse_schema_rows(schema, lines)
        if not rows:
            rows = [["无", *[""] * (len(headers) - 1)]]
        return self._markdown_table(headers, rows)

    def _parse_schema_rows(self, schema: dict[str, Any], lines: list[str]) -> list[list[str]]:
        mode = str(schema.get("mode") or "fixed")
        headers = [str(header) for header in schema.get("headers") or []]
        if mode == "row_start":
            return self._parse_row_start_rows(lines, len(headers), str(schema.get("row_start") or ""))
        if mode == "priority":
            return self._parse_fixed_rows(lines, len(headers), last_cell_continues=False)
        if mode == "summary_pairs":
            return self._parse_summary_pairs(lines)
        if mode == "issue":
            return self._parse_fixed_rows(lines, len(headers), last_cell_continues=True)
        return self._parse_fixed_rows(lines, len(headers), last_cell_continues=False)

    def _parse_row_start_rows(self, lines: list[str], width: int, row_start: str) -> list[list[str]]:
        if not row_start:
            return self._parse_fixed_rows(lines, width, last_cell_continues=True)
        starts = [idx for idx, line in enumerate(lines) if re.search(row_start, line, flags=re.I)]
        if not starts:
            return self._parse_fixed_rows(lines, width, last_cell_continues=True)
        rows: list[list[str]] = []
        for pos, start in enumerate(starts):
            end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
            chunk = lines[start:end]
            row = chunk[: width - 1]
            tail = chunk[width - 1 :]
            row.append("\n".join(tail).strip() if tail else "")
            rows.append(self._pad_row(row, width))
        return rows

    def _parse_fixed_rows(self, lines: list[str], width: int, *, last_cell_continues: bool) -> list[list[str]]:
        rows: list[list[str]] = []
        index = 0
        while index < len(lines):
            remaining = lines[index:]
            if len(remaining) < width:
                if rows:
                    rows[-1][-1] = "\n".join([rows[-1][-1], *remaining]).strip()
                else:
                    rows.append(self._pad_row(remaining, width))
                break
            row = remaining[:width]
            index += width
            if last_cell_continues:
                while index < len(lines) and not self._looks_like_next_row_start(lines[index], len(lines) - index, width):
                    row[-1] = "\n".join([row[-1], lines[index]]).strip()
                    index += 1
            rows.append(self._pad_row(row, width))
        return rows

    def _parse_summary_pairs(self, lines: list[str]) -> list[list[str]]:
        rows: list[list[str]] = []
        index = 0
        while index < len(lines):
            key = lines[index]
            value = lines[index + 1] if index + 1 < len(lines) else ""
            rows.append([key, value])
            index += 2
        return rows

    def _looks_like_next_row_start(self, line: str, remaining_count: int, width: int) -> bool:
        if remaining_count < width:
            return False
        text = line.strip()
        if not text:
            return False
        if text.startswith(("-", "•", "*", "—", "–", '"', "'", "（", "(", ":", "：")):
            return False
        if re.match(r"^(?:第\s*\d+\s*点|Bullet\s*#?\d+|图|图片|主图|模块|P\d|缺失)", text, flags=re.I):
            return True
        if len(text) > 34:
            return False
        if text.endswith(("。", ".", "；", ";", "，", ",", "：", ":")):
            return False
        return True

    def _pad_row(self, row: list[str], width: int) -> list[str]:
        if len(row) >= width:
            return [*row[: width - 1], "\n".join(row[width - 1 :]).strip()] if len(row) > width else row
        return [*row, *[""] * (width - len(row))]

    def _markdown_table(self, headers: list[str], rows: list[list[str]]) -> list[str]:
        table = [
            "| " + " | ".join(self._md_cell(header) for header in headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for row in rows:
            table.append("| " + " | ".join(self._md_cell(cell) for cell in self._pad_row(row, len(headers))) + " |")
        return table

    def _md_cell(self, value: Any) -> str:
        text = "" if value is None else str(value)
        text = re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n").replace("\r", "\n")).strip()
        text = text.replace("\\", "\\\\").replace("|", "\\|")
        return text.replace("\n", "<br>")

    def _render_title_content(self, lines: list[str]) -> list[str]:
        if not lines:
            return ["无"]
        title_lines: list[str] = []
        rest: list[str] = []
        for line in lines:
            if re.search(r"共约|字符", line):
                rest.append(f"**{line.strip('（）()')}**")
            elif not title_lines:
                title_lines.append(f"> {line}")
            else:
                rest.append(line)
        return [*title_lines, "", *rest] if rest else title_lines

    def _render_optimized_title(self, lines: list[str]) -> list[str]:
        if not lines:
            return ["无"]
        title = lines[0]
        rendered = [f"> **{title}**"]
        rest = lines[1:]
        if rest:
            rendered.extend(["", "#### 优化对比说明"])
            rendered.extend(self._render_plain_lines(rest))
        return rendered

    def _render_bullet_content(self, lines: list[str]) -> list[str]:
        if not lines:
            return ["无"]
        rendered: list[str] = []
        index = 0
        bullet_index = 1
        while index < len(lines):
            line = lines[index]
            number_match = re.match(r"^(\d+)[.)、]?$", line)
            bullet_match = re.match(r"^Bullet\s*#?(\d+)\s*[-—:：]?\s*(.*)$", line, flags=re.I)
            if number_match and index + 1 < len(lines):
                rendered.append(f"#### Bullet {number_match.group(1)}：{lines[index + 1]}")
                index += 2
                continue
            if bullet_match:
                suffix = bullet_match.group(2).strip()
                rendered.append(f"#### Bullet {bullet_match.group(1)}：{suffix}" if suffix else f"#### Bullet {bullet_match.group(1)}")
                index += 1
                continue
            if re.match(r"^[A-Z][A-Za-z0-9 +&'/-]+[:：]", line) and bullet_index <= 8:
                rendered.append(f"#### Bullet {bullet_index}：{line}")
                bullet_index += 1
            else:
                rendered.append(line)
            index += 1
            if index < len(lines) and rendered and rendered[-1]:
                rendered.append("")
        return self._trim_blank(rendered)

    def _render_summary_bullets(self, lines: list[str]) -> list[str]:
        if not lines:
            return ["无"]
        rendered: list[str] = []
        counter = 1
        for line in lines:
            if line.startswith("- "):
                rendered.append(line)
            elif self._looks_like_summary_heading(line):
                rendered.append(f"- **{counter}** {line}")
                counter += 1
            else:
                if rendered and rendered[-1].startswith("- **"):
                    rendered[-1] = f"{rendered[-1]} {line}"
                else:
                    rendered.append(line)
        return rendered

    def _looks_like_summary_heading(self, line: str) -> bool:
        text = line.strip()
        return bool(text) and len(text) <= 28 and not text.endswith(("。", ".", "；", ";", "，", ","))

    def _render_plain_lines(self, lines: list[str]) -> list[str]:
        if not lines:
            return ["无"]
        rendered: list[str] = []
        for line in lines:
            if line.startswith("- "):
                rendered.append(line)
            elif re.match(r"^Step\s+\d+", line, flags=re.I):
                rendered.extend(["", f"#### {line}"])
            else:
                rendered.append(line)
        return self._trim_blank(rendered)

    def _trim_blank(self, lines: list[str]) -> list[str]:
        start = 0
        end = len(lines)
        while start < end and not str(lines[start]).strip():
            start += 1
        while end > start and not str(lines[end - 1]).strip():
            end -= 1
        return lines[start:end] or ["无"]

    def _format_section(self, index: int, answer: Any, question: str) -> str:
        """格式化单题 section。"""
        answer_data = answer if isinstance(answer, dict) else {}
        lines = [f"## 第 {index} 题：{question}"]
        product_links = self._format_product_links(answer_data.get("productLinks"))
        if product_links:
            lines.extend(["", "### 相关产品", "", *product_links])

        summary_text = str(answer_data.get("summaryText") or "").strip()
        body_lines = self._format_answer_body(index, answer_data)
        if body_lines or not summary_text:
            lines.extend(["", "### 答案", ""])
            lines.extend(body_lines or [f"第 {index} 题未获取到答案"])

        recommended = self._format_recommended_asins(answer_data.get("recommendedAsins"))
        if recommended:
            lines.extend(["", "### 推荐 ASIN", "", *recommended])

        if summary_text:
            lines.extend(["", "### 总结", "", summary_text])
        return "\n".join(lines)

    def _format_answer_body(self, index: int, answer: dict) -> list[str]:
        """按前端 block 模型格式化答案正文。"""
        text = str(answer.get("text") or "").strip()
        if answer.get("isSuccess") is False and not text:
            return []
        blocks = self._build_answer_blocks(text, answer.get("blocks"))
        return self._render_blocks(blocks)

    def _format_product_links(self, raw_links: Any) -> list[str]:
        """格式化相关产品。"""
        return self._format_link_items(raw_links, include_source=False)

    def _format_recommended_asins(self, raw_items: Any) -> list[str]:
        """格式化推荐 ASIN。"""
        return self._format_link_items(raw_items, include_source=True)

    def _format_link_items(self, raw_items: Any, *, include_source: bool) -> list[str]:
        """兼容字符串链接和前端链接对象。"""
        if not isinstance(raw_items, list):
            return []
        lines: list[str] = []
        for item in raw_items:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    lines.append(f"- {text}")
                continue
            if not isinstance(item, dict):
                continue
            asin = str(item.get("asin") or "").strip()
            title = str(item.get("title") or item.get("href") or "").strip()
            href = str(item.get("href") or "").strip()
            source = str(item.get("source") or "").strip()
            description = str(item.get("description") or "").strip()
            label = " - ".join(part for part in (asin, title) if part)
            if include_source and source:
                label = f"{label} ({source})" if label else f"({source})"
            if label:
                lines.append(f"- {label}")
            if href:
                lines.append(f"  {href}")
            if description:
                lines.append(f"  {description}")
        return lines

    def _build_answer_blocks(self, text: str, structured_blocks: Any) -> list[dict]:
        """优先使用结构化 blocks，不可渲染时回退解析文本。"""
        if isinstance(structured_blocks, list) and structured_blocks:
            blocks = self._build_structured_answer_blocks(structured_blocks)
            if blocks:
                return blocks
        if not text:
            return []
        fallback_blocks = self._build_text_fallback_blocks(text)
        structured_fallback = self._to_structured_blocks(fallback_blocks)
        blocks = self._build_structured_answer_blocks(structured_fallback)
        return blocks or [{"type": "text", "text": text.strip()}]

    def _build_structured_answer_blocks(self, structured_blocks: list[Any]) -> list[dict]:
        """按前端结构化 block 规则组装展示块。"""
        blocks: list[dict] = []
        list_buffer: list[str] = []
        table_rows: list[list[str]] = []

        def flush_list() -> None:
            nonlocal list_buffer
            if list_buffer:
                blocks.append({"type": "list", "items": list_buffer})
                list_buffer = []

        def flush_table() -> None:
            nonlocal table_rows
            if not table_rows:
                return
            if len(table_rows) < 2:
                blocks.append({"type": "text", "text": "\n".join(" | ".join(row) for row in table_rows)})
                table_rows = []
                return
            header = table_rows[0]
            blocks.append(
                {
                    "type": "table",
                    "header": header,
                    "rows": [self._normalize_row_cells(row, len(header)) for row in table_rows[1:]],
                }
            )
            table_rows = []

        for raw_block in structured_blocks:
            if not isinstance(raw_block, dict):
                continue
            block_type = raw_block.get("type")
            text = str(raw_block.get("text") or "").strip()
            if not text and block_type != "table_row":
                continue
            if block_type == "heading":
                flush_list()
                flush_table()
                level = raw_block.get("level")
                level = level if isinstance(level, int) else 2
                blocks.append({"type": "heading", "text": text, "level": min(6, max(1, level))})
                continue
            if block_type == "paragraph":
                flush_list()
                flush_table()
                blocks.append({"type": "text", "text": text})
                continue
            if block_type == "list_item":
                flush_table()
                list_buffer.append(text)
                continue
            if block_type == "table_row":
                flush_list()
                row = self._normalize_structured_row(raw_block)
                if row:
                    table_rows.append(row)
                elif text:
                    flush_table()
                    blocks.append({"type": "text", "text": text})
        flush_list()
        flush_table()
        return blocks

    def _normalize_structured_row(self, block: dict) -> list[str] | None:
        """读取结构化表格行。"""
        cells = block.get("cells")
        if isinstance(cells, list) and cells:
            return [str(cell or "").strip() for cell in cells]
        return self._parse_pipe_row(str(block.get("text") or ""))

    def _normalize_row_cells(self, row: list[str], width: int) -> list[str]:
        """补齐或合并表格列。"""
        if len(row) == width:
            return row
        if len(row) < width:
            return [*row, *[""] * (width - len(row))]
        return [*row[: width - 1], " | ".join(row[width - 1 :])]

    def _build_text_fallback_blocks(self, text: str) -> list[dict]:
        """解析 Markdown-like 文本为中间块。"""
        lines = self._normalize_text_lines(text)
        blocks: list[dict] = []
        paragraph_buffer: list[str] = []
        in_code_fence = False

        def flush_paragraph() -> None:
            nonlocal paragraph_buffer
            paragraph = "\n".join(paragraph_buffer).strip()
            paragraph_buffer = []
            if paragraph:
                blocks.append({"kind": "text", "text": paragraph})

        index = 0
        while index < len(lines):
            line = lines[index]
            trimmed = line.strip()
            if trimmed.startswith("```"):
                in_code_fence = not in_code_fence
                paragraph_buffer.append(line.rstrip())
                index += 1
                continue
            if in_code_fence:
                paragraph_buffer.append(line.rstrip())
                index += 1
                continue
            if not trimmed:
                flush_paragraph()
                index += 1
                continue
            heading = self._parse_markdown_heading(line)
            if heading:
                flush_paragraph()
                blocks.append(heading)
                index += 1
                continue
            table = self._parse_markdown_table(lines, index)
            if table:
                flush_paragraph()
                result, next_index = table
                blocks.append(result)
                index = next_index
                continue
            list_item = self._parse_markdown_list_item(line)
            if list_item:
                flush_paragraph()
                blocks.append(list_item)
                index += 1
                continue
            is_continuation = bool(re.match(r"^\s+", line)) and blocks and blocks[-1].get("kind") == "list_item"
            if is_continuation:
                blocks[-1]["text"] = f"{blocks[-1]['text']} {trimmed}".strip()
                index += 1
                continue
            paragraph_buffer.append(line.rstrip())
            index += 1
        flush_paragraph()
        return blocks or ([{"kind": "text", "text": text.strip()}] if text.strip() else [])

    def _to_structured_blocks(self, blocks: list[dict]) -> list[dict]:
        """将中间块转换为前端结构化 block。"""
        structured: list[dict] = []
        for block in blocks:
            kind = block.get("kind")
            if kind == "heading":
                structured.append({"type": "heading", "text": block.get("text", ""), "level": block.get("level", 2)})
            elif kind == "list_item":
                structured.append({"type": "list_item", "text": block.get("text", "")})
            elif kind == "table":
                header = block.get("header") if isinstance(block.get("header"), list) else []
                rows = block.get("rows") if isinstance(block.get("rows"), list) else []
                structured.append({"type": "table_row", "text": " | ".join(header), "cells": header})
                for row in rows:
                    if isinstance(row, list):
                        structured.append({"type": "table_row", "text": " | ".join(row), "cells": row})
            else:
                structured.append({"type": "paragraph", "text": block.get("text", "")})
        return structured

    def _render_blocks(self, blocks: list[dict]) -> list[str]:
        """将展示块渲染为 Markdown-like 文本。"""
        lines: list[str] = []
        for block in blocks:
            if lines:
                lines.append("")
            block_type = block.get("type")
            if block_type == "heading":
                level = block.get("level") if isinstance(block.get("level"), int) else 2
                lines.append(f"{'#' * min(6, max(1, level + 2))} {block.get('text', '')}".strip())
            elif block_type == "list":
                for item in block.get("items", []):
                    lines.append(f"- {item}")
            elif block_type == "table":
                header = [str(cell) for cell in block.get("header", [])]
                rows = block.get("rows", [])
                if header:
                    lines.append(f"| {' | '.join(header)} |")
                    lines.append(f"| {' | '.join(['---'] * len(header))} |")
                    for row in rows:
                        if isinstance(row, list):
                            lines.append(f"| {' | '.join(str(cell) for cell in row)} |")
            else:
                text = str(block.get("text") or "").strip()
                if text:
                    lines.append(text)
        return lines

    def _normalize_text_lines(self, text: str) -> list[str]:
        """统一换行符。"""
        return str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")

    def _parse_markdown_heading(self, line: str) -> dict | None:
        """解析 Markdown 标题。"""
        match = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if not match:
            return None
        text = match.group(2).strip()
        return {"kind": "heading", "level": len(match.group(1)), "text": text} if text else None

    def _parse_markdown_list_item(self, line: str) -> dict | None:
        """解析 Markdown 列表项。"""
        trimmed = line.strip()
        unordered = re.match(r"^([-*•])\s+(.*)$", trimmed)
        if unordered:
            text = unordered.group(2).strip()
            return {"kind": "list_item", "text": text} if text else None
        ordered = re.match(r"^\d+[.)]\s+(.*)$", trimmed)
        if ordered:
            text = ordered.group(1).strip()
            return {"kind": "list_item", "text": text} if text else None
        return None

    def _parse_markdown_table(self, lines: list[str], start_index: int) -> tuple[dict, int] | None:
        """解析带 delimiter 的 Markdown 表格。"""
        header = self._parse_pipe_row(lines[start_index] if start_index < len(lines) else "")
        if not header:
            return None
        delimiter = self._parse_pipe_row(lines[start_index + 1] if start_index + 1 < len(lines) else "")
        if not delimiter or not self._is_markdown_delimiter_row(delimiter):
            return None
        rows: list[list[str]] = []
        index = start_index + 2
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                break
            row = self._parse_pipe_row(line)
            if not row or self._is_markdown_delimiter_row(row):
                break
            rows.append(row)
            index += 1
        return {"kind": "table", "header": header, "rows": rows}, index

    def _parse_pipe_row(self, line: str) -> list[str] | None:
        """解析管道分隔行。"""
        if "|" not in line:
            return None
        cells = [cell.strip() for cell in line.split("|")]
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        if len(cells) < 2:
            return None
        return cells if any(cell and cell != "-" for cell in cells) else None

    def _is_markdown_delimiter_row(self, cells: list[str]) -> bool:
        """判断是否为 Markdown 表头分隔符。"""
        return bool(cells) and all(re.match(r"^:?-{3,}:?$", cell.strip()) for cell in cells)

    def _collapse_blank_lines(self, text: str) -> str:
        """压缩连续空行并清理行尾空白。"""
        lines = [line.rstrip() for line in text.splitlines()]
        collapsed: list[str] = []
        blank = False
        for line in lines:
            if not line.strip():
                if not blank:
                    collapsed.append("")
                blank = True
                continue
            collapsed.append(line)
            blank = False
        while collapsed and collapsed[-1] == "":
            collapsed.pop()
        return "\n".join(collapsed)

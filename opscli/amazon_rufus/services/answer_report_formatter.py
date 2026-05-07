"""Amazon Rufus 答案报告格式化服务。"""

from __future__ import annotations

import re
from typing import Any


class AnswerReportFormatter:
    """将 Rufus 全量结果投影为前端风格的终端报告。"""

    def format_data(self, data: dict) -> str:
        """格式化 manager 返回的完整数据。"""
        answers = data.get("answers")
        if not isinstance(answers, list) or not answers:
            return ""
        questions = self._extract_questions(data)
        sections = [
            self._format_section(index, answer, self._question_at(questions, index))
            for index, answer in enumerate(answers, start=1)
        ]
        return self._collapse_blank_lines("\n\n".join(section for section in sections if section))

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

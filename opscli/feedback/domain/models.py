"""feedback 模块数据结构与 schema。"""

from __future__ import annotations

FEEDBACK_TYPES = ("bug", "feature", "data_issue", "ux", "docs", "other")
SEVERITIES = ("low", "medium", "high", "critical")
SOURCES = ("cli", "mcp", "skill", "api")

FEEDBACK_SCHEMA = {
    "source": "cli|mcp|skill|api",
    "feedback_type": "bug|feature|data_issue|ux|docs|other",
    "severity": "low|medium|high|critical",
    "title": "string, required, <=200 chars",
    "content": "string, required",
    "payload": "object|null, raw structured feedback payload",
    "context": "object|null, command/tool/skill/version/cwd context",
    "execution_summary": {
        "summary": "string, required by ops-feedback Skill",
        "failed_calls": [
            {
                "tool": "string, concrete tool or command",
                "call_params": "object, concrete important parameters and field values",
                "error_message": "string, original error code/message",
                "reason": "string, cause or explicitly marked inference",
                "fix_suggestion": "string, adopted fix or next suggestion",
            }
        ],
        "successful_calls": "array, optional",
        "final_resolution": "string, final result or next step",
    },
    "attachments": "array|null, references only",
}

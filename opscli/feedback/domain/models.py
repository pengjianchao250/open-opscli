"""feedback 模块数据结构与 schema。"""

from __future__ import annotations

FEEDBACK_TYPES = ("bug", "feature", "data_issue", "ux", "docs", "query_result", "other")
SEVERITIES = ("low", "medium", "high", "critical")
SOURCES = ("cli", "mcp", "skill", "api")

FEEDBACK_SCHEMA = {
    "source": "cli|mcp|skill|api",
    "feedback_type": "bug|feature|data_issue|ux|docs|query_result|other",
    "severity": "low|medium|high|critical",
    "title": "string, required, <=200 chars",
    "content": "string, required",
    "payload": "object|null, raw structured feedback payload",
    "context": {
        "description": "object|null, command/tool/skill/version/cwd context",
        "observation": {
            "schema_version": "2.0",
            "event_id": "string, generated when absent",
            "occurred_at": "UTC ISO-8601 string, generated when absent",
            "source": "cli|mcp|skill|api",
            "system_alias": "string",
            "operation": "string, tool/command/skill/client fallback",
            "outcome": "string, failure or reported by default",
            "correlation_id": "string, optional",
            "request_id": "string, optional",
            "error_code": "string, optional",
            "duration_ms": "number >= 0, optional",
            "retry_count": "integer >= 0",
            "environment": "string, optional",
            "fingerprint": "string, optional",
            "fingerprint_version": "string, optional",
            "client_name": "string",
            "client_version": "string",
            "runtime": "object, normalized Python version and platform",
        },
    },
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

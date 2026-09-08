"""取数结果内层错误提取（CLI / REST API 共用）。

取数服务有两层错误信封：外层 Laravel 信封的字段级原因在 error_details 里，
但取数引擎自己的校验失败是包在成功的外层信封里返回的——`result.success=false`，
真正的字段级原因埋在 `result.error.details.errors[]`。若不单独提取，调用方会看到
「命令成功」却拿不到数据，只能自己去翻嵌套结构。
实测形态：limit 超上限时返回
`{"code":"VALIDATION_ERROR","message":"请求参数验证失败",
  "details":{"errors":[{"field":"body.query.limit",
                        "message":"Input should be less than or equal to 500000"}]}}`
"""

from __future__ import annotations


def extract_inner_result_error(result: object) -> dict | None:
    """提取取数服务内层的失败信息（HTTP 200 + 外层 code=200 但内层 success=false）。"""
    if not isinstance(result, dict):
        return None
    inner = result.get("result")
    if not isinstance(inner, dict) or inner.get("success") is not False:
        return None
    error = inner.get("error")
    if not isinstance(error, dict):
        error = {}
    message = str(error.get("message") or "取数服务返回失败但未说明原因").strip()
    reasons = field_level_reasons(error.get("details"))
    return {
        "code": str(error.get("code") or "QUERY_SERVICE_ERROR"),
        "message": f"{message}（{reasons}）" if reasons else message,
        "details": error.get("details"),
    }


def field_level_reasons(details: object) -> str:
    """把取数引擎的 details.errors[] 压成一行可读原因。"""
    if not isinstance(details, dict):
        return ""
    errors = details.get("errors")
    if not isinstance(errors, (list, tuple)):
        return ""
    parts = []
    for item in errors[:6]:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        text = str(item.get("message") or "").strip()
        if field and text:
            parts.append(f"{field}: {text}")
        elif text:
            parts.append(text)
    return "；".join(parts)

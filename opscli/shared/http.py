"""统一远端 HTTP 响应解析。

将 query 和 amazon 模块中重复的 HTTP 响应解析逻辑提取为共享函数，
确保错误识别、消息提取、异常抛出行为一致。
"""
from __future__ import annotations

import httpx


def extract_error_message(payload: dict) -> str | None:
    """从远端返回中提取最有价值的错误信息。

    按优先级依次检查 msg / message / error 三个常用字段，
    返回第一个非空字符串值。

    Args:
        payload: 远端返回的 JSON 字典

    Returns:
        提取到的错误信息，或 None（未找到有效信息）
    """
    for key in ("msg", "message", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_remote_response(
    response: httpx.Response,
    *,
    http_error_cls: type,
    business_error_cls: type,
    bad_json_error_cls: type,
) -> dict:
    """统一解析远端 HTTP 响应，识别业务层错误并抛出对应异常。

    解析流程：
        1. 尝试 JSON 解码，失败则抛出 bad_json_error_cls
        2. HTTP 状态码 >= 400 时抛出 http_error_cls（含 status_code）
        3. 业务层 code 不为 None/0/200 时抛出 business_error_cls（含 business_code）
        4. 响应不是 dict 时抛出 bad_json_error_cls
        5. 全部通过则返回解析后的 dict

    Args:
        response: httpx.Response 原始响应对象
        http_error_cls: HTTP 错误异常类，需支持 (status_code, message) 构造
        business_error_cls: 业务错误异常类，需支持 (business_code, message) 构造
        bad_json_error_cls: JSON 解析错误异常类，需支持 (message,) 构造

    Returns:
        解析后的 JSON dict

    Raises:
        bad_json_error_cls: JSON 解码失败或结构非法
        http_error_cls: HTTP 状态码 >= 400
        business_error_cls: 业务层返回非成功 code
    """
    try:
        payload = response.json()
    except Exception as exc:
        raise bad_json_error_cls("远端返回了无法解析的 JSON") from exc

    if response.status_code >= 400:
        message = (extract_error_message(payload) if isinstance(payload, dict) else None)
        message = message or f"远端请求失败，HTTP {response.status_code}"
        raise http_error_cls(response.status_code, message)

    if isinstance(payload, dict):
        business_code = payload.get("code")
        if business_code not in (None, 0, 200):
            message = extract_error_message(payload) or "远端业务执行失败"
            raise business_error_cls(business_code, message)

    if not isinstance(payload, dict):
        raise bad_json_error_cls("远端返回结构不是 JSON 对象")

    return payload
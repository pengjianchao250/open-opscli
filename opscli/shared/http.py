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


# 一条错误里最多展开多少个字段级原因：够定位即可，避免把整个校验器输出灌进终端
MAX_ERROR_DETAIL_FIELDS = 6


def extract_error_details(payload: dict) -> str | None:
    """把服务端的字段级错误详情压成一行可读中文。

    为什么必须提取：服务端（Laravel）在 ``error_details`` 里返回的是
    ``{"filters.0.operator": ["..."], "tableId": ["..."]}`` 这种字段级原因，
    而 ``msg`` 只有笼统的一句「参数验证失败」。此前解析只取 ``msg``，
    详情被整段丢弃，调用方拿不到「是哪个字段哪条规则不合法」，
    只能改写请求盲试——线上 347 条反馈都卡在这一步。
    """
    details = payload.get("error_details")
    if isinstance(details, str):
        return details.strip() or None
    parts: list[str] = []
    if isinstance(details, dict):
        for field, reasons in list(details.items())[:MAX_ERROR_DETAIL_FIELDS]:
            if isinstance(reasons, (list, tuple)):
                text = "；".join(str(item).strip() for item in reasons if str(item).strip())
            else:
                text = str(reasons).strip()
            if text:
                parts.append(f"{field}: {text}")
    elif isinstance(details, (list, tuple)):
        parts = [str(item).strip() for item in details[:MAX_ERROR_DETAIL_FIELDS] if str(item).strip()]
    if not parts:
        return None
    suffix = " …" if _detail_count(details) > MAX_ERROR_DETAIL_FIELDS else ""
    return "；".join(parts) + suffix


def _detail_count(details: object) -> int:
    """错误详情的条目数，用于判断是否需要标注省略。"""
    if isinstance(details, dict):
        return len(details)
    if isinstance(details, (list, tuple)):
        return len(details)
    return 0


def _with_details(message: str, payload: dict) -> str:
    """把字段级原因拼到主消息后面。

    直接改写 message 而不是给异常加参数：各模块的业务异常构造签名都是
    ``(code, message)`` 两参，加参数要动十几处调用点；而所有消费方（终端输出、
    反馈提交、Agent 读取）看的都是 message，拼进去即可全链路生效。
    """
    details = extract_error_details(payload)
    if not details or details in message:
        return message
    return f"{message}（{details}）"


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
        if isinstance(payload, dict):
            message = _with_details(message, payload)
        raise http_error_cls(response.status_code, message)

    if isinstance(payload, dict):
        business_code = payload.get("code")
        if business_code not in (None, 0, 200):
            message = extract_error_message(payload) or "远端业务执行失败"
            raise business_error_cls(business_code, _with_details(message, payload))

    if not isinstance(payload, dict):
        raise bad_json_error_cls("远端返回结构不是 JSON 对象")

    return payload
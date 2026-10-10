"""统一远端 HTTP 响应解析。

将 query 和 amazon 模块中重复的 HTTP 响应解析逻辑提取为共享函数，
确保错误识别、消息提取、异常抛出行为一致。
"""
from __future__ import annotations

import re

import httpx

# 非 JSON 错误页只摘 <title>：nginx/网关错误页标题很短（如「504 Gateway Time-out」），80 字足够定位
MAX_ERROR_TITLE_CHARS = 80
# <title> 一定出现在页面头部，只在前 4KB 内查找，避免对超大错误页做全文正则
_TITLE_SCAN_CHARS = 4096
_TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
# 标题命中这些模式时可能回显了凭证或请求原文（如把 Cookie 头拼进错误页标题），一律用占位替换
_SENSITIVE_TITLE_PATTERN = re.compile(r"cookie|session|token|curl|passw|secret|authoriz|bearer|=", re.IGNORECASE)


def describe_non_json_response(response: httpx.Response) -> str:
    """生成非 JSON 响应的脱敏诊断摘要，供错误消息定位「哪个接口、什么形态的响应」。

    只输出 Content-Type、是否空 body、请求路径，以及 4xx/5xx HTML 错误页的 ``<title>``：
    - 请求路径只取 path，不带 query——query 里可能有业务参数或凭证；
    - 2xx 响应绝不截取 body 任何内容：例如平台 Cookie 接口的 2xx body 就是 Amazon Cookie 原文，
      即使 body 混入了 PHP Warning 导致解析失败，也不回显；
    - 非 HTML 的错误正文（如 PHP fatal 文本）同样不回显、不摘标题，避免带出服务器路径等内部信息；
    - 标题命中 cookie/session/token/curl/= 等敏感模式时用占位替换；
    - 不写 body 字节数：字节数随响应浮动，写进消息会让反馈按「错误码+消息」去重的指纹漂移，
      只保留稳定的「空 body」标记（空 body 与非空的排查方向不同）。

    兼容只有 ``status_code`` 和 ``json()`` 的测试桩对象：取不到的字段直接省略，不额外抛错。

    Args:
        response: 解析失败的远端响应

    Returns:
        形如 ``content-type=text/html，path=/api/v1/x，title=504 Gateway Time-out`` 的摘要
    """
    headers = getattr(response, "headers", None)
    content_type = headers.get("content-type") if headers is not None else None
    # 只保留主类型，去掉 charset 等参数，摘要更短
    main_type = (content_type or "未知").split(";")[0].strip() or "未知"
    parts = [f"content-type={main_type}"]
    try:
        if not response.content:
            parts.append("空 body")
    except Exception:
        pass
    try:
        parts.append(f"path={response.request.url.path}")
    except Exception:
        # httpx.Response 未绑定 request 时访问 .request 会抛 RuntimeError，属于测试桩场景，省略即可
        pass
    if getattr(response, "status_code", 0) >= 400 and "html" in main_type.lower():
        try:
            match = _TITLE_PATTERN.search((response.text or "")[:_TITLE_SCAN_CHARS])
        except Exception:
            match = None
        title = " ".join(match.group(1).split())[:MAX_ERROR_TITLE_CHARS] if match else ""
        if title:
            parts.append("title=（已隐藏）" if _SENSITIVE_TITLE_PATTERN.search(title) else f"title={title}")
    return "，".join(parts)


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
        1. 尝试 JSON 解码；失败时先看状态码：>= 400 抛 http_error_cls（网关 502/504 HTML、
           PHP fatal 文本等），2xx/3xx 才抛 bad_json_error_cls；两者消息都带脱敏诊断摘要
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
        # 先看状态码再归类：网关超时页、5xx 纯文本、空 body 本质是 HTTP 失败，
        # 若一律报 bad_json，状态码丢失，调用方无法判断是否属于可重试的网关瞬时错误（Bug 12133）。
        diagnosis = describe_non_json_response(response)
        if response.status_code >= 400:
            raise http_error_cls(
                response.status_code,
                f"远端请求失败，HTTP {response.status_code}（非 JSON 响应；{diagnosis}）",
            ) from exc
        raise bad_json_error_cls(f"远端返回了无法解析的 JSON（HTTP {response.status_code}；{diagnosis}）") from exc

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
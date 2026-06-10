"""Amazon Rufus MCP 工具模块。

Rufus 获取能力由 MCP Tool 拥有，Skill 只保留题库数据与授权编排规则。
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.types import ToolAnnotations

from opscli.amazon_rufus.constants import DEFAULT_RUFUS_TIMEOUT_SECONDS
from opscli.amazon_rufus.services.answer_report_writer import AnswerReportWriter
from opscli.amazon_rufus.services.manager import RufusManager

from .helpers import _err, _ok


async def amazon_rufus_get(
    asin: str,
    country: str,
    question: str | None = None,
    questions: list[str] | None = None,
    skills_dir: str | None = None,
    timeout_seconds: int = DEFAULT_RUFUS_TIMEOUT_SECONDS,
) -> dict:
    """获取指定 ASIN 的 Rufus 回答并写入本地报告。

    Args:
        asin: 目标 ASIN
        country: 国家站点代码，如 US、UK、DE、JP
        question: 可选，指定单题问题；为空时读取 Skill 默认题库
        questions: 可选，指定多题问题列表；传入后跳过 Skill 默认题库
        skills_dir: 可选，自定义 Skills 根目录
        timeout_seconds: Rufus 获取超时时间；默认按每题 180 秒计
    """
    try:
        data = await _run_manager(
            "get_backend",
            asin=asin,
            country=country,
            question=question,
            questions=questions,
            skills_dir=skills_dir,
            timeout_seconds=timeout_seconds,
            include_upload_payload=False,
        )
        return _ok(_build_success_payload(data))
    except Exception as exc:
        return _rufus_error(
            "amazon_rufus_get",
            exc,
            {
                "asin": asin,
                "country": country,
                "question": question,
                "questions": questions,
                "skills_dir": skills_dir,
            },
        )


async def _run_manager(method_name: str, **kwargs: Any) -> dict:
    """在线程中执行同步 RufusManager 方法，避免阻塞 MCP 事件循环。"""

    def call() -> dict:
        manager = RufusManager()
        method = getattr(manager, method_name)
        return method(**kwargs)

    return await asyncio.to_thread(call)


def _build_success_payload(data: dict) -> dict:
    """构造 MCP allowlist 响应，避免返回内部请求字段。"""
    report_path = AnswerReportWriter().write(data)
    answers = data.get("answers")
    return {
        "report_path": report_path.as_posix(),
        "asin": str(data.get("asin") or "").strip().upper(),
        "country": str(data.get("country") or "").strip().upper(),
        "question_count": int(data.get("question_count") or len(data.get("questions") or [])),
        "answer_count": len(answers) if isinstance(answers, list) else 0,
        "next_action": "已生成 Rufus 报告，请读取 report_path 查看完整答案。",
    }


def _rufus_error(tool: str, exc: Exception, call_params: dict) -> dict:
    """按 Rufus 错误语义返回 MCP 失败结构。"""
    return _err(exc, tool=tool, call_params=call_params)


_NETWORK_WRITE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    openWorldHint=True,
    destructiveHint=False,
)


_ALL_TOOLS = [
    amazon_rufus_get,
]


def register(mcp) -> None:
    """向指定 MCP 实例注册 Amazon Rufus 工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool(annotations=_NETWORK_WRITE_ANNOTATIONS)(fn)

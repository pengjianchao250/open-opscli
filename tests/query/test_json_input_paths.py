"""JSON 传参路径的回归测试：文件（含 BOM）、stdin、以及解析失败时的可执行提示。

事故形态：内联 `--json` 在 PowerShell 下被引号与转义规则改写，服务端收到的
已不是合法 JSON（INVALID_PAYLOAD / Expecting property name enclosed in
double quotes）。线上 3987 条取数反馈里有 447 条（11.2%、98 人、近 30 天日均
5.3→9.0，涨得最快的一类）卡在这里。此前的提示只在两种窄条件下才出现，
绝大多数用户只看到一句 JSON 语法错误位置，不知道换传参方式就能绕开。

另一半是 BOM：PowerShell 的 Out-File / > 默认写 UTF-8 with BOM，
用 utf-8 读会在首字符残留 \ufeff 导致 json.loads 直接失败。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opscli.query.commands.cli import _inline_json_hint, app

runner = CliRunner()

PAYLOAD = {
    "tableId": "2",
    "metrics": [{"field": "price", "alias": "price", "aggregation": "SUM"}],
    "filters": [{"field": "date_id", "operator": ">=", "value": "2026-08-13"}],
    "limit": 1,
}


def _invoke(args, stdin: str | None = None):
    return runner.invoke(app, args, input=stdin)


def _payload_of(result) -> dict:
    return json.loads(result.stdout)["data"]["payload"]


def test_payload_file_with_bom_is_accepted(tmp_path: Path):
    """PowerShell 写出的 UTF-8 with BOM 文件必须能直接读。"""
    target = tmp_path / "p.json"
    target.write_text(json.dumps(PAYLOAD), encoding="utf-8-sig")
    result = _invoke(["simple", "--table-id", "2", "--payload", str(target)])
    assert result.exit_code == 0, result.stdout
    assert _payload_of(result)["tableId"] == 2


def test_payload_dash_reads_stdin():
    """--payload - 从 stdin 读，管道不经历 Shell 的引号重写。"""
    result = _invoke(["simple", "--table-id", "2", "--payload", "-"], stdin=json.dumps(PAYLOAD))
    assert result.exit_code == 0, result.stdout
    assert _payload_of(result)["tableId"] == 2


def test_stdin_tolerates_bom():
    """管道内容带 BOM 时同样要能解析。"""
    result = _invoke(
        ["simple", "--table-id", "2", "--payload", "-"], stdin="\ufeff" + json.dumps(PAYLOAD)
    )
    assert result.exit_code == 0, result.stdout


def test_inline_json_failure_always_offers_an_alternative():
    """内联 JSON 解析失败时必须给出可直接照做的替代命令，而不只报语法位置。"""
    result = _invoke(["simple", "--table-id", "2", "--json", "{'tableId':2}"])
    message = json.loads(result.stdout)["error"]["message"]
    assert "--payload" in message, f"未给出替代传参方式：{message}"
    assert "--payload -" in message, "未给出管道形态"


@pytest.mark.parametrize(
    "raw,fragment",
    [
        ("{'a':1}", "单引号"),
        ('{"a":"c:\\\\d"}', "双反斜杠"),
        ("not json at all", "建议改用文件或管道传参"),
    ],
)
def test_hint_covers_common_shapes(raw: str, fragment: str):
    """三种常见坏形态都要给出针对性说明；未识别时也要给通用替代方案。"""
    assert fragment in _inline_json_hint(raw)


def test_missing_payload_file_reports_path(tmp_path: Path):
    """文件不存在时如实报路径，不要退化成 JSON 语法错误。"""
    result = _invoke(["simple", "--table-id", "2", "--payload", str(tmp_path / "nope.json")])
    assert "payload 文件不存在" in json.loads(result.stdout)["error"]["message"]


# ── 取数服务内层失败必须冒泡到顶层（验证阶段发现）────────────────────────
#
# 服务端有两层错误信封：外层 Laravel（error_details，已由 shared.http 透传）
# 与取数引擎自己的结果信封。引擎校验失败时是包在**成功的**外层信封里返回的：
# HTTP 200 + code=200，但 data.result.success=false，字段级原因埋在
# data.result.error.details.errors[]。此前 CLI 对这种情况照样输出 success=true，
# 调用方看到「命令成功」却拿不到数据。实测：limit 超上限返回
# {"field":"body.query.limit","message":"Input should be less than or equal to 500000"}

from opscli.query.commands.cli import _field_level_reasons, _inner_result_error  # noqa: E402

_ENGINE_FAILURE = {
    "payload": {"tableId": 2},
    "result": {
        "success": False,
        "data": [],
        "meta": {"rowCount": 0},
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "请求参数验证失败",
            "details": {"errors": [
                {"field": "body.query.limit",
                 "message": "Input should be less than or equal to 500000"},
            ]},
        },
    },
}


def test_inner_failure_is_detected_and_carries_field_reason():
    """内层失败要被识别，且把字段级原因拼进消息。"""
    error = _inner_result_error(_ENGINE_FAILURE)
    assert error is not None
    assert error["code"] == "VALIDATION_ERROR"
    assert "body.query.limit" in error["message"]
    assert "500000" in error["message"]


def test_successful_result_is_not_flagged():
    """内层成功时不得误报。"""
    assert _inner_result_error({"result": {"success": True, "data": [{"a": 1}]}}) is None


def test_build_only_result_without_inner_result_is_ignored():
    """未 --run 的纯构造结果没有 result 键，不得误判。"""
    assert _inner_result_error({"payload": {"tableId": 2}, "output": None}) is None


def test_inner_failure_without_error_object_still_reported():
    """内层只说 success=false、不给 error 对象时也要报出来，不能静默放行。"""
    error = _inner_result_error({"result": {"success": False, "data": []}})
    assert error is not None
    assert error["code"] == "QUERY_SERVICE_ERROR"


@pytest.mark.parametrize(
    "details,expected",
    [
        ({"errors": [{"field": "a", "message": "bad"}]}, "a: bad"),
        ({"errors": [{"message": "no field"}]}, "no field"),
        ({"errors": []}, ""),
        (None, ""),
        ("not a dict", ""),
    ],
)
def test_field_level_reason_shapes(details, expected):
    assert _field_level_reasons(details) == expected


def test_engine_failure_exits_non_zero_via_cli():
    """端到端：CLI 对内层失败要输出 success=false 并以非零码退出。"""
    import json as _json
    from unittest.mock import patch

    with patch(
        "opscli.query.services.manager.QueryManager.build_simple_and_run",
        return_value=_ENGINE_FAILURE,
    ):
        result = runner.invoke(
            app, ["simple", "--table-id", "2", "--payload", "-", "--run"],
            input=_json.dumps(PAYLOAD),
        )
    assert result.exit_code == 1, "内层失败必须以非零码退出"
    body = _json.loads(result.stdout)
    assert body["success"] is False
    assert "body.query.limit" in body["error"]["message"]
    assert result.stdout.strip().count("\n") == 0, "不得重复输出（typer.Exit 被 except 接住的老问题）"

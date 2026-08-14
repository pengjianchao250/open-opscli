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

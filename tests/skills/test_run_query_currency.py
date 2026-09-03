"""返回币种 meta.currency 进入 stdout disclosures 的回归测试。

背景：服务端在 `meta.currency` 声明本次查询金额实际使用的币种（如 CNY），
旧实现只把完整返回落盘到 `full_result_file`，stdout 的 disclosures 不含币种。
Agent 为省一次工具调用往往不去读文件，于是金额结论要么不带币种，要么按
`_cny` 后缀或模型记忆的汇率自行推断——两种都是错数。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = (
    Path(__file__).parents[2]
    / "opscli"
    / "skills"
    / "templates"
    / "ops-dataset-query"
    / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import run_query  # noqa: E402


@pytest.mark.parametrize(
    "response, expected",
    [
        # 用户实测形状：币种在顶层 meta
        ({"success": True, "data": [], "meta": {"currency": "CNY"}}, "CNY"),
        # 执行器提取行数用的形状：币种在 data.result.meta
        ({"data": {"result": {"data": [], "meta": {"currency": "USD"}}}}, "USD"),
        ({"data": {"meta": {"currency": "JPY"}}}, "JPY"),
        # 大小写与空白归一为标准 ISO 4217 代码
        ({"meta": {"currency": " usd "}}, "USD"),
        # 未声明的各种形态一律返回 None，绝不猜币种
        ({"meta": {"currency": None}}, None),
        ({"meta": {"currency": ""}}, None),
        ({"meta": {"totalCount": 38}}, None),
        ({"success": True, "data": []}, None),
    ],
)
def test_extract_currency_covers_all_response_shapes(response, expected):
    """三种返回形状都要能取到币种；取不到时返回 None，不做任何推断。"""
    assert run_query._extract_currency(response) == expected


def _run_main(monkeypatch, capsys, tmp_path, response: dict) -> dict:
    """跑一次完整 main()，返回 stdout 解析出的执行器输出。"""
    monkeypatch.setattr(run_query, "_run_opscli", lambda *_a, **_k: response)
    exit_code = run_query.main(
        [
            "--table-id", "1",
            "--json", json.dumps({"metrics": [{"field": "sales", "alias": "f_sales"}]}),
            "--unsafe-unbound-plan",
            "--no-evidence",
            "--result-dir", str(tmp_path),
        ]
    )
    assert exit_code == 0
    return json.loads(capsys.readouterr().out)


def test_declared_currency_reaches_stdout_disclosures(monkeypatch, capsys, tmp_path):
    """币种有值时必须出现在 stdout 的 disclosures，Agent 无需再读全量结果文件。"""
    output = _run_main(
        monkeypatch,
        capsys,
        tmp_path,
        {"success": True, "data": [{"f_sales": 1}], "meta": {"totalCount": 1, "currency": "CNY"}},
    )

    assert output["disclosures"]["currency"] == "CNY"
    assert "CNY" in output["disclosures"]["currency_disclosure_zh"]
    assert "外部汇率" in output["disclosures"]["currency_disclosure_zh"]


def test_missing_currency_is_disclosed_as_undeclared(monkeypatch, capsys, tmp_path):
    """未声明币种时也要出披露，明确禁止推断，而不是静默省略该键。"""
    output = _run_main(
        monkeypatch,
        capsys,
        tmp_path,
        {"success": True, "data": [{"f_sales": 1}], "meta": {"totalCount": 1}},
    )

    assert output["disclosures"]["currency"] is None
    assert "未声明币种" in output["disclosures"]["currency_disclosure_zh"]

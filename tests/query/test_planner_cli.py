"""query plan / query flow CLI 子命令测试。"""

import json

from typer.testing import CliRunner

from opscli.query.commands import cli as query_cli

runner = CliRunner()


def _sample_contract():
    return {
        "contract": "query_plan_model_contract_v2",
        "query_mode": "dataset_query",
        "status": "planned",
        "model_view": {"dataset_name_zh": "即时综合数据集", "dimensions": [], "metrics": ["销售额"]},
        "execution_ref": {"query_template": {"tableId": 1}},
    }


def test_plan_command_emits_contract(monkeypatch):
    """query plan：读登录邮箱→调 run_plan→输出含 model_view 的合同包裹。"""
    captured = {}

    def _fake_run_plan(request, *, user_email, requested_fields=(), top_n=None):
        captured["request"] = request
        captured["email"] = user_email
        captured["fields"] = list(requested_fields)
        return _sample_contract()

    monkeypatch.setattr(query_cli, "run_plan", _fake_run_plan)
    monkeypatch.setattr(query_cli, "_current_email", lambda: "u@x.com")

    result = runner.invoke(query_cli.app, ["plan", "查销售额", "--field", "销售额"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["command"] == "query plan"
    assert "model_view" in payload["data"]
    assert captured["request"] == "查销售额"
    assert captured["email"] == "u@x.com"
    assert captured["fields"] == ["销售额"]


def test_plan_command_requires_login(monkeypatch):
    """未登录（无邮箱）→ 统一错误输出，退出码 1。"""
    monkeypatch.setattr(query_cli, "run_plan", lambda *a, **k: _sample_contract())

    def _no_login():
        raise RuntimeError("请先执行 opscli auth login 登录")

    monkeypatch.setattr(query_cli, "_current_email", _no_login)
    result = runner.invoke(query_cli.app, ["plan", "查销售额"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert "auth login" in payload["error"]["message"]


def test_flow_command_executes(monkeypatch):
    """query flow：调 run_flow 输出带 result 的合同。"""
    def _fake_run_flow(request, *, user_email, requested_fields=(), result_dir=None, **kwargs):
        return {**_sample_contract(), "result": {"data": {"result": {"data": [{"销售额": 100}]}}}}

    monkeypatch.setattr(query_cli, "run_flow", _fake_run_flow)
    monkeypatch.setattr(query_cli, "_current_email", lambda: "u@x.com")

    result = runner.invoke(query_cli.app, ["flow", "查销售额 近7天"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["command"] == "query flow"
    assert payload["data"]["result"]["data"]["result"]["data"] == [{"销售额": 100}]


def test_flow_command_limit_order_offset(monkeypatch):
    """query flow --limit/--order-by/--offset 解析并透传给 run_flow。"""
    captured = {}

    def _fake_run_flow(request, *, user_email, requested_fields=(), limit=None,
                       order_by=None, offset=None, result_dir=None, **kwargs):
        captured.update(limit=limit, order_by=order_by, offset=offset)
        return {**_sample_contract(), "result": {}}

    monkeypatch.setattr(query_cli, "run_flow", _fake_run_flow)
    monkeypatch.setattr(query_cli, "_current_email", lambda: "u@x.com")

    result = runner.invoke(
        query_cli.app,
        ["flow", "查销售额", "--limit", "100", "--order-by", "f_x:desc", "--order-by", "f_y", "--offset", "10"],
    )
    assert result.exit_code == 0, result.stdout
    assert captured["limit"] == 100
    assert captured["offset"] == 10
    # f_x:desc → desc True；f_y 无方向 → 默认升序 desc False
    assert captured["order_by"] == [{"field": "f_x", "desc": True}, {"field": "f_y", "desc": False}]


def test_flow_command_invalid_order_direction(monkeypatch):
    """--order-by 方向非法 → 统一错误输出，退出码 1。"""
    monkeypatch.setattr(query_cli, "run_flow", lambda *a, **k: _sample_contract())
    monkeypatch.setattr(query_cli, "_current_email", lambda: "u@x.com")
    result = runner.invoke(query_cli.app, ["flow", "查销售额", "--order-by", "f_x:bad"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False


def test_metadata_all_fields_command(monkeypatch):
    """query metadata --all-fields：走 metadata_all，输出全量字段数。"""
    class _R:
        payload = {"datasets": [{"table_id": 1}], "fields": [{"field_name": "a"}, {"field_name": "b"}]}
        stale = False
        from_cache = False

    captured = {}

    def _fake_all(self, *, user_email, base_dir=None):
        captured["email"] = user_email
        return _R()

    monkeypatch.setattr(query_cli, "_current_email", lambda: "u@x.com")
    monkeypatch.setattr(query_cli.QueryManager, "metadata_all", _fake_all)

    result = runner.invoke(query_cli.app, ["metadata", "--all-fields"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["command"] == "query metadata --all-fields"
    assert payload["data"]["field_count"] == 2
    assert payload["data"]["dataset_count"] == 1
    assert captured["email"] == "u@x.com"


def test_plan_command_query_file(monkeypatch, tmp_path):
    """--query-file 读取含特殊字符的请求原文。"""
    qf = tmp_path / "req.txt"
    qf.write_text("查询销售额 & 库存量", encoding="utf-8")
    captured = {}
    monkeypatch.setattr(
        query_cli,
        "run_plan",
        lambda request, **k: captured.update(request=request) or _sample_contract(),
    )
    monkeypatch.setattr(query_cli, "_current_email", lambda: "u@x.com")
    result = runner.invoke(query_cli.app, ["plan", "--query-file", str(qf)])
    assert result.exit_code == 0, result.stdout
    assert captured["request"] == "查询销售额 & 库存量"

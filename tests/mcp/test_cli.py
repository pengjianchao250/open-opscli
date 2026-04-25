import json

from typer.testing import CliRunner

from opscli.mcp.cli import app


runner = CliRunner()


def test_mcp_user_add_list_rotate_remove(tmp_path):
    result = runner.invoke(app, ["user", "add", "--desc", "测试", "--config-dir", str(tmp_path)])
    assert result.exit_code == 0
    created = json.loads(result.stdout)
    user_id = created["data"]["user_id"]
    api_key = created["data"]["api_key"]

    assert api_key.startswith("opscli-mcp-")

    listed = runner.invoke(app, ["user", "list", "--config-dir", str(tmp_path)])
    assert listed.exit_code == 0
    assert json.loads(listed.stdout)["data"][0]["user_id"] == user_id

    rotated = runner.invoke(app, ["user", "rotate", "--id", user_id, "--config-dir", str(tmp_path)])
    assert rotated.exit_code == 0
    assert json.loads(rotated.stdout)["data"]["api_key"] != api_key

    removed = runner.invoke(app, ["user", "remove", "--id", user_id, "--config-dir", str(tmp_path)])
    assert removed.exit_code == 0

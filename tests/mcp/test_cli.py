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


def test_mcp_upstream_validate_outputs_only_approved_metadata(tmp_path):
    config_path = tmp_path / "mcp-upstreams.json"
    config_path.write_text(
        json.dumps(
            {
                "version": 1,
                "servers": [
                    {
                        "id": "vendor",
                        "url_env": "OPSCLI_UPSTREAM_VENDOR_URL",
                        "allowed_hosts": ["mcp.vendor.example"],
                        "auth": {"type": "none"},
                        "tools": [
                            {
                                "remote_name": "search",
                                "exposed_name": "ext_vendor_search",
                                "description": "查询 Vendor 数据。",
                                "input_schema": {"type": "object", "properties": {}},
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["upstream", "validate", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["data"] == {
        "server_count": 1,
        "tool_count": 1,
        "servers": [
            {
                "id": "vendor",
                "url_env": "OPSCLI_UPSTREAM_VENDOR_URL",
                "allowed_hosts": ["mcp.vendor.example"],
                "tools": ["ext_vendor_search"],
            }
        ],
    }
    assert "secret" not in result.stdout.lower()

import json
from pathlib import Path

from typer.testing import CliRunner

from opscli.mcp.cli import app

runner = CliRunner()


def test_yingyan_example_requires_explicit_user_trigger():
    example_path = Path(__file__).parents[2] / "configs" / "mcp-upstreams.example.json"
    payload = json.loads(example_path.read_text(encoding="utf-8"))

    server = payload["servers"][0]
    descriptions = [tool["description"] for tool in server["tools"]]

    assert server["id"] == "pnd"
    assert descriptions
    assert all("仅当用户明确提到“鹰眼”" in description for description in descriptions)
    assert all("PND" not in description for description in descriptions)


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


def test_mcp_upstream_validate_never_echoes_inline_authorization(tmp_path):
    config_path = tmp_path / "mcp-upstreams.json"
    config_path.write_text(
        json.dumps(
            {
                "version": 1,
                "servers": [
                    {
                        "id": "pnd",
                        "url": "http://10.1.6.13:8008/mcp",
                        "allow_private_networks": True,
                        "auth": {
                            "type": "header",
                            "header_name": "Authorization",
                            "value": "Basic must-not-leak",
                        },
                        "caller_identity": {
                            "source": "email",
                            "location": "header",
                            "header_name": "X-Opscli-User-Email",
                            "required": True,
                        },
                        "tools": [
                            {
                                "remote_name": "list_available_datasets",
                                "exposed_name": "ext_pnd_list_available_datasets",
                                "description": "查询鹰眼数据集目录。",
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
    assert "must-not-leak" not in result.stdout
    assert "Authorization" not in result.stdout

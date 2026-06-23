from typer.testing import CliRunner

from opscli.cli import app
from opscli.seller_sprite import cli as seller_sprite_cli

runner = CliRunner()


def test_public_seller_sprite_scenarios_uses_remote_adapter(monkeypatch):
    class FakeAdapter:
        def scenarios(self):
            return {
                "success": True,
                "data": [{"id": "keyword-reverse"}],
                "error": None,
            }

    monkeypatch.setattr(seller_sprite_cli, "SellerSpriteRemoteAdapter", lambda: FakeAdapter())

    result = runner.invoke(app, ["seller-sprite", "scenarios"])

    assert result.exit_code == 0
    assert '"keyword-reverse"' in result.stdout


def test_public_seller_sprite_quota_status_uses_remote_adapter(monkeypatch):
    class FakeAdapter:
        def quota_status(self):
            return {
                "success": True,
                "data": {"service": "seller_sprite", "remaining": 4},
                "error": None,
            }

    monkeypatch.setattr(seller_sprite_cli, "SellerSpriteRemoteAdapter", lambda: FakeAdapter())

    result = runner.invoke(app, ["seller-sprite", "quota-status"])

    assert result.exit_code == 0
    assert '"remaining": 4' in result.stdout

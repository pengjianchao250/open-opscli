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

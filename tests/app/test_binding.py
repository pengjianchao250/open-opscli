"""站点绑定文件测试。"""

from pathlib import Path

import pytest

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.domain.models import SiteBinding
from opscli.app.services.binding import BindingStore


def _binding(site_id: str = "site-1") -> SiteBinding:
    return SiteBinding(
        site_id=site_id,
        site_name="销售看板",
        slug="sales-dashboard",
        repo_url="https://gitlab.example/sites/sales-dashboard.git",
    )


def test_binding_round_trip_and_source_detection(tmp_path: Path) -> None:
    store = BindingStore()

    target = store.save(tmp_path, _binding())

    assert target == tmp_path / ".opscli" / "app.json"
    assert store.load(tmp_path) == _binding()
    assert store.has_source_files(tmp_path) is False

    (tmp_path / "index.html").write_text("site", encoding="utf-8")
    assert store.has_source_files(tmp_path) is True


def test_binding_refuses_different_site(tmp_path: Path) -> None:
    store = BindingStore()
    store.save(tmp_path, _binding())

    with pytest.raises(AppProjectError) as caught:
        store.save(tmp_path, _binding("site-2"))

    assert caught.value.code == "APP-ALREADY-BOUND"

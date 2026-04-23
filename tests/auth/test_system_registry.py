import pytest
from opscli.auth.core.system_registry import SystemRegistry
from opscli.auth.exceptions import SystemNotFoundError

BUILTINS = [
    {"alias": "ops", "system_key": "ops", "url": "https://ops.example.com",
     "token_endpoint": "/v1/auth/cli-token", "source": "builtin"},
    {"alias": "polaris",  "system_key": "polaris",  "url": "https://bi.example.com",
     "token_endpoint": "/api/auth/cli-token", "source": "builtin"},
]


@pytest.fixture
def reg(tmp_path):
    return SystemRegistry(base_dir=tmp_path, builtin_systems=BUILTINS)


def test_list_returns_builtins(reg):
    aliases = [s["alias"] for s in reg.list_all()]
    assert "ops" in aliases and "polaris" in aliases


def test_get_existing(reg):
    assert reg.get("ops")["url"] == "https://ops.example.com"


def test_get_unknown_raises(reg):
    with pytest.raises(SystemNotFoundError):
        reg.get("不存在")


def test_add_and_get_local(reg):
    reg.add_local("营销部", "dept_mkt", "https://dept.example.com")
    assert reg.get("营销部")["source"] == "local"


def test_remove_local(reg):
    reg.add_local("营销部", "dept_mkt", "https://dept.example.com")
    reg.remove("营销部")
    with pytest.raises(SystemNotFoundError):
        reg.get("营销部")


def test_sync_ops_systems(reg):
    reg.sync_from_ops([{"alias": "HR部", "system_key": "xm_hr",
                        "url": "https://xm-hr.example.com",
                        "token_endpoint": "/api/auth/cli-token"}])
    assert reg.get("HR部")["source"] == "ops_sync"


def test_sync_does_not_overwrite_local(reg):
    reg.add_local("本地", "local_sys", "https://local.example.com")
    reg.sync_from_ops([{"alias": "本地", "system_key": "local_sys",
                        "url": "https://other.example.com",
                        "token_endpoint": "/api/auth/cli-token"}])
    assert reg.get("本地")["source"] == "local"
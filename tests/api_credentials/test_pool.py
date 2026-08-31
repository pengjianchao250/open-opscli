"""API 凭据池租约和状态回写测试。"""

from opscli.api_credentials.models import ApiCredentialAccount
from opscli.api_credentials.pool import ApiCredentialPool


class FakeRepository:
    def __init__(self):
        self.runtime_updates = []
        self.status_updates = []
        self.account = ApiCredentialAccount(
            account_id=7,
            provider="canopy",
            name="backup-1",
            api_key="secret-canopy-key",
            api_key_masked="secr****-key",
            status="active",
            secret_version=3,
        )

    def acquire(self, provider, *, exclude_account_ids=None):
        self.acquire_call = (provider, exclude_account_ids)
        return self.account

    def update_runtime(self, account_id, values):
        self.runtime_updates.append((account_id, values))

    def get_account(self, account_id):
        return self.account

    def set_status(self, account_id, status):
        self.status_updates.append((account_id, status))


def test_pool_returns_account_lease_without_exposing_storage_details():
    repository = FakeRepository()
    pool = ApiCredentialPool(repository=repository)

    lease = pool.acquire("canopy", exclude_account_ids={2, 3})

    assert lease.account_id == 7
    assert lease.account_name == "backup-1"
    assert lease.secret == "secret-canopy-key"
    assert lease.secret_version == 3
    assert "secret-canopy-key" not in str(lease.to_public_dict())
    assert repository.acquire_call == ("canopy", {2, 3})


def test_pool_reports_success_and_disables_invalid_account():
    repository = FakeRepository()
    pool = ApiCredentialPool(repository=repository)
    lease = pool.acquire("canopy")

    pool.report_success(lease, runtime={"remaining_quota": 99})
    pool.report_failure(
        lease,
        error_code="HTTP_401",
        message="invalid key",
        disable=True,
    )

    assert repository.runtime_updates[0][1]["remaining_quota"] == 99
    assert repository.runtime_updates[0][1]["consecutive_failures"] == 0
    assert repository.runtime_updates[1][1]["last_error_code"] == "HTTP_401"
    assert repository.status_updates == [(7, "invalid")]


def test_pool_ignores_result_from_rotated_secret_version():
    repository = FakeRepository()
    pool = ApiCredentialPool(repository=repository)
    stale = pool.acquire("canopy")
    repository.account = ApiCredentialAccount(
        **{
            **repository.account.__dict__,
            "secret_version": stale.secret_version + 1,
            "api_key": "rotated-secret",
        }
    )

    pool.report_success(stale, runtime={"remaining_quota": 1})
    pool.report_failure(stale, error_code="HTTP_401", message="old key", disable=True)

    assert repository.runtime_updates == []
    assert repository.status_updates == []

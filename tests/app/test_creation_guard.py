"""跨目录创建保护只隔离同一账号、环境和 slug。"""

from pathlib import Path

import pytest

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.services.creation_guard import CreationGuard


def test_pending_create_blocks_other_directory_and_manual_retry_stays_in_original(
    tmp_path: Path,
) -> None:
    guard = CreationGuard(tmp_path / "guard")
    original = tmp_path / "original"
    assert guard.claim("owner-env", "same-slug", original) is True

    with pytest.raises(AppProjectError) as blocked:
        guard.claim("owner-env", "same-slug", tmp_path / "other")
    assert blocked.value.code == "APP-CREATE-PENDING-ELSEWHERE"
    with pytest.raises(AppProjectError) as bypass:
        guard.claim("owner-env", "same-slug", tmp_path / "other", retry_create=True)
    assert bypass.value.code == "APP-CREATE-PENDING-ELSEWHERE"
    assert guard.claim("owner-env", "same-slug", original, retry_create=True) is False

    guard.release("owner-env", "same-slug", original)
    assert guard.claim("owner-env", "same-slug", tmp_path / "other") is True


def test_pending_create_does_not_block_other_scope_or_slug(tmp_path: Path) -> None:
    guard = CreationGuard(tmp_path / "guard")
    guard.claim("owner-one", "same-slug", tmp_path / "first")
    guard.claim("owner-two", "same-slug", tmp_path / "second")
    guard.claim("owner-one", "other-slug", tmp_path / "third")

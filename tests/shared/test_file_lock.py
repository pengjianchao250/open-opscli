"""file_lock 文件锁单测。"""
from pathlib import Path

from opscli.shared.file_lock import file_lock


def test_file_lock_basic_acquire_and_release(tmp_path: Path):
    """能进入/退出上下文，并在锁目录不存在时自动创建父目录。"""
    lock_path = tmp_path / "sub" / ".lock_x"
    with file_lock(lock_path):
        # 锁上下文内可正常执行业务
        (tmp_path / "sub" / "marker").write_text("ok", encoding="utf-8")
    assert (tmp_path / "sub" / "marker").read_text(encoding="utf-8") == "ok"


def test_file_lock_reentrant_sequential(tmp_path: Path):
    """同一路径先后两次获取锁应都成功（释放后可再获取）。"""
    lock_path = tmp_path / ".lock_y"
    with file_lock(lock_path):
        pass
    with file_lock(lock_path):
        pass

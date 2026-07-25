"""跨进程独占文件锁工具。

从 auth/core/token_manager.py 内联的 flock 逻辑抽取为可复用 context manager，
供元数据缓存等需要跨进程串行化刷新的场景使用。

Windows 无 fcntl，降级为空操作（仅依赖调用方的进程内线程锁）。
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# fcntl 仅 POSIX 可用；Windows 上导入失败则跳过跨进程锁
try:
    import fcntl

    _FCNTL_AVAILABLE = True
except ImportError:  # pragma: no cover - Windows 分支
    _FCNTL_AVAILABLE = False


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """获取基于 fcntl.flock 的独占文件锁。

    Args:
        path: 锁文件路径；父目录不存在时自动创建。

    行为：
        - POSIX：以独占方式 flock，退出时解锁。
        - Windows（无 fcntl）：直接进入/退出，不加跨进程锁。
    """
    if not _FCNTL_AVAILABLE:
        # Windows 降级：无跨进程锁，直接放行
        yield
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    # 以写模式打开锁文件；flock 作用于该文件描述符
    with open(path, "w") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX)  # 独占锁，阻塞直至获取
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)  # 显式解锁（关闭 fd 也会释放）

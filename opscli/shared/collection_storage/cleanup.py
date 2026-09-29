"""采集任务成功入库后的本地临时文件清理。"""

from __future__ import annotations

import shutil
from pathlib import Path

from opscli.shared.collection_storage.models import ParsedCollection


# 这些文件只服务于入库解析或故障对账；MySQL 入库后不再需要长期保留。
# result.json 和 export 文件继续保留，分别供任务状态和用户下载使用。
TRANSIENT_ARTIFACT_TYPES = frozenset({"params", "raw"})
TRANSIENT_DIRECTORY_NAMES = frozenset({"attempts"})


def cleanup_transient_files(document: ParsedCollection) -> None:
    """尽力删除已成功入库任务的请求参数和原始响应文件。

    清理失败不会影响已经完成的数据库事务或 Outbox 状态。文件路径来自
    Parser 校验过的任务目录，且只清理标准临时制品类型。
    """
    root_dir = document.submission.result_path.resolve().parent
    for artifact in document.artifacts:
        if artifact.artifact_type not in TRANSIENT_ARTIFACT_TYPES:
            continue
        path = artifact.path.resolve()
        try:
            path.relative_to(root_dir)
        except ValueError:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # Windows 文件占用或权限问题不应让已成功入库的任务重试。
            continue
    for name in TRANSIENT_DIRECTORY_NAMES:
        directory = root_dir / name
        if not directory.is_dir():
            continue
        try:
            shutil.rmtree(directory)
        except OSError:
            continue
    for html_path in root_dir.glob("*.html"):
        try:
            html_path.unlink(missing_ok=True)
        except OSError:
            continue

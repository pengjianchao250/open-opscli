"""卖家精灵历史数据回流脚本命令面。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from opscli.shared.collection_storage.config import load_storage_settings
from opscli.seller_sprite.history_migration import (
    PURGE_CONFIRMATION,
    HistoryMigrationError,
    HistoryMigrationRepository,
    IncompleteHistoryTask,
    SellerSpriteHistoryScanner,
    purge_verified_task,
)


def main(argv: Sequence[str] | None = None) -> int:
    """执行审计、Schema、迁移、核验或清理命令。

    Args:
        argv: 可选命令行参数；为空时读取当前进程参数。

    Returns:
        成功返回 0，数据校验未通过返回 2，运行异常返回 1。

    Raises:
        SystemExit: argparse 遇到非法命令行参数时终止解析。
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            return _audit(args)
        repository = _repository()
        if args.command == "init-schema":
            repository.create_extension_schema()
            _print_result({"success": True, "schema": "history-formatted-v2"})
            return 0
        repository.check_schema()
        if args.command == "migrate":
            return _migrate(args, repository)
        if args.command == "verify":
            return _verify(args, repository)
        if args.command == "purge":
            return _purge(args, repository)
        raise HistoryMigrationError("不支持的历史迁移命令")
    except Exception as exc:
        # 生产输出只保留稳定错误类型，避免异常文本携带源目录或数据库信息。
        _print_result(
            {
                "success": False,
                "error": {
                    "code": type(exc).__name__,
                    "message": _safe_error_message(exc),
                },
            }
        )
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="卖家精灵历史数据回流 MySQL")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="只读扫描，不连接 MySQL")
    _add_source_dir(audit)
    audit.add_argument("--limit", type=int, default=None, help="仅审计前 N 个任务")

    subparsers.add_parser("init-schema", help="创建历史迁移扩展表")

    migrate = subparsers.add_parser("migrate", help="幂等写入历史成功任务")
    _add_source_dir(migrate)
    migrate.add_argument("--batch-id", required=True)
    migrate.add_argument("--limit", type=int, default=None, help="仅迁移前 N 个任务")

    verify = subparsers.add_parser("verify", help="核对数据库与源 manifest")
    _add_source_dir(verify)
    verify.add_argument("--batch-id", required=True)

    purge = subparsers.add_parser("purge", help="清理已核验源文件")
    _add_source_dir(purge)
    purge.add_argument("--batch-id", required=True)
    purge.add_argument(
        "--confirm",
        required=True,
        help=f"必须显式传入 {PURGE_CONFIRMATION}",
    )
    return parser


def _add_source_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--source-dir",
        type=Path,
        required=True,
        help="历史 api_runs 目录；仅在当前进程使用，不写入数据库或日志",
    )


def _audit(args: argparse.Namespace) -> int:
    scanner = SellerSpriteHistoryScanner(args.source_dir)
    directories = _selected_directories(scanner, args.limit)
    audit = scanner.audit(directories)
    _print_result({"success": True, "mode": "audit", **audit.to_dict()})
    return 0 if audit.invalid_tasks == 0 else 2


def _migrate(
    args: argparse.Namespace,
    repository: HistoryMigrationRepository,
) -> int:
    scanner = SellerSpriteHistoryScanner(args.source_dir)
    directories = _selected_directories(scanner, args.limit)
    audit = scanner.audit(directories)
    repository.begin_batch(args.batch_id, audit)
    imported = 0
    skipped_existing = 0
    incomplete = 0
    failed = 0
    for index, task_dir in enumerate(directories, start=1):
        try:
            prepared = scanner.prepare(task_dir)
            outcome = repository.persist(args.batch_id, prepared)
            if outcome == "imported":
                imported += 1
            else:
                skipped_existing += 1
        except IncompleteHistoryTask:
            incomplete += 1
        except Exception:
            failed += 1
        if index % 100 == 0:
            _print_result(
                {
                    "success": True,
                    "mode": "migrate-progress",
                    "processed": index,
                    "total": len(directories),
                    "imported": imported,
                    "skipped_existing": skipped_existing,
                    "incomplete": incomplete,
                    "failed": failed,
                }
            )
    repository.finish_batch(args.batch_id, "failed" if failed else "imported")
    _print_result(
        {
            "success": failed == 0,
            "mode": "migrate",
            "batch_id": args.batch_id,
            "processed": len(directories),
            "imported": imported,
            "skipped_existing": skipped_existing,
            "incomplete": incomplete,
            "failed": failed,
        }
    )
    return 0 if failed == 0 else 2


def _verify(
    args: argparse.Namespace,
    repository: HistoryMigrationRepository,
) -> int:
    expected = repository.batch_manifests(args.batch_id)
    if not expected:
        raise HistoryMigrationError("批次没有可核验任务")
    scanner = SellerSpriteHistoryScanner(args.source_dir)
    verified = 0
    failed = 0
    found: set[str] = set()
    for task_dir in scanner.task_directories():
        try:
            prepared = scanner.prepare(task_dir)
        except Exception:
            continue
        job_id = prepared.submission.source_job_id
        if job_id not in expected:
            continue
        found.add(job_id)
        if (
            prepared.manifest_sha256 == expected[job_id]
            and repository.verify_task(args.batch_id, prepared)
        ):
            verified += 1
        else:
            failed += 1
    missing = len(set(expected) - found)
    if failed == 0 and missing == 0 and verified == len(expected):
        repository.finish_batch(args.batch_id, "verified")
    _print_result(
        {
            "success": failed == 0 and missing == 0 and verified == len(expected),
            "mode": "verify",
            "batch_id": args.batch_id,
            "expected": len(expected),
            "verified": verified,
            "failed": failed,
            "missing": missing,
        }
    )
    return 0 if failed == 0 and missing == 0 and verified == len(expected) else 2


def _purge(
    args: argparse.Namespace,
    repository: HistoryMigrationRepository,
) -> int:
    if args.confirm != PURGE_CONFIRMATION:
        raise HistoryMigrationError("源文件清理确认口令不正确")
    verified = repository.verified_manifests(args.batch_id)
    if not verified:
        raise HistoryMigrationError("批次没有已核验且可清理的任务")
    scanner = SellerSpriteHistoryScanner(args.source_dir)
    removed_tasks = 0
    removed_files = 0
    failed = 0
    found: set[str] = set()
    # 先固定目录清单；删除父目录中的普通文件不会改变嵌套任务遍历范围。
    task_directories = scanner.task_directories()
    for task_dir in task_directories:
        try:
            prepared = scanner.prepare(task_dir)
        except Exception:
            continue
        job_id = prepared.submission.source_job_id
        if job_id not in verified:
            continue
        found.add(job_id)
        try:
            removed_files += purge_verified_task(
                prepared,
                expected_manifest_sha256=verified[job_id],
                confirmation=args.confirm,
            )
            repository.mark_purged(args.batch_id, job_id)
            removed_tasks += 1
        except Exception:
            failed += 1
    missing = len(set(verified) - found)
    residual_files = sum(
        1 for path in args.source_dir.rglob("*") if path.is_file()
    )
    residual_task_dirs = max(0, len(task_directories) - len(found))
    success = (
        failed == 0
        and missing == 0
        and removed_tasks == len(verified)
        and residual_files == 0
    )
    # 只有源目录完全没有残留文件时才标记 completed；不完整或孤立文件必须人工处置。
    if success:
        repository.finish_batch(args.batch_id, "completed")
    _print_result(
        {
            "success": success,
            "mode": "purge",
            "batch_id": args.batch_id,
            "removed_tasks": removed_tasks,
            "removed_files": removed_files,
            "failed": failed,
            "missing": missing,
            "residual_task_dirs": residual_task_dirs,
            "residual_files": residual_files,
        }
    )
    return 0 if success else 2


def _selected_directories(
    scanner: SellerSpriteHistoryScanner,
    limit: int | None,
) -> tuple[Path, ...]:
    directories = scanner.task_directories()
    if limit is None:
        return directories
    if limit <= 0:
        raise HistoryMigrationError("limit 必须大于 0")
    return directories[:limit]


def _repository() -> HistoryMigrationRepository:
    settings = load_storage_settings("collector").mysql
    if not settings.configured:
        raise HistoryMigrationError("未配置完整的采集 MySQL 连接信息")
    return HistoryMigrationRepository(settings=settings)


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, HistoryMigrationError):
        message = str(exc)
        # HistoryMigrationError 只能使用受控短消息；额外兜底不回显疑似路径文本。
        if "\\" not in message and ":/" not in message and "file://" not in message.lower():
            return message
    return "操作失败；请根据错误码检查输入、Schema 或数据库连接"


def _print_result(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


def default_batch_id() -> str:
    """生成可读且不包含主机、用户或路径的批次 ID。

    Returns:
        基于 UTC 秒级时间生成的卖家精灵回填批次标识。
    """
    return "seller-sprite-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


__all__ = ["default_batch_id", "main"]

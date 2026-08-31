"""Update the local status ledger for a Sorftime queue batch."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


STATUSES = {"pending", "running", "success", "failed"}


def update_state(state_path: Path, batch_id: str, status: str, run_dir: str | None, error: str | None) -> int:
    if status not in STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(STATUSES))}")
    connection = sqlite3.connect(state_path)
    now = datetime.now(timezone.utc).isoformat()
    try:
        if status == "running":
            connection.execute(
                "UPDATE queue_items SET status = ?, attempts = attempts + 1, run_dir = COALESCE(?, run_dir), error = NULL, updated_at = ? WHERE batch_id = ?",
                (status, run_dir, now, batch_id),
            )
        else:
            connection.execute(
                "UPDATE queue_items SET status = ?, run_dir = COALESCE(?, run_dir), error = ?, updated_at = ? WHERE batch_id = ?",
                (status, run_dir, error, now, batch_id),
            )
        changed = connection.total_changes
        connection.commit()
    finally:
        connection.close()
    if changed == 0:
        raise ValueError(f"batch not found: {batch_id}")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Update Sorftime batch status in state.sqlite")
    parser.add_argument("batch_id", help="for example batch-013")
    parser.add_argument("status", choices=sorted(STATUSES))
    parser.add_argument("--state", type=Path, default=Path("test-data/sorftime/batch-queue/state.sqlite"))
    parser.add_argument("--run-dir")
    parser.add_argument("--error")
    args = parser.parse_args()
    changed = update_state(args.state, args.batch_id, args.status, args.run_dir, args.error)
    print(f"updated={changed} batch={args.batch_id} status={args.status}")


if __name__ == "__main__":
    main()

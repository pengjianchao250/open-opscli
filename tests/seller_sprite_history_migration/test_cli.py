"""验证卖家精灵历史迁移命令不会回显本地源路径。"""

import json
from pathlib import Path

from seller_sprite_history_migration.cli import main


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_audit_command_outputs_counts_without_source_path(
    tmp_path: Path,
    capsys,
) -> None:
    task_dir = tmp_path / "job-1"
    task_dir.mkdir()
    _write_json(
        task_dir / "params.json",
        {
            "request": {
                "job_id": "job-1",
                "scenario": "keyword-reverse",
                "site": "US",
            },
            "resolved_params": {},
            "payload": {},
        },
    )
    _write_json(task_dir / "raw.json", {"response": {"data": []}})
    _write_json(
        task_dir / "export.json",
        {"sheet_name": "main", "columns": ["关键词"], "rows": []},
    )
    _write_json(
        task_dir / "result.json",
        {
            "job_id": "job-1",
            "scenario": "keyword-reverse",
            "site": "US",
            "export": {"filename": "export.json", "format": "json"},
        },
    )

    exit_code = main(["audit", "--source-dir", str(tmp_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert '"complete_tasks": 1' in output
    assert str(tmp_path) not in output

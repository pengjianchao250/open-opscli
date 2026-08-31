"""ops-dataset-query Skill 的本地更新脚本。

提供独立于 `opscli skills upgrade` 的本地入口，适合在 Skill 目录内直接运行：

- `python updater.py --check`：仅检查远端版本
- `python updater.py`：执行更新
- `python updater.py --force`：强制重新拉取
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opscli.skills.models import SkillRecord
from opscli.skills.updater import SkillsUpdater


def build_record(skill_root: Path) -> SkillRecord:
    """基于当前 Skill 目录构造记录对象。"""
    data_dir = skill_root / "data"
    version_file = data_dir / "VERSION.json"
    version = "v0.0.0"
    if version_file.exists():
        payload = json.loads(version_file.read_text(encoding="utf-8"))
        version = str(payload.get("version", "v0.0.0"))

    return SkillRecord(
        name="ops-dataset-query",
        version=version,
        runtime="custom",
        root=skill_root,
        version_file=version_file,
    )


def check_update(updater: SkillsUpdater, record: SkillRecord) -> dict:
    """检查当前 Skill 是否存在远端更新。"""
    manifest = updater.fetch_manifest(record.name)
    if not manifest:
        raise ValueError("远端 manifest 不存在")

    remote_version = str(manifest.get("version", "v0.0.0"))
    compare_result = updater.compare_versions(record.version, remote_version)

    return {
        "name": record.name,
        "current_version": record.version,
        "remote_version": remote_version,
        "update_available": compare_result < 0,
    }


def _emit(payload: dict, pretty: bool) -> None:
    """统一输出 JSON。"""
    if pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))


def main() -> None:
    """运行本地更新脚本。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="仅检查远端版本，不执行更新")
    parser.add_argument("--force", action="store_true", help="强制重新下载远端数据")
    parser.add_argument("--pretty", action="store_true", help="格式化输出 JSON")
    args = parser.parse_args()

    skill_root = Path(__file__).resolve().parent.parent
    updater = SkillsUpdater()
    record = build_record(skill_root)

    try:
        if args.check:
            payload = {
                "success": True,
                "command": "ops-dataset-query updater check",
                "data": check_update(updater, record),
                "error": None,
            }
        else:
            result = updater.upgrade_ops_dataset_query(record, force=args.force)
            payload = {
                "success": True,
                "command": "ops-dataset-query updater upgrade",
                "data": result.to_dict(),
                "error": None,
            }
        _emit(payload, args.pretty)
    except Exception as exc:
        _emit(
            {
                "success": False,
                "command": "ops-dataset-query updater",
                "data": None,
                "error": str(exc),
            },
            args.pretty,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

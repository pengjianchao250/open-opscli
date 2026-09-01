"""同步或检查 AppHub 导出的 app.yaml JSON Schema。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "opscli" / "app" / "contracts" / "appyaml.schema.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apphub-repo", type=Path, default=_default_apphub_repo())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = args.apphub_repo / "docs" / "contracts" / "appyaml.schema.json"
    if not source.is_file():
        parser.error(f"找不到 AppHub schema：{source}")
    source_payload = json.loads(source.read_text(encoding="utf-8"))
    if args.check:
        target_payload = json.loads(TARGET.read_text(encoding="utf-8"))
        if source_payload != target_payload:
            print("AppHub app.yaml schema 与 opscli 打包副本不一致。")
            return 1
        print("AppHub app.yaml schema 已同步。")
        return 0
    TARGET.write_text(json.dumps(source_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已同步：{source} -> {TARGET}")
    return 0


def _default_apphub_repo() -> Path:
    configured = os.getenv("APPHUB_REPO")
    if configured:
        return Path(configured).expanduser()
    return ROOT.parent / "codex-custom-sites-all" / "ops-apphub"


if __name__ == "__main__":
    raise SystemExit(main())

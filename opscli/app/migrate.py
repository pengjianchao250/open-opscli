"""`python -m opscli.app.migrate` 入口。"""

from __future__ import annotations

import json

from opscli.app.domain.exceptions import AppError
from opscli.app.services.migrations import run_migrations


def main() -> int:
    try:
        result = run_migrations()
    except AppError as exc:
        print(json.dumps({"success": False, "error": exc.to_dict()}, ensure_ascii=False))
        return 1
    print(json.dumps({"success": True, "data": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

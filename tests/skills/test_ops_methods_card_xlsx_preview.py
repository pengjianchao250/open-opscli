import json
import subprocess
import sys
from pathlib import Path


def test_xlsx_preview_outputs_headers_and_numeric_summary():
    script = Path("opscli/skills/templates/ops-methods-card/scripts/xlsx_preview.py")
    workbook = Path("opscli/skills/templates/ops-methods-card/交叉表-1778233062511.xlsx")

    result = subprocess.run(
        [sys.executable, str(script), "--input", str(workbook), "--max-rows", "3"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )

    payload = json.loads(result.stdout)
    sheet = payload["sheets"][0]
    assert sheet["headers"] == ["SPU", "已售天数"]
    assert sheet["row_count"] > 0
    assert sheet["preview_rows"][0][0] == "BSB-131"
    assert sheet["numeric_summary"][0]["field"] == "已售天数"


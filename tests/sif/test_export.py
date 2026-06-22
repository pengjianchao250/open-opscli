from pathlib import Path
from uuid import uuid4

import pytest

from opscli.sif.domain.exceptions import SifDownloadError
from opscli.sif.sales.export import save_xlsx_bytes


def test_save_xlsx_bytes_writes_file():
    output = Path("output") / "test-artifacts" / f"sif-export-{uuid4().hex}" / "demo.xlsx"

    result = save_xlsx_bytes(content=b"xlsx", output_path=output)

    assert output.read_bytes() == b"xlsx"
    assert result.filename == "demo.xlsx"
    assert result.url == output.resolve().as_uri()


def test_save_xlsx_bytes_rejects_empty_content():
    output = Path("output") / "test-artifacts" / f"sif-export-empty-{uuid4().hex}" / "empty.xlsx"
    with pytest.raises(SifDownloadError):
        save_xlsx_bytes(content=b"", output_path=output)

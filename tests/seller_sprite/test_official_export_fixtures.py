"""SellerSprite 官网 XLSX golden fixtures 完整性测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "seller_sprite"
    / "official_exports"
)


def test_official_export_fixture_index_matches_immutable_files():
    """清单必须覆盖全部官方原件，并固定大小、哈希和 XLSX 基础结构。"""
    index = json.loads((FIXTURE_ROOT / "index.json").read_text(encoding="utf-8"))
    entries = index["fixtures"]
    indexed_paths = {entry["path"] for entry in entries}
    actual_paths = {
        path.relative_to(FIXTURE_ROOT).as_posix()
        for path in FIXTURE_ROOT.rglob("*.xlsx")
    }

    assert index["immutable"] is True
    assert indexed_paths == actual_paths
    assert len(entries) == 4

    for entry in entries:
        fixture_path = FIXTURE_ROOT / entry["path"]
        content = fixture_path.read_bytes()

        assert len(content) == entry["size"]
        assert hashlib.sha256(content).hexdigest() == entry["sha256"]
        with ZipFile(fixture_path) as archive:
            assert archive.testzip() is None
            assert "[Content_Types].xml" in archive.namelist()
            assert "xl/workbook.xml" in archive.namelist()

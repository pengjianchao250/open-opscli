"""Sif 查销量导出文件处理。"""

from __future__ import annotations

from pathlib import Path

from opscli.sif.domain.exceptions import SifDownloadError
from opscli.sif.sales.models import SifSalesExportResult


def save_xlsx_bytes(*, content: bytes | None, output_path: Path) -> SifSalesExportResult:
    """保存 Sif 下载接口返回的 XLSX 二进制。"""
    if not content:
        raise SifDownloadError(f"Sif 下载文件为空：{output_path.name}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(content)
    resolved = output_path.resolve()
    return SifSalesExportResult(path=str(resolved), filename=resolved.name, url=resolved.as_uri())


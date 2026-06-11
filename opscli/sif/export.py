"""Shared Sif export helpers."""

from __future__ import annotations

from pathlib import Path

from opscli.sif.domain.exceptions import SifDownloadError
from opscli.sif.domain.models import SifExportResult


def save_sif_xlsx(*, content: bytes | None, output_path: Path) -> SifExportResult:
    """Save XLSX bytes returned by Sif."""
    if not content:
        raise SifDownloadError(f"Sif 下载文件为空：{output_path.name}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(content)
    resolved = output_path.resolve()
    return SifExportResult(path=str(resolved), filename=resolved.name, url=resolved.as_uri())

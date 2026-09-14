"""Amazon Rufus 答案报告写入服务。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from opscli.amazon_rufus.services.answer_report_formatter import AnswerReportFormatter


class AnswerReportWriter:
    """统一写入 Rufus Markdown 答案报告。"""

    def __init__(
        self,
        formatter: AnswerReportFormatter | None = None,
        *,
        unique_filenames: bool = False,
        encoding: str = "utf-8",
    ) -> None:
        self.formatter = formatter or AnswerReportFormatter()
        self.unique_filenames = unique_filenames
        self.encoding = encoding

    def write(self, data: dict, output_dir: str | Path | None = None) -> Path:
        """格式化并写入报告，返回报告路径。"""
        target_dir = Path(output_dir) if output_dir else Path("output") / "amazon-rufus"
        target_dir.mkdir(parents=True, exist_ok=True)
        report_path = target_dir / self._build_filename(data)
        render_data = dict(data)
        render_data.setdefault("report_path", report_path.as_posix())
        report_path.write_text(self.formatter.format_data(render_data), encoding=self.encoding)
        return report_path

    def _build_filename(self, data: dict) -> str:
        """按 ASIN、秒级时间和调用级唯一标识生成文件名。"""
        asin = str(data.get("asin") or "UNKNOWN").strip().upper() or "UNKNOWN"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        unique_suffix = f"-{uuid4().hex}" if self.unique_filenames else ""
        return f"{asin}-{timestamp}{unique_suffix}.md"

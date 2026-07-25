from __future__ import annotations

from pathlib import Path

from opscli.amazon_rufus.domain.exceptions import RufusAnswerValidationError
from opscli.amazon_rufus.services.batch_backend import BatchGetBackendOptions, RufusBatchBackendRunner
from opscli.amazon_rufus.services.report_validator import RufusDiagnosisReportValidator


def _valid_report(asin: str = "B0TEST1234") -> str:
    lines = [f"# ASIN {asin} Listing 优化诊断报告", ""]
    for section in range(1, 7):
        lines.extend([f"## {section}. 模块{section}", ""])
        for subsection in range(1, 5):
            lines.extend(
                [
                    f"### {subsection}、小节{subsection}",
                    "",
                    f"这是第 {section} 个模块第 {subsection} 个小节的有效内容，包含足够的信息用于完整度校验。",
                    "",
                ]
            )
        if section < 6:
            lines.extend(["---", ""])
    return "\n".join(lines)


def test_rufus_diagnosis_report_validator_rejects_placeholder_subsection():
    text = _valid_report().replace(
        "这是第 3 个模块第 4 个小节的有效内容，包含足够的信息用于完整度校验。",
        "无",
    )

    result = RufusDiagnosisReportValidator().validate_text(text, expected_section_count=6)

    assert result.is_valid is False
    assert any(issue.code == "subsection_incomplete" and "### 4、" in issue.heading for issue in result.issues)


def test_batch_backend_runner_resumes_valid_report(tmp_path: Path):
    output_dir = tmp_path / "rufus"
    output_dir.mkdir()
    report_path = output_dir / "B0TEST1234-20260612-120000.md"
    report_path.write_text(_valid_report(), encoding="utf-8")

    def fail_manager():
        raise AssertionError("resume 命中时不应调用 Rufus manager")

    runner = RufusBatchBackendRunner(manager_factory=fail_manager)

    summary = runner.run(
        BatchGetBackendOptions(
            asins=["B0TEST1234"],
            country="US",
            questions=["1、A\n2、B\n3、C\n4、D"] * 6,
            output_dir=output_dir,
            resume=True,
        )
    )

    assert summary["success"] is True
    assert summary["data"]["skipped_count"] == 1
    assert summary["data"]["results"][0]["status"] == "skipped"
    assert summary["data"]["results"][0]["report_path"] == report_path.as_posix()


def test_batch_backend_runner_falls_back_to_safe_serial_after_fast_failure(tmp_path: Path):
    calls = []

    class FakeManager:
        def get_backend(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RufusAnswerValidationError(
                    "fast failed",
                    question_index=3,
                    question="图片问题",
                    reason="diagnosis_section_missing_4",
                    attempt_count=2,
                )
            asin = kwargs["asin"]
            return {
                "asin": asin,
                "country": kwargs["country"],
                "questions": kwargs["questions"],
                "answers": [{"text": "ok", "isSuccess": True}],
                "seed_request": {"request_url": "hidden"},
            }

    class FakeWriter:
        def write(self, data, output_dir=None):
            path = Path(output_dir) / f"{data['asin']}-fallback.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_valid_report(data["asin"]), encoding="utf-8")
            return path

    runner = RufusBatchBackendRunner(manager_factory=FakeManager, writer=FakeWriter())

    summary = runner.run(
        BatchGetBackendOptions(
            asins=["B0TEST1234"],
            country="US",
            questions=["1、A\n2、B\n3、C\n4、D"] * 6,
            mode="balanced",
            output_dir=tmp_path / "rufus",
            resume=False,
            fallback_serial=True,
        )
    )

    result = summary["data"]["results"][0]
    assert summary["success"] is True
    assert result["status"] == "success"
    assert [attempt["name"] for attempt in result["attempts"]] == ["fast", "safe"]
    assert calls[0]["parallel"] is True
    assert calls[0]["concurrency"] == 2
    assert calls[0]["retry"] == 1
    assert calls[0]["timeout_seconds"] == 240
    assert calls[1]["parallel"] is False
    assert calls[1]["concurrency"] == 1
    assert calls[1]["retry"] == 3
    assert calls[1]["timeout_seconds"] == 360

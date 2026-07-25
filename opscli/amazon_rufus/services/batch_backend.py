"""Batch orchestration for Rufus backend fetching."""

from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from opscli.amazon_rufus.domain.exceptions import InvalidQuestionError
from opscli.amazon_rufus.services.answer_report_writer import AnswerReportWriter
from opscli.amazon_rufus.services.manager import RufusManager
from opscli.amazon_rufus.services.question_bank import QuestionBankService
from opscli.amazon_rufus.services.report_validator import ReportValidationResult, RufusDiagnosisReportValidator


@dataclass(frozen=True)
class BatchRunProfile:
    """Concrete runtime knobs for a batch Rufus run."""

    mode: str
    timeout_seconds: int
    retry: int
    asin_concurrency: int
    question_parallel: bool
    question_concurrency: int


@dataclass(frozen=True)
class BatchGetBackendOptions:
    """User-facing batch options after CLI normalization."""

    asins: list[str]
    country: str
    questions: list[str] | None = None
    skills_dir: str | None = None
    mode: str = "balanced"
    asin_concurrency: int | None = None
    question_parallel: bool | None = None
    question_concurrency: int | None = None
    timeout_seconds: int | None = None
    retry: int | None = None
    strict_answer: bool = True
    resume: bool = True
    fallback_serial: bool = True
    validate_report: bool = True
    output_dir: Path = Path("output") / "amazon-rufus"


class RufusBatchBackendRunner:
    """Run multiple ASIN Rufus backend fetches with fast pass and safe fallback."""

    def __init__(
        self,
        *,
        manager_factory: Callable[[], RufusManager] | None = None,
        writer: AnswerReportWriter | None = None,
        validator: RufusDiagnosisReportValidator | None = None,
        question_bank_factory: Callable[[str | None], QuestionBankService] | None = None,
    ) -> None:
        self.manager_factory = manager_factory or RufusManager
        self.writer = writer or AnswerReportWriter()
        self.validator = validator or RufusDiagnosisReportValidator()
        self.question_bank_factory = question_bank_factory or (lambda skills_dir: QuestionBankService(skills_dir=skills_dir))

    def run(self, options: BatchGetBackendOptions) -> dict[str, Any]:
        """Run the batch and return a machine-readable summary."""
        asins = self._normalize_asins(options.asins)
        if not asins:
            raise InvalidQuestionError("至少需要提供一个 ASIN")

        started_at = datetime.now()
        output_dir = Path(options.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        fast_profile = self._resolve_profile(options)
        safe_profile = self._safe_profile(fast_profile)
        question_templates = options.questions or self._load_question_templates(options.skills_dir)
        expected_section_count = len(question_templates)

        results: list[dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=fast_profile.asin_concurrency) as executor:
            future_map = {
                executor.submit(
                    self._run_one,
                    asin=asin,
                    country=options.country,
                    question_templates=question_templates,
                    output_dir=output_dir,
                    fast_profile=fast_profile,
                    safe_profile=safe_profile,
                    strict_answer=options.strict_answer,
                    resume=options.resume,
                    fallback_serial=options.fallback_serial,
                    validate_report=options.validate_report,
                    expected_section_count=expected_section_count,
                ): index
                for index, asin in enumerate(asins)
            }
            ordered: dict[int, dict[str, Any]] = {}
            for future in concurrent.futures.as_completed(future_map):
                ordered[future_map[future]] = future.result()
            results = [ordered[index] for index in range(len(asins))]

        failed = [item for item in results if item.get("status") == "failed"]
        skipped = [item for item in results if item.get("status") == "skipped"]
        succeeded = [item for item in results if item.get("status") == "success"]
        return {
            "success": not failed,
            "command": "amazon-rufus batch-get-backend",
            "data": {
                "country": options.country.strip().upper(),
                "mode": fast_profile.mode,
                "started_at": started_at.isoformat(timespec="seconds"),
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "asin_count": len(asins),
                "question_count": len(question_templates),
                "success_count": len(succeeded),
                "skipped_count": len(skipped),
                "failed_count": len(failed),
                "fast_profile": self._profile_dict(fast_profile),
                "safe_profile": self._profile_dict(safe_profile),
                "output_dir": output_dir.as_posix(),
                "results": results,
            },
            "error": None if not failed else {"code": "RUFUS_BATCH_PARTIAL_FAILURE", "message": f"{len(failed)} 个 ASIN 获取失败"},
        }

    def _run_one(
        self,
        *,
        asin: str,
        country: str,
        question_templates: list[str],
        output_dir: Path,
        fast_profile: BatchRunProfile,
        safe_profile: BatchRunProfile,
        strict_answer: bool,
        resume: bool,
        fallback_serial: bool,
        validate_report: bool,
        expected_section_count: int,
    ) -> dict[str, Any]:
        started = time.monotonic()
        if resume:
            resume_result = self._resume_result(asin, output_dir, validate_report, expected_section_count)
            if resume_result:
                return resume_result

        attempts: list[dict[str, Any]] = []
        fast_result = self._attempt_fetch(
            asin=asin,
            country=country,
            question_templates=question_templates,
            output_dir=output_dir,
            profile=fast_profile,
            strict_answer=strict_answer,
            validate_report=validate_report,
            expected_section_count=expected_section_count,
        )
        attempts.append(self._attempt_summary("fast", fast_result))
        if fast_result["ok"]:
            return self._success_result(asin, fast_result, attempts, started)

        if fallback_serial:
            safe_result = self._attempt_fetch(
                asin=asin,
                country=country,
                question_templates=question_templates,
                output_dir=output_dir,
                profile=safe_profile,
                strict_answer=strict_answer,
                validate_report=validate_report,
                expected_section_count=expected_section_count,
            )
            attempts.append(self._attempt_summary("safe", safe_result))
            if safe_result["ok"]:
                return self._success_result(asin, safe_result, attempts, started)

        return {
            "asin": asin,
            "status": "failed",
            "report_path": fast_result.get("report_path"),
            "duration_seconds": round(time.monotonic() - started, 2),
            "attempts": attempts,
            "error_message": attempts[-1].get("error_message") or "Rufus batch fetch failed",
        }

    def _attempt_fetch(
        self,
        *,
        asin: str,
        country: str,
        question_templates: list[str],
        output_dir: Path,
        profile: BatchRunProfile,
        strict_answer: bool,
        validate_report: bool,
        expected_section_count: int,
    ) -> dict[str, Any]:
        questions = [self._render_asin_placeholder(template, asin) for template in question_templates]
        try:
            data = self.manager_factory().get_backend(
                asin=asin,
                country=country,
                questions=questions,
                timeout_seconds=profile.timeout_seconds,
                parallel=profile.question_parallel,
                concurrency=profile.question_concurrency,
                retry=profile.retry,
                strict_answer=strict_answer,
                include_upload_payload=True,
                submit_upload=False,
            )
            report_path = self.writer.write(data, output_dir=output_dir)
            validation = self._validate_report(report_path, validate_report, expected_section_count)
            if validation and not validation.is_valid:
                return {
                    "ok": False,
                    "report_path": report_path.as_posix(),
                    "profile": self._profile_dict(profile),
                    "validation": validation.to_dict(),
                    "error_message": "Rufus report failed validation",
                }
            return {
                "ok": True,
                "report_path": report_path.as_posix(),
                "profile": self._profile_dict(profile),
                "validation": validation.to_dict() if validation else None,
            }
        except Exception as exc:
            return {
                "ok": False,
                "profile": self._profile_dict(profile),
                "error_code": getattr(exc, "code", exc.__class__.__name__),
                "error_message": str(exc),
            }

    def _resume_result(
        self,
        asin: str,
        output_dir: Path,
        validate_report: bool,
        expected_section_count: int,
    ) -> dict[str, Any] | None:
        candidates = sorted(output_dir.glob(f"{asin}-*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not candidates:
            return None
        latest = candidates[0]
        validation = self._validate_report(latest, validate_report, expected_section_count)
        if validation is None or validation.is_valid:
            return {
                "asin": asin,
                "status": "skipped",
                "reason": "resume_valid_report",
                "report_path": latest.as_posix(),
                "validation": validation.to_dict() if validation else None,
                "attempts": [],
                "duration_seconds": 0,
            }
        return None

    def _validate_report(
        self,
        report_path: Path,
        validate_report: bool,
        expected_section_count: int,
    ) -> ReportValidationResult | None:
        if not validate_report:
            return None
        return self.validator.validate_path(report_path, expected_section_count=expected_section_count)

    def _success_result(
        self,
        asin: str,
        attempt_result: dict[str, Any],
        attempts: list[dict[str, Any]],
        started: float,
    ) -> dict[str, Any]:
        return {
            "asin": asin,
            "status": "success",
            "report_path": attempt_result.get("report_path"),
            "validation": attempt_result.get("validation"),
            "attempts": attempts,
            "duration_seconds": round(time.monotonic() - started, 2),
        }

    def _attempt_summary(self, name: str, result: dict[str, Any]) -> dict[str, Any]:
        summary = {
            "name": name,
            "ok": bool(result.get("ok")),
            "profile": result.get("profile"),
            "report_path": result.get("report_path"),
            "error_code": result.get("error_code"),
            "error_message": result.get("error_message"),
        }
        validation = result.get("validation")
        if isinstance(validation, dict):
            summary["validation"] = validation
        return summary

    def _resolve_profile(self, options: BatchGetBackendOptions) -> BatchRunProfile:
        mode = str(options.mode or "balanced").strip().lower()
        if mode == "fast":
            base = BatchRunProfile(mode="fast", timeout_seconds=240, retry=1, asin_concurrency=3, question_parallel=True, question_concurrency=3)
        elif mode == "safe":
            base = BatchRunProfile(mode="safe", timeout_seconds=360, retry=3, asin_concurrency=1, question_parallel=False, question_concurrency=1)
        elif mode == "balanced":
            base = BatchRunProfile(mode="balanced", timeout_seconds=240, retry=1, asin_concurrency=2, question_parallel=True, question_concurrency=2)
        else:
            raise InvalidQuestionError("mode 仅支持 fast、balanced、safe")

        question_parallel = base.question_parallel if options.question_parallel is None else bool(options.question_parallel)
        return BatchRunProfile(
            mode=base.mode,
            timeout_seconds=int(options.timeout_seconds if options.timeout_seconds is not None else base.timeout_seconds),
            retry=int(options.retry if options.retry is not None else base.retry),
            asin_concurrency=max(1, int(options.asin_concurrency if options.asin_concurrency is not None else base.asin_concurrency)),
            question_parallel=question_parallel,
            question_concurrency=max(1, int(options.question_concurrency if options.question_concurrency is not None else base.question_concurrency)),
        )

    def _safe_profile(self, profile: BatchRunProfile) -> BatchRunProfile:
        return replace(
            profile,
            mode="safe",
            timeout_seconds=max(profile.timeout_seconds, 360),
            retry=max(profile.retry, 3),
            asin_concurrency=1,
            question_parallel=False,
            question_concurrency=1,
        )

    def _load_question_templates(self, skills_dir: str | None) -> list[str]:
        templates = self.question_bank_factory(skills_dir).load_templates()
        return [question.text for template in templates for question in template.questions if question.text]

    def _normalize_asins(self, asins: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in asins:
            for item in str(value or "").replace(",", " ").split():
                asin = item.strip().upper()
                if not asin or asin in seen:
                    continue
                seen.add(asin)
                normalized.append(asin)
        return normalized

    def _render_asin_placeholder(self, question: str, asin: str) -> str:
        return str(question).replace("{{asin}}", asin).replace("{asin}", asin)

    def _profile_dict(self, profile: BatchRunProfile) -> dict[str, Any]:
        return {
            "mode": profile.mode,
            "timeout_seconds": profile.timeout_seconds,
            "retry": profile.retry,
            "asin_concurrency": profile.asin_concurrency,
            "question_parallel": profile.question_parallel,
            "question_concurrency": profile.question_concurrency,
        }

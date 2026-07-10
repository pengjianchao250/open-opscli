from __future__ import annotations

from pathlib import Path

from opscli.asin_data.services.daily_pipeline import DailyAsinDataPipeline


class FailingRufusBatchRunner:
    def run(self, options):  # pragma: no cover - should never be called
        raise AssertionError("Rufus batch runner should not run during dry-run")


def test_rufus_stage_dry_run_writes_planned_cache_without_calling_batch(tmp_path: Path):
    result = DailyAsinDataPipeline(rufus_batch_runner=FailingRufusBatchRunner()).run_stage(
        "rufus",
        asin="B0TEST1234",
        site="US",
        output_dir=str(tmp_path),
        run_id="daily-rufus-dry-run",
        dry_run=True,
    )

    stage_path = Path(result["data"]["stage_path"])
    assert result["data"]["status"] == "planned"
    assert stage_path.exists()
    assert "rufus planned by --dry-run" in stage_path.read_text(encoding="utf-8")


def test_daily_pipeline_dry_run_merges_standard_split_package(tmp_path: Path):
    result = DailyAsinDataPipeline(rufus_batch_runner=FailingRufusBatchRunner()).run_all(
        asin="B0TEST1234",
        site="US",
        keywords=["bed frame"],
        output_dir=str(tmp_path),
        run_id="daily-dry-run",
        dry_run=True,
        upload=False,
        rufus_strict_answer=True,
        rufus_timeout_seconds=240,
        rufus_concurrency=2,
        rufus_retry=1,
    )

    output_dir = Path(result["output_dir"])
    assert (output_dir / "stages" / "rufus.json").exists()
    assert (output_dir / "stages" / "seller-keyword-reverse.jsonl").exists()
    assert (output_dir / "frontend-data.json").exists()
    assert Path(result["manifest"]["files"]["asin_data_package_zip"]).exists()
    assert result["manifest"]["options"]["daily_stage_pipeline"] is True
    assert result["manifest"]["options"]["rufus_strict_answer"] is True

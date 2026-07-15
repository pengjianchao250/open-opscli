from __future__ import annotations

import importlib.util
import json
import sys
import time
import zipfile
from argparse import Namespace
from pathlib import Path

import pytest
from openpyxl import Workbook


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "asin_data_daily_full_package.py"
spec = importlib.util.spec_from_file_location("asin_data_daily_full_package", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
daily = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = daily
spec.loader.exec_module(daily)


def write_xlsx(path: Path, value: str = "ok") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.append(["value"])
    ws.append([value])
    wb.save(path)


def touch_days_ago(path: Path, days: int) -> None:
    timestamp = time.time() - days * 24 * 60 * 60
    path.touch()
    path.chmod(0o666)
    import os

    os.utime(path, (timestamp, timestamp))


def make_seller_dir(root: Path, asin: str, days_ago: int = 0) -> Path:
    asin_dir = root / "run" / daily.PACKAGE_ROOT_NAME / asin
    for name in daily.SELLER_FILES:
        path = asin_dir / name
        write_xlsx(path, name)
        if days_ago:
            touch_days_ago(path, days_ago)
    return asin_dir


def test_find_recent_file_set_requires_complete_recent_files(tmp_path: Path) -> None:
    asin = "B0TEST1234"
    old_dir = make_seller_dir(tmp_path / "old", asin, days_ago=8)
    new_dir = make_seller_dir(tmp_path / "new", asin, days_ago=0)

    hit = daily.find_recent_file_set(
        roots=[tmp_path],
        asin=asin,
        filenames=daily.SELLER_FILES,
        cache_days=7,
        source="seller_sprite",
    )

    assert hit is not None
    assert hit.path == new_dir
    assert hit.path != old_dir
    assert set(hit.file_paths) == set(daily.SELLER_FILES)


def test_find_recent_rufus_cache_requires_passing_score(tmp_path: Path) -> None:
    asin = "B0TEST1234"
    failed = tmp_path / "failed" / asin
    failed.mkdir(parents=True)
    (failed / "final-round.md").write_text("failed", encoding="utf-8")
    (failed / "final-round-quality-score.json").write_text(
        json.dumps({"passed": False, "title": {"score": 90}, "bullet_points": {"score": 70}}),
        encoding="utf-8",
    )
    passed = tmp_path / "passed" / asin
    passed.mkdir(parents=True)
    (passed / "final-round.md").write_text("passed", encoding="utf-8")
    (passed / "final-round-quality-score.json").write_text(
        json.dumps({"passed": True, "title": {"score": 88}, "bullet_points": {"score": 80}}),
        encoding="utf-8",
    )

    hit = daily.find_recent_rufus_cache(roots=[tmp_path], asin=asin, cache_days=7, threshold=80)

    assert hit is not None
    assert hit.path == passed
    assert hit.file_paths[daily.FILE_RUFUS] == passed / "final-round.md"


def test_build_final_package_matches_sample_zip_layout(tmp_path: Path) -> None:
    asin = "B0TEST1234"
    run_root = tmp_path / "out" / "daily-run"
    base_package = run_root / daily.PACKAGE_ROOT_NAME
    base_asin = base_package / asin
    write_xlsx(base_asin / daily.FILE_BASIC, "basic")
    write_xlsx(base_asin / daily.FILE_BI, "bi")
    seller_dir = make_seller_dir(tmp_path / "seller-cache", asin)
    rufus_dir = tmp_path / "rufus-cache" / asin
    rufus_dir.mkdir(parents=True)
    rufus_report = rufus_dir / "final-round.md"
    rufus_report.write_text("# final", encoding="utf-8")
    score_path = rufus_dir / "final-round-quality-score.json"
    score_path.write_text(
        json.dumps({"passed": True, "title": {"score": 90}, "bullet_points": {"score": 90}}),
        encoding="utf-8",
    )
    seller_hit = daily.CacheHit(
        asin=asin,
        source="seller_sprite",
        path=seller_dir,
        file_paths={name: seller_dir / name for name in daily.SELLER_FILES},
        newest_mtime=time.time(),
        oldest_mtime=time.time(),
    )
    rufus_hit = daily.CacheHit(
        asin=asin,
        source="rufus",
        path=rufus_dir,
        file_paths={daily.FILE_RUFUS: rufus_report, "score": score_path},
        newest_mtime=time.time(),
        oldest_mtime=time.time(),
    )

    package = daily.build_final_package(
        run_root=run_root,
        run_id="daily-run",
        asins=[asin],
        base_package_dir=base_package,
        seller_hits={asin: seller_hit},
        rufus_hits={asin: rufus_hit},
    )

    zip_path = Path(package["zip_path"])
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())

    expected = {f"{daily.PACKAGE_ROOT_NAME}/{asin}/{name}" for name in daily.OUTPUT_FILES}
    expected.add(f"{daily.PACKAGE_ROOT_NAME}/README.md")
    assert expected.issubset(names)

    asin_zip_path = Path(package["asin_zips"][asin]["zip_path"])
    assert asin_zip_path.name == f"{asin}-asin-data-package.zip"
    with zipfile.ZipFile(asin_zip_path) as archive:
        asin_zip_names = set(archive.namelist())
    assert {f"{daily.PACKAGE_ROOT_NAME}/{asin}/{name}" for name in daily.OUTPUT_FILES}.issubset(asin_zip_names)
    assert f"{daily.PACKAGE_ROOT_NAME}/README.md" not in asin_zip_names


def test_build_final_package_writes_one_zip_per_asin(tmp_path: Path) -> None:
    asins = ["B0TEST1234", "B0TEST5678"]
    run_root = tmp_path / "out" / "daily-run"
    seller_hits = {}
    rufus_hits = {}
    base_package_dirs = {}

    for asin in asins:
        base_package = tmp_path / "base" / asin / daily.PACKAGE_ROOT_NAME
        base_asin = base_package / asin
        write_xlsx(base_asin / daily.FILE_BASIC, f"basic-{asin}")
        write_xlsx(base_asin / daily.FILE_BI, f"bi-{asin}")
        base_package_dirs[asin] = base_package

        seller_dir = make_seller_dir(tmp_path / "seller-cache" / asin, asin)
        rufus_dir = tmp_path / "rufus-cache" / asin
        rufus_dir.mkdir(parents=True)
        rufus_report = rufus_dir / "final-round.md"
        rufus_report.write_text(f"# final {asin}", encoding="utf-8")
        score_path = rufus_dir / "final-round-quality-score.json"
        score_path.write_text(
            json.dumps({"passed": True, "title": {"score": 90}, "bullet_points": {"score": 90}}),
            encoding="utf-8",
        )
        seller_hits[asin] = daily.CacheHit(
            asin=asin,
            source="seller_sprite",
            path=seller_dir,
            file_paths={name: seller_dir / name for name in daily.SELLER_FILES},
            newest_mtime=time.time(),
            oldest_mtime=time.time(),
        )
        rufus_hits[asin] = daily.CacheHit(
            asin=asin,
            source="rufus",
            path=rufus_dir,
            file_paths={daily.FILE_RUFUS: rufus_report, "score": score_path},
            newest_mtime=time.time(),
            oldest_mtime=time.time(),
        )

    package = daily.build_final_package(
        run_root=run_root,
        run_id="daily-run",
        asins=asins,
        base_package_dirs=base_package_dirs,
        seller_hits=seller_hits,
        rufus_hits=rufus_hits,
    )

    assert set(package["asin_zips"]) == set(asins)
    for asin in asins:
        with zipfile.ZipFile(package["asin_zips"][asin]["zip_path"]) as archive:
            names = set(archive.namelist())
        assert any(name.startswith(f"{daily.PACKAGE_ROOT_NAME}/{asin}/") for name in names)
        other_asins = set(asins) - {asin}
        assert not any(name.startswith(f"{daily.PACKAGE_ROOT_NAME}/{other}/") for other in other_asins for name in names)


def test_collect_base_packages_runs_single_asin_submit_commands(tmp_path: Path) -> None:
    asin = "B0TEST1234"
    run_root = tmp_path / "out" / "daily-run"
    args = Namespace(
        site="US",
        run_id="daily-run",
        report_date="2026-06-25",
        base_collect_full=False,
        no_upload=False,
        no_submit_report_files=False,
        collect_timeout=30,
        dry_run=True,
    )

    result = daily.collect_base_packages(args, [asin], run_root)

    command = result["results"][0]["command"]
    assert "--asin" in command
    assert command[command.index("--asin") + 1] == asin
    assert "--input" not in command
    assert "--no-fetch-report-files" in command
    assert "--submit-report-files" in command
    assert command[command.index("--report-date") + 1] == "2026-06-25"
    assert "--skip-seller-sprite" in command
    assert Path(result["base_package_dirs"][asin]) == run_root / "base-collect" / f"daily-run-{asin}" / daily.PACKAGE_ROOT_NAME


def test_build_final_package_fails_when_base_01_02_missing(tmp_path: Path) -> None:
    asin = "B0TEST1234"
    run_root = tmp_path / "out" / "daily-run"
    seller_dir = make_seller_dir(tmp_path / "seller-cache", asin)
    rufus_dir = tmp_path / "rufus-cache" / asin
    rufus_dir.mkdir(parents=True)
    rufus_report = rufus_dir / "final-round.md"
    rufus_report.write_text("# final", encoding="utf-8")
    score_path = rufus_dir / "final-round-quality-score.json"
    score_path.write_text(
        json.dumps({"passed": True, "title": {"score": 90}, "bullet_points": {"score": 90}}),
        encoding="utf-8",
    )
    seller_hit = daily.CacheHit(
        asin=asin,
        source="seller_sprite",
        path=seller_dir,
        file_paths={name: seller_dir / name for name in daily.SELLER_FILES},
        newest_mtime=time.time(),
        oldest_mtime=time.time(),
    )
    rufus_hit = daily.CacheHit(
        asin=asin,
        source="rufus",
        path=rufus_dir,
        file_paths={daily.FILE_RUFUS: rufus_report, "score": score_path},
        newest_mtime=time.time(),
        oldest_mtime=time.time(),
    )

    with pytest.raises(FileNotFoundError, match="Required base package file is missing"):
        daily.build_final_package(
            run_root=run_root,
            run_id="daily-run",
            asins=[asin],
            base_package_dir=run_root / daily.PACKAGE_ROOT_NAME,
            seller_hits={asin: seller_hit},
            rufus_hits={asin: rufus_hit},
        )

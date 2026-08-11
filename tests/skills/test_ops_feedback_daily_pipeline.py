"""反馈日报“提前取数 + Codex 洞察 + 离线发布”契约测试。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


SCRIPT_PATH = Path("opscli/skills/templates/ops-feedback-query/scripts/daily_feedback_report.py")
CLAIM_ARGS = [
    "--claim-ready",
    "--date-from",
    "2026-08-05 00:00:00",
    "--date-to",
    "2026-08-05 23:59:59",
]


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ops_feedback_daily_pipeline", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_feedback_fakes(module: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "load_api_key", lambda: "feedback-secret")
    monkeypatch.setattr(
        module,
        "DEFAULT_TAXONOMY_PATH",
        Path.cwd() / ".test-feedback-taxonomy.json",
    )

    def fake_list(self, params):
        period = params["date_from"][:10]
        return {
            "code": 200,
            "msg": "成功",
            "data": {
                "list": [
                    {
                        "feedback_uuid": f"feedback-{period}",
                        "feedback_type": "bug",
                        "severity": "high",
                        "source": "mcp",
                        "status": "new",
                        "title": "字段映射失败",
                        "failed_call_count": 1,
                        "created_at": f"{period}T01:00:00Z",
                        "user_id": 42,
                    }
                ]
                if params["page"] == 1
                else [],
            },
        }

    monkeypatch.setattr(module.FeedbackQueryClient, "list_feedbacks", fake_list)
    monkeypatch.setattr(
        module.FeedbackQueryClient,
        "batch_detail",
        lambda self, feedback_uuids, feedback_type=None: {
            "code": 200,
            "msg": "成功",
            "data": {
                "list": [
                    {
                        "feedback_uuid": value,
                        "content": (
                            '字段别名无法映射 sk-1234567890 '
                            'eyJabcde.abcdef.uvwxyz {"api_key":"json-secret-value"}'
                        ),
                        "execution_summary": {
                            "failed_calls": [
                                {
                                    "error_message": "FIELD_NOT_FOUND: alias 42",
                                    "reason": "字段别名不一致",
                                    "fix_suggestion": "统一字段解析入口",
                                }
                            ]
                        },
                    }
                    for value in feedback_uuids
                ]
            },
        },
    )


def _prepare_and_claim(
    module: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> tuple[Path, dict, dict]:
    assert module.main(
        [
            "--prepare-only",
            "--date-from",
            "2026-08-05 00:00:00",
            "--date-to",
            "2026-08-05 23:59:59",
        ]
    ) == 0
    prepared = json.loads(capsys.readouterr().out)
    prepared_dir = Path(prepared["prepared_dir"])
    assert module.main(CLAIM_ARGS) == 0
    claimed = json.loads(capsys.readouterr().out)
    chunk_input = json.loads(
        (prepared_dir / claimed["chunks"][0]["input"]).read_text(encoding="utf-8")
    )
    return prepared_dir, claimed, chunk_input


def _chunk_output(module: ModuleType, claimed: dict, chunk_input: dict) -> dict:
    return {
        "schema_version": module.PREPARED_ARTIFACT_SCHEMA_VERSION,
        "period_key": claimed["period_key"],
        "chunk_index": 1,
        "classifications": [
            {
                "feedback_uuid": item["feedback_uuid"],
                "module": "query",
                "problem_key": "field_mapping_failed",
                "problem_category": "字段映射",
                "problem_summary": "字段映射失败",
                "recommended_work": "统一字段解析入口并增加回归测试",
                "confidence": 0.95,
            }
            for item in chunk_input["feedbacks"]
        ],
    }


def _write_valid_narrative(
    module: ModuleType,
    prepared_dir: Path,
    narrative_prepared: dict,
) -> Path:
    narrative_input = json.loads(
        Path(narrative_prepared["input"]).read_text(encoding="utf-8")
    )
    problem_ref = narrative_input["facts"]["all_problems"][0]["problem_ref"]
    module_name = narrative_input["facts"]["modules"][0]["module"]
    problem_priority = narrative_input["facts"]["all_problems"][0]["priority"]
    risk_themes = []
    if problem_priority in {"P0", "P1"}:
        risk_themes.append(
            {
                "title": "查询字段合同不稳定",
                "summary": "同类字段映射失败仍在重复出现。",
                "problem_refs": [problem_ref],
                "recommendation": "统一字段解析入口并增加契约回归测试。",
            }
        )
    output_path = Path(narrative_prepared["output"])
    output_path.write_text(
        json.dumps(
            {
                "schema_version": module.PREPARED_ARTIFACT_SCHEMA_VERSION,
                "period_key": narrative_input["period_key"],
                "executive_summary": [
                    "主要问题集中在查询字段合同，应该优先统一解析入口并补齐回归验证。"
                ],
                "module_insights": [
                    {
                        "module": module_name,
                        "insight": "该模块是本日最集中的治理入口。",
                    }
                ],
                "risk_themes": risk_themes,
                "governance_actions": [
                    {
                        "title": "收敛字段解析入口",
                        "summary": "把重复问题合并为统一治理项目。",
                        "problem_refs": [problem_ref],
                        "recommendation": "统一解析、错误提示和回归测试。",
                    }
                ],
                "limitations": ["单日报告只使用相邻对比窗口，不能代表长期故障率。"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return output_path


def test_prepare_only_writes_ready_marker_and_chunk_without_calling_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    _install_feedback_fakes(module, monkeypatch)
    monkeypatch.setattr(
        module,
        "run_feedback_insight",
        lambda *args, **kwargs: pytest.fail("准备阶段不得调用大模型"),
    )

    exit_code = module.main(
        [
            "--prepare-only",
            "--date-from",
            "2026-08-05 00:00:00",
            "--date-to",
            "2026-08-05 23:59:59",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    prepared_dir = Path(output["prepared_dir"])
    manifest = json.loads((prepared_dir / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert output["state"] == "ready"
    assert (prepared_dir / "READY").read_text(encoding="utf-8") == "2026-08-05 数据已完成\n"
    assert manifest["state"] == "ready"
    assert manifest["feedback_count"] == 1
    assert manifest["comparison_feedback_count"] == 1
    assert manifest["chunks"][0]["status"] == "pending"
    assert (prepared_dir / "analysis-input.json").exists()
    assert (prepared_dir / "report-input.json").exists()
    assert (prepared_dir / manifest["chunks"][0]["input"]).exists()
    serialized_input = (prepared_dir / "analysis-input.json").read_text(encoding="utf-8")
    assert "sk-1234567890" not in serialized_input
    assert "eyJabcde.abcdef.uvwxyz" not in serialized_input
    assert "json-secret-value" not in serialized_input


def test_two_stage_pipeline_reuses_persistent_taxonomy_without_codex_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """确定性错误命中 taxonomy 时不得再次交给 Codex 分类。"""
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    _install_feedback_fakes(module, monkeypatch)
    taxonomy_path = tmp_path / "feedback-taxonomy.json"
    store = module.FeedbackTaxonomyStore(taxonomy_path)
    seed_feedback = {
        "feedback_uuid": "seed",
        "error_message": "FIELD_NOT_FOUND: alias 7",
    }
    seed_classification = {
        "feedback_uuid": "seed",
        "module": "query",
        "problem_key": "field_mapping_failed",
        "problem_category": "字段映射",
        "problem_summary": "字段映射失败",
        "recommended_work": "统一字段解析入口并增加回归测试",
        "confidence": 0.95,
    }
    store.persist(store.load(), [seed_feedback], {"seed": seed_classification})

    assert module.main(
        [
            "--prepare-only",
            "--date-from",
            "2026-08-05 00:00:00",
            "--date-to",
            "2026-08-05 23:59:59",
            "--taxonomy-file",
            str(taxonomy_path),
        ]
    ) == 0
    prepared_result = json.loads(capsys.readouterr().out)
    prepared_dir = Path(prepared_result["prepared_dir"])
    manifest = json.loads((prepared_dir / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["taxonomy"]["cache_hit_count"] == 2
    assert manifest["taxonomy"]["model_classification_count"] == 0
    assert manifest["chunks"] == []

    assert module.main(CLAIM_ARGS) == 0
    claimed = json.loads(capsys.readouterr().out)
    assert claimed["chunks"] == []
    assert module.main(
        [
            "--prepare-narrative",
            str(prepared_dir),
            "--taxonomy-file",
            str(taxonomy_path),
        ]
    ) == 0
    narrative_prepared = json.loads(capsys.readouterr().out)
    narrative_output = _write_valid_narrative(
        module, prepared_dir, narrative_prepared
    )
    assert module.main(["--validate-narrative", str(narrative_output)]) == 0
    capsys.readouterr()
    assert module.main(
        [
            "--finalize-prepared",
            str(prepared_dir),
            "--taxonomy-file",
            str(taxonomy_path),
        ]
    ) == 0
    finalized = json.loads(capsys.readouterr().out)

    assert finalized["insight"] is True
    assert finalized["taxonomy_cache_hit_count"] == 2


def test_prepare_does_not_reuse_artifacts_from_another_taxonomy_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """准备产物必须绑定 taxonomy 文件身份，避免跨存储污染。"""
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    _install_feedback_fakes(module, monkeypatch)
    base_args = [
        "--prepare-only",
        "--date-from",
        "2026-08-05 00:00:00",
        "--date-to",
        "2026-08-05 23:59:59",
    ]

    assert module.main([*base_args, "--taxonomy-file", str(tmp_path / "first.json")]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["reused"] is False
    assert module.main([*base_args, "--taxonomy-file", str(tmp_path / "second.json")]) == 0
    second = json.loads(capsys.readouterr().out)

    assert second["reused"] is False


def test_prepare_does_not_leave_ready_marker_when_ready_manifest_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    _install_feedback_fakes(module, monkeypatch)
    original_write = module._write_json_artifact

    def fail_ready_manifest(payload, output_path):
        if Path(output_path).name == "manifest.json" and payload.get("state") == "ready":
            raise module.DailyReportError("ready manifest write failed")
        return original_write(payload, output_path)

    monkeypatch.setattr(module, "_write_json_artifact", fail_ready_manifest)

    exit_code = module.main(
        [
            "--prepare-only",
            "--date-from",
            "2026-08-05 00:00:00",
            "--date-to",
            "2026-08-05 23:59:59",
        ]
    )
    capsys.readouterr()
    prepared_dir = project_root / "output" / "feedback-query" / "prepared" / "2026-08-05"
    manifest = json.loads((prepared_dir / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 1
    assert manifest["state"] == "failed"
    assert not (prepared_dir / "READY").exists()


def test_prepare_rebuilds_corrupted_chunk_instead_of_reusing_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    _install_feedback_fakes(module, monkeypatch)
    args = [
        "--prepare-only",
        "--date-from",
        "2026-08-05 00:00:00",
        "--date-to",
        "2026-08-05 23:59:59",
    ]

    assert module.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    prepared_dir = Path(first["prepared_dir"])
    manifest = json.loads((prepared_dir / "manifest.json").read_text(encoding="utf-8"))
    chunk_path = prepared_dir / manifest["chunks"][0]["input"]
    chunk_path.write_text("{}", encoding="utf-8")

    assert module.main(args) == 0
    rebuilt = json.loads(capsys.readouterr().out)
    repaired_chunk = json.loads(chunk_path.read_text(encoding="utf-8"))

    assert rebuilt["reused"] is False
    assert repaired_chunk["feedbacks"]


def test_claim_ignores_ready_manifest_without_ready_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    _install_feedback_fakes(module, monkeypatch)

    assert module.main(
        [
            "--prepare-only",
            "--date-from",
            "2026-08-05 00:00:00",
            "--date-to",
            "2026-08-05 23:59:59",
        ]
    ) == 0
    prepared = json.loads(capsys.readouterr().out)
    (Path(prepared["prepared_dir"]) / "READY").unlink()

    assert module.main(CLAIM_ARGS) == 0
    claimed = json.loads(capsys.readouterr().out)

    assert claimed["state"] == "idle"


def test_claim_does_not_publish_an_older_ready_backlog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    _install_feedback_fakes(module, monkeypatch)
    assert module.main(
        [
            "--prepare-only",
            "--date-from",
            "2026-08-05 00:00:00",
            "--date-to",
            "2026-08-05 23:59:59",
        ]
    ) == 0
    capsys.readouterr()

    assert module.main(
        [
            "--claim-ready",
            "--date-from",
            "2026-08-06 00:00:00",
            "--date-to",
            "2026-08-06 23:59:59",
        ]
    ) == 0
    claimed = json.loads(capsys.readouterr().out)

    assert claimed["state"] == "idle"
    assert claimed["period"] == "2026-08-06"


def test_validate_chunk_rejects_and_scrubs_contract_extra_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    _install_feedback_fakes(module, monkeypatch)
    prepared_dir, claimed, chunk_input = _prepare_and_claim(module, capsys)
    output_path = prepared_dir / claimed["chunks"][0]["output"]
    output = _chunk_output(module, claimed, chunk_input)
    output["classifications"][0]["raw_payload"] = "secret-debug-payload"
    output_path.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")

    exit_code = module.main(["--validate-chunk", str(output_path)])
    capsys.readouterr()
    manifest = json.loads((prepared_dir / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 1
    assert manifest["chunks"][0]["status"] == "failed"
    assert "secret-debug-payload" not in output_path.read_text(encoding="utf-8")


def test_claim_resets_corrupted_validated_chunk_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    _install_feedback_fakes(module, monkeypatch)
    prepared_dir, claimed, chunk_input = _prepare_and_claim(module, capsys)
    output_path = prepared_dir / claimed["chunks"][0]["output"]
    output_path.write_text(
        json.dumps(_chunk_output(module, claimed, chunk_input), ensure_ascii=False),
        encoding="utf-8",
    )
    assert module.main(["--validate-chunk", str(output_path)]) == 0
    capsys.readouterr()
    output_path.write_text(
        json.dumps({"raw_payload": "secret-corrupt-output"}),
        encoding="utf-8",
    )

    assert module.main(CLAIM_ARGS) == 0
    resumed = json.loads(capsys.readouterr().out)
    manifest = json.loads((prepared_dir / "manifest.json").read_text(encoding="utf-8"))

    assert resumed["state"] == "analyzing"
    assert manifest["chunks"][0]["status"] == "failed"
    assert "output_sha256" not in manifest["chunks"][0]
    assert "secret-corrupt-output" not in output_path.read_text(encoding="utf-8")


def test_finalize_does_not_leave_completed_marker_when_manifest_commit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    _install_feedback_fakes(module, monkeypatch)
    prepared_dir, claimed, chunk_input = _prepare_and_claim(module, capsys)
    output_path = prepared_dir / claimed["chunks"][0]["output"]
    output_path.write_text(
        json.dumps(_chunk_output(module, claimed, chunk_input), ensure_ascii=False),
        encoding="utf-8",
    )
    assert module.main(["--validate-chunk", str(output_path)]) == 0
    capsys.readouterr()
    assert module.main(["--prepare-narrative", str(prepared_dir)]) == 0
    narrative_prepared = json.loads(capsys.readouterr().out)
    narrative_output = _write_valid_narrative(
        module, prepared_dir, narrative_prepared
    )
    assert module.main(["--validate-narrative", str(narrative_output)]) == 0
    capsys.readouterr()
    original_write = module._write_json_artifact

    def fail_completed_manifest(payload, target_path):
        if Path(target_path) == prepared_dir / "manifest.json" and payload.get("state") == "completed":
            raise module.DailyReportError("completed manifest write failed")
        return original_write(payload, target_path)

    monkeypatch.setattr(module, "_write_json_artifact", fail_completed_manifest)

    exit_code = module.main(["--finalize-prepared", str(prepared_dir)])
    capsys.readouterr()
    manifest = json.loads((prepared_dir / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 1
    assert manifest["state"] == "failed"
    assert not (prepared_dir / "COMPLETED").exists()


def test_claim_and_finalize_prepared_codex_classifications(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    _install_feedback_fakes(module, monkeypatch)

    assert module.main(
        [
            "--prepare-only",
            "--date-from",
            "2026-08-05 00:00:00",
            "--date-to",
            "2026-08-05 23:59:59",
        ]
    ) == 0
    prepared = json.loads(capsys.readouterr().out)
    prepared_dir = Path(prepared["prepared_dir"])

    assert module.main(CLAIM_ARGS) == 0
    claimed = json.loads(capsys.readouterr().out)
    assert claimed["state"] == "analyzing"
    assert module.main(CLAIM_ARGS) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["period_key"] == claimed["period_key"]
    assert resumed["state"] == "analyzing"
    chunk_input = json.loads(
        (prepared_dir / claimed["chunks"][0]["input"]).read_text(encoding="utf-8")
    )
    output_path = prepared_dir / claimed["chunks"][0]["output"]
    output_path.write_text(
        json.dumps(
            {
                "schema_version": module.PREPARED_ARTIFACT_SCHEMA_VERSION,
                "period_key": claimed["period_key"],
                "chunk_index": 1,
                "classifications": [
                    {
                        "feedback_uuid": item["feedback_uuid"],
                        "module": "query",
                        "problem_key": "field_mapping_failed",
                        "problem_category": "字段映射",
                        "problem_summary": "字段映射失败",
                        "recommended_work": "统一字段解析入口并增加回归测试 sk-1234567890",
                        "confidence": 0.95,
                    }
                    for item in chunk_input["feedbacks"]
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert module.main(["--validate-chunk", str(output_path)]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["status"] == "validated"
    assert "sk-1234567890" not in output_path.read_text(encoding="utf-8")
    assert module.main(["--prepare-narrative", str(prepared_dir)]) == 0
    narrative_prepared = json.loads(capsys.readouterr().out)
    narrative_input = json.loads(
        Path(narrative_prepared["input"]).read_text(encoding="utf-8")
    )
    assert narrative_input["facts"]["root_causes"][0]["category"] == "字段映射"
    assert narrative_input["facts"]["repeated_problems"] == []
    assert module.main(["--prepare-narrative", str(prepared_dir)]) == 0
    narrative_resumed = json.loads(capsys.readouterr().out)
    assert narrative_resumed["reused"] is True
    assert narrative_resumed["narrative_status"] == "pending"
    narrative_output = _write_valid_narrative(
        module, prepared_dir, narrative_prepared
    )
    assert module.main(["--validate-narrative", str(narrative_output)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "validated"
    assert module.main(
        [
            "--finalize-prepared",
            str(prepared_dir),
            "--analysis-model",
            "scheduled-codex",
        ]
    ) == 0
    finalized = json.loads(capsys.readouterr().out)
    manifest = json.loads((prepared_dir / "manifest.json").read_text(encoding="utf-8"))
    report = Path(finalized["output"]).read_text(encoding="utf-8")

    assert finalized["insight"] is True
    assert manifest["state"] == "completed"
    assert manifest["analysis"]["provider"] == "codex_app"
    assert manifest["analysis"]["model"] == "scheduled-codex"
    assert (prepared_dir / "COMPLETED").read_text(encoding="utf-8") == "2026-08-05 AI 洞察已完成\n"
    assert "## 一、范围与口径" in report
    assert "## 二、执行摘要" in report
    assert "## 三、根因分布" in report
    assert "## 四、重点模块" in report
    assert "## 五、重复问题证据" in report
    assert "## 六、P0/P1 风险" in report
    assert "## 七、治理工作建议" in report
    assert "## 八、日环比" in report
    assert "## 九、局限与后续" in report
    assert "<summary>查看全部问题簇" in report
    assert "字段映射失败" in report


def test_validate_narrative_rejects_unknown_problem_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    _install_feedback_fakes(module, monkeypatch)
    prepared_dir, claimed, chunk_input = _prepare_and_claim(module, capsys)
    output_path = prepared_dir / claimed["chunks"][0]["output"]
    output_path.write_text(
        json.dumps(_chunk_output(module, claimed, chunk_input), ensure_ascii=False),
        encoding="utf-8",
    )
    assert module.main(["--validate-chunk", str(output_path)]) == 0
    capsys.readouterr()
    assert module.main(["--prepare-narrative", str(prepared_dir)]) == 0
    narrative_prepared = json.loads(capsys.readouterr().out)
    narrative_output = _write_valid_narrative(
        module, prepared_dir, narrative_prepared
    )
    payload = json.loads(narrative_output.read_text(encoding="utf-8"))
    payload["governance_actions"][0]["problem_refs"] = ["unknown/problem"]
    narrative_output.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    assert module.main(["--validate-narrative", str(narrative_output)]) == 1
    error = json.loads(capsys.readouterr().err)
    assert "未在事实包中声明" in error["msg"]

    narrative_input = json.loads(
        Path(narrative_prepared["input"]).read_text(encoding="utf-8")
    )
    payload["governance_actions"][0]["problem_refs"] = [
        narrative_input["facts"]["all_problems"][0]["problem_ref"]
    ]
    payload["executive_summary"][0] = "本日发生 10 次字段映射失败。"
    narrative_output.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    assert module.main(["--validate-narrative", str(narrative_output)]) == 1
    error = json.loads(capsys.readouterr().err)
    assert "不得自行引用数字" in error["msg"]

    payload["executive_summary"][0] = "本日发生十次字段映射失败。"
    narrative_output.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    assert module.main(["--validate-narrative", str(narrative_output)]) == 1
    error = json.loads(capsys.readouterr().err)
    assert "不得自行引用数字" in error["msg"]

    payload["executive_summary"][0] = "本日存在三项字段映射问题。"
    narrative_output.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    assert module.main(["--validate-narrative", str(narrative_output)]) == 1
    error = json.loads(capsys.readouterr().err)
    assert "不得自行引用数字" in error["msg"]

    payload["executive_summary"][0] = "The report contains three failures."
    narrative_output.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    assert module.main(["--validate-narrative", str(narrative_output)]) == 1
    error = json.loads(capsys.readouterr().err)
    assert "不得自行引用数字" in error["msg"]

    payload["executive_summary"][0] = "The report contains a dozen failures."
    narrative_output.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    assert module.main(["--validate-narrative", str(narrative_output)]) == 1
    error = json.loads(capsys.readouterr().err)
    assert "不得自行引用数字" in error["msg"]

    payload["executive_summary"][0] = "字段映射失败需要统一治理。"
    risk_problem = narrative_input["facts"]["all_problems"][0]
    risk_problem["priority"] = "P1"
    narrative_input["facts"]["priority_risks"] = [risk_problem]
    with pytest.raises(module.DailyReportError, match="未完整覆盖"):
        module._validate_report_narrative(payload, narrative_input)

    payload["risk_themes"] = [
        {
            "title": "字段映射风险",
            "summary": "字段映射问题需要优先处理。",
            "problem_refs": [risk_problem["problem_ref"]],
            "recommendation": "统一字段解析入口。",
        }
    ]
    payload["governance_actions"] = []
    with pytest.raises(module.DailyReportError, match="必须提供治理工作建议"):
        module._validate_report_narrative(payload, narrative_input)

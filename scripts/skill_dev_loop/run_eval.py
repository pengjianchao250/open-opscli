#!/usr/bin/env python3
"""Run local Skill regression contracts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES_DIR = REPO_ROOT / "opscli" / "skills" / "evals" / "cases"
DEFAULT_TEMPLATES_DIR = REPO_ROOT / "opscli" / "skills" / "templates"
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".skill-dev-loop" / "runs"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"eval case JSON 无效: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"eval case 根节点必须是对象: {path}")
    return payload


def _contains_all(text: str, terms: list[str]) -> tuple[list[str], list[str]]:
    found: list[str] = []
    missing: list[str] = []
    for term in terms:
        if term in text:
            found.append(term)
        else:
            missing.append(term)
    return found, missing


def _assertion(ok: bool, name: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": ok, "name": name, "detail": detail or {}}


def _evaluate_case(case_doc: dict[str, Any], *, templates_dir: Path) -> dict[str, Any]:
    skill_name = str(case_doc.get("skill", "")).strip()
    skill_dir = templates_dir / skill_name
    assertions: list[dict[str, Any]] = []

    assertions.append(_assertion(skill_dir.exists(), "skill_dir_exists", {"path": str(skill_dir)}))

    for relative in case_doc.get("required_skill_files", []):
        path = skill_dir / str(relative)
        assertions.append(_assertion(path.exists(), "required_skill_file_exists", {"path": str(path)}))

    skill_md = skill_dir / "SKILL.md"
    skill_text = skill_md.read_text(encoding="utf-8") if skill_md.exists() else ""
    found, missing = _contains_all(skill_text, [str(term) for term in case_doc.get("required_skill_terms", [])])
    assertions.append(
        _assertion(
            not missing,
            "skill_terms_present",
            {"found": found, "missing": missing, "path": str(skill_md)},
        )
    )

    script_terms = case_doc.get("required_script_terms", {})
    if not isinstance(script_terms, dict):
        raise ValueError(f"required_script_terms 必须是对象: {skill_name}")
    for relative, terms in script_terms.items():
        script_path = skill_dir / str(relative)
        script_text = script_path.read_text(encoding="utf-8") if script_path.exists() else ""
        found, missing = _contains_all(script_text, [str(term) for term in terms])
        assertions.append(
            _assertion(
                script_path.exists() and not missing,
                "script_terms_present",
                {"found": found, "missing": missing, "path": str(script_path)},
            )
        )

    total = len(assertions)
    passed = sum(1 for item in assertions if item["ok"])
    score = passed / total if total else 0.0
    min_score = float(case_doc.get("min_score", 1.0))
    return {
        "skill": skill_name,
        "case_file": case_doc.get("_case_file"),
        "evaluation_type": case_doc.get("evaluation_type", "static_contract"),
        "score": score,
        "min_score": min_score,
        "success": score >= min_score,
        "assertions": assertions,
        "agent_prompts": case_doc.get("agent_prompts", []),
        "success_criteria": case_doc.get("success_criteria", []),
    }


def _case_files(cases_dir: Path, skill: str) -> list[Path]:
    files = sorted(cases_dir.glob("*.json"))
    if skill == "all":
        return files
    return [path for path in files if path.stem == skill]


def _load_cases(cases_dir: Path, skill: str) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for path in _case_files(cases_dir, skill):
        doc = _load_json(path)
        doc["_case_file"] = str(path)
        docs.append(doc)
    return docs


def _write_report(report: dict[str, Any], output_dir: Path, *, label: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    safe_label = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in label)
    path = output_dir / f"skill-eval-{safe_label}-{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local Skill dev-loop eval contracts.")
    parser.add_argument("--skill", default="all", help="Skill name, or all")
    parser.add_argument("--cases-dir", default=str(DEFAULT_CASES_DIR))
    parser.add_argument("--templates-dir", default=str(DEFAULT_TEMPLATES_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--fail-under", type=float, default=None)
    parser.add_argument("--list", action="store_true", help="List available eval case files")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    cases_dir = Path(args.cases_dir).expanduser().resolve()
    templates_dir = Path(args.templates_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()

    docs = _load_cases(cases_dir, args.skill)
    if args.list:
        print(json.dumps({"cases": [doc.get("skill") for doc in docs]}, ensure_ascii=False, indent=2))
        return 0
    if not docs:
        print(json.dumps({"success": False, "error": f"未找到 eval case: {args.skill}"}, ensure_ascii=False))
        return 2

    results = [_evaluate_case(doc, templates_dir=templates_dir) for doc in docs]
    if args.fail_under is not None:
        for result in results:
            result["min_score"] = args.fail_under
            result["success"] = result["score"] >= args.fail_under

    report = {
        "success": all(result["success"] for result in results),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "results": results,
    }
    report["report_path"] = str(_write_report(report, output_dir, label=args.skill))
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())

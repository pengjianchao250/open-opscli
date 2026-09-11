"""ops-app-build-spec 模板安全 clone 脚本测试。"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest


SCRIPT_PATH = Path(
    "opscli/skills/templates/ops-app-build-spec/scripts/clone_template.py"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ops_app_clone_template", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    return result.stdout.strip()


def test_detach_git_metadata_preserves_template_files(tmp_path: Path) -> None:
    module = _load_script()
    project = tmp_path / "project"
    (project / ".git" / "objects").mkdir(parents=True)
    (project / ".git" / "config").write_text("template remote", encoding="utf-8")
    (project / ".gitignore").write_text(".opscli/\n", encoding="utf-8")
    (project / "app.yaml").write_text("app_id: Ab123\n", encoding="utf-8")

    result = module.detach_git_metadata(project)

    assert result == project.resolve()
    assert not (project / ".git").exists()
    assert (project / ".gitignore").read_text(encoding="utf-8") == ".opscli/\n"
    assert (project / "app.yaml").is_file()


def test_clone_template_rejects_non_empty_target(tmp_path: Path) -> None:
    module = _load_script()
    target = tmp_path / "project"
    target.mkdir()
    (target / "keep.txt").write_text("existing", encoding="utf-8")

    with pytest.raises(module.TemplateCloneError, match="项目目录必须为空"):
        module.clone_template(target, repo_url="unused")

    assert (target / "keep.txt").read_text(encoding="utf-8") == "existing"


def test_clone_template_defaults_to_master_branch() -> None:
    module = _load_script()

    assert module.DEFAULT_TEMPLATE_BRANCH == "master"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_clone_template_removes_cloned_repository_metadata(tmp_path: Path) -> None:
    module = _load_script()
    source = tmp_path / "template"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.name", "Template Test")
    _git(source, "config", "user.email", "template@example.com")
    (source / ".gitignore").write_text(".opscli/\n", encoding="utf-8")
    (source / "app.yaml").write_text("app_id: Ab123\n", encoding="utf-8")
    _git(source, "add", "-A")
    _git(source, "commit", "-m", "template")

    target = tmp_path / "project"
    result = module.clone_template(target, repo_url=str(source), branch="main")

    assert result == target.resolve()
    assert not (target / ".git").exists()
    assert (target / ".gitignore").read_text(encoding="utf-8") == ".opscli/\n"
    assert (target / "app.yaml").read_text(encoding="utf-8") == "app_id: Ab123\n"

import re
from pathlib import Path


def _extract_version(pattern: str, content: str) -> str:
    match = re.search(pattern, content, re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_pyproject_and_fallback_version_are_aligned():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    version_module = Path("opscli/version.py").read_text(encoding="utf-8")

    package_version = _extract_version(r'^version = "([^"]+)"$', pyproject)
    fallback_version = _extract_version(r'^FALLBACK_VERSION = "([^"]+)"$', version_module)

    assert fallback_version == f"{package_version}-dev"

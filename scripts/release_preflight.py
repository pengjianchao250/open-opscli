"""Cross-platform release preflight checks for opscli.

This script is intended to be runnable both locally and in CI before publishing
to PyPI/TestPyPI. It focuses on current single-package release reality:

1. install test dependencies
2. run unit tests
3. build sdist/wheel
4. install the built wheel into a clean virtualenv
5. smoke-test the installed CLI entry point
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist"


def run(cmd: list[str], *, cwd: Path = REPO_ROOT, env: dict[str, str] | None = None) -> None:
    """Run a command and stream output."""
    printable = " ".join(str(part) for part in cmd)
    print(f"\n[preflight] $ {printable}", flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def install_dev_dependencies() -> None:
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    run([sys.executable, "-m", "pip", "install", "-e", ".[dev]"])


def run_tests(pytest_args: list[str] | None = None) -> None:
    args = pytest_args or ["-q"]
    run([sys.executable, "-m", "pytest", *args])


def build_artifacts() -> None:
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    run([sys.executable, "-m", "pip", "install", "build"])
    env = os.environ.copy()
    env.setdefault("OPSCLI_SKILL_PROFILE", "python-release")
    run([sys.executable, "-m", "build"], env=env)
    run(
        [
            sys.executable,
            "scripts/check_skill_release_manifest.py",
            "--profile",
            env["OPSCLI_SKILL_PROFILE"],
            "--artifact",
            "wheel",
            "--dist",
            "dist/*.whl",
        ]
    )
    run(
        [
            sys.executable,
            "scripts/check_skill_release_manifest.py",
            "--profile",
            env["OPSCLI_SKILL_PROFILE"],
            "--artifact",
            "sdist",
            "--dist",
            "dist/*.tar.gz",
        ]
    )


def latest_wheel() -> Path:
    wheels = sorted(DIST_DIR.glob("*.whl"))
    if not wheels:
        raise FileNotFoundError("dist/ 下未找到 wheel 文件，请先执行 build")
    return wheels[-1]


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def venv_cli(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "opscli.exe"
    return venv_dir / "bin" / "opscli"


def smoke_test_built_wheel() -> None:
    wheel = latest_wheel()
    with tempfile.TemporaryDirectory(prefix="opscli-release-preflight-") as tmp:
        venv_dir = Path(tmp) / "venv"
        venv.EnvBuilder(with_pip=True).create(venv_dir)

        python_bin = venv_python(venv_dir)
        cli_bin = venv_cli(venv_dir)

        run([str(python_bin), "-m", "pip", "install", "--upgrade", "pip"])
        run([str(python_bin), "-m", "pip", "install", str(wheel)])

        if not cli_bin.exists():
            raise FileNotFoundError(f"未找到安装后的 CLI 入口: {cli_bin}")

        smoke_commands = [
            [str(cli_bin), "--version"],
            [str(cli_bin), "--help"],
            [str(cli_bin), "auth", "--help"],
            [str(cli_bin), "query", "--help"],
            [str(cli_bin), "skills", "--help"],
            [str(cli_bin), "amazon", "--help"],
        ]
        for cmd in smoke_commands:
            run(cmd)

        run(
            [
                str(python_bin),
                "-c",
                (
                    "from opscli import AuthClient; "
                    "from opscli.auth import AuthClient as AuthClient2; "
                    "assert AuthClient is AuthClient2; "
                    "print('sdk-import-ok')"
                ),
            ]
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run release preflight checks.")
    parser.add_argument(
        "--stage",
        choices=["install", "test", "build", "smoke", "all"],
        default="all",
        help="Run a single stage or the full sequence.",
    )
    parser.add_argument(
        "--pytest-args",
        nargs=argparse.REMAINDER,
        help="Additional pytest args, e.g. --pytest-args -q tests/auth",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pytest_args = args.pytest_args

    if args.stage == "install":
        install_dev_dependencies()
        return
    if args.stage == "test":
        install_dev_dependencies()
        run_tests(pytest_args)
        return
    if args.stage == "build":
        build_artifacts()
        return
    if args.stage == "smoke":
        smoke_test_built_wheel()
        return

    install_dev_dependencies()
    run_tests(pytest_args)
    build_artifacts()
    smoke_test_built_wheel()


if __name__ == "__main__":
    main()

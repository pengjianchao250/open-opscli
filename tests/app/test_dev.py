"""本地看板开发预览服务测试。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.services.dev import DEFAULT_BACKEND_PORT, PORT_SCAN_ATTEMPTS, DevService


def _write_project(root: Path) -> None:
    (root / "scripts").mkdir()
    (root / "frontend").mkdir()
    (root / "backend").mkdir()
    for relative in (
        ".env.example",
        "scripts/init_env.py",
        "scripts/check_startup.py",
        "requirements.txt",
        "frontend/package.json",
        "frontend/pnpm-lock.yaml",
        "backend/app.py",
    ):
        (root / relative).write_text("", encoding="utf-8")


def test_prepare_root_rejects_non_template_project() -> None:
    with TemporaryDirectory(dir=Path.cwd()) as directory:
        with pytest.raises(AppProjectError, match="不是受支持的 AppHub 看板模板"):
            DevService()._prepare_root(Path(directory))


def test_validate_env_rejects_missing_keys_and_placeholder_token() -> None:
    with TemporaryDirectory(dir=Path.cwd()) as directory:
        root = Path(directory)
        (root / ".env.example").write_text(
            "INTERNAL_API_TOKEN=placeholder\nSQLITE_PATH=.data/app.db\n",
            encoding="utf-8",
        )
        (root / ".env").write_text(
            "INTERNAL_API_TOKEN=please-change-me-to-a-random-32-chars\n",
            encoding="utf-8",
        )

        with pytest.raises(AppProjectError, match="缺少配置项"):
            DevService()._validate_env(root)


def test_validate_env_rejects_duplicate_keys() -> None:
    with TemporaryDirectory(dir=Path.cwd()) as directory:
        root = Path(directory)
        (root / ".env.example").write_text("INTERNAL_API_TOKEN=placeholder\n", encoding="utf-8")
        (root / ".env").write_text(
            "INTERNAL_API_TOKEN=one\nINTERNAL_API_TOKEN=two\n",
            encoding="utf-8",
        )

        with pytest.raises(AppProjectError, match="重复键"):
            DevService()._validate_env(root)


def test_validate_env_accepts_generated_configuration() -> None:
    with TemporaryDirectory(dir=Path.cwd()) as directory:
        root = Path(directory)
        (root / ".env.example").write_text(
            "INTERNAL_API_TOKEN=placeholder\nSQLITE_PATH=.data/app.db\n",
            encoding="utf-8",
        )
        (root / ".env").write_text(
            "INTERNAL_API_TOKEN=0123456789abcdef\nSQLITE_PATH=.data/app.db\n",
            encoding="utf-8",
        )

        DevService()._validate_env(root)


def test_resolve_package_manager_prefers_corepack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(
        json.dumps({"packageManager": "pnpm@11.0.0"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "opscli.app.services.dev.shutil.which",
        lambda name: "C:/tools/corepack.cmd" if name == "corepack" else None,
    )

    result = DevService()._resolve_package_manager(frontend)

    assert result == {
        "command": ["C:/tools/corepack.cmd", "pnpm"],
        "package_manager": "pnpm",
        "package_manager_version": "11.0.0",
        "package_manager_via": "corepack",
    }


def test_resolve_package_manager_allows_matching_direct_pnpm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(
        json.dumps({"packageManager": "pnpm@11.0.0"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "opscli.app.services.dev.shutil.which",
        lambda name: "C:/tools/pnpm.cmd" if name == "pnpm" else None,
    )
    monkeypatch.setattr(
        "opscli.app.services.dev.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "11.0.0\n", ""),
    )

    result = DevService()._resolve_package_manager(frontend)

    assert result["command"] == ["C:/tools/pnpm.cmd"]
    assert result["package_manager_via"] == "direct"


def test_resolve_package_manager_rejects_mismatched_direct_pnpm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(
        json.dumps({"packageManager": "pnpm@11.0.0"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "opscli.app.services.dev.shutil.which",
        lambda name: "C:/tools/pnpm.cmd" if name == "pnpm" else None,
    )
    monkeypatch.setattr(
        "opscli.app.services.dev.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "10.0.0\n", ""),
    )

    with pytest.raises(AppProjectError, match="项目要求 11.0.0"):
        DevService()._resolve_package_manager(frontend)


@pytest.mark.parametrize("package_manager", [None, "npm@11.0.0", "pnpm@latest", "pnpm@11"])
def test_resolve_package_manager_rejects_invalid_declaration(
    tmp_path: Path,
    package_manager: str | None,
) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(
        json.dumps({"packageManager": package_manager}),
        encoding="utf-8",
    )

    with pytest.raises(AppProjectError, match="packageManager"):
        DevService()._resolve_package_manager(frontend)


def test_select_ports_uses_defaults_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    service = DevService()
    monkeypatch.setattr(service, "_is_port_available", lambda port: True)

    assert service._select_ports(None, None) == (8035, 5173)


def test_select_ports_skips_occupied_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    service = DevService()
    occupied = {8035, 5173}
    monkeypatch.setattr(service, "_is_port_available", lambda port: port not in occupied)

    assert service._select_ports(None, None) == (8036, 5174)


@pytest.mark.parametrize(
    ("occupied", "expected"),
    [
        ({8035}, (8036, 5173)),
        ({5173}, (8035, 5174)),
    ],
)
def test_select_ports_only_moves_conflicting_side(
    occupied: set[int],
    expected: tuple[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DevService()
    monkeypatch.setattr(service, "_is_port_available", lambda port: port not in occupied)

    assert service._select_ports(None, None) == expected


def test_select_ports_keeps_explicit_port_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    service = DevService()
    monkeypatch.setattr(service, "_is_port_available", lambda port: port != 8035)

    with pytest.raises(AppProjectError, match="端口 8035 已被占用"):
        service._select_ports(8035, None)


def test_select_ports_avoids_explicit_port_when_selecting_other_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DevService()
    monkeypatch.setattr(service, "_is_port_available", lambda port: True)

    assert service._select_ports(None, 8035) == (8036, 8035)


def test_select_ports_reports_exhausted_scan_range(monkeypatch: pytest.MonkeyPatch) -> None:
    service = DevService()
    monkeypatch.setattr(service, "_is_port_available", lambda port: False)

    last_port = DEFAULT_BACKEND_PORT + PORT_SCAN_ATTEMPTS - 1
    with pytest.raises(AppProjectError, match=rf"{DEFAULT_BACKEND_PORT}~{last_port}"):
        service._select_ports(None, None)


def test_status_reports_running_only_when_project_processes_and_ports_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DevService()
    service._write_state(
        tmp_path,
        backend_port=8036,
        frontend_port=5174,
        backend_pid=1201,
        frontend_pid=1202,
    )
    monkeypatch.setattr(service, "_is_process_running", lambda pid: True)
    monkeypatch.setattr(service, "_is_backend_ready", lambda port: port == 8036)
    monkeypatch.setattr(service, "_is_port_open", lambda port: port == 5174)

    result = service.status(tmp_path)

    assert result["status"] == "running"
    assert result["running"] is True
    assert result["identity_verified"] is True
    assert result["project_root"] == str(tmp_path.resolve())
    assert result["backend_url"] == "http://127.0.0.1:8036"
    assert result["frontend_url"] == "http://127.0.0.1:5174"


def test_status_rejects_reused_ports_after_recorded_processes_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DevService()
    service._write_state(
        tmp_path,
        backend_port=8035,
        frontend_port=5173,
        backend_pid=1301,
        frontend_pid=1302,
    )
    monkeypatch.setattr(service, "_is_process_running", lambda pid: False)
    monkeypatch.setattr(service, "_is_backend_ready", lambda port: True)
    monkeypatch.setattr(service, "_is_port_open", lambda port: True)

    result = service.status(tmp_path)

    assert result["status"] == "stale"
    assert result["running"] is False
    assert result["identity_verified"] is False
    assert result["ports_reused"] is True
    assert "不得视为当前项目" in result["message"]


def test_status_does_not_claim_running_without_project_state(tmp_path: Path) -> None:
    result = DevService().status(tmp_path)

    assert result["status"] == "not_running"
    assert result["running"] is False
    assert "不得仅凭已有端口" in result["message"]


def test_ensure_no_active_state_rejects_duplicate_project_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DevService()
    monkeypatch.setattr(
        service,
        "status",
        lambda root: {
            "active": True,
            "frontend_url": "http://127.0.0.1:5174",
            "backend_url": "http://127.0.0.1:8036",
        },
    )

    with pytest.raises(AppProjectError, match="已有本地开发预览进程"):
        service._ensure_no_active_state(tmp_path)


def test_run_uses_frontend_cwd_and_forwards_vite_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = DevService()
    starts: list[tuple[list[str], Path, dict[str, str] | None]] = []
    stopped: list[object] = []
    processes: list[object] = []

    class FakeProcess:
        def __init__(self, pid: int):
            self.pid = pid

        def poll(self):
            return None

    monkeypatch.setattr(service, "_prepare_root", lambda path: tmp_path)
    monkeypatch.setattr(service, "_validate_ports", lambda *args: None)
    monkeypatch.setattr(service, "_select_ports", lambda *args: (8036, 5174))
    monkeypatch.setattr(service, "_find_tool", lambda name, message: f"C:/tools/{name}.exe")
    monkeypatch.setattr(
        service,
        "_resolve_package_manager",
        lambda frontend: {
            "command": ["C:/tools/corepack.cmd", "pnpm"],
            "package_manager": "pnpm",
            "package_manager_version": "11.0.0",
            "package_manager_via": "corepack",
        },
    )
    monkeypatch.setattr(service, "_initialize_env", lambda root: None)
    monkeypatch.setattr(service, "_validate_env", lambda root: None)
    monkeypatch.setattr(service, "_ensure_virtualenv", lambda root, uv: "C:/project/.venv/python.exe")
    monkeypatch.setattr(service, "_run_command", lambda *args, **kwargs: None)
    def start_process(args, cwd, env=None):
        starts.append((list(args), cwd, env))
        process = FakeProcess(1400 + len(processes))
        processes.append(process)
        return process

    monkeypatch.setattr(service, "_start_process", start_process)
    monkeypatch.setattr(service, "_wait_for_backend", lambda *args: None)
    monkeypatch.setattr(service, "_wait_for_port", lambda *args: None)
    monkeypatch.setattr(service, "_wait_for_processes", lambda processes: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(service, "_stop_processes", lambda processes: stopped.extend(processes))

    service.run(tmp_path)

    frontend_args, frontend_cwd, frontend_env = starts[1]
    assert frontend_cwd == tmp_path / "frontend"
    assert frontend_args == [
        "C:/tools/corepack.cmd",
        "pnpm",
        "dev",
        "--host",
        "127.0.0.1",
        "--port",
        "5174",
    ]
    assert frontend_env == {"APP_DEV_BACKEND_PORT": "8036"}
    assert starts[0][2] is None
    assert stopped == processes
    output = capsys.readouterr().out
    assert "前端 http://127.0.0.1:5174" in output
    assert "后端 http://127.0.0.1:8036" in output
    assert "opscli app dev-status" in output
    assert not (tmp_path / ".opscli" / "dev.json").exists()


def test_run_stops_backend_when_frontend_process_cannot_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DevService()
    backend = object()
    stopped: list[object] = []
    calls = 0

    monkeypatch.setattr(service, "_prepare_root", lambda path: tmp_path)
    monkeypatch.setattr(service, "_validate_ports", lambda *args: None)
    monkeypatch.setattr(service, "_select_ports", lambda *args: (8035, 5173))
    monkeypatch.setattr(service, "_find_tool", lambda name, message: f"C:/tools/{name}.exe")
    monkeypatch.setattr(
        service,
        "_resolve_package_manager",
        lambda frontend: {
            "command": ["pnpm"],
            "package_manager": "pnpm",
            "package_manager_version": "11.0.0",
            "package_manager_via": "direct",
        },
    )
    monkeypatch.setattr(service, "_initialize_env", lambda root: None)
    monkeypatch.setattr(service, "_validate_env", lambda root: None)
    monkeypatch.setattr(service, "_ensure_virtualenv", lambda root, uv: "python")
    monkeypatch.setattr(service, "_run_command", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_wait_for_backend", lambda *args: None)
    monkeypatch.setattr(service, "_stop_processes", lambda processes: stopped.extend(processes))

    def start_process(args, cwd, env=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return backend
        raise AppProjectError("APP-DEV-COMMAND", "frontend failed")

    monkeypatch.setattr(service, "_start_process", start_process)

    with pytest.raises(AppProjectError, match="frontend failed"):
        service.run(tmp_path)

    assert stopped == [backend]


def test_start_process_merges_environment_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    process = object()

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return process

    monkeypatch.setenv("EXISTING_ENV", "kept")
    monkeypatch.setattr("opscli.app.services.dev.subprocess.Popen", fake_popen)

    result = DevService()._start_process(
        ["node", "server.js"],
        tmp_path,
        env={"APP_DEV_BACKEND_PORT": "8036"},
    )

    assert result is process
    assert captured["env"]["EXISTING_ENV"] == "kept"
    assert captured["env"]["APP_DEV_BACKEND_PORT"] == "8036"

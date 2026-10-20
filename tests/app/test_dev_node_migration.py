"""Node 单服务迁移项目的本地开发启动回归。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from opscli.app.domain.exceptions import AppProjectError
from opscli.app.services.dev import DevService


def _write_node_project(root: Path, *, manager: str = "pnpm", framework: str = "vinext") -> Path:
    migration = root / ".opscli" / "migration" / "migration-test"
    migration.mkdir(parents=True)
    (root / ".opscli" / "project.json").write_text(
        json.dumps({"origin_type": "migration_copy", "migration_id": "migration-test"}),
        encoding="utf-8",
    )
    (migration / "migration.json").write_text(
        json.dumps({"delivery_ready": True}), encoding="utf-8"
    )
    script = "node scripts/run_vinext.mjs dev" if framework == "vinext" else f"{framework} dev"
    frontend = {
        "kind": "node_web",
        "command": [manager, "dev"] if manager == "yarn" else [manager, "run", "dev"],
        "cwd": ".",
        "script": "dev",
        "script_command": script,
        "orchestrator": True,
    }
    manifest_path = migration / "startup-manifest.json"
    manifest_path.write_text(
        json.dumps({
            "status": "ready",
            "launch_mode": "single",
            "runtime": {"kind": "dockerfile_native", "command": ["node", "server.js"]},
            "backend": None,
            "frontend": frontend,
        }),
        encoding="utf-8",
    )
    (root / "package.json").write_text(
        json.dumps({"scripts": {"dev": script}, "devDependencies": {framework: "1.0.0"}}),
        encoding="utf-8",
    )
    lock = {"pnpm": "pnpm-lock.yaml", "npm": "package-lock.json", "yarn": "yarn.lock"}[manager]
    (root / lock).write_text("", encoding="utf-8")
    (root / "node_modules").mkdir()
    return manifest_path


def test_node_migration_accepts_real_vinext_manifest_without_template(tmp_path: Path) -> None:
    _write_node_project(tmp_path)
    service = DevService()

    assert service._prepare_root(tmp_path) == tmp_path.resolve()
    startup = service._load_migration_startup(tmp_path)
    assert startup is not None
    assert "backend" not in startup
    assert startup["frontend"]["command"] == ["pnpm", "run", "dev"]


@pytest.mark.parametrize("cwd", ["../", "missing"])
def test_node_migration_rejects_invalid_cwd(tmp_path: Path, cwd: str) -> None:
    manifest_path = _write_node_project(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["frontend"]["cwd"] = cwd
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AppProjectError, match="工作目录"):
        DevService()._load_migration_startup(tmp_path)


@pytest.mark.parametrize("framework,host_flag", [("vinext", "--hostname"), ("next", "--hostname"), ("vite", "--host")])
@pytest.mark.parametrize("manager", ["pnpm", "npm", "yarn"])
def test_node_commands_preserve_manager_and_reuse_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, framework: str, host_flag: str, manager: str,
) -> None:
    _write_node_project(tmp_path, manager=manager, framework=framework)
    service = DevService()
    monkeypatch.setattr(service, "_find_tool", lambda name, message: f"/tools/{name}")
    monkeypatch.setattr(service, "_run_command", lambda *args, **kwargs: pytest.fail("不应重装或构建"))
    item = service._load_migration_startup(tmp_path)["frontend"]

    command, cwd = service._prepare_migration_node(tmp_path, item, 5174)

    prefix = [f"/tools/{manager}", "dev"] if manager == "yarn" else [f"/tools/{manager}", "run", "dev"]
    if manager == "npm":
        prefix.append("--")
    expected = [*prefix, host_flag, "127.0.0.1", "--port", "5174"]
    if framework == "vite":
        expected.append("--strictPort")
    assert command == expected
    assert cwd == tmp_path.resolve()


@pytest.mark.parametrize("manager,install", [
    ("pnpm", ["install", "--frozen-lockfile"]),
    ("npm", ["ci"]),
    ("yarn", ["install", "--frozen-lockfile"]),
])
def test_node_installs_missing_dependencies_with_existing_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manager: str, install: list[str],
) -> None:
    _write_node_project(tmp_path, manager=manager)
    (tmp_path / "node_modules").rmdir()
    service = DevService()
    commands = []
    monkeypatch.setattr(service, "_find_tool", lambda name, message: name)
    monkeypatch.setattr(service, "_run_command", lambda args, cwd, *rest, **kwargs: commands.append((args, cwd)))

    service._prepare_migration_node(tmp_path, service._load_migration_startup(tmp_path)["frontend"], 5174)

    assert commands == [([manager, *install], tmp_path.resolve())]


@pytest.mark.parametrize("change,message", [
    ("script", "开发脚本"), ("framework", "无法确认"), ("command", "参数"),
    ("manager", "packageManager"), ("lock", "缺少 pnpm-lock.yaml"), ("compound", "单服务"),
])
def test_node_rejects_drift_or_ambiguous_entry_before_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str, message: str,
) -> None:
    _write_node_project(tmp_path)
    service = DevService()
    item = service._load_migration_startup(tmp_path)["frontend"]
    package_path = tmp_path / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    if change == "script":
        package["scripts"]["dev"] = "vinext dev --port 3001"
    elif change == "framework":
        package["devDependencies"] = {}
    elif change == "command":
        item["command"].extend(["--", "--port", "8000"])
    elif change == "manager":
        package["packageManager"] = "npm@10.0.0"
    elif change == "lock":
        (tmp_path / "node_modules").rmdir()
        (tmp_path / "pnpm-lock.yaml").unlink()
    else:
        package["scripts"]["dev"] = "vinext dev && node server.js"
        item["script_command"] = package["scripts"]["dev"]
    package_path.write_text(json.dumps(package), encoding="utf-8")
    monkeypatch.setattr(service, "_find_tool", lambda name, message: name)

    with pytest.raises(AppProjectError, match=message) as caught:
        service._prepare_migration_node(tmp_path, item, 5174)
    assert "scan-startup" in caught.value.fix_hint


def test_node_selects_recorded_dev_candidate_instead_of_production_runtime(tmp_path: Path) -> None:
    manifest_path = _write_node_project(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dev = dict(manifest["frontend"])
    manifest["frontend"].update(script="start", command=["pnpm", "run", "start"], candidate_scripts=[dev])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert DevService()._load_migration_startup(tmp_path)["frontend"] == dev


def test_node_requires_recorded_dev_candidate(tmp_path: Path) -> None:
    manifest_path = _write_node_project(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["frontend"]["script"] = "start"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AppProjectError, match="dev 开发入口"):
        DevService()._load_migration_startup(tmp_path)


def test_node_requires_delivery_gate(tmp_path: Path) -> None:
    manifest = _write_node_project(tmp_path)
    (manifest.parent / "migration.json").write_text(json.dumps({"delivery_ready": False}), encoding="utf-8")

    with pytest.raises(AppProjectError, match="门禁"):
        DevService().run(tmp_path)


def test_unknown_migration_entry_explains_recovery(tmp_path: Path) -> None:
    manifest_path = _write_node_project(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["frontend"]["kind"] = "unknown"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AppProjectError, match="本地开发入口") as caught:
        DevService()._load_migration_startup(tmp_path)
    assert "scan-startup" in caught.value.fix_hint


def test_node_uses_scanned_subdirectory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _write_node_project(tmp_path)
    web = tmp_path / "web"
    web.mkdir()
    for name in ("package.json", "pnpm-lock.yaml", "node_modules"):
        (tmp_path / name).rename(web / name)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["frontend"]["cwd"] = "web"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    service = DevService()
    monkeypatch.setattr(service, "_find_tool", lambda name, message: name)

    _, cwd = service._prepare_migration_node(tmp_path, service._load_migration_startup(tmp_path)["frontend"], 5174)

    assert cwd == web.resolve()


def test_node_package_manager_respects_declared_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DevService()
    monkeypatch.setattr("opscli.app.services.dev.shutil.which", lambda name: "/tools/corepack")
    assert service._migration_node_manager(tmp_path, tmp_path, "pnpm", "pnpm@10.15.0") == ["/tools/corepack", "pnpm"]
    monkeypatch.setattr("opscli.app.services.dev.shutil.which", lambda name: None)
    monkeypatch.setattr(service, "_find_tool", lambda *args: "/tools/pnpm")
    monkeypatch.setattr("opscli.app.services.dev.subprocess.run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "10.15.0\n"))
    assert service._migration_node_manager(tmp_path, tmp_path, "pnpm", "pnpm@10.15.0") == ["/tools/pnpm"]
    with pytest.raises(AppProjectError, match="10.16.0"):
        service._migration_node_manager(tmp_path, tmp_path, "pnpm", "pnpm@10.16.0")


@pytest.mark.parametrize("backend_port,frontend_port", [(8035, 5173), (0, None), (None, 65536)])
def test_node_rejects_conflicting_or_invalid_ports(backend_port: int | None, frontend_port: int | None) -> None:
    with pytest.raises(AppProjectError):
        DevService()._validate_node_ports(backend_port, frontend_port)


@pytest.mark.parametrize("ports", [(None, 5174), (5174, None), (5174, 5174)])
def test_node_explicit_port_never_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ports: tuple[int | None, int | None],
) -> None:
    _write_node_project(tmp_path)
    service = DevService()
    monkeypatch.setattr(service, "_is_port_available", lambda port: False)
    monkeypatch.setattr(service, "_find_tool", lambda *args: pytest.fail("端口校验应先失败"))

    with pytest.raises(AppProjectError, match="5174"):
        service.run(tmp_path, backend_port=ports[0], frontend_port=ports[1])


@pytest.mark.parametrize("failure", [None, "readiness", "runtime", "state"])
def test_node_run_tracks_real_single_process_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None,
) -> None:
    _write_node_project(tmp_path)
    service = DevService()
    process = type("FakeProcess", (), {"pid": 9101})()
    starts = []
    stopped = []
    monkeypatch.setattr(service, "_is_port_available", lambda port: port == 5174)
    monkeypatch.setattr(service, "_find_tool", lambda name, message: name if name in {"node", "pnpm"} else pytest.fail("不应要求 Python"))
    monkeypatch.setattr(service, "_run_command", lambda *args, **kwargs: pytest.fail("不应安装或构建"))
    monkeypatch.setattr(service, "_start_process", lambda args, cwd: starts.append((args, cwd)) or process)
    monkeypatch.setattr(service, "_stop_processes", lambda processes: stopped.extend(processes))

    def ready(selected_process, port):
        assert selected_process is process
        assert port == 5174
        if failure == "readiness":
            raise AppProjectError("APP-DEV-RUNTIME", "就绪失败")

    def wait(processes):
        state = json.loads((tmp_path / ".opscli" / "dev.json").read_text(encoding="utf-8"))
        assert processes == [process]
        assert state["app_pid"] == 9101
        assert state["app_port"] == 5174
        assert "backend_pid" not in state
        if failure == "runtime":
            raise AppProjectError("APP-DEV-RUNTIME", "进程退出")
        raise KeyboardInterrupt

    monkeypatch.setattr(service, "_wait_for_port", ready)
    monkeypatch.setattr(service, "_wait_for_processes", wait)
    if failure == "state":
        monkeypatch.setattr(service, "_write_single_state", lambda *args, **kwargs: (_ for _ in ()).throw(AppProjectError("APP-DEV-STATE", "写入失败")))
    if failure:
        with pytest.raises(AppProjectError):
            service.run(tmp_path)
    else:
        service.run(tmp_path)
    assert len(starts) == 1
    assert starts[0][1] == tmp_path.resolve()
    assert stopped == [process]
    assert not (tmp_path / ".opscli" / "dev.json").exists()


@pytest.mark.parametrize("supervisor_alive,app_alive,ready,status", [
    (True, True, True, "running"), (True, True, False, "starting"),
    (False, True, True, "stale"), (True, False, True, "stale"),
])
def test_single_status_requires_processes_and_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    supervisor_alive: bool, app_alive: bool, ready: bool, status: str,
) -> None:
    service = DevService()
    service._write_single_state(tmp_path, app_port=5174, app_pid=9101)
    monkeypatch.setattr(service, "_is_process_running", lambda pid: app_alive if pid == 9101 else supervisor_alive)
    monkeypatch.setattr(service, "_is_port_open", lambda port: ready)

    result = service.status(tmp_path)

    assert result["status"] == status
    assert result["identity_verified"] is (status == "running")
    assert result["ports_reused"] is (status == "stale" and ready)
    assert result["frontend_url"] == result["app_url"] == "http://127.0.0.1:5174"
    assert result["backend_url"] is None
    if status in {"running", "starting"}:
        with pytest.raises(AppProjectError, match="已有本地开发"):
            service._ensure_no_active_state(tmp_path)


@pytest.mark.parametrize("field,value,status", [
    ("project_root", "other", "identity_mismatch"), ("app_pid", 0, "invalid"),
    ("app_port", 65536, "invalid"), ("launch_mode", "dual", "invalid"),
])
def test_single_status_rejects_invalid_or_copied_state(tmp_path: Path, field: str, value: object, status: str) -> None:
    service = DevService()
    service._write_single_state(tmp_path, app_port=5174, app_pid=9101)
    path = tmp_path / ".opscli" / "dev.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state[field] = value
    path.write_text(json.dumps(state), encoding="utf-8")

    result = service.status(tmp_path)

    assert result["status"] == status
    assert result["running"] is False
    assert result["identity_verified"] is False

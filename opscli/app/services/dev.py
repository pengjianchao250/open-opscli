"""本地看板开发预览的环境准备与双进程编排。"""

from __future__ import annotations

import csv
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from opscli.app.domain.exceptions import AppProjectError

DEFAULT_BACKEND_PORT = 8035
DEFAULT_FRONTEND_PORT = 5173
PORT_SCAN_ATTEMPTS = 100
STARTUP_TIMEOUT_SECONDS = 60.0
ENV_KEY_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
DEV_STATE_SCHEMA_VERSION = 1
DEV_STATE_RELATIVE_PATH = Path(".opscli") / "dev.json"


class DevService:
    """准备模板项目并启动本地后端 reload 与前端热更新服务。"""

    def run(
        self,
        path: str | Path = ".",
        *,
        backend_port: int | None = None,
        frontend_port: int | None = None,
    ) -> None:
        root = self._prepare_root(path)
        self._ensure_no_active_state(root)
        self._validate_ports(backend_port, frontend_port)
        self._find_tool("node", "未检测到 Node.js，请按 frontend/package.json 安装后重试。")
        uv = self._find_tool("uv", "未检测到 uv，请安装 uv 后重试。")
        package_manager = self._resolve_package_manager(root / "frontend")
        backend_port, frontend_port = self._select_ports(backend_port, frontend_port)
        self._initialize_env(root)
        self._validate_env(root)
        python_path = self._ensure_virtualenv(root, uv)

        self._run_command(
            [python_path, str(root / "scripts" / "check_startup.py"), "--port", str(backend_port)],
            root,
            "本地启动环境检查失败。",
            stage="startup_check",
        )
        self._run_command(
            [uv, "pip", "install", "--python", python_path, "-r", "requirements.txt"],
            root,
            "后端依赖安装失败。",
            stage="backend_install",
        )
        self._run_command(
            [*package_manager["command"], "install", "--frozen-lockfile"],
            root / "frontend",
            "前端依赖安装失败。",
            stage="frontend_install",
            context=package_manager,
        )

        processes: list[subprocess.Popen] = []
        try:
            backend = self._start_process(
                [
                    python_path,
                    "-m",
                    "uvicorn",
                    "backend.app:app",
                    "--reload",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(backend_port),
                ],
                root,
            )
            processes.append(backend)
            self._wait_for_backend(backend, backend_port)

            frontend = self._start_process(
                [
                    *package_manager["command"],
                    "dev",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(frontend_port),
                ],
                root / "frontend",
                env={"APP_DEV_BACKEND_PORT": str(backend_port)},
            )
            processes.append(frontend)
            self._wait_for_port(frontend, frontend_port)
            self._write_state(
                root,
                backend_port=backend_port,
                frontend_port=frontend_port,
                backend_pid=backend.pid,
                frontend_pid=frontend.pid,
            )
            print(
                f"本地开发预览已启动：前端 http://127.0.0.1:{frontend_port}，"
                f"后端 http://127.0.0.1:{backend_port}"
            )
            print(f'项目身份校验：opscli app dev-status "{root}" --json')
            self._wait_for_processes(processes)
        except KeyboardInterrupt:
            print("\n正在停止本地开发预览。")
        finally:
            try:
                self._stop_processes(processes)
            finally:
                self._remove_state(root, supervisor_pid=os.getpid())

    def status(self, path: str | Path = ".") -> dict[str, object]:
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise AppProjectError("APP-DEV-PROJECT", f"项目目录不存在：{root}")

        state_path = self._state_path(root)
        base: dict[str, object] = {
            "project_root": str(root),
            "state_file": str(state_path),
            "running": False,
            "active": False,
            "identity_verified": False,
            "ports_reused": False,
        }
        if not state_path.is_file():
            return {
                **base,
                "status": "not_running",
                "message": "未找到当前项目的本地开发状态；不得仅凭已有端口或浏览器页面判断项目正在运行。",
            }

        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                **base,
                "status": "invalid",
                "message": "本地开发状态文件无法读取；不得把现有端口响应认定为当前项目。",
            }
        if not isinstance(state, dict) or state.get("schema_version") != DEV_STATE_SCHEMA_VERSION:
            return {
                **base,
                "status": "invalid",
                "message": "本地开发状态文件格式不受支持；请重新执行 opscli app dev。",
            }

        state_root = state.get("project_root")
        if not isinstance(state_root, str) or self._normalize_path(state_root) != self._normalize_path(root):
            return {
                **base,
                "status": "identity_mismatch",
                "message": "状态文件中的项目身份与当前目录不一致；不得使用其中的端口。",
            }

        integer_fields = ("supervisor_pid", "backend_pid", "frontend_pid", "backend_port", "frontend_port")
        if any(not self._is_positive_integer(state.get(field)) for field in integer_fields):
            return {
                **base,
                "status": "invalid",
                "message": "本地开发状态文件缺少有效的进程或端口信息；请重新执行 opscli app dev。",
            }

        supervisor_pid = int(state["supervisor_pid"])
        backend_pid = int(state["backend_pid"])
        frontend_pid = int(state["frontend_pid"])
        backend_port = int(state["backend_port"])
        frontend_port = int(state["frontend_port"])
        supervisor_running = self._is_process_running(supervisor_pid)
        backend_running = self._is_process_running(backend_pid)
        frontend_running = self._is_process_running(frontend_pid)
        backend_ready = self._is_backend_ready(backend_port)
        frontend_ready = self._is_port_open(frontend_port)
        active = supervisor_running and backend_running and frontend_running
        running = active and backend_ready and frontend_ready
        ports_reused = not active and (backend_ready or frontend_ready)

        if running:
            status = "running"
            message = "本地开发预览正在运行，项目身份已通过状态文件、进程和端口联合校验。"
        elif active:
            status = "starting"
            message = "本地开发进程仍在运行，但前后端尚未全部就绪。"
        else:
            status = "stale"
            message = "记录中的开发进程已退出；即使原端口仍返回 HTTP 200，也不得视为当前项目。"

        return {
            **base,
            **state,
            "status": status,
            "running": running,
            "active": active,
            "identity_verified": running,
            "ports_reused": ports_reused,
            "supervisor_running": supervisor_running,
            "backend_running": backend_running,
            "frontend_running": frontend_running,
            "backend_ready": backend_ready,
            "frontend_ready": frontend_ready,
            "backend_url": f"http://127.0.0.1:{backend_port}",
            "frontend_url": f"http://127.0.0.1:{frontend_port}",
            "message": message,
        }

    def _prepare_root(self, path: str | Path) -> Path:
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise AppProjectError("APP-DEV-PROJECT", f"项目目录不存在：{root}")
        required = (
            ".env.example",
            "scripts/init_env.py",
            "scripts/check_startup.py",
            "requirements.txt",
            "frontend/package.json",
            "frontend/pnpm-lock.yaml",
            "backend/app.py",
        )
        missing = [item for item in required if not (root / item).is_file()]
        if missing:
            raise AppProjectError(
                "APP-DEV-PROJECT",
                f"项目不是受支持的 AppHub 看板模板，缺少：{', '.join(missing)}",
                fix_hint="请先按 ops-app-build-spec 补齐模板项目结构。",
            )
        return root

    def _validate_ports(self, backend_port: int | None, frontend_port: int | None) -> None:
        for name, port in (("后端", backend_port), ("前端", frontend_port)):
            if port is None:
                continue
            if not 1 <= port <= 65535:
                raise AppProjectError("APP-DEV-ARGUMENT", f"{name}端口必须在 1~65535 之间。")
        if backend_port is not None and backend_port == frontend_port:
            raise AppProjectError("APP-DEV-ARGUMENT", "后端和前端不能使用同一个端口。")

    def _select_ports(
        self,
        backend_port: int | None,
        frontend_port: int | None,
    ) -> tuple[int, int]:
        reserved: set[int] = set()
        if backend_port is not None:
            self._check_port(backend_port)
            reserved.add(backend_port)
        if frontend_port is not None:
            self._check_port(frontend_port)
            reserved.add(frontend_port)

        selected_backend = backend_port
        if selected_backend is None:
            selected_backend = self._find_available_port(DEFAULT_BACKEND_PORT, reserved)
            reserved.add(selected_backend)

        selected_frontend = frontend_port
        if selected_frontend is None:
            selected_frontend = self._find_available_port(DEFAULT_FRONTEND_PORT, reserved)

        return selected_backend, selected_frontend

    def _ensure_no_active_state(self, root: Path) -> None:
        current = self.status(root)
        if current.get("active"):
            raise AppProjectError(
                "APP-DEV-ALREADY-RUNNING",
                "当前项目已有本地开发预览进程。",
                fix_hint="请使用 opscli app dev-status . --json 查看实际地址，或先停止原启动进程。",
                detail={
                    "project_root": str(root),
                    "frontend_url": current.get("frontend_url"),
                    "backend_url": current.get("backend_url"),
                },
            )
        state_path = self._state_path(root)
        if state_path.exists():
            try:
                state_path.unlink()
            except OSError as exc:
                raise AppProjectError("APP-DEV-STATE", f"无法清理失效的开发状态文件：{state_path}") from exc

    def _initialize_env(self, root: Path) -> None:
        self._run_command(
            [sys.executable, str(root / "scripts" / "init_env.py")],
            root,
            "本地环境配置生成失败。",
            stage="env_initialize",
        )

    def _validate_env(self, root: Path) -> None:
        example_keys = self._read_env_keys(root / ".env.example")
        env_path = root / ".env"
        if not env_path.is_file():
            raise AppProjectError("APP-DEV-ENV", "本地环境配置生成后仍不存在 .env。")
        env_keys = self._read_env_keys(env_path)
        missing = sorted(example_keys - env_keys)
        if missing:
            raise AppProjectError(
                "APP-DEV-ENV",
                f".env 缺少配置项：{', '.join(missing)}",
                fix_hint="请补齐 .env 后重新执行本地启动。",
            )
        token = self._read_env_value(env_path, "INTERNAL_API_TOKEN")
        if token in {None, "", "please-change-me-to-a-random-32-chars"}:
            raise AppProjectError(
                "APP-DEV-ENV",
                ".env 的 INTERNAL_API_TOKEN 未配置有效值。",
                fix_hint="删除 .env 后重新执行本地启动，或手动设置随机令牌。",
            )

    def _read_env_keys(self, path: Path) -> set[str]:
        keys: set[str] = set()
        duplicates: set[str] = set()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise AppProjectError("APP-DEV-ENV", f"无法读取环境配置：{path}") from exc
        for line in lines:
            match = ENV_KEY_RE.match(line)
            if match is None:
                continue
            key = match.group(1)
            if key in keys:
                duplicates.add(key)
            keys.add(key)
        if duplicates:
            raise AppProjectError(
                "APP-DEV-ENV",
                f"环境配置存在重复键：{', '.join(sorted(duplicates))}",
            )
        return keys

    def _read_env_value(self, path: Path, key: str) -> str | None:
        prefix = f"{key}="
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(prefix):
                return line[len(prefix) :].strip()
        return None

    def _ensure_virtualenv(self, root: Path, uv: str) -> str:
        python_path = root / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
        if not python_path.is_file():
            try:
                version = (root / ".python-version").read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise AppProjectError("APP-DEV-PROJECT", "项目缺少 .python-version。") from exc
            self._run_command(
                [uv, "venv", "--python", version, ".venv"],
                root,
                "Python 虚拟环境创建失败。",
                stage="virtualenv_create",
            )
        return str(python_path)

    def _resolve_package_manager(self, frontend: Path) -> dict:
        try:
            manifest = json.loads((frontend / "package.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AppProjectError("APP-DEV-PROJECT", "无法读取 frontend/package.json。") from exc
        declaration = manifest.get("packageManager")
        if not isinstance(declaration, str) or not re.fullmatch(r"pnpm@\d+\.\d+\.\d+", declaration):
            raise AppProjectError(
                "APP-DEV-PACKAGE-MANAGER",
                "frontend/package.json 的 packageManager 必须为 pnpm@<完整版本>。",
            )
        required_version = declaration.removeprefix("pnpm@")
        corepack = shutil.which("corepack")
        if corepack is not None:
            return {
                "command": [corepack, "pnpm"],
                "package_manager": "pnpm",
                "package_manager_version": required_version,
                "package_manager_via": "corepack",
            }

        pnpm = shutil.which("pnpm")
        if pnpm is None:
            raise AppProjectError(
                "APP-DEV-TOOL",
                f"未检测到 corepack 或 pnpm {required_version}，请启用 Corepack 后重试。",
            )
        try:
            result = subprocess.run(
                [pnpm, "--version"],
                cwd=frontend,
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AppProjectError("APP-DEV-TOOL", "无法检测现有 pnpm 版本。") from exc
        actual_version = result.stdout.strip() if result.returncode == 0 else ""
        if actual_version != required_version:
            raise AppProjectError(
                "APP-DEV-PACKAGE-MANAGER",
                f"现有 pnpm 为 {actual_version or '未知版本'}，项目要求 {required_version}。",
                fix_hint="启用 Corepack，或安装与 frontend/package.json 完全匹配的 pnpm。",
                detail={"required_version": required_version, "actual_version": actual_version},
            )
        return {
            "command": [pnpm],
            "package_manager": "pnpm",
            "package_manager_version": required_version,
            "package_manager_via": "direct",
        }

    def _find_tool(self, name: str, message: str) -> str:
        tool = shutil.which(name)
        if tool is None:
            raise AppProjectError("APP-DEV-TOOL", message)
        return tool

    def _run_command(
        self,
        args: Sequence[str],
        cwd: Path,
        failure_message: str,
        *,
        stage: str,
        context: dict | None = None,
    ) -> None:
        command = subprocess.list2cmdline(list(args)) if os.name == "nt" else shlex.join(args)
        try:
            result = subprocess.run(list(args), cwd=cwd, check=False)
        except OSError as exc:
            raise AppProjectError(
                "APP-DEV-COMMAND",
                f"{failure_message} 阶段：{stage}。",
                detail={"stage": stage, "command": command, "cwd": str(cwd), **(context or {})},
            ) from exc
        if result.returncode != 0:
            raise AppProjectError(
                "APP-DEV-COMMAND",
                f"{failure_message} 阶段：{stage}，退出码：{result.returncode}。",
                detail={
                    "stage": stage,
                    "command": command,
                    "cwd": str(cwd),
                    "return_code": result.returncode,
                    **(context or {}),
                },
            )

    def _check_port(self, port: int) -> None:
        if not self._is_port_available(port):
            raise AppProjectError("APP-DEV-PORT", f"端口 {port} 已被占用或无法绑定。")

    def _find_available_port(self, preferred_port: int, excluded: set[int]) -> int:
        last_port = min(65535, preferred_port + PORT_SCAN_ATTEMPTS - 1)
        for port in range(preferred_port, last_port + 1):
            if port in excluded:
                continue
            if self._is_port_available(port):
                return port
        raise AppProjectError(
            "APP-DEV-PORT",
            f"未在 {preferred_port}~{last_port} 范围内找到空闲端口。",
            fix_hint="请释放本地端口，或通过 --backend-port/--frontend-port 显式指定端口。",
        )

    def _is_port_available(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                return False
        return True

    def _state_path(self, root: Path) -> Path:
        return root / DEV_STATE_RELATIVE_PATH

    def _write_state(
        self,
        root: Path,
        *,
        backend_port: int,
        frontend_port: int,
        backend_pid: int,
        frontend_pid: int,
    ) -> None:
        state_path = self._state_path(root)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": DEV_STATE_SCHEMA_VERSION,
            "project_root": str(root),
            "supervisor_pid": os.getpid(),
            "backend_pid": backend_pid,
            "frontend_pid": frontend_pid,
            "backend_port": backend_port,
            "frontend_port": frontend_port,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        temporary_path = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
        try:
            temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary_path.replace(state_path)
        except OSError as exc:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise AppProjectError("APP-DEV-STATE", f"无法写入本地开发状态文件：{state_path}") from exc

    def _remove_state(self, root: Path, *, supervisor_pid: int) -> None:
        state_path = self._state_path(root)
        if not state_path.is_file():
            return
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(state, dict) or state.get("supervisor_pid") != supervisor_pid:
            return
        try:
            state_path.unlink()
        except OSError:
            pass

    def _normalize_path(self, path: str | Path) -> str:
        return os.path.normcase(str(Path(path).expanduser().resolve()))

    def _is_positive_integer(self, value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    def _is_process_running(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                )
            except (OSError, subprocess.TimeoutExpired):
                return False
            if result.returncode != 0:
                return False
            rows = csv.reader(result.stdout.splitlines())
            return any(len(row) > 1 and row[1].strip() == str(pid) for row in rows)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _is_backend_ready(self, port: int) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/__apphub_healthz", timeout=1) as response:
                return response.status == 200
        except (OSError, urllib.error.URLError):
            return False

    def _is_port_open(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.25)
            return probe.connect_ex(("127.0.0.1", port)) == 0

    def _start_process(
        self,
        args: Sequence[str],
        cwd: Path,
        *,
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen:
        kwargs: dict[str, object] = {"cwd": cwd, "stdin": None, "stdout": None, "stderr": None}
        if env:
            kwargs["env"] = {**os.environ, **env}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        try:
            return subprocess.Popen(list(args), **kwargs)
        except OSError as exc:
            raise AppProjectError("APP-DEV-COMMAND", f"无法启动本地开发进程：{args[0]}") from exc

    def _wait_for_backend(self, process: subprocess.Popen, port: int) -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AppProjectError("APP-DEV-RUNTIME", "后端开发服务启动后立即退出。")
            if self._is_backend_ready(port):
                return
            time.sleep(0.25)
        raise AppProjectError("APP-DEV-RUNTIME", f"后端开发服务未在 {int(STARTUP_TIMEOUT_SECONDS)} 秒内就绪。")

    def _wait_for_port(self, process: subprocess.Popen, port: int) -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AppProjectError("APP-DEV-RUNTIME", "前端开发服务启动后立即退出。")
            if self._is_port_open(port):
                return
            time.sleep(0.25)
        raise AppProjectError("APP-DEV-RUNTIME", f"前端开发服务未在 {int(STARTUP_TIMEOUT_SECONDS)} 秒内就绪。")

    def _wait_for_processes(self, processes: list[subprocess.Popen]) -> None:
        while True:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    raise AppProjectError("APP-DEV-RUNTIME", f"本地开发进程异常退出，退出码：{return_code}。")
            time.sleep(0.5)

    def _stop_processes(self, processes: list[subprocess.Popen]) -> None:
        for process in reversed(processes):
            if process.poll() is not None:
                continue
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                else:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass

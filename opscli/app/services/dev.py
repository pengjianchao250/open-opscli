"""本地看板开发预览的模板环境准备与迁移服务编排。"""

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
SINGLE_DEV_STATE_SCHEMA_VERSION = 2
DEV_STATE_RELATIVE_PATH = Path(".opscli") / "dev.json"


class DevService:
    """准备模板或迁移项目并监督本地开发预览服务。"""

    def run(
        self,
        path: str | Path = ".",
        *,
        backend_port: int | None = None,
        frontend_port: int | None = None,
    ) -> None:
        root = self._prepare_root(path)
        migration_startup = self._load_migration_startup(root)
        if migration_startup is not None:
            self._run_migration(
                root,
                migration_startup,
                backend_port=backend_port,
                frontend_port=frontend_port,
            )
            return
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
        if not isinstance(state, dict) or state.get("schema_version") not in (
            DEV_STATE_SCHEMA_VERSION, SINGLE_DEV_STATE_SCHEMA_VERSION
        ):
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

        if state["schema_version"] == SINGLE_DEV_STATE_SCHEMA_VERSION:
            return self._single_status(base, state)

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

    def _single_status(self, base: dict[str, object], state: dict[str, object]) -> dict[str, object]:
        """校验单服务状态，不把监听相同端口的其他进程认领为当前项目。"""

        if state.get("launch_mode") != "single" or any(
            not self._is_positive_integer(state.get(field))
            for field in ("supervisor_pid", "app_pid", "app_port")
        ) or int(state["app_port"]) > 65535:
            return {**base, "status": "invalid", "message": "单服务开发状态缺少有效进程或端口信息。"}
        supervisor_running = self._is_process_running(int(state["supervisor_pid"]))
        app_running = self._is_process_running(int(state["app_pid"]))
        app_ready = self._is_port_open(int(state["app_port"]))
        active = supervisor_running and app_running
        running = active and app_ready
        url = f'http://127.0.0.1:{state["app_port"]}'
        return {
            **base,
            **state,
            "status": "running" if running else "starting" if active else "stale",
            "running": running,
            "active": active,
            "identity_verified": running,
            "ports_reused": not active and app_ready,
            "supervisor_running": supervisor_running,
            "app_running": app_running,
            "app_ready": app_ready,
            "app_url": url,
            "frontend_url": url,
            "backend_url": None,
            "message": (
                "单服务开发预览正在运行，项目身份已通过状态文件、进程和端口联合校验。"
                if running else "单服务开发进程仍在运行，端口尚未就绪。"
                if active else "记录中的开发进程已退出；即使原端口仍有响应，也不得视为当前项目。"
            ),
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
        if missing and self._load_migration_startup(root) is None:
            raise AppProjectError(
                "APP-DEV-PROJECT",
                f"项目不是受支持的 AppHub 看板模板，缺少：{', '.join(missing)}",
                fix_hint="请先按 ops-app-build-spec 补齐模板项目结构。",
            )
        return root

    def _load_migration_startup(self, root: Path) -> dict[str, dict[str, object]] | None:
        """读取已通过交付门禁的迁移项目启动清单。"""

        marker_path = root / ".opscli" / "project.json"
        if not marker_path.is_file():
            return None
        marker = self._read_json_object(marker_path, "迁移项目标识")
        if marker.get("origin_type") != "migration_copy":
            return None
        migration_id = marker.get("migration_id")
        if not isinstance(migration_id, str) or not migration_id:
            raise AppProjectError("APP-DEV-MIGRATION", "迁移项目标识缺少 migration_id。")

        migration_dir = root / ".opscli" / "migration" / migration_id
        state = self._read_json_object(migration_dir / "migration.json", "迁移状态")
        startup = self._read_json_object(migration_dir / "startup-manifest.json", "迁移启动清单")
        if state.get("delivery_ready") is not True or startup.get("status") != "ready":
            raise AppProjectError(
                "APP-DEV-MIGRATION",
                "迁移项目尚未通过启动与交付门禁。",
                fix_hint=f'请先执行 opscli app migrate verify --target "{root}" --json。',
            )

        frontend = startup.get("frontend")
        node_only = (
            startup.get("backend") is None
            and isinstance(frontend, dict)
            and frontend.get("kind") == "node_web"
        )
        if startup.get("backend") is None and not node_only:
            raise self._node_startup_error(root, "迁移项目缺少当前支持的本地开发入口。")
        if node_only and frontend.get("script") != "dev":
            candidates = frontend.get("candidate_scripts", [])
            frontend = next(
                (item for item in candidates if isinstance(item, dict) and item.get("script") == "dev"),
                None,
            ) if isinstance(candidates, list) else None
            if frontend is None:
                raise self._node_startup_error(root, "迁移清单缺少明确的 Node dev 开发入口。")
            startup["frontend"] = frontend
        commands: dict[str, dict[str, object]] = {}
        for name in (("frontend",) if node_only else ("backend", "frontend")):
            item = startup.get(name)
            if not isinstance(item, dict):
                raise AppProjectError("APP-DEV-MIGRATION", f"迁移启动清单缺少 {name} 命令。")
            command = item.get("command")
            cwd = item.get("cwd")
            if not isinstance(command, list) or not command or not all(
                isinstance(part, str) and part for part in command
            ):
                raise AppProjectError("APP-DEV-MIGRATION", f"迁移启动清单的 {name} 命令无效。")
            if not isinstance(cwd, str) or Path(cwd).is_absolute():
                raise AppProjectError("APP-DEV-MIGRATION", f"迁移启动清单的 {name} 工作目录无效。")
            resolved_cwd = (root / cwd).resolve()
            if root != resolved_cwd and root not in resolved_cwd.parents:
                raise AppProjectError("APP-DEV-MIGRATION", f"迁移启动清单的 {name} 工作目录越界。")
            if not resolved_cwd.is_dir():
                raise AppProjectError("APP-DEV-MIGRATION", f"迁移启动清单的 {name} 工作目录不存在。")
            commands[name] = item
        return commands

    def _read_json_object(self, path: Path, label: str) -> dict[str, object]:
        """读取迁移状态 JSON，并把损坏状态转换为稳定错误。"""

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AppProjectError("APP-DEV-MIGRATION", f"无法读取{label}：{path}") from exc
        if not isinstance(payload, dict):
            raise AppProjectError("APP-DEV-MIGRATION", f"{label}必须为 JSON 对象：{path}")
        return payload

    def _run_migration(
        self,
        root: Path,
        startup: dict[str, dict[str, object]],
        *,
        backend_port: int | None,
        frontend_port: int | None,
    ) -> None:
        """按迁移入口启动 Node 单服务或既有 FastAPI 开发流程。"""

        if "backend" not in startup:
            self._run_migration_node(root, startup["frontend"], backend_port, frontend_port)
            return
        self._ensure_no_active_state(root)
        app_port = self._select_migration_port(backend_port, frontend_port)
        self._find_tool("node", "未检测到 Node.js，请按 frontend/package.json 安装后重试。")
        uv = self._find_tool("uv", "未检测到 uv，请安装 uv 后重试。")
        package_manager = self._resolve_package_manager(root / "frontend")
        python_path = self._ensure_virtualenv(root, uv)

        requirements = ["requirements.txt"]
        if (root / "requirements-apphub.txt").is_file():
            requirements.append("requirements-apphub.txt")
        install_backend = [uv, "pip", "install", "--python", python_path]
        for requirement in requirements:
            install_backend.extend(["-r", requirement])
        self._run_command(
            install_backend,
            root,
            "后端依赖安装失败。",
            stage="migration_backend_install",
        )
        self._run_command(
            [*package_manager["command"], "install", "--frozen-lockfile"],
            root / "frontend",
            "前端依赖安装失败。",
            stage="migration_frontend_install",
            context=package_manager,
        )
        self._run_command(
            [*package_manager["command"], "run", "build"],
            root / "frontend",
            "前端构建失败。",
            stage="migration_frontend_build",
            context=package_manager,
        )

        backend_command = self._migration_backend_command(startup["backend"], python_path, app_port)
        frontend_command = self._migration_frontend_command(startup["frontend"], package_manager)
        backend_cwd = (root / str(startup["backend"]["cwd"])).resolve()
        frontend_cwd = (root / str(startup["frontend"]["cwd"])).resolve()
        processes: list[subprocess.Popen] = []
        try:
            backend = self._start_process(backend_command, backend_cwd)
            processes.append(backend)
            self._wait_for_backend(backend, app_port)

            frontend = self._start_process(
                frontend_command,
                frontend_cwd,
                env={"APP_DEV_BACKEND_PORT": str(app_port)},
            )
            processes.append(frontend)
            self._wait_for_port(frontend, app_port)
            self._write_state(
                root,
                backend_port=app_port,
                frontend_port=app_port,
                backend_pid=backend.pid,
                frontend_pid=frontend.pid,
            )
            print(
                f"本地开发预览已启动：前端 http://127.0.0.1:{app_port}，"
                f"后端 http://127.0.0.1:{app_port}"
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

    def _node_startup_error(self, root: Path, message: str) -> AppProjectError:
        """为不支持或已漂移的 Node 入口提供重新扫描指引。"""

        return AppProjectError(
            "APP-DEV-MIGRATION", message,
            fix_hint=f'请核对本地开发入口并执行 opscli app migrate scan-startup --target "{root}" --json 后重试。',
        )

    def _run_migration_node(
        self, root: Path, item: dict[str, object],
        backend_port: int | None, frontend_port: int | None,
    ) -> None:
        """复用迁移项目原有 Node 开发脚本，仅监督一个 Web 服务。"""

        self._ensure_no_active_state(root)
        self._validate_node_ports(backend_port, frontend_port)
        port = frontend_port if frontend_port is not None else backend_port
        if port is None:
            port = self._find_available_port(DEFAULT_FRONTEND_PORT, set())
        else:
            self._check_port(port)
        command, cwd = self._prepare_migration_node(root, item, port)
        processes: list[subprocess.Popen] = []
        try:
            process = self._start_process(command, cwd)
            processes.append(process)
            self._wait_for_port(process, port)
            self._write_single_state(root, app_port=port, app_pid=process.pid)
            print(f"本地开发预览已启动：单服务 http://127.0.0.1:{port}")
            print(f'项目身份校验：opscli app dev-status "{root}" --json')
            self._wait_for_processes(processes)
        except KeyboardInterrupt:
            print("\n正在停止本地开发预览。")
        finally:
            try:
                self._stop_processes(processes)
            finally:
                self._remove_state(root, supervisor_pid=os.getpid())

    def _validate_node_ports(self, backend_port: int | None, frontend_port: int | None) -> None:
        """单服务允许两个端口参数作为别名，但同时指定时必须一致。"""

        for port in (backend_port, frontend_port):
            if port is not None and not 1 <= port <= 65535:
                raise AppProjectError("APP-DEV-ARGUMENT", "单服务端口必须在 1~65535 之间。")
        if backend_port is not None and frontend_port is not None and backend_port != frontend_port:
            raise AppProjectError("APP-DEV-ARGUMENT", "Node 单服务的两个显式端口必须一致。")

    def _prepare_migration_node(
        self, root: Path, item: dict[str, object], port: int,
    ) -> tuple[list[str], Path]:
        """确认开发脚本及框架参数，复用依赖并构造本地启动命令。"""

        cwd = (root / str(item["cwd"])).resolve()
        package = self._read_json_object(cwd / "package.json", "Node package.json")
        scripts = package.get("scripts")
        script = scripts.get("dev") if isinstance(scripts, dict) else None
        if item.get("script") != "dev" or not isinstance(script, str) or script != item.get("script_command"):
            raise self._node_startup_error(root, "Node 开发脚本与迁移扫描记录不一致。")
        scanned_command = list(item["command"])
        manager = scanned_command[0]
        expected = [manager, "dev"] if manager == "yarn" else [manager, "run", "dev"]
        if manager not in {"pnpm", "npm", "yarn"} or scanned_command != expected:
            raise self._node_startup_error(root, "Node 开发命令包含无法自动适配的参数。")
        dependencies = {}
        for key in ("dependencies", "devDependencies"):
            values = package.get(key, {})
            if not isinstance(values, dict):
                raise self._node_startup_error(root, "Node 依赖声明格式无效。")
            dependencies.update(values)
        framework = next(
            (name for name in ("vinext", "next", "vite") if name in dependencies and name in script), None
        )
        if framework is None or re.search(r"[;&|]", script):
            raise self._node_startup_error(root, "无法确认支持端口透传的 Node 单服务开发入口。")
        self._find_tool("node", "未检测到 Node.js，请按迁移项目 package.json 安装后重试。")
        manager_command = self._migration_node_manager(root, cwd, manager, package.get("packageManager"))
        if not (cwd / "node_modules").is_dir():
            lock = {"pnpm": "pnpm-lock.yaml", "npm": "package-lock.json", "yarn": "yarn.lock"}[manager]
            if not (cwd / lock).is_file():
                raise self._node_startup_error(root, f"Node 依赖未安装且缺少 {lock}，请先核对依赖环境。")
            if manager == "npm":
                install_args = ["ci"]
            else:
                declaration = str(package.get("packageManager", ""))
                modern_yarn = manager == "yarn" and re.match(r"yarn@(?:[2-9]|[1-9]\d)\.", declaration)
                install_args = ["install", "--immutable" if modern_yarn else "--frozen-lockfile"]
            self._run_command(
                [*manager_command, *install_args], cwd, "迁移 Node 依赖安装失败。",
                stage="migration_node_install",
            )
        args = ["dev"] if manager == "yarn" else ["run", "dev"]
        if manager == "npm":
            args.append("--")
        args.extend(["--host" if framework == "vite" else "--hostname", "127.0.0.1", "--port", str(port)])
        if framework == "vite":
            args.append("--strictPort")
        return [*manager_command, *args], cwd

    def _migration_node_manager(
        self, root: Path, cwd: Path, manager: str, declaration: object,
    ) -> list[str]:
        """保留扫描所得包管理器，并在项目声明版本时遵守该版本。"""

        version = None
        if declaration is not None:
            match = re.fullmatch(r"(pnpm|npm|yarn)@(\d+\.\d+\.\d+)(?:\+[^\s]+)?", str(declaration))
            if match is None or match[1] != manager:
                raise self._node_startup_error(root, "packageManager 与迁移开发命令不一致或版本声明无效。")
            version = match[2]
            corepack = shutil.which("corepack") if manager != "npm" else None
            if corepack:
                return [corepack, manager]
        executable = self._find_tool(manager, f"未检测到迁移项目使用的 {manager}，请安装后重试。")
        if version:
            try:
                result = subprocess.run(
                    [executable, "--version"], cwd=cwd, check=False, capture_output=True,
                    text=True, encoding="utf-8", errors="replace", timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise AppProjectError("APP-DEV-TOOL", f"无法检测 {manager} 版本。") from exc
            if result.returncode != 0 or result.stdout.strip() != version:
                raise AppProjectError("APP-DEV-PACKAGE-MANAGER", f"请安装项目声明的 {manager}@{version} 后重试。")
        return [executable]

    def _select_migration_port(
        self,
        backend_port: int | None,
        frontend_port: int | None,
    ) -> int:
        """为单进程托管前端的迁移项目选择唯一 HTTP 端口。"""

        for name, port in (("后端", backend_port), ("前端", frontend_port)):
            if port is not None and not 1 <= port <= 65535:
                raise AppProjectError("APP-DEV-ARGUMENT", f"{name}端口必须在 1~65535 之间。")
        if backend_port is not None and frontend_port is not None and backend_port != frontend_port:
            raise AppProjectError(
                "APP-DEV-ARGUMENT",
                "迁移项目由同一 FastAPI 进程托管前后端，两个显式端口必须一致。",
            )
        selected = backend_port if backend_port is not None else frontend_port
        if selected is not None:
            self._check_port(selected)
            return selected
        return self._find_available_port(DEFAULT_BACKEND_PORT, set())

    def _migration_backend_command(
        self,
        item: dict[str, object],
        python_path: str,
        port: int,
    ) -> list[str]:
        """把迁移扫描得到的 Uvicorn 命令绑定到本地虚拟环境与选定端口。"""

        command = list(item["command"])
        if len(command) < 4 or command[1:3] != ["-m", "uvicorn"]:
            raise AppProjectError(
                "APP-DEV-MIGRATION",
                "当前迁移后端命令无法接入本地开发端口。",
                fix_hint="请重新执行迁移启动扫描，或补齐可识别的 FastAPI 入口。",
            )
        command[0] = python_path
        return [*command, "--reload", "--host", "127.0.0.1", "--port", str(port)]

    def _migration_frontend_command(
        self,
        item: dict[str, object],
        package_manager: dict,
    ) -> list[str]:
        """复用已校验包管理器执行迁移清单中的前端监听命令。"""

        command = list(item["command"])
        if command[0] != "pnpm":
            raise AppProjectError(
                "APP-DEV-MIGRATION",
                "当前迁移前端命令与 frontend/package.json 的 pnpm 合同不一致。",
            )
        return [*package_manager["command"], *command[1:]]

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
        self._save_state(root, payload)

    def _write_single_state(self, root: Path, *, app_port: int, app_pid: int) -> None:
        """记录真实单服务进程，避免伪造前后端双进程状态。"""

        self._save_state(root, {
            "schema_version": SINGLE_DEV_STATE_SCHEMA_VERSION,
            "launch_mode": "single",
            "project_root": str(root),
            "supervisor_pid": os.getpid(),
            "app_pid": app_pid,
            "app_port": app_port,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })

    def _save_state(self, root: Path, payload: dict[str, object]) -> None:
        """原子保存开发状态，兼容双进程与单服务记录。"""

        state_path = self._state_path(root)
        state_path.parent.mkdir(parents=True, exist_ok=True)
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

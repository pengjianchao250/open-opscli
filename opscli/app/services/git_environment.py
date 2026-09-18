"""本地 Git 环境探测与受控安装。"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urljoin, urlsplit

import httpx

from opscli.app.domain.constants import GIT_MIN_VERSION
from opscli.app.domain.exceptions import AppGitError

WINDOWS_INSTALL_PAGE = "https://git-scm.com/install/windows"
TRUSTED_DOWNLOAD_HOSTS = {
    "git-scm.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
WINDOWS_INSTALLER_ARGS = (
    "/VERYSILENT",
    "/NORESTART",
    "/NOCANCEL",
    "/SP-",
    "/CLOSEAPPLICATIONS",
    "/RESTARTAPPLICATIONS",
)
MAX_REDIRECTS = 8
MAX_INSTALLER_BYTES = 250 * 1024 * 1024


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


class GitEnvironmentService:
    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        system: str | None = None,
        machine: str | None = None,
    ) -> None:
        self.environ = dict(os.environ if environ is None else environ)
        self.system = system or platform.system()
        self.machine = machine or platform.machine()

    def check(self) -> dict:
        platform_name = self._platform_name()
        architecture, translated = self._native_architecture(platform_name)
        candidates: list[tuple[tuple[int, int, int], Path, str]] = []
        for candidate in self._git_candidates(platform_name, architecture):
            if isinstance(candidate, tuple):
                executable, detected_via = candidate
            else:
                executable, detected_via = candidate, "standard_location"
            version = self._git_version(executable)
            if version is not None:
                candidates.append((version, executable, detected_via))

        minimum = _version_text(GIT_MIN_VERSION)
        if not candidates:
            return {
                "ready": False,
                "status": "missing",
                "platform": platform_name,
                "architecture": architecture,
                "translated": translated,
                "git_path": None,
                "detected_via": None,
                "git_version": None,
                "minimum_version": minimum,
                "install_method": None,
                "message": "未检测到可用 Git。",
            }

        version, executable, detected_via = max(candidates, key=lambda item: item[0])
        ready = version >= GIT_MIN_VERSION
        return {
            "ready": ready,
            "status": "ready" if ready else "version_unsupported",
            "platform": platform_name,
            "architecture": architecture,
            "translated": translated,
            "git_path": str(executable),
            "detected_via": detected_via,
            "git_version": _version_text(version),
            "minimum_version": minimum,
            "install_method": None,
            "message": (
                "Git 环境已就绪。"
                if ready
                else f"Git 版本过低，最低要求 {minimum}。"
            ),
        }

    def ensure(self, *, install: bool = False) -> dict:
        state = self.check()
        if state["ready"] or not install:
            return state
        if state["platform"] == "windows":
            installation = self._install_windows(state["architecture"])
        elif state["platform"] == "macos":
            installation = self._install_macos(
                state["architecture"], translated=bool(state["translated"])
            )
        else:
            return {
                **state,
                "status": "platform_unsupported",
                "message": "当前平台只检测 Git，不自动安装系统软件。",
            }

        if installation.get("status") in {
            "platform_unsupported",
            "elevation_required",
            "user_confirmation_required",
        }:
            return {**state, **installation, "ready": False}

        verified = self.check()
        if not verified["ready"]:
            raise AppGitError(
                "GIT-VERIFY-FAILED",
                "Git 安装流程结束后仍未检测到满足版本要求的 Git。",
                fix_hint="核对系统安装状态后重新执行 opscli app ensure-git --install --json。",
                detail={"installation": installation, "probe": verified},
            )
        return {
            **verified,
            **installation,
            "detected_via": "installed",
            "ready": True,
            "status": "ready",
        }

    def _platform_name(self) -> str:
        lowered = self.system.lower()
        if lowered == "windows":
            return "windows"
        if lowered == "darwin":
            return "macos"
        if lowered == "linux":
            return "linux"
        return lowered or "unknown"

    def _native_architecture(self, platform_name: str) -> tuple[str, bool]:
        raw = self.machine
        translated = False
        if platform_name == "windows":
            raw = (
                self.environ.get("PROCESSOR_ARCHITEW6432")
                or self.environ.get("PROCESSOR_ARCHITECTURE")
                or raw
            )
        elif platform_name == "macos" and raw.lower() in {"x86_64", "amd64"}:
            translated = self._sysctl_value("sysctl.proc_translated") == "1"
            if translated or self._sysctl_value("hw.optional.arm64") == "1":
                raw = "arm64"

        normalized = raw.strip().lower()
        if normalized in {"amd64", "x86_64", "x64"}:
            return "x64", translated
        if normalized in {"arm64", "aarch64"}:
            return "arm64", translated
        if normalized in {"x86", "i386", "i686"}:
            return "x86", translated
        return normalized or "unknown", translated

    def _sysctl_value(self, key: str) -> str | None:
        try:
            result = subprocess.run(
                ["/usr/sbin/sysctl", "-in", key],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    def _git_candidates(self, platform_name: str, architecture: str) -> list[tuple[Path, str]]:
        values: list[tuple[str | Path | None, str]] = [(shutil.which("git"), "path")]
        if platform_name == "windows":
            local = self.environ.get("LOCALAPPDATA")
            program_files = self.environ.get("ProgramFiles")
            program_files_x86 = self.environ.get("ProgramFiles(x86)")
            for root in (local, program_files, program_files_x86):
                if not root:
                    continue
                base = Path(root)
                if root == local:
                    base = base / "Programs"
                values.extend(
                    (
                        (base / "Git" / "cmd" / "git.exe", "standard_location"),
                        (base / "Git" / "bin" / "git.exe", "standard_location"),
                    )
                )
        elif platform_name == "macos":
            if architecture == "arm64":
                values.append(("/opt/homebrew/bin/git", "standard_location"))
            values.extend(
                (
                    ("/usr/local/bin/git", "standard_location"),
                    ("/opt/local/bin/git", "standard_location"),
                    ("/usr/bin/git", "standard_location"),
                )
            )

        unique: list[tuple[Path, str]] = []
        seen: set[str] = set()
        for value, detected_via in values:
            if not value:
                continue
            path = Path(value).expanduser().resolve(strict=False)
            key = os.path.normcase(str(path))
            if key in seen or not path.is_file():
                continue
            seen.add(key)
            unique.append((path, detected_via))
        return unique

    def _git_version(self, executable: Path) -> tuple[int, int, int] | None:
        try:
            result = subprocess.run(
                [str(executable), "--version"],
                env=self.environ,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=15,
                check=False,
            )
        except (FileNotFoundError, PermissionError, OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return _parse_git_version(result.stdout)

    def _install_windows(self, architecture: str) -> dict:
        if architecture not in {"x64", "arm64"}:
            return {
                "status": "platform_unsupported",
                "install_method": None,
                "message": f"Git 官网没有适用于当前 Windows 架构的受控安装流程：{architecture}",
            }
        try:
            installer_url = self._windows_installer_url(architecture)
            with tempfile.TemporaryDirectory(prefix="opscli-git-") as directory:
                installer = Path(directory) / Path(urlsplit(installer_url).path).name
                self._download(installer_url, installer)
                publisher = self._verify_authenticode(installer)
                result = self._run_installer(installer)
        except AppGitError as exc:
            if exc.code not in {"GIT-DOWNLOAD-FAILED", "GIT-INSTALLER-UNAVAILABLE"}:
                raise
            return self._install_windows_with_winget(exc)

        if result.returncode == 740:
            return {
                "status": "elevation_required",
                "install_method": "git-scm-official-installer",
                "installer_url": installer_url,
                "installer_publisher": publisher,
                "message": "Git for Windows 安装需要系统权限，请由宿主申请权限后重试。",
            }
        if result.returncode != 0:
            raise AppGitError(
                "GIT-INSTALL-FAILED",
                f"Git for Windows 安装器退出码异常：{result.returncode}",
                detail={"stderr": result.stderr.strip(), "stdout": result.stdout.strip()},
            )
        return {
            "install_method": "git-scm-official-installer",
            "installer_url": installer_url,
            "installer_publisher": publisher,
            "message": "已从 Git 官网入口安装 Git for Windows。",
        }

    def _windows_installer_url(self, architecture: str) -> str:
        try:
            response = httpx.get(WINDOWS_INSTALL_PAGE, timeout=30, follow_redirects=False)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AppGitError(
                "GIT-DOWNLOAD-FAILED",
                f"访问 Git 官网 Windows 安装页失败：{exc}",
            ) from exc
        parser = _LinkParser()
        parser.feed(response.text)
        suffix = "-arm64.exe" if architecture == "arm64" else "-64-bit.exe"
        for href in parser.links:
            url = urljoin(WINDOWS_INSTALL_PAGE, href)
            parsed = urlsplit(url)
            filename = Path(parsed.path).name
            if (
                parsed.scheme == "https"
                and parsed.hostname == "github.com"
                and "/git-for-windows/git/releases/download/" in parsed.path
                and filename.startswith("Git-")
                and filename.endswith(suffix)
                and not filename.startswith("PortableGit-")
            ):
                return url
        raise AppGitError(
            "GIT-INSTALLER-UNAVAILABLE",
            f"Git 官网未提供当前架构的 Git for Windows Setup：{architecture}",
        )

    def _download(self, url: str, target: Path) -> None:
        current = url
        try:
            with httpx.Client(timeout=120, follow_redirects=False) as client:
                for _ in range(MAX_REDIRECTS + 1):
                    self._assert_trusted_url(current)
                    with client.stream("GET", current) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                raise AppGitError("GIT-DOWNLOAD-FAILED", "Git 安装包重定向缺少目标地址。")
                            current = urljoin(current, location)
                            continue
                        response.raise_for_status()
                        size = 0
                        with target.open("wb") as handle:
                            for chunk in response.iter_bytes():
                                size += len(chunk)
                                if size > MAX_INSTALLER_BYTES:
                                    raise AppGitError("GIT-DOWNLOAD-FAILED", "Git 安装包超过允许的大小。")
                                handle.write(chunk)
                        if size == 0:
                            raise AppGitError("GIT-DOWNLOAD-FAILED", "Git 安装包下载结果为空。")
                        return
        except AppGitError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise AppGitError("GIT-DOWNLOAD-FAILED", f"下载 Git 安装包失败：{exc}") from exc
        raise AppGitError("GIT-DOWNLOAD-FAILED", "Git 安装包重定向次数过多。")

    def _assert_trusted_url(self, url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in TRUSTED_DOWNLOAD_HOSTS:
            raise AppGitError(
                "GIT-SOURCE-UNTRUSTED",
                f"Git 安装包下载地址不在官方可信范围：{parsed.hostname or url}",
            )

    def _verify_authenticode(self, installer: Path) -> str:
        powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
        if not powershell:
            raise AppGitError("GIT-SIGNATURE-INVALID", "无法找到 PowerShell 验证 Git 安装包签名。")
        env = {**self.environ, "OPSCLI_GIT_INSTALLER": str(installer)}
        script = (
            "$sig=Get-AuthenticodeSignature -LiteralPath $env:OPSCLI_GIT_INSTALLER;"
            "[PSCustomObject]@{Status=[string]$sig.Status;"
            "Subject=[string]$sig.SignerCertificate.Subject}|ConvertTo-Json -Compress"
        )
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=60,
            check=False,
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AppGitError("GIT-SIGNATURE-INVALID", "无法读取 Git 安装包数字签名结果。") from exc
        status = str(payload.get("Status") or "")
        subject = str(payload.get("Subject") or "").strip()
        if result.returncode != 0 or status != "Valid" or not subject:
            raise AppGitError(
                "GIT-SIGNATURE-INVALID",
                "Git 安装包数字签名无效。",
                detail={"status": status, "publisher": subject or None},
            )
        return subject

    def _run_installer(self, installer: Path) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [str(installer), *WINDOWS_INSTALLER_ARGS],
                env=self.environ,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=900,
                check=False,
            )
        except PermissionError:
            return subprocess.CompletedProcess([str(installer)], 740, "", "elevation required")
        except OSError as exc:
            if getattr(exc, "winerror", None) == 740:
                return subprocess.CompletedProcess([str(installer)], 740, "", str(exc))
            raise AppGitError("GIT-INSTALL-FAILED", f"启动 Git 安装器失败：{exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AppGitError("GIT-INSTALL-FAILED", "Git 安装器执行超时。") from exc

    def _install_windows_with_winget(self, original_error: AppGitError) -> dict:
        winget = shutil.which("winget.exe") or shutil.which("winget")
        if not winget:
            raise AppGitError(
                "GIT-INSTALLER-UNAVAILABLE",
                "Git 官网直装失败，且当前系统没有可用 WinGet。",
                detail={"official_error": original_error.to_dict()},
            ) from original_error
        result = subprocess.run(
            [
                winget,
                "install",
                "--id",
                "Git.Git",
                "-e",
                "--source",
                "winget",
                "--silent",
                "--accept-package-agreements",
                "--accept-source-agreements",
                "--disable-interactivity",
            ],
            env=self.environ,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=900,
            check=False,
        )
        if result.returncode != 0:
            raise AppGitError(
                "GIT-INSTALL-FAILED",
                f"WinGet 安装 Git 失败：exit={result.returncode}",
                detail={
                    "official_error": original_error.to_dict(),
                    "stderr": result.stderr.strip(),
                },
            )
        return {
            "install_method": "winget-git.git",
            "message": "Git 官网直装不可用，已使用官网推荐的 WinGet 安装 Git。",
        }

    def _install_macos(self, architecture: str, *, translated: bool) -> dict:
        brew = self._brew_path(architecture, translated=translated)
        if brew:
            listed = subprocess.run(
                [brew, "list", "--versions", "git"],
                env=self.environ,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=60,
                check=False,
            )
            action = "upgrade" if listed.returncode == 0 and listed.stdout.strip() else "install"
            result = subprocess.run(
                [brew, action, "git"],
                env=self.environ,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=1800,
                check=False,
            )
            if result.returncode != 0:
                raise AppGitError(
                    "GIT-INSTALL-FAILED",
                    f"Homebrew {action} git 失败：exit={result.returncode}",
                    detail={"stderr": result.stderr.strip()},
                )
            return {
                "install_method": f"homebrew-{action}",
                "message": "已按 Git 官网推荐方式通过 Homebrew 安装 Git。",
            }

        port = shutil.which("port")
        if port:
            geteuid = getattr(os, "geteuid", lambda: 1)
            if geteuid() != 0:
                return {
                    "status": "elevation_required",
                    "install_method": "macports",
                    "message": "MacPorts 安装 Git 需要系统权限，请由宿主申请权限后重试。",
                }
            result = subprocess.run(
                [port, "install", "git"],
                env=self.environ,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=1800,
                check=False,
            )
            if result.returncode != 0:
                raise AppGitError(
                    "GIT-INSTALL-FAILED",
                    f"MacPorts 安装 Git 失败：exit={result.returncode}",
                    detail={"stderr": result.stderr.strip()},
                )
            return {
                "install_method": "macports",
                "message": "已按 Git 官网推荐方式通过 MacPorts 安装 Git。",
            }

        try:
            result = subprocess.run(
                ["xcode-select", "--install"],
                env=self.environ,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (FileNotFoundError, OSError) as exc:
            raise AppGitError(
                "GIT-INSTALLER-UNAVAILABLE",
                f"无法启动 Apple Command Line Tools：{exc}",
            ) from exc
        detail = (result.stderr or result.stdout).strip()
        if result.returncode != 0 and "already installed" not in detail.lower():
            raise AppGitError(
                "GIT-INSTALL-FAILED",
                f"启动 Apple Command Line Tools 安装失败：{detail or result.returncode}",
            )
        return {
            "status": "user_confirmation_required",
            "install_method": "apple-command-line-tools",
            "message": "已发起 Apple Command Line Tools 安装，请完成系统窗口后重新检测。",
        }

    def _brew_path(self, architecture: str, *, translated: bool) -> str | None:
        candidates: Sequence[str]
        if architecture == "arm64":
            candidates = ("/opt/homebrew/bin/brew",)
        else:
            candidates = ("/usr/local/bin/brew",)
        for candidate in candidates:
            if Path(candidate).is_file():
                return candidate
        discovered = shutil.which("brew")
        if translated and discovered and discovered.startswith("/usr/local/"):
            return None
        return discovered


def _parse_git_version(text: str) -> tuple[int, int, int] | None:
    match = re.search(r"git version (\d+)\.(\d+)(?:\.(\d+))?", text)
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def _version_text(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)

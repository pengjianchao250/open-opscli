"""远程 Skill 安装器。

处理 `opscli skills install pengjianchao@ops-auth` 场景：
1. 解析标识符，获取广场元数据
2. 下载 OSS 文件写入中央存储
3. 通过 SkillsManager 链接到各工具目录
4. 回调后端记录安装次数
"""

from __future__ import annotations

import io
import json
import logging
import platform
import shutil
import tempfile
import zipfile
from pathlib import Path

import httpx

from opscli.skills.domain.exceptions import SkillRemoteError, error_to_dict
from opscli.skills.marketplace.client import MarketplaceClient
from opscli.skills.marketplace.usage_reporter import _get_client_id
from opscli.skills.packaging import get_central_skills_dir
from opscli.version import get_version

_logger = logging.getLogger("opscli.skills.marketplace.remote_installer")


def _parse_identifier(identifier: str) -> tuple[str, str]:
    """拆分 username@skill_name，验证格式合法性。"""
    if identifier.count("@") != 1:
        raise ValueError(f"无效的 Skill 标识符: {identifier!r}，应为 username@skill_name 格式")
    username, skill_name = identifier.split("@", 1)
    if not username or not skill_name:
        raise ValueError(f"标识符格式错误: {identifier!r}")
    return username, skill_name


def _download_skill_file(download_url: str, dest_path: Path) -> None:
    """从 OSS 下载 skill.md 到指定路径。"""
    resp = httpx.get(download_url, follow_redirects=True, timeout=60)
    if resp.status_code != 200:
        raise SkillRemoteError(
            f"下载技能文件失败，HTTP {resp.status_code}",
            endpoint=download_url,
            status_code=resp.status_code,
        )
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(resp.content)


_ZIP_MAGIC = b"PK\x03\x04"


def _build_skill_dir(skill_name: str, content: bytes, version: str) -> Path:
    """在中央存储目录构建技能目录结构，返回目录路径。

    支持两种格式：
    - ZIP 包（以 PK magic bytes 开头）：解压整个包到技能目录
    - 旧版 .md 文件：仅写入 SKILL.md（向后兼容）

    最终目录结构（zip 格式）：
    ~/.opscli/skills/{skill_name}/
    ├── SKILL.md
    ├── data/
    │   └── VERSION.json
    └── ...（zip 内其他文件）
    """
    central_dir = get_central_skills_dir() / skill_name
    central_dir.mkdir(parents=True, exist_ok=True)

    if content[:4] == _ZIP_MAGIC:
        # ZIP 格式：解压全部内容
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            zf.extractall(central_dir)
    else:
        # 旧版 md 格式（向后兼容）
        (central_dir / "SKILL.md").write_bytes(content)

    # 无论哪种格式，都确保 VERSION.json 包含正确版本号
    data_dir = central_dir / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "VERSION.json").write_text(
        json.dumps({"version": version, "name": skill_name}, ensure_ascii=False),
        encoding="utf-8",
    )
    return central_dir


def install_remote_skill(
    identifier: str,
    version: str | None = None,
    skills_dir: str | None = None,
    runtime: str | None = None,
    force: bool = False,
    share_code: str | None = None,
) -> dict:
    """安装远程广场技能的完整流程，返回统一 payload dict。

    share_code 不为 None 时，在步骤 1/2/6 中透传给服务端，
    用于绕过 personal/department 技能的权限校验。

    skills_dir 的语义（隔离安装）：
        显式传入时只把技能装到这一个目录，不做任何运行时探测，
        也不写入 ~/.claude、~/.codex 等用户自己的运行时目录；
        此时 runtime 参数被忽略（skills_dir 优先级更高）。
        不传时保持既有行为：按 runtime 或自动探测，链接到全部检测到的 AI 工具目录。
    """
    command = f"skills install {identifier}"

    try:
        username, skill_name = _parse_identifier(identifier)
    except ValueError as exc:
        return {"success": False, "command": command, "data": None, "error": error_to_dict(exc)}

    client = MarketplaceClient()

    # Step 1：获取技能元数据（携带 share_code 时可绕过权限校验）
    try:
        skill_data = client.get_by_identifier(username, skill_name, share_code=share_code)
    except Exception as exc:
        return {"success": False, "command": command, "data": None, "error": error_to_dict(exc)}

    skill_id = skill_data.get("id")
    target_version = version or skill_data.get("latest_version", "1.0.0")

    # Step 2：获取下载 URL（携带 share_code 时可绕过权限校验）
    try:
        download_url = client.get_download_url(skill_id, target_version if version else None, share_code=share_code)
    except Exception as exc:
        return {"success": False, "command": command, "data": None, "error": error_to_dict(exc)}

    if not download_url:
        return {
            "success": False,
            "command": command,
            "data": None,
            "error": {"type": "SkillRemoteError", "message": "服务端未返回下载地址"},
        }

    # Step 3：下载文件内容
    try:
        resp = httpx.get(download_url, follow_redirects=True, timeout=60)
        resp.raise_for_status()
        skill_md_content = resp.content
    except Exception as exc:
        return {"success": False, "command": command, "data": None, "error": error_to_dict(exc)}

    # Step 4：写入中央存储目录
    central_dir = get_central_skills_dir() / skill_name
    if central_dir.exists():
        if not force:
            # 检查版本是否相同
            ver_file = central_dir / "data" / "VERSION.json"
            if ver_file.exists():
                try:
                    existing_ver = json.loads(ver_file.read_text(encoding="utf-8")).get("version", "")
                    if existing_ver == target_version:
                        replaced = False
                    else:
                        shutil.rmtree(central_dir)
                        replaced = True
                except Exception:
                    shutil.rmtree(central_dir)
                    replaced = True
            else:
                shutil.rmtree(central_dir)
                replaced = True
        else:
            shutil.rmtree(central_dir)
            replaced = True
    else:
        replaced = False

    try:
        _build_skill_dir(skill_name, skill_md_content, target_version)
    except Exception as exc:
        return {"success": False, "command": command, "data": None, "error": error_to_dict(exc)}

    # Step 5：链接到 AI 工具目录（复用 SkillsManager）
    # _install_central force=True 时会先删除 central_dir 再从 template_dir copytree。
    # 若 template_dir == central_dir 则自我引用必然失败，所以先复制到临时目录再传入。
    from opscli.skills.services.manager import SkillsManager
    manager = SkillsManager()

    # 显式传入 skills_dir 时把安装目标锁死为这一个目录：
    # link_targets 一旦给出，_install_central 就跳过 runtime 解析与运行时探测，
    # 因此不会再写入 ~/.claude、~/.codex 等用户自己的运行时目录。
    # 这是下游「自带独立 CODEX_HOME 的本地 Agent」赖以隔离的语义——
    # 一旦回退成探测，用户本机 codex 可见的技能集合与版本就会被本命令改掉。
    # runtime 与 skills_dir 同传时以 skills_dir 为准（CLI 层会额外给出提示）。
    resolved_skills_dir = Path(skills_dir).expanduser() if skills_dir else None
    link_targets = [("custom", resolved_skills_dir)] if resolved_skills_dir else None

    try:
        with tempfile.TemporaryDirectory() as _tmp:
            tmp_template = Path(_tmp) / skill_name
            shutil.copytree(central_dir, tmp_template)
            batch_result = manager._install_central(
                skill_name,
                template_dir=tmp_template,
                link_targets=link_targets,
                cwd=Path.home(),   # 从家目录探测全局 AI 工具，不受调用时的工作目录影响
                runtime=runtime,
                force=force,
            )
    except Exception as exc:
        return {"success": False, "command": command, "data": None, "error": error_to_dict(exc)}

    # Step 6：回调后端记录安装（失败不影响安装结果）
    # 携带 share_code 时服务端会记录 install_source=share_code 并更新 used_count
    try:
        install_payload: dict = {
            "version":     target_version,
            "runtime":     runtime or "claude",
            "platform":    platform.system().lower(),
            "cli_version": get_version(),
            "client_id":   _get_client_id(),
        }
        if share_code:
            install_payload["share_code"] = share_code
        client.record_install(skill_id, install_payload)
    except Exception as exc:
        _logger.debug("安装回调失败（忽略）: %s", exc)

    return {
        "success": True,
        "command": command,
        "data": {
            "identifier":   identifier,
            "skill_name":   skill_name,
            "version":      target_version,
            "replaced":     replaced,
            "central_dir":  str(central_dir),
            # 显式指定的隔离安装目录；未指定时为 None（走运行时探测的默认行为）。
            # 下游调用方据此确认本次安装确实被限制在自己的目录里。
            "skills_dir":   str(resolved_skills_dir) if resolved_skills_dir else None,
            "installs":     [i.to_dict() for i in batch_result.installs],
        },
        "error": None,
    }

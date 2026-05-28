"""Skill 技能广场 HTTP 客户端。

封装全部广场 API 调用，认证方式复用 AuthClient（JWT Bearer），
HTTP 库使用 httpx，与 query/transport/client.py 保持一致风格。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from opscli.auth import AuthClient, OPS_URL
from opscli.skills.domain.exceptions import SkillRemoteError

_logger = logging.getLogger("opscli.skills.marketplace")

_TIMEOUT = 30

# 视为业务成功的 code 值（200=通用成功，201=创建成功，0/None=部分旧接口）
_SUCCESS_CODES = frozenset({0, 200, 201, None})


def _fields_to_multipart(fields: dict[str, Any]) -> list[tuple[str, str]]:
    """将字段字典转换为 multipart form-data 元组列表。

    列表类型的值（如 dept_ids）会展开为重复键 dept_ids[]，以符合 Laravel 数组参数规范。
    """
    result: list[tuple[str, str]] = []
    for key, value in fields.items():
        if isinstance(value, list):
            for item in value:
                result.append((f"{key}[]", str(item)))
        else:
            result.append((key, str(value)))
    return result


def _parse(response: httpx.Response, endpoint: str) -> dict:
    """统一解析响应：HTTP 错误或业务 code 不在 _SUCCESS_CODES 时抛出 SkillRemoteError。"""
    try:
        payload = response.json()
    except Exception as exc:
        raise SkillRemoteError("远端返回了无法解析的 JSON", endpoint=endpoint) from exc

    if response.status_code >= 400:
        msg = (payload.get("msg") or payload.get("message") or "") if isinstance(payload, dict) else ""
        raise SkillRemoteError(
            msg or f"远端请求失败，HTTP {response.status_code}",
            endpoint=endpoint,
            status_code=response.status_code,
        )

    if not isinstance(payload, dict):
        raise SkillRemoteError("远端返回结构不是 JSON 对象", endpoint=endpoint)

    code = payload.get("code")
    if code not in _SUCCESS_CODES:
        msg = payload.get("msg") or payload.get("message") or "远端业务执行失败"
        raise SkillRemoteError(msg, endpoint=endpoint)

    return payload


class MarketplaceClient:
    """技能广场 API 客户端。"""

    def __init__(
        self,
        auth_client: AuthClient | None = None,
        ops_url: str | None = None,
    ) -> None:
        self._auth = auth_client or AuthClient()
        self._base = (ops_url or OPS_URL).rstrip("/")

    # ──────────────────────────────────────────
    # 内部辅助
    # ──────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        token = self._auth.get_token("ops")
        return {"Authorization": f"Bearer {token}"}

    # ──────────────────────────────────────────
    # 分类
    # ──────────────────────────────────────────

    def get_categories(self) -> list[dict]:
        url = f"{self._base}/v1/skills/categories"
        resp = httpx.get(url, headers=self._auth_headers(), timeout=_TIMEOUT)
        return _parse(resp, url).get("data", [])

    # ──────────────────────────────────────────
    # 列表 / 搜索
    # ──────────────────────────────────────────

    def list_skills(self, params: dict) -> dict:
        """返回 {list, total} 原始分页数据。"""
        url = f"{self._base}/v1/skills"
        resp = httpx.get(url, headers=self._auth_headers(), params=params, timeout=_TIMEOUT)
        return _parse(resp, url).get("data", {"list": [], "total": 0})

    def get_by_identifier(self, username: str, skill_name: str) -> dict:
        url = f"{self._base}/v1/skills/by-identifier/{username}/{skill_name}"
        resp = httpx.get(url, headers=self._auth_headers(), timeout=_TIMEOUT)
        return _parse(resp, url).get("data", {})

    def get_by_id(self, skill_id: int) -> dict:
        url = f"{self._base}/v1/skills/{skill_id}"
        resp = httpx.get(url, headers=self._auth_headers(), timeout=_TIMEOUT)
        return _parse(resp, url).get("data", {})

    # ──────────────────────────────────────────
    # 版本
    # ──────────────────────────────────────────

    def get_versions(self, skill_id: int) -> list[dict]:
        url = f"{self._base}/v1/skills/{skill_id}/versions"
        resp = httpx.get(url, headers=self._auth_headers(), timeout=_TIMEOUT)
        return _parse(resp, url).get("data", [])

    def get_download_url(self, skill_id: int, version: str | None = None) -> str:
        if version:
            url = f"{self._base}/v1/skills/{skill_id}/download/{version}"
        else:
            url = f"{self._base}/v1/skills/{skill_id}/download"
        resp = httpx.get(url, headers=self._auth_headers(), timeout=_TIMEOUT)
        data = _parse(resp, url).get("data", {})
        return data.get("download_url", "")

    # ──────────────────────────────────────────
    # 上传 / 发布
    # ──────────────────────────────────────────

    @staticmethod
    def _skill_file_tuple(skill_file_path: Path) -> tuple:
        """根据文件扩展名返回 multipart files 元组（filename, fh, content_type）。"""
        mime = "application/zip" if skill_file_path.suffix.lower() == ".zip" else "text/markdown"
        return (skill_file_path.name, open(skill_file_path, "rb"), mime)

    def create_skill(self, fields: dict[str, Any], skill_file_path: Path) -> dict:
        """上传新技能。skill_file_path 可为 .zip 打包文件或 .md 文件。"""
        url = f"{self._base}/v1/skills"
        with open(skill_file_path, "rb") as fh:
            mime = "application/zip" if skill_file_path.suffix.lower() == ".zip" else "text/markdown"
            files = {"skill_file": (skill_file_path.name, fh, mime)}
            resp = httpx.post(
                url,
                headers=self._auth_headers(),
                data=_fields_to_multipart(fields),
                files=files,
                timeout=60,
            )
        return _parse(resp, url).get("data", {})

    def publish_version(self, skill_id: int, fields: dict[str, Any], skill_file_path: Path) -> dict:
        """发布新版本到已有技能。skill_file_path 可为 .zip 打包文件或 .md 文件。"""
        url = f"{self._base}/v1/skills/{skill_id}/versions"
        with open(skill_file_path, "rb") as fh:
            mime = "application/zip" if skill_file_path.suffix.lower() == ".zip" else "text/markdown"
            files = {"skill_file": (skill_file_path.name, fh, mime)}
            resp = httpx.post(
                url,
                headers=self._auth_headers(),
                data=_fields_to_multipart(fields),
                files=files,
                timeout=60,
            )
        return _parse(resp, url).get("data", {})

    def full_update_skill(
        self,
        skill_id: int,
        fields: dict[str, Any],
        skill_file_path: Path | None = None,
    ) -> dict:
        """完整编辑已有技能（元数据 + 可选文件重传 + 可选版本变更）。

        对应 POST /v1/skills/{id}（multipart/form-data）。
        skill_file_path 为 None 时仅更新元数据和/或版本号。
        """
        url = f"{self._base}/v1/skills/{skill_id}"
        data = _fields_to_multipart(fields)

        if skill_file_path is not None:
            with open(skill_file_path, "rb") as fh:
                mime = "application/zip" if skill_file_path.suffix.lower() == ".zip" else "text/markdown"
                files = {"skill_file": (skill_file_path.name, fh, mime)}
                resp = httpx.post(
                    url,
                    headers=self._auth_headers(),
                    data=data,
                    files=files,
                    timeout=60,
                )
        else:
            # 无文件时仍用 multipart/form-data 以保持接口一致性
            resp = httpx.post(
                url,
                headers=self._auth_headers(),
                data=data,
                timeout=60,
            )

        return _parse(resp, url).get("data", {})

    def delete_skill(self, skill_id: int) -> None:
        url = f"{self._base}/v1/skills/{skill_id}"
        resp = httpx.delete(url, headers=self._auth_headers(), timeout=_TIMEOUT)
        _parse(resp, url)

    # ──────────────────────────────────────────
    # 市场同步队列 & 排除名单
    # ──────────────────────────────────────────

    def get_sync_queue(self) -> list[dict]:
        """获取待同步列表（服务端安装记录 − 排除名单）。"""
        url = f"{self._base}/v1/skills/sync/queue"
        resp = httpx.get(url, headers=self._auth_headers(), timeout=_TIMEOUT)
        return _parse(resp, url).get("data", [])

    def list_sync_excludes(self) -> list[dict]:
        """查看当前用户的不同步排除名单。"""
        url = f"{self._base}/v1/skills/sync/excludes"
        resp = httpx.get(url, headers=self._auth_headers(), timeout=_TIMEOUT)
        return _parse(resp, url).get("data", [])

    def add_sync_exclude(self, identifier: str) -> dict:
        """将指定技能加入不同步排除名单（幂等）。"""
        url = f"{self._base}/v1/skills/sync/excludes"
        resp = httpx.post(
            url,
            headers=self._auth_headers(),
            json={"identifier": identifier},
            timeout=_TIMEOUT,
        )
        return _parse(resp, url).get("data", {})

    def remove_sync_exclude(self, skill_id: int) -> None:
        """将指定技能移出排除名单。"""
        url = f"{self._base}/v1/skills/sync/excludes/{skill_id}"
        resp = httpx.delete(url, headers=self._auth_headers(), timeout=_TIMEOUT)
        _parse(resp, url)

    # ──────────────────────────────────────────
    # 统计回调
    # ──────────────────────────────────────────

    def record_install(self, skill_id: int, payload: dict) -> None:
        """安装成功后回调，失败静默忽略不影响主流程。"""
        url = f"{self._base}/v1/skills/{skill_id}/installs"
        try:
            resp = httpx.post(
                url,
                headers=self._auth_headers(),
                json=payload,
                timeout=10,
            )
            _parse(resp, url)
        except Exception as exc:
            _logger.debug("record_install 回调失败（忽略）: %s", exc)

    def batch_usage(self, records: list[dict]) -> dict:
        """批量上报使用记录。"""
        url = f"{self._base}/v1/skills/usages/batch"
        resp = httpx.post(
            url,
            headers=self._auth_headers(),
            json={"records": records},
            timeout=15,
        )
        return _parse(resp, url).get("data", {})

    # ──────────────────────────────────────────
    # 评分
    # ──────────────────────────────────────────

    def submit_rating(self, skill_id: int, score: float, comment: str | None = None) -> dict:
        """提交或更新评分（1-5 分整数；小数自动向下取整）。

        服务端验证规则：integer|min:1|max:5。
        若 score 为小数（如 4.7），先 floor 为整数（4），再做范围限制。
        """
        int_score = max(1, min(5, int(score)))  # floor + clamp [1,5]
        url = f"{self._base}/v1/skills/{skill_id}/ratings"
        payload: dict = {"score": int_score}
        if comment:
            payload["comment"] = comment
        resp = httpx.post(url, headers=self._auth_headers(), json=payload, timeout=_TIMEOUT)
        return _parse(resp, url).get("data", {})

    def get_ratings(self, skill_id: int, page: int = 1, limit: int = 20) -> dict:
        """获取指定技能的评分列表（分页）。"""
        url = f"{self._base}/v1/skills/{skill_id}/ratings"
        resp = httpx.get(
            url,
            headers=self._auth_headers(),
            params={"page": page, "limit": limit},
            timeout=_TIMEOUT,
        )
        return _parse(resp, url).get("data", {})

    # ──────────────────────────────────────────
    # 我的技能（用于 publish 时判断是否已存在）
    # ──────────────────────────────────────────

    def get_my_skill_by_name(self, skill_name: str) -> dict | None:
        """通过 skill_name 在我的技能列表中查找，返回 None 表示尚未上传过。"""
        url = f"{self._base}/v1/skills/mine"
        resp = httpx.get(url, headers=self._auth_headers(), params={"limit": 100}, timeout=_TIMEOUT)
        data = _parse(resp, url).get("data", {})
        for item in data.get("list", []):
            if item.get("skill_name") == skill_name and not item.get("deleted_at"):
                return item
        return None

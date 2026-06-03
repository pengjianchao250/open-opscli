"""公共文件上传客户端。"""

from __future__ import annotations

import json
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from opscli.auth import AuthClient, OPS_URL
from opscli.mcp.context import get_mcp_request_headers
from opscli.shared.exceptions import RemoteError
from opscli.shared.http import extract_error_message


ENV_FILE_UPLOAD_ENDPOINT = "OPSCLI_FILE_UPLOAD_ENDPOINT"
ENV_FILE_UPLOAD_FIELD = "OPSCLI_FILE_UPLOAD_FIELD"
ENV_FILE_UPLOAD_FOLDER = "OPSCLI_FILE_UPLOAD_FOLDER"
ENV_FILE_UPLOAD_PUBLIC = "OPSCLI_FILE_UPLOAD_PUBLIC"

DEFAULT_ENDPOINT = "/v1/file/upload"
DEFAULT_FILE_FIELD = "file"
DEFAULT_FOLDER = "uploads"
DEFAULT_PUBLIC = "0"
DEFAULT_TIMEOUT = 60


class FileUploadError(RemoteError):
    """文件上传错误。"""

    code = "FILE_UPLOAD_ERROR"


class FileUploadHttpError(FileUploadError):
    """文件上传 HTTP 错误。"""

    code = "FILE_UPLOAD_HTTP_ERROR"

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class FileUploadBusinessError(FileUploadError):
    """文件上传业务错误。"""

    code = "FILE_UPLOAD_BUSINESS_ERROR"

    def __init__(self, business_code: int | str, message: str):
        super().__init__(message)
        self.business_code = business_code


class FileUploadBadJsonError(FileUploadError):
    """文件上传响应结构错误。"""

    code = "FILE_UPLOAD_BAD_JSON"


@dataclass(frozen=True)
class FileUploadResult:
    """文件上传结果。"""

    url: str
    raw: dict[str, Any]


class FileUploadClient:
    """复用 OPS 鉴权的公共文件上传客户端。"""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        file_field: str | None = None,
        folder: str | None = None,
        public: str | None = None,
        auth_client: AuthClient | None = None,
    ) -> None:
        self.endpoint = endpoint or os.getenv(ENV_FILE_UPLOAD_ENDPOINT) or DEFAULT_ENDPOINT
        self.file_field = file_field or os.getenv(ENV_FILE_UPLOAD_FIELD) or DEFAULT_FILE_FIELD
        self.folder = folder or os.getenv(ENV_FILE_UPLOAD_FOLDER) or DEFAULT_FOLDER
        self.public = public or os.getenv(ENV_FILE_UPLOAD_PUBLIC) or DEFAULT_PUBLIC
        self.auth_client = auth_client or AuthClient()

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint)

    def upload(
        self,
        path: str | Path,
        *,
        purpose: str,
        folder: str | None = None,
        public: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> FileUploadResult:
        """上传文件并返回远端下载链接。"""
        if not self.endpoint:
            raise FileUploadError(f"缺少 {ENV_FILE_UPLOAD_ENDPOINT}")
        file_path = Path(path)
        if not file_path.exists():
            raise FileUploadError(f"上传文件不存在：{file_path}")

        headers, cookies = self.auth_client.build_request_auth("ops")
        headers.update(get_mcp_request_headers())
        fields: list[tuple[str, Any]] = [
            ("folder", (None, folder or self.folder)),
            ("public", (None, public or self.public)),
            ("purpose", (None, purpose)),
        ]
        if metadata:
            fields.append(("metadata", (None, json.dumps(metadata, ensure_ascii=False))))

        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        with file_path.open("rb") as file_handle:
            fields.append((self.file_field, (file_path.name, file_handle, mime_type)))
            response = httpx.post(
                _resolve_endpoint(self.endpoint),
                headers=headers,
                cookies=cookies,
                files=fields,
                timeout=DEFAULT_TIMEOUT,
            )

        payload = _parse_upload_response(response)
        url = _extract_upload_url(payload)
        if not url:
            raise FileUploadBadJsonError("文件上传响应缺少下载链接")
        return FileUploadResult(url=url, raw=payload)


def _resolve_endpoint(endpoint: str) -> str:
    text = endpoint.strip()
    if text.startswith(("http://", "https://")):
        return text
    if not text.startswith("/"):
        text = f"/{text}"
    return f"{OPS_URL.rstrip('/')}{text}"


def _parse_upload_response(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        raise FileUploadBadJsonError("远端返回了无法解析的 JSON") from exc
    if not isinstance(payload, dict):
        raise FileUploadBadJsonError("远端返回结构不是 JSON 对象")
    if response.status_code >= 400:
        raise FileUploadHttpError(response.status_code, extract_error_message(payload) or f"远端请求失败，HTTP {response.status_code}")
    code = payload.get("code")
    if code not in (None, 0, 200, 201, "0", "200", "201"):
        raise FileUploadBusinessError(code, extract_error_message(payload) or "远端业务执行失败")
    return payload


def _extract_upload_url(payload: dict[str, Any]) -> str | None:
    for source in (payload.get("data"), payload):
        if not isinstance(source, dict):
            continue
        for key in ("url", "download_url", "downloadUrl", "file_url", "fileUrl"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None

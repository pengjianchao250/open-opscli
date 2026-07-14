"""公共文件上传客户端。"""

from __future__ import annotations

import json
import mimetypes
import os
import time
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
ENV_FILE_UPLOAD_RETRIES = "OPSCLI_FILE_UPLOAD_RETRIES"

DEFAULT_ENDPOINT = "/v1/file/upload"
DEFAULT_FILE_FIELD = "file"
DEFAULT_FOLDER = "uploads"
DEFAULT_PUBLIC = "0"
DEFAULT_TIMEOUT = 60
DEFAULT_RETRIES = 2
RETRYABLE_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}


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
        jwt: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.endpoint = endpoint or os.getenv(ENV_FILE_UPLOAD_ENDPOINT) or DEFAULT_ENDPOINT
        self.file_field = file_field or os.getenv(ENV_FILE_UPLOAD_FIELD) or DEFAULT_FILE_FIELD
        self.folder = folder or os.getenv(ENV_FILE_UPLOAD_FOLDER) or DEFAULT_FOLDER
        self.public = public or os.getenv(ENV_FILE_UPLOAD_PUBLIC) or DEFAULT_PUBLIC
        self.auth_client = auth_client or AuthClient()
        self.jwt = jwt
        self.session_id = session_id

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
        filename: str | None = None,
    ) -> FileUploadResult:
        """上传文件并返回远端下载链接。"""
        if not self.endpoint:
            raise FileUploadError(f"缺少 {ENV_FILE_UPLOAD_ENDPOINT}")
        file_path = Path(path)
        if not file_path.exists():
            raise FileUploadError(f"上传文件不存在：{file_path}")

        headers, cookies = self._get_auth("ops")
        upload_folder = folder or self.folder
        upload_public = public or self.public
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        upload_filename = filename or file_path.name

        response = self._post_with_retry(
            file_path,
            headers=headers,
            cookies=cookies,
            purpose=purpose,
            folder=upload_folder,
            public=upload_public,
            metadata=metadata,
            upload_filename=upload_filename,
            mime_type=mime_type,
        )
        payload = _parse_upload_response(response)
        url = _extract_upload_url(payload)
        if not url:
            raise FileUploadBadJsonError("文件上传响应缺少下载链接")
        return FileUploadResult(url=url, raw=payload)

    def _post_with_retry(
        self,
        file_path: Path,
        *,
        headers: dict[str, str],
        cookies: dict[str, str],
        purpose: str,
        folder: str,
        public: str,
        metadata: dict[str, Any] | None,
        upload_filename: str,
        mime_type: str,
    ) -> httpx.Response:
        """执行文件上传，并对网关类瞬时错误做有限重试。"""
        endpoint = _resolve_endpoint(self.endpoint)
        max_attempts = _upload_attempt_count()
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = self._post_once(
                    file_path,
                    endpoint=endpoint,
                    headers=headers,
                    cookies=cookies,
                    purpose=purpose,
                    folder=folder,
                    public=public,
                    metadata=metadata,
                    upload_filename=upload_filename,
                    mime_type=mime_type,
                )
                if response.status_code not in RETRYABLE_HTTP_STATUS_CODES:
                    return response
                if attempt >= max_attempts:
                    raise FileUploadHttpError(
                        response.status_code,
                        _upload_context_message(
                            file_path,
                            endpoint=endpoint,
                            purpose=purpose,
                            folder=folder,
                            attempt=attempt,
                            max_attempts=max_attempts,
                            message=f"远端返回 HTTP {response.status_code}",
                        ),
                    )
                last_error = FileUploadHttpError(
                    response.status_code,
                    _upload_context_message(
                        file_path,
                        endpoint=endpoint,
                        purpose=purpose,
                        folder=folder,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        message=f"远端返回 HTTP {response.status_code}",
                    ),
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt >= max_attempts:
                    raise FileUploadError(
                        _upload_context_message(
                            file_path,
                            endpoint=endpoint,
                            purpose=purpose,
                            folder=folder,
                            attempt=attempt,
                            max_attempts=max_attempts,
                            message=str(exc),
                        )
                    ) from exc
            time.sleep(min(0.2 * attempt, 1.0))
        if last_error:
            raise last_error
        raise FileUploadError("文件上传失败：未执行上传请求")

    def _post_once(
        self,
        file_path: Path,
        *,
        endpoint: str,
        headers: dict[str, str],
        cookies: dict[str, str],
        purpose: str,
        folder: str,
        public: str,
        metadata: dict[str, Any] | None,
        upload_filename: str,
        mime_type: str,
    ) -> httpx.Response:
        """单次上传请求；每次重试都重新打开文件句柄。"""
        fields: list[tuple[str, Any]] = [
            ("folder", (None, folder)),
            ("public", (None, public)),
            ("purpose", (None, purpose)),
        ]
        if metadata:
            fields.append(("metadata", (None, json.dumps(metadata, ensure_ascii=False))))
        with file_path.open("rb") as file_handle:
            fields.append((self.file_field, (upload_filename, file_handle, mime_type)))
            return httpx.post(
                endpoint,
                headers=headers,
                cookies=cookies,
                files=fields,
                timeout=DEFAULT_TIMEOUT,
            )

    def _get_auth(self, alias: str) -> tuple[dict[str, str], dict[str, str]]:
        mcp_headers = get_mcp_request_headers()
        if self.session_id:
            jwt = self.jwt or self.auth_client.get_token_by_session(self.session_id, alias)
            headers = {"Authorization": f"Bearer {jwt}"}
            headers.update(mcp_headers)
            return headers, {"polarisUserToken": self.session_id}
        if self.jwt:
            headers = {"Authorization": f"Bearer {self.jwt}"}
            headers.update(mcp_headers)
            return headers, {}
        if _has_mcp_api_key(mcp_headers):
            return mcp_headers, {}
        headers, cookies = self.auth_client.build_request_auth(alias)
        headers.update(mcp_headers)
        return headers, cookies


def _resolve_endpoint(endpoint: str) -> str:
    text = endpoint.strip()
    if text.startswith(("http://", "https://")):
        return text
    if not text.startswith("/"):
        text = f"/{text}"
    return f"{OPS_URL.rstrip('/')}{text}"


def _has_mcp_api_key(headers: dict[str, str]) -> bool:
    return bool(headers.get("X-MCP-API-Key"))


def _upload_attempt_count() -> int:
    value = os.getenv(ENV_FILE_UPLOAD_RETRIES)
    if not value:
        return DEFAULT_RETRIES + 1
    try:
        retries = max(int(value), 0)
    except ValueError:
        retries = DEFAULT_RETRIES
    return retries + 1


def _upload_context_message(
    file_path: Path,
    *,
    endpoint: str,
    purpose: str,
    folder: str,
    attempt: int,
    max_attempts: int,
    message: str,
) -> str:
    size = file_path.stat().st_size if file_path.exists() else 0
    return (
        f"文件上传失败：{message}；"
        f"endpoint={endpoint}，folder={folder}，purpose={purpose}，"
        f"file={file_path.name}，size={size}，attempt={attempt}/{max_attempts}"
    )


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

"""Rufus Copy-as-cURL 解析服务。"""

from __future__ import annotations

import json
import re
import shlex
from typing import Any
from urllib.parse import urlsplit

from opscli.amazon_rufus.domain.exceptions import InvalidRufusCurlError
from opscli.amazon_rufus.domain.models import ParsedCurlRufusRequest


class RufusCurlParser:
    """将浏览器 Copy-as-cURL 转换为 Rufus 后端请求材料。"""

    _URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)
    _STREAMING_PATH = "/rufus/cl/streaming"
    _BLOCKED_HEADERS = {"cookie", "content-length", "authorization", "proxy-authorization"}
    _DATA_FLAGS = {
        "-d",
        "--data",
        "--data-raw",
        "--data-binary",
        "--data-urlencode",
        "--data-ascii",
    }

    def parse(self, raw_curl: str) -> ParsedCurlRufusRequest:
        """解析 cURL 文本并返回可本地保存的请求材料。"""
        text = self._normalize(raw_curl)
        if not text:
            raise InvalidRufusCurlError("curl 不能为空")

        tokens = self._split_tokens(text)
        if not tokens:
            raise InvalidRufusCurlError("curl 解析失败")

        url: str | None = None
        headers: dict[str, str] = {}
        cookies_from_flag = ""
        cookies_from_header = ""
        payload_template: dict[str, Any] | None = None

        i = 0
        while i < len(tokens):
            token = tokens[i]

            if url is None and self._URL_PATTERN.match(token):
                url = token
                i += 1
                continue

            if token == "--url":
                if i + 1 >= len(tokens):
                    raise InvalidRufusCurlError("curl 缺少 --url 参数值")
                url = tokens[i + 1]
                i += 2
                continue

            if token in ("-H", "--header"):
                if i + 1 >= len(tokens):
                    raise InvalidRufusCurlError("curl 缺少 header 参数值")
                key, value = self._parse_header(tokens[i + 1])
                if key.lower() == "cookie":
                    cookies_from_header = value
                elif key.lower() not in self._BLOCKED_HEADERS:
                    headers[key] = value
                i += 2
                continue

            if token in ("-b", "--cookie"):
                if i + 1 >= len(tokens):
                    raise InvalidRufusCurlError("curl 缺少 cookie 参数值")
                cookies_from_flag = str(tokens[i + 1]).strip()
                i += 2
                continue

            if token in self._DATA_FLAGS or token.startswith("--data"):
                data_value, i = self._consume_data_value(tokens, i)
                payload_template = self._parse_payload(data_value)
                continue

            i += 1

        parsed_url = self._validate_url(url)
        cookies = cookies_from_flag or cookies_from_header
        if not cookies.strip():
            raise InvalidRufusCurlError("curl 未解析到 Cookie")

        return ParsedCurlRufusRequest(
            url=parsed_url,
            headers=headers,
            cookies=cookies.strip(),
            payload_template=payload_template or {},
        )

    def _normalize(self, raw_curl: str) -> str:
        """兼容 Bash 与 PowerShell 的多行 cURL 文本。"""
        text = str(raw_curl or "").strip()
        if not text:
            return ""
        text = re.sub(r"\\\r?\n\s*", " ", text)
        text = re.sub(r"`\r?\n\s*", " ", text)
        text = re.sub(r"\^\r?\n\s*", " ", text)
        text = re.sub(r"\r?\n+", " ", text)
        return text.strip()

    def _split_tokens(self, text: str) -> list[str]:
        """按 shell quoting 规则拆分参数。"""
        try:
            return shlex.split(text, posix=True)
        except ValueError:
            try:
                return shlex.split(text, posix=False)
            except ValueError as exc:
                raise InvalidRufusCurlError("curl quoting 格式无效") from exc

    def _parse_header(self, raw_header: str) -> tuple[str, str]:
        """解析单个 header 行。"""
        if ":" not in raw_header:
            raise InvalidRufusCurlError("header 格式无效")
        key, value = raw_header.split(":", 1)
        normalized_key = key.strip()
        if not normalized_key:
            raise InvalidRufusCurlError("header key 不能为空")
        return normalized_key, value.lstrip()

    def _consume_data_value(self, tokens: list[str], index: int) -> tuple[str, int]:
        """读取 --data 系列参数值。"""
        token = tokens[index]
        if token.startswith("--data") and "=" in token:
            _, data_value = token.split("=", 1)
            return data_value, index + 1
        if index + 1 >= len(tokens):
            raise InvalidRufusCurlError("curl 缺少 data 参数值")
        return tokens[index + 1], index + 2

    def _parse_payload(self, raw_payload: str) -> dict[str, Any]:
        """尽力解析 JSON payload，非对象时返回空模板。"""
        text = str(raw_payload or "").strip()
        if not text:
            return {}
        if text.startswith("$'") and text.endswith("'") and len(text) >= 3:
            text = text[2:-1]
        try:
            parsed: Any = json.loads(text)
        except json.JSONDecodeError:
            try:
                parsed = json.loads(bytes(text, "utf-8").decode("unicode_escape"))
            except Exception:
                return {}
        return parsed if isinstance(parsed, dict) else {}

    def _validate_url(self, url: str | None) -> str:
        """校验 Rufus streaming URL。"""
        normalized = str(url or "").strip()
        parsed = urlsplit(normalized)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https") or not host:
            raise InvalidRufusCurlError("curl 未解析到有效 URL")
        if "amazon." not in host:
            raise InvalidRufusCurlError("curl URL 必须是 Amazon 域名")
        if self._STREAMING_PATH not in parsed.path:
            raise InvalidRufusCurlError("curl URL 必须是 Rufus streaming 请求")
        return normalized

"""内部反馈列表与批量详情查询脚本。

本脚本是 `ops-feedback-query` 的专用内部入口，只访问 feedback
open-query API，并使用 Skill 自身凭据文件中的独立 API Key。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx


# OpenAPI 声明的生产服务根地址，不包含 `/api` 路径前缀。
DEFAULT_BASE_URL = "https://ops.api.xenkee.com"
# 内部只读查询的默认超时，避免网络异常导致脚本长期阻塞。
DEFAULT_TIMEOUT = 20.0
# 凭据模板占位值；检测到该值时禁止发起真实请求。
PLACEHOLDER_API_KEY = "REPLACE_WITH_INTERNAL_FEEDBACK_API_KEY"
# Skill 自带的内部凭据位置，不读取 opscli JWT 或 session。
CREDENTIALS_PATH = Path(__file__).resolve().parent.parent / "data" / "credentials.json"
# feedback open-query 列表与批量详情固定路径。
LIST_PATH = "/api/v1/data-metrics/open/feedbacks"
BATCH_DETAIL_PATH = "/api/v1/data-metrics/open/feedbacks/batch-detail"
# OpenAPI 允许的反馈类型枚举，用于 argparse 本地校验。
FEEDBACK_TYPES = ("all", "bug", "feature", "data_issue", "ux", "docs", "other", "query_result")
# 密钥只允许发送到 OpenAPI 生产根地址或明确的本地开发域名。
TRUSTED_BASE_URLS = {
    ("https", "ops.api.xenkee.com"),
    ("http", "ops.cm"),
}


class FeedbackQueryError(Exception):
    """表示本地配置、参数或远端反馈查询失败。

    Args:
        message: 面向开发人员的错误说明。
        payload: 可安全输出的结构化错误，不得包含 API Key。
    """

    def __init__(self, message: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.payload = payload or {"code": "FEEDBACK_QUERY_ERROR", "msg": message}


def _bounded_int(value: str, *, minimum: int, maximum: int | None = None) -> int:
    """解析带上下界的整数参数。"""
    parsed = int(value)
    if parsed < minimum or (maximum is not None and parsed > maximum):
        if maximum is None:
            raise argparse.ArgumentTypeError(f"必须大于或等于 {minimum}")
        raise argparse.ArgumentTypeError(f"必须在 {minimum} 到 {maximum} 之间")
    return parsed


def _positive_int(value: str) -> int:
    """解析大于或等于 1 的整数。"""
    return _bounded_int(value, minimum=1)


def _per_page(value: str) -> int:
    """解析 1 到 100 的分页大小。"""
    return _bounded_int(value, minimum=1, maximum=100)


def _positive_float(value: str) -> float:
    """解析大于 0 的浮点数。"""
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return parsed


def _max_length(maximum: int):
    """构造文本最大长度校验器。"""
    def parse(value: str) -> str:
        if len(value) > maximum:
            raise argparse.ArgumentTypeError(f"长度不能超过 {maximum}")
        return value

    return parse


def _uuid(value: str) -> str:
    """校验并规范化 UUID 字符串。"""
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是有效 UUID") from exc


def load_credentials(credentials_path: Path = CREDENTIALS_PATH) -> dict[str, Any]:
    """读取 Skill 本地凭据 JSON 对象。

    Args:
        credentials_path: Skill 内部凭据 JSON 文件路径。

    Returns:
        凭据 JSON 对象。

    Raises:
        FeedbackQueryError: 文件缺失、格式非法或根节点不是对象。
    """
    try:
        payload = json.loads(credentials_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FeedbackQueryError(f"未找到内部反馈查询凭据文件: {credentials_path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise FeedbackQueryError(f"无法读取内部反馈查询凭据文件: {credentials_path}") from exc
    if not isinstance(payload, dict):
        raise FeedbackQueryError(f"内部反馈查询凭据必须是 JSON 对象: {credentials_path}")
    return payload


def load_api_key(credentials_path: Path = CREDENTIALS_PATH) -> str:
    """从 Skill 凭据文件读取反馈查询 API Key。

    Args:
        credentials_path: Skill 内部凭据 JSON 文件路径。

    Returns:
        已去除首尾空白的 API Key。

    Raises:
        FeedbackQueryError: 文件缺失、格式非法或仍为占位值。
    """
    payload = load_credentials(credentials_path)
    api_key = payload.get("feedback_api_key")
    if not isinstance(api_key, str) or not api_key.strip() or api_key.strip() == PLACEHOLDER_API_KEY:
        raise FeedbackQueryError(f"尚未配置内部反馈查询密钥: {credentials_path}")
    return api_key.strip()


def _redact_secrets(value: Any, secrets: tuple[str, ...]) -> Any:
    """递归替换远端响应中意外回显的请求密钥。"""
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            if secret:
                redacted = redacted.replace(secret, "[REDACTED]")
        return redacted
    if isinstance(value, list):
        return [_redact_secrets(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact_secrets(item, secrets) for key, item in value.items()}
    return value


def parse_response(response: httpx.Response, *, secrets: tuple[str, ...] = ()) -> dict[str, Any]:
    """解析 feedback open-query 的 HTTP 200 + 业务码响应。

    Args:
        response: httpx 返回的原始响应。
        secrets: 必须从返回内容中递归脱敏的请求密钥。

    Returns:
        业务码为 200 的完整 JSON 信封。

    Raises:
        FeedbackQueryError: HTTP、JSON 结构或业务码异常。
    """
    try:
        payload = _redact_secrets(response.json(), secrets)
    except Exception as exc:
        raise FeedbackQueryError("反馈查询接口返回了无法解析的 JSON") from exc

    if response.status_code >= 400:
        message = payload.get("msg") if isinstance(payload, dict) else None
        safe_payload = {
            "code": "REMOTE_HTTP_ERROR",
            "msg": message or f"反馈查询接口 HTTP {response.status_code}",
            "http_status": response.status_code,
        }
        raise FeedbackQueryError(safe_payload["msg"], safe_payload)

    if not isinstance(payload, dict):
        raise FeedbackQueryError("反馈查询接口返回结构不是 JSON 对象")

    if payload.get("code") != 200:
        safe_payload = {
            "code": payload.get("code", "REMOTE_BUSINESS_ERROR"),
            "msg": payload.get("msg") or "反馈查询接口业务执行失败",
        }
        if "error_details" in payload:
            safe_payload["error_details"] = payload["error_details"]
        raise FeedbackQueryError(str(safe_payload["msg"]), safe_payload)
    return payload


class FeedbackQueryClient:
    """使用独立 API Key 调用内部 feedback open-query API。"""

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, timeout: float = DEFAULT_TIMEOUT) -> None:
        """初始化反馈查询客户端。

        Args:
            api_key: 独立反馈查询密钥。
            base_url: ops 服务根地址，不含 `/api`。
            timeout: 单次 HTTP 请求超时秒数。
        """
        parsed_url = urlparse(base_url)
        if (parsed_url.scheme, parsed_url.hostname) not in TRUSTED_BASE_URLS:
            raise FeedbackQueryError("反馈查询基础地址不受信任")
        if (
            parsed_url.port is not None
            or parsed_url.path not in ("", "/")
            or parsed_url.username
            or parsed_url.password
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise FeedbackQueryError("反馈查询基础地址格式无效")

        self._api_key = api_key
        self._headers = {"X-Feedback-Api-Key": api_key}
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def list_feedbacks(self, params: dict[str, Any]) -> dict[str, Any]:
        """按过滤条件分页查询反馈列表。"""
        # 未传参数交给服务端使用默认值，避免客户端复制业务默认逻辑。
        clean_params = {key: value for key, value in params.items() if value is not None}
        response = httpx.get(
            f"{self._base_url}{LIST_PATH}",
            params=clean_params,
            headers=self._headers,
            timeout=self._timeout,
        )
        return parse_response(response, secrets=(self._api_key,))

    def batch_detail(self, feedback_uuids: list[str], feedback_type: str | None = None) -> dict[str, Any]:
        """按 1 到 100 个反馈 UUID 批量查询完整详情。"""
        body: dict[str, Any] = {"feedback_uuids": feedback_uuids}
        if feedback_type is not None:
            body["feedback_type"] = feedback_type
        response = httpx.post(
            f"{self._base_url}{BATCH_DETAIL_PATH}",
            json=body,
            headers=self._headers,
            timeout=self._timeout,
        )
        return parse_response(response, secrets=(self._api_key,))


def _add_runtime_options(parser: argparse.ArgumentParser) -> None:
    """为子命令增加非敏感运行参数。"""
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="ops 服务根地址，不含 /api")
    parser.add_argument("--timeout", type=_positive_float, default=DEFAULT_TIMEOUT, help="HTTP 请求超时秒数")
    parser.add_argument("--output", type=Path, help="JSON 输出文件路径；自动创建父目录")
    parser.add_argument("--pretty", action="store_true", help="格式化输出 JSON")


def build_parser() -> argparse.ArgumentParser:
    """构造列表和批量详情命令行解析器。"""
    parser = argparse.ArgumentParser(description="内部反馈列表与批量详情查询")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="分页查询反馈列表")
    _add_runtime_options(list_parser)
    list_parser.add_argument("--feedback-type", choices=FEEDBACK_TYPES)
    list_parser.add_argument("--severity", choices=("low", "medium", "high", "critical"))
    list_parser.add_argument("--status", choices=("new", "triaged", "processing", "resolved", "rejected"))
    list_parser.add_argument("--source", choices=("cli", "mcp", "skill", "api"))
    list_parser.add_argument("--user-id", type=_positive_int)
    list_parser.add_argument("--user-email", type=_max_length(191))
    list_parser.add_argument("--system-alias", type=_max_length(64))
    list_parser.add_argument("--search", type=_max_length(200))
    list_parser.add_argument("--date-from")
    list_parser.add_argument("--date-to")
    list_parser.add_argument(
        "--sort-by",
        choices=("created_at", "updated_at", "severity", "failed_call_count", "id"),
    )
    list_parser.add_argument("--sort-direction", choices=("asc", "desc"))
    list_parser.add_argument("--page", type=_positive_int)
    list_parser.add_argument("--per-page", type=_per_page)

    batch_parser = subparsers.add_parser("batch-detail", help="按 UUID 批量查询完整详情")
    _add_runtime_options(batch_parser)
    batch_parser.add_argument("--feedback-uuids", nargs="+", required=True, type=_uuid)
    batch_parser.add_argument("--feedback-type", choices=FEEDBACK_TYPES)
    return parser


def build_list_params(args: argparse.Namespace) -> dict[str, Any]:
    """把列表命令参数映射为 OpenAPI query 参数。"""
    return {
        "feedback_type": args.feedback_type,
        "severity": args.severity,
        "status": args.status,
        "source": args.source,
        "user_id": args.user_id,
        "user_email": args.user_email,
        "system_alias": args.system_alias,
        "search": args.search,
        "date_from": args.date_from,
        "date_to": args.date_to,
        "sort_by": args.sort_by,
        "sort_direction": args.sort_direction,
        "page": args.page,
        "per_page": args.per_page,
    }


def build_batch_payload(args: argparse.Namespace) -> tuple[list[str], str | None]:
    """校验并构造批量详情业务参数。"""
    if len(args.feedback_uuids) > 100:
        raise FeedbackQueryError("批量详情一次不能超过 100 个反馈 UUID")
    return args.feedback_uuids, args.feedback_type


def _serialize_json(payload: dict[str, Any], *, pretty: bool, ascii_only: bool = False) -> str:
    """将结构化结果序列化为 JSON 文本。

    Args:
        payload: 待序列化的 JSON 对象。
        pretty: 是否使用两空格缩进。
        ascii_only: 是否转义非 ASCII 字符，供 Windows 终端安全输出。

    Returns:
        序列化后的 JSON 文本。
    """
    indent = 2 if pretty else None
    return json.dumps(payload, ensure_ascii=ascii_only, indent=indent)


def _print_json(payload: dict[str, Any], *, pretty: bool, stream: Any = sys.stdout) -> None:
    """以 GBK 安全的 ASCII JSON 格式输出终端结果。"""
    print(_serialize_json(payload, pretty=pretty, ascii_only=True), file=stream)


def resolve_output_path(output_path: Path, *, start_dir: Path | None = None) -> Path:
    """把输出路径限制在项目根 `output/feedback-query/` 目录内。

    Args:
        output_path: 文件名、专用目录相对路径或专用目录内的绝对路径。
        start_dir: 查找项目根的起始目录，默认使用当前工作目录。

    Returns:
        位于专用反馈导出目录内的绝对路径。

    Raises:
        FeedbackQueryError: 无法定位项目根或输出路径越过专用目录。
    """
    current = (start_dir or Path.cwd()).resolve()
    project_root = next(
        (directory for directory in (current, *current.parents) if (directory / ".git").exists()),
        None,
    )
    if project_root is None:
        raise FeedbackQueryError("无法定位 Git 项目根目录，不能导出反馈查询结果")

    export_root = (project_root / "output" / "feedback-query").resolve()
    expanded = output_path.expanduser()
    if expanded.is_absolute():
        resolved = expanded.resolve()
    else:
        parts = expanded.parts
        if len(parts) >= 2 and parts[:2] == ("output", "feedback-query"):
            expanded = Path(*parts[2:])
        resolved = (export_root / expanded).resolve()

    if not resolved.is_relative_to(export_root) or resolved == export_root:
        raise FeedbackQueryError("反馈查询结果只能写入项目根 output/feedback-query/ 目录")
    return resolved


def write_json_file(payload: dict[str, Any], output_path: Path, *, pretty: bool) -> Path:
    """创建父目录并把完整 JSON 信封写入指定文件。

    Args:
        payload: 接口返回的完整 JSON 信封。
        output_path: 用户显式指定的输出文件路径。
        pretty: 是否使用缩进格式化 JSON。

    Returns:
        已解析为绝对路径的输出文件位置。

    Raises:
        FeedbackQueryError: 目录创建或文件写入失败。
    """
    resolved_path = resolve_output_path(output_path)
    try:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        text = _serialize_json(payload, pretty=pretty)
        resolved_path.write_text(f"{text}\n", encoding="utf-8")
    except OSError as exc:
        raise FeedbackQueryError(f"无法写入反馈查询结果文件: {resolved_path}") from exc
    return resolved_path


def main(argv: list[str] | None = None) -> int:
    """解析命令、执行查询并返回进程退出码。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        # 在创建客户端和发起请求前校验凭据，避免占位配置误触远端接口。
        api_key = load_api_key()
        client = FeedbackQueryClient(api_key, args.base_url, args.timeout)
        if args.command == "list":
            result = client.list_feedbacks(build_list_params(args))
        else:
            feedback_uuids, feedback_type = build_batch_payload(args)
            result = client.batch_detail(feedback_uuids, feedback_type)

        output_path = write_json_file(result, args.output, pretty=args.pretty) if args.output else None
    except FeedbackQueryError as exc:
        _print_json(exc.payload, pretty=args.pretty, stream=sys.stderr)
        return 1
    except httpx.HTTPError:
        # 不拼接原始请求信息，避免某些异常上下文意外带出敏感 Header。
        _print_json(
            {"code": "NETWORK_ERROR", "msg": "反馈查询接口网络请求失败"},
            pretty=args.pretty,
            stream=sys.stderr,
        )
        return 1

    if output_path is not None:
        # 文件导出时终端只返回路径，避免把完整敏感详情重复打印到控制台。
        _print_json(
            {"success": True, "output": str(output_path)},
            pretty=args.pretty,
        )
    else:
        _print_json(result, pretty=args.pretty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

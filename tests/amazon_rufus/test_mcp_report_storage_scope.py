"""Bug 12138 回归：Rufus MCP 报告按运行模式区分存储位置与读取方式。

远端 HTTP/SSE MCP 是多客户端共享部署，报告写在 MCP 服务器磁盘上，调用方（AI 助手沙箱、
远程 Agent）读不到；旧响应却固定要求「读取 report_path」，导致 Agent 在本地 cat/find 扑空。
本文件用真实 RufusMcpManager + AnswerReportPublisher/Writer，只给 Amazon 抓取与 OSS 上传打桩，
分别验证远端模式、可信上游（无 API Key）模式、本地 stdio 模式以及 CLI 输出不受影响。
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opscli.amazon_rufus.cli import app
from opscli.amazon_rufus.domain.exceptions import RufusReportUploadError
from opscli.amazon_rufus.domain.mcp_models import RufusGetRequest
from opscli.amazon_rufus.services.answer_report_publisher import AnswerReportPublisher
from opscli.amazon_rufus.services.mcp_manager import RufusMcpManager
from opscli.mcp.context import mcp_request_ctx
from opscli.mcp.tools import amazon_rufus as amazon_rufus_tools
from opscli.shared.file_uploads import FileUploadResult

# 与线上 seq 4966 同形态的 OSS 直链前缀，测试不发真实网络请求。
_OSS_PREFIX = "https://p-amazon-task-test.oss-cn-hongkong.aliyuncs.com/amazon-rufus/reports/2026/09/"


class _StubRufusManager:
    """替代真实 RufusManager：返回单题、单回答的获取结果。"""

    def get_backend(self, **kwargs):
        """模拟 headless 获取成功。"""
        return {
            "asin": kwargs["asin"],
            "country": kwargs["country"],
            "question_count": 1,
            "questions": [kwargs.get("question") or "这是什么商品？"],
            "answers": [{"text": "这是一张厨房岛台餐桌。", "isSuccess": True, "summaryText": ""}],
        }


class _StubUploadClient:
    """替代真实 FileUploadClient：返回 OSS 直链，不访问网络。"""

    def upload(self, path, *, purpose, folder, filename, metadata, public=None):
        """模拟 OPS 文件上传成功。"""
        return FileUploadResult(url=f"{_OSS_PREFIX}{filename}", raw={})


class _FixedUrlUploadClient:
    """返回指定 URL 的上传桩，用于构造含 shell 特殊字符的地址。"""

    def __init__(self, url: str) -> None:
        self.url = url

    def upload(self, path, **kwargs):
        """模拟上传成功并返回固定 URL。"""
        return FileUploadResult(url=self.url, raw={})


class _FailingUploadClient:
    """模拟 OPS 文件上传失败。"""

    def upload(self, path, **kwargs):
        """抛出上传异常，由发布服务包装成 RufusReportUploadError。"""
        raise RuntimeError("upload failed")


def _real_manager(upload_client=None) -> RufusMcpManager:
    """构造只打桩外部依赖的真实 RufusMcpManager。"""
    return RufusMcpManager(
        rufus_manager=_StubRufusManager(),
        remote_consent_store=None,  # get() 不使用远程授权偏好
        report_publisher=AnswerReportPublisher(file_upload_client=upload_client or _StubUploadClient()),
    )


@pytest.fixture
def mcp_ctx():
    """按需设置 MCP 请求上下文，并在测试结束后恢复，避免污染其他用例。"""
    tokens = []

    def _set(value):
        tokens.append(mcp_request_ctx.set(value))

    yield _set
    for token in reversed(tokens):
        mcp_request_ctx.reset(token)


def _get(manager: RufusMcpManager) -> dict:
    """以固定参数调用 get()。"""
    return manager.get(RufusGetRequest(asin="B0FL2B5HZS", country="US", question="这是什么商品？"))


def test_remote_http_mode_returns_download_url_instead_of_server_path(
    monkeypatch, tmp_path: Path, mcp_ctx, caplog,
):
    """远端 API Key 模式：不给调用方不可读的 report_path，改给 download_url 与 curl 下载指引。"""
    server_cwd = tmp_path / "mcp_server_pod"
    server_cwd.mkdir()
    monkeypatch.chdir(server_cwd)  # 模拟远端 MCP 服务进程的工作目录
    mcp_ctx({"api_key": "mcp_key_demo", "auth_mode": "remote"})

    with caplog.at_level(logging.INFO, logger="opscli.amazon_rufus.services.mcp_manager"):
        result = _get(_real_manager())

    report_url = result["report_url"]
    assert report_url.startswith(_OSS_PREFIX)
    assert result["storage_scope"] == "remote"
    assert result["local_readable"] is False
    assert result["report_path"] is None
    assert result["download_url"] == report_url
    # 服务端路径不下发（避免再诱导本地读取），只写服务端日志供审计。
    assert "remote_report_path" not in result
    server_files = list((server_cwd / "output" / "amazon-rufus").glob("B0FL2B5HZS-*.md"))
    assert len(server_files) == 1
    assert any(server_files[0].name in record.getMessage() for record in caplog.records)
    next_action = result["next_action"]
    assert "不要在本地文件系统查找" in next_action
    # -f 必须存在：链接失效时 curl 以非 0 退出，避免把 OSS 错误页当成报告；输出文件名由 Agent 决定。
    assert f"curl -fsSL {shlex.quote(report_url)} -o <本地文件>" in next_action
    assert "最终向用户返回 report_url" in next_action
    assert "请读取 report_path" not in next_action


def test_remote_next_action_quotes_url_with_shell_metacharacters(monkeypatch, tmp_path: Path, mcp_ctx):
    """URL 含 $、反引号时，curl 命令中的 URL 必须被安全引用，不能在调用方 shell 中被展开执行。"""
    monkeypatch.chdir(tmp_path)
    mcp_ctx({"api_key": "mcp_key_demo", "auth_mode": "remote"})
    hostile_url = f"{_OSS_PREFIX}report-$(touch pwned)-`id`-$HOME.md"

    result = _get(_real_manager(_FixedUrlUploadClient(hostile_url)))

    next_action = result["next_action"]
    start = next_action.index("curl ")
    command = next_action[start:next_action.index("<本地文件>", start) + len("<本地文件>")]
    # shlex 解析后 URL 是一个完整参数，且整体处于单引号内，$(...)、反引号和 $HOME 都不会展开。
    assert shlex.split(command) == ["curl", "-fsSL", hostile_url, "-o", "<本地文件>"]
    assert f"'{hostile_url}'" in command


def test_remote_upload_failure_hides_server_report_path(monkeypatch, tmp_path: Path, mcp_ctx, caplog):
    """远端上传失败：错误结构不带服务端路径，文案不再写「已保留本地文件」，路径只进服务端日志。"""
    monkeypatch.chdir(tmp_path)
    mcp_ctx({"api_key": "mcp_key_demo", "auth_mode": "remote"})

    with caplog.at_level(logging.WARNING, logger="opscli.amazon_rufus.services.mcp_manager"):
        with pytest.raises(RufusReportUploadError) as exc_info:
            _get(_real_manager(_FailingUploadClient()))

    error = exc_info.value.to_dict()
    assert "report_path" not in error
    assert error["code"] == "RUFUS_REPORT_UPLOAD_ERROR"
    assert "远端 MCP 服务器" in error["message"]
    assert "已保留本地文件" not in error["message"]
    assert error["upload_error"]["type"] == "RuntimeError"
    assert any("output/amazon-rufus/B0FL2B5HZS-" in record.getMessage() for record in caplog.records)


def test_stdio_upload_failure_returns_absolute_report_path(monkeypatch, tmp_path: Path):
    """本地 stdio 上传失败：错误结构给本机绝对路径，文案保持「已保留本地文件」。"""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RufusReportUploadError) as exc_info:
        _get(_real_manager(_FailingUploadClient()))

    error = exc_info.value.to_dict()
    report_path = Path(error["report_path"])
    assert error["message"] == "Rufus 报告上传失败，已保留本地文件"
    assert report_path.is_absolute()
    assert report_path.exists()


def test_trusted_upstream_mode_without_api_key_is_treated_as_remote(monkeypatch, tmp_path: Path, mcp_ctx):
    """可信上游（internal）不携带 API Key 但同样经 HTTP 调用，不能误判成本地 stdio。"""
    monkeypatch.chdir(tmp_path)
    mcp_ctx({"api_key": None, "auth_mode": "internal", "email": "user@example.com"})

    result = _get(_real_manager())

    assert result["storage_scope"] == "remote"
    assert result["local_readable"] is False
    assert result["report_path"] is None
    assert result["download_url"] == result["report_url"]


def test_stdio_mode_returns_absolute_readable_report_path(monkeypatch, tmp_path: Path):
    """本地 stdio 模式：返回本机绝对路径，调用方 CWD 与 MCP 子进程不同也能读到。"""
    monkeypatch.chdir(tmp_path)
    assert mcp_request_ctx.get() is None  # 无 HTTP 请求上下文即 stdio

    result = _get(_real_manager())

    report_path = Path(result["report_path"])
    assert result["storage_scope"] == "local"
    assert result["local_readable"] is True
    assert report_path.is_absolute()
    assert report_path.exists()
    assert "厨房岛台餐桌" in report_path.read_text(encoding="utf-8-sig")
    assert result["report_url"].startswith(_OSS_PREFIX)
    assert "download_url" not in result
    assert "remote_report_path" not in result
    assert "report_path" in result["next_action"]
    assert "curl" not in result["next_action"]


def test_mcp_tool_propagates_remote_context_into_worker_thread(monkeypatch, tmp_path: Path, mcp_ctx):
    """工具层在线程中执行 manager，远端上下文必须随线程传递，否则会退化为本地文案。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        amazon_rufus_tools,
        "_rufus_mcp_manager_for_current_request",
        lambda **kwargs: _real_manager(),
    )
    mcp_ctx({"api_key": "mcp_key_demo", "auth_mode": "remote"})

    result = asyncio.run(amazon_rufus_tools.amazon_rufus_get("B0FL2B5HZS", "US", question="这是什么商品？"))

    assert result["success"] is True
    assert result["data"]["storage_scope"] == "remote"
    assert result["data"]["report_path"] is None
    assert result["data"]["download_url"] == result["data"]["report_url"]


def test_cli_get_backend_output_is_unchanged(monkeypatch, tmp_path: Path):
    """CLI 在调用方本机运行，仍输出相对报告路径与地址，不引入 MCP 存储字段。"""
    monkeypatch.setattr("opscli.amazon_rufus.commands.cli.RufusManager", lambda: _StubRufusManager())
    monkeypatch.setattr(
        "opscli.amazon_rufus.services.answer_report_publisher.FileUploadClient",
        _StubUploadClient,
    )
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        app,
        ["get-backend", "B0FL2B5HZS", "US", "-q", "这是什么商品？", "--no-upload-payload"],
    )

    report_files = list((tmp_path / "output" / "amazon-rufus").glob("B0FL2B5HZS-*.md"))
    assert result.exit_code == 0
    assert len(report_files) == 1
    relative_path = report_files[0].relative_to(tmp_path).as_posix()
    assert f"Rufus 答案报告已保存：{relative_path}" in result.stdout
    assert f"Rufus 答案报告地址：{_OSS_PREFIX}{report_files[0].name}" in result.stdout
    for key in ("storage_scope", "local_readable", "download_url", "next_action"):
        assert key not in result.stdout

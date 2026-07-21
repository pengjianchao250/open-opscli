"""内部反馈查询 Skill 及脚本契约测试。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import httpx
import pytest


SKILL_DIR = Path("opscli/skills/templates/ops-feedback-query")
SCRIPT_PATH = SKILL_DIR / "scripts" / "query_feedbacks.py"


def _load_script() -> ModuleType:
    """从 Skill 模板加载查询脚本，避免要求脚本成为 Python 包。"""
    spec = importlib.util.spec_from_file_location("ops_feedback_query_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _response(payload: object, status_code: int = 200) -> httpx.Response:
    """构造带请求上下文的 HTTP 响应。"""
    request = httpx.Request("GET", "https://ops.api.xenkee.com/test")
    return httpx.Response(status_code, json=payload, request=request)


def test_internal_feedback_query_skill_structure_and_manifest():
    """Skill 必须包含文档、版本、凭据和脚本，并保持内部发行策略。"""
    skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    version = json.loads((SKILL_DIR / "data" / "VERSION.json").read_text(encoding="utf-8"))
    credentials = json.loads((SKILL_DIR / "data" / "credentials.json").read_text(encoding="utf-8"))
    manifest = json.loads(Path("opscli/skills/templates/manifest.json").read_text(encoding="utf-8"))
    row = manifest["skills"]["ops-feedback-query"]

    frontmatter = skill_text.split("---", 2)[1]
    assert "name: ops-feedback-query" in frontmatter
    assert "description: Use when" in frontmatter
    assert "version:" not in frontmatter
    assert version["name"] == "ops-feedback-query"
    assert version["version"] == "v1.1.0"
    assert isinstance(credentials["feedback_api_key"], str)
    assert credentials["feedback_api_key"].strip()
    assert isinstance(credentials["wecom_webhook_url"], str)
    assert credentials["wecom_webhook_url"].strip()
    assert row["tier"] == "internal"
    assert all(row[key] is False for key in ("source", "wheel", "binary", "binary_full"))
    assert SCRIPT_PATH.is_file()


def test_load_api_key_rejects_placeholder_before_request(tmp_path: Path):
    """占位密钥必须在创建网络请求前被拒绝。"""
    module = _load_script()
    credentials_path = tmp_path / "credentials.json"
    credentials_path.write_text(
        json.dumps({"feedback_api_key": "REPLACE_WITH_INTERNAL_FEEDBACK_API_KEY"}),
        encoding="utf-8",
    )

    with pytest.raises(module.FeedbackQueryError, match="尚未配置内部反馈查询密钥"):
        module.load_api_key(credentials_path)


def test_list_request_uses_only_feedback_api_key(monkeypatch: pytest.MonkeyPatch):
    """列表请求只能使用独立 Header，不能夹带 opscli 登录凭据。"""
    module = _load_script()
    captured: dict = {}

    def fake_get(url: str, **kwargs):
        captured.update(url=url, **kwargs)
        return _response({"code": 200, "msg": "成功", "data": {"list": [], "total": 0}})

    monkeypatch.setattr(module.httpx, "get", fake_get)
    client = module.FeedbackQueryClient("test-secret", "https://ops.api.xenkee.com", timeout=9)

    payload = client.list_feedbacks(
        {
            "feedback_type": "bug",
            "status": "new",
            "page": 2,
            "per_page": 50,
            "search": None,
        }
    )

    assert payload["code"] == 200
    assert captured["url"] == "https://ops.api.xenkee.com/api/v1/data-metrics/open/feedbacks"
    assert captured["headers"] == {"X-Feedback-Api-Key": "test-secret"}
    assert captured["params"] == {
        "feedback_type": "bug",
        "status": "new",
        "page": 2,
        "per_page": 50,
    }
    assert captured["timeout"] == 9
    assert "cookies" not in captured
    assert "api_key" not in captured["params"]


def test_batch_detail_request_uses_expected_body(monkeypatch: pytest.MonkeyPatch):
    """批量详情请求必须只发送 OpenAPI 声明的业务字段。"""
    module = _load_script()
    captured: dict = {}
    feedback_uuid = "f782fbb3-c51d-4d3e-ab58-216e6882446c"

    def fake_post(url: str, **kwargs):
        captured.update(url=url, **kwargs)
        return _response({"code": 200, "msg": "成功", "data": {"list": [], "total": 0}})

    monkeypatch.setattr(module.httpx, "post", fake_post)
    client = module.FeedbackQueryClient("test-secret", "https://ops.api.xenkee.com/")

    client.batch_detail([feedback_uuid], "all")

    assert captured["url"].endswith("/api/v1/data-metrics/open/feedbacks/batch-detail")
    assert captured["headers"] == {"X-Feedback-Api-Key": "test-secret"}
    assert captured["json"] == {
        "feedback_uuids": [feedback_uuid],
        "feedback_type": "all",
    }
    assert "api_key" not in captured["json"]
    assert "cookies" not in captured


@pytest.mark.parametrize("business_code", [401, 422, 500])
def test_business_error_preserves_details_without_leaking_key(business_code: int):
    """业务错误需要保留详情，同时不得把客户端密钥写入异常。"""
    module = _load_script()
    response = _response(
        {
            "code": business_code,
            "msg": "请求失败",
            "data": [],
            "error_details": {"status": ["invalid"]},
        }
    )

    with pytest.raises(module.FeedbackQueryError) as exc_info:
        module.parse_response(response)

    assert exc_info.value.payload["code"] == business_code
    assert exc_info.value.payload["error_details"] == {"status": ["invalid"]}
    assert "test-secret" not in str(exc_info.value)


def test_invalid_json_and_http_error_are_rejected():
    """非法 JSON 与异常 HTTP 状态都应返回结构化错误。"""
    module = _load_script()
    request = httpx.Request("GET", "https://ops.api.xenkee.com/test")
    invalid_json = httpx.Response(200, text="not-json", request=request)

    with pytest.raises(module.FeedbackQueryError, match="无法解析的 JSON"):
        module.parse_response(invalid_json)

    with pytest.raises(module.FeedbackQueryError) as exc_info:
        module.parse_response(_response({"code": 500, "msg": "网关失败"}, status_code=502))

    assert exc_info.value.payload["http_status"] == 502


def test_remote_error_cannot_echo_api_key(monkeypatch: pytest.MonkeyPatch):
    """即使远端错误正文意外回显密钥，客户端也必须脱敏后再抛出。"""
    module = _load_script()
    api_key = "secret-that-must-not-leak"

    def fake_get(_url: str, **_kwargs):
        return _response({"code": 401, "msg": f"无效密钥: {api_key}", "data": []})

    monkeypatch.setattr(module.httpx, "get", fake_get)
    client = module.FeedbackQueryClient(api_key)

    with pytest.raises(module.FeedbackQueryError) as exc_info:
        client.list_feedbacks({})

    assert api_key not in str(exc_info.value)
    assert api_key not in json.dumps(exc_info.value.payload, ensure_ascii=False)
    assert "[REDACTED]" in exc_info.value.payload["msg"]


def test_parser_validates_batch_uuid_count_and_format():
    """批量详情参数必须限制 UUID 格式及 1 到 100 条边界。"""
    module = _load_script()
    parser = module.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["batch-detail", "--feedback-uuids", "not-a-uuid"])

    uuids = [f"00000000-0000-0000-0000-{index:012d}" for index in range(101)]
    args = parser.parse_args(["batch-detail", "--feedback-uuids", *uuids])
    with pytest.raises(module.FeedbackQueryError, match="不能超过 100 个"):
        module.build_batch_payload(args)


def test_parser_rejects_invalid_list_boundaries():
    """分页、文本长度及超时参数必须遵循本地和 OpenAPI 边界。"""
    module = _load_script()
    parser = module.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["list", "--page", "0"])
    with pytest.raises(SystemExit):
        parser.parse_args(["list", "--per-page", "101"])
    with pytest.raises(SystemExit):
        parser.parse_args(["list", "--user-id", "0"])
    with pytest.raises(SystemExit):
        parser.parse_args(["list", "--user-email", "a" * 192])
    with pytest.raises(SystemExit):
        parser.parse_args(["list", "--system-alias", "a" * 65])
    with pytest.raises(SystemExit):
        parser.parse_args(["list", "--search", "a" * 201])
    with pytest.raises(SystemExit):
        parser.parse_args(["list", "--timeout", "0"])


def test_client_rejects_untrusted_base_url_before_request():
    """基础地址必须限制在 OpenAPI 声明的精确根地址，防止密钥外发。"""
    module = _load_script()

    for base_url in (
        "https://attacker.example",
        "https://ops.api.xenkee.com:8443",
        "https://ops.api.xenkee.com/other",
    ):
        with pytest.raises(module.FeedbackQueryError, match="不受信任|格式无效"):
            module.FeedbackQueryClient("test-secret", base_url)

    assert module.FeedbackQueryClient("test-secret", "https://ops.api.xenkee.com")
    assert module.FeedbackQueryClient("test-secret", "http://ops.cm")


def test_output_option_writes_json_and_creates_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """显式输出路径应自动创建父目录并写入完整 JSON 信封。"""
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    output_path = project_root / "output" / "feedback-query" / "feedback-list.json"
    payload = {"code": 200, "msg": "成功", "data": {"list": [], "total": 0}}

    written_path = module.write_json_file(payload, output_path, pretty=True)

    assert written_path == output_path.resolve()
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload
    assert "\n  \"code\"" in output_path.read_text(encoding="utf-8")


def test_output_option_is_available_for_both_commands(tmp_path: Path):
    """列表与批量详情命令都应接受显式 --output 参数。"""
    module = _load_script()
    parser = module.build_parser()
    output_path = tmp_path / "result.json"
    feedback_uuid = "f782fbb3-c51d-4d3e-ab58-216e6882446c"

    list_args = parser.parse_args(["list", "--output", str(output_path)])
    detail_args = parser.parse_args(
        [
            "batch-detail",
            "--feedback-uuids",
            feedback_uuid,
            "--output",
            str(output_path),
        ]
    )

    assert list_args.output == output_path
    assert detail_args.output == output_path


def test_relative_output_path_is_anchored_to_feedback_export_directory(tmp_path: Path):
    """相对路径必须统一落在项目根 output/feedback-query 下。"""
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    skill_dir = project_root / "opscli" / "skills" / "templates" / "ops-feedback-query"
    skill_dir.mkdir(parents=True)
    expected = (project_root / "output" / "feedback-query" / "result.json").resolve()

    assert module.resolve_output_path(Path("result.json"), start_dir=skill_dir) == expected
    assert module.resolve_output_path(
        Path("output/feedback-query/result.json"),
        start_dir=skill_dir,
    ) == expected


def test_output_path_cannot_escape_feedback_export_directory(tmp_path: Path):
    """绝对路径和父目录跳转都不能把敏感反馈写到专用目录之外。"""
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    skill_dir = project_root / "opscli" / "skills" / "templates" / "ops-feedback-query"
    skill_dir.mkdir(parents=True)

    for output_path in (Path("../outside.json"), project_root / "outside.json"):
        with pytest.raises(module.FeedbackQueryError, match="output/feedback-query"):
            module.resolve_output_path(output_path, start_dir=skill_dir)


def test_output_path_requires_project_root(tmp_path: Path):
    """无法定位 Git 项目根时必须拒绝导出，不能写到任意工作目录。"""
    module = _load_script()

    with pytest.raises(module.FeedbackQueryError, match="无法定位 Git 项目根目录"):
        module.resolve_output_path(Path("result.json"), start_dir=tmp_path)


def test_main_output_file_suppresses_sensitive_terminal_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """导出文件时终端只能显示文件路径，不能重复输出完整反馈数据。"""
    module = _load_script()
    project_root = tmp_path / "repo"
    (project_root / ".git").mkdir(parents=True)
    monkeypatch.chdir(project_root)
    output_path = project_root / "output" / "feedback-query" / "feedback.json"
    payload = {"code": 200, "msg": "成功", "data": {"secret_content": "敏感正文"}}

    monkeypatch.setattr(module, "load_api_key", lambda: "test-secret")
    monkeypatch.setattr(module.FeedbackQueryClient, "list_feedbacks", lambda self, params: payload)

    exit_code = module.main(["list", "--output", str(output_path), "--pretty"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "敏感正文" not in captured.out
    assert json.loads(captured.out) == {
        "success": True,
        "output": str(output_path.resolve()),
    }
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload


def test_main_without_output_keeps_terminal_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """未传输出路径时必须保持原有完整 JSON 终端输出。"""
    module = _load_script()
    payload = {"code": 200, "msg": "成功", "data": {"total": 0}}

    monkeypatch.setattr(module, "load_api_key", lambda: "test-secret")
    monkeypatch.setattr(module.FeedbackQueryClient, "list_feedbacks", lambda self, params: payload)

    exit_code = module.main(["list"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out) == payload

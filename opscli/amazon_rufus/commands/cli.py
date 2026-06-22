"""amazon-rufus CLI 子命令。"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from opscli.amazon_rufus.constants import DEFAULT_RUFUS_TIMEOUT_SECONDS
from opscli.amazon_rufus.domain.exceptions import InvalidRufusCookieError, InvalidRufusCurlError, RufusError
from opscli.amazon_rufus.services.answer_report_formatter import AnswerReportFormatter
from opscli.amazon_rufus.services.answer_report_writer import AnswerReportWriter
from opscli.amazon_rufus.services.batch_backend import BatchGetBackendOptions, RufusBatchBackendRunner
from opscli.amazon_rufus.services.manager import RufusManager
from opscli.amazon_rufus.services.remote_consent import RemoteConsentStore

app = typer.Typer(help="Amazon Rufus 自动问答采集")
cookie_app = typer.Typer(help="管理 Rufus 本地 Cookie 状态")
curl_app = typer.Typer(help="管理 Rufus 本地 cURL 请求状态")
remote_consent_app = typer.Typer(help="管理 Rufus 远程授权偏好")
app.add_typer(cookie_app, name="cookie")
app.add_typer(curl_app, name="curl")
app.add_typer(remote_consent_app, name="remote-consent")


@app.callback()
def main():
    """Amazon Rufus 命令组入口。"""


def _emit(payload: dict, pretty: bool) -> None:
    """统一输出 JSON。"""
    if pretty:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(json.dumps(payload, ensure_ascii=False))


def _emit_answer_report(data: dict) -> None:
    """将前端风格的 Rufus 答案报告写入运行目录。"""
    report_path = AnswerReportWriter().write(data)
    typer.echo(f"Rufus 答案报告已保存：{report_path.as_posix()}")


def _load_json_file(path: Path) -> dict:
    """读取本地 Rufus JSON 文件。"""
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Rufus JSON root must be an object")
    return payload


def _error_payload(command: str, exc: Exception) -> dict:
    """统一错误结构。"""
    if isinstance(exc, RufusError):
        error = exc.to_dict()
    else:
        error = {"code": "RUFUS_ERROR", "message": str(exc)}
    return {"success": False, "command": command, "data": None, "error": error}


def _split_question_options(question: list[str] | None) -> tuple[str | None, list[str] | None]:
    """将 CLI 可重复问题参数拆成旧单题参数或新多题参数。"""
    if not question:
        return None, None
    if len(question) == 1:
        return question[0], None
    return None, question


def _load_batch_asins(asin: list[str] | None, asin_file: Path | None) -> list[str]:
    """Read batch ASIN values from repeated options and an optional text file."""
    values: list[str] = []
    values.extend(asin or [])
    if asin_file is not None:
        for line in asin_file.read_text(encoding="utf-8-sig").splitlines():
            cleaned = line.split("#", 1)[0].strip()
            if cleaned:
                values.append(cleaned)
    return values


@app.command("render-report")
def render_report(
    input_path: Path = typer.Argument(..., help="本地 Rufus JSON 文件路径"),
    output_path: Path | None = typer.Option(None, "--output", "-o", help="指定输出 Markdown 文件路径"),
    output_dir: Path | None = typer.Option(None, "--output-dir", help="指定输出目录，未传 --output 时生效"),
    pretty: bool = typer.Option(False, "--pretty", help="错误时格式化输出"),
):
    """将 Rufus JSON 渲染为 Listing 优化诊断 Markdown。"""
    try:
        data = _load_json_file(input_path)
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            render_data = dict(data)
            render_data.setdefault("report_path", output_path.as_posix())
            output_path.write_text(AnswerReportFormatter().format_data(render_data), encoding="utf-8")
            report_path = output_path
        else:
            report_path = AnswerReportWriter().write(data, output_dir=output_dir)
    except Exception as exc:
        _emit(_error_payload("amazon-rufus render-report", exc), pretty)
        raise typer.Exit(1)
    typer.echo(f"Rufus 答案报告已保存：{report_path.as_posix()}")


@app.command("get")
def get(
    asin: str = typer.Argument(..., help="目标 ASIN"),
    country: str = typer.Argument(..., help="国家名，如 US、UK、DE、JP"),
    question: list[str] | None = typer.Option(None, "--question", "-q", help="指定 Rufus 问题，可多次传入；传入后跳过默认题库"),
    skills_dir: str | None = typer.Option(None, "--skills-dir", help="指定 Skill 根目录"),
    cdp_url: str = typer.Option("http://127.0.0.1:9222", "--cdp-url", help="Chrome DevTools 地址"),
    new_chrome: bool = typer.Option(False, "--new-chrome", help="先新开 Chrome 调试窗口再连接"),
    keep_chrome_open: bool = typer.Option(False, "--keep-chrome-open", help="保留本次新开的 Chrome 调试窗口"),
    chrome_path: str | None = typer.Option(None, "--chrome-path", help="指定 Chrome 可执行文件路径"),
    launch_if_needed: bool = typer.Option(False, "--launch-if-needed", help="当 CDP 不可用时自动启动 Chrome"),
    timeout_seconds: int = typer.Option(DEFAULT_RUFUS_TIMEOUT_SECONDS, "--timeout", min=1, help="Rufus 获取超时秒数（每题）"),
    include_upload_payload: bool = typer.Option(True, "--upload-payload/--no-upload-payload", help="是否输出上传 payload"),
    submit_upload: bool = typer.Option(False, "--submit-upload", help="显式提交 Rufus upload_payload 到配置的后端接口"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """获取指定 ASIN 在 Rufus 中的题库回答。"""
    manager = RufusManager()
    single_question, multiple_questions = _split_question_options(question)
    try:
        data = manager.get(
            asin=asin,
            country=country,
            question=single_question,
            questions=multiple_questions,
            skills_dir=skills_dir,
            cdp_url=cdp_url,
            new_chrome=new_chrome,
            keep_chrome_open=keep_chrome_open,
            chrome_path=chrome_path,
            launch_if_needed=launch_if_needed,
            timeout_seconds=timeout_seconds,
            include_upload_payload=include_upload_payload or submit_upload,
            submit_upload=submit_upload,
        )
    except Exception as exc:
        _emit(_error_payload("amazon-rufus get", exc), pretty)
        raise typer.Exit(1)
    _emit_answer_report(data)


@app.command("get-backend")
def get_backend(
    asin: str = typer.Argument(..., help="目标 ASIN"),
    country: str = typer.Argument(..., help="国家名，如 US、UK、DE、JP"),
    question: list[str] | None = typer.Option(None, "--question", "-q", help="指定 Rufus 问题，可多次传入；传入后跳过默认题库"),
    skills_dir: str | None = typer.Option(None, "--skills-dir", help="指定 Skill 根目录"),
    timeout_seconds: int = typer.Option(DEFAULT_RUFUS_TIMEOUT_SECONDS, "--timeout", min=1, help="Rufus 获取超时秒数（每题）"),
    parallel: bool = typer.Option(False, "--parallel", help="多问题并发请求；每题独立 Rufus 会话"),
    concurrency: int = typer.Option(3, "--concurrency", min=1, help="并发请求数，仅 --parallel 生效"),
    retry: int = typer.Option(0, "--retry", min=0, help="单题无效回答重试次数"),
    strict_answer: bool = typer.Option(False, "--strict-answer", help="无效回答重试后仍失败时直接报错"),
    include_upload_payload: bool = typer.Option(True, "--upload-payload/--no-upload-payload", help="是否输出上传 payload"),
    submit_upload: bool = typer.Option(False, "--submit-upload", help="显式提交 Rufus upload_payload 到配置的后端接口"),
    pretty: bool = typer.Option(False, "--pretty", help="错误时格式化输出"),
):
    """通过后端/headless 链路获取指定 ASIN 的 Rufus 回答。"""
    manager = RufusManager()
    single_question, multiple_questions = _split_question_options(question)
    try:
        data = manager.get_backend(
            asin=asin,
            country=country,
            question=single_question,
            questions=multiple_questions,
            skills_dir=skills_dir,
            timeout_seconds=timeout_seconds,
            parallel=parallel,
            concurrency=concurrency,
            retry=retry,
            strict_answer=strict_answer,
            include_upload_payload=include_upload_payload or submit_upload,
            submit_upload=submit_upload,
        )
    except Exception as exc:
        _emit(_error_payload("amazon-rufus get-backend", exc), pretty)
        raise typer.Exit(1)
    _emit_answer_report(data)


@app.command("batch-get-backend")
def batch_get_backend(
    country: str = typer.Argument(..., help="国家名，如 US、UK、DE、JP"),
    asin: list[str] | None = typer.Option(None, "--asin", "-a", help="目标 ASIN，可重复传入，也可用逗号或空格分隔"),
    asin_file: Path | None = typer.Option(None, "--asin-file", help="包含 ASIN 的文本文件，支持空格/逗号分隔和 # 注释"),
    question: list[str] | None = typer.Option(None, "--question", "-q", help="指定 Rufus 问题，可多次传入；传入后跳过默认题库"),
    skills_dir: str | None = typer.Option(None, "--skills-dir", help="指定 Skill 根目录"),
    mode: str = typer.Option("balanced", "--mode", help="运行模式：fast、balanced、safe"),
    asin_concurrency: int | None = typer.Option(None, "--asin-concurrency", min=1, help="ASIN 并发数；未传时由 mode 决定"),
    parallel_questions: bool = typer.Option(False, "--parallel-questions", help="强制每个 ASIN 内多问题并发"),
    serial_questions: bool = typer.Option(False, "--serial-questions", help="强制每个 ASIN 内多问题串行"),
    question_concurrency: int | None = typer.Option(None, "--question-concurrency", min=1, help="问题并发数，仅并发问题时生效"),
    timeout_seconds: int | None = typer.Option(None, "--timeout", min=1, help="Rufus 获取超时秒数（每题）；未传时由 mode 决定"),
    retry: int | None = typer.Option(None, "--retry", min=0, help="单题无效回答重试次数；未传时由 mode 决定"),
    strict_answer: bool = typer.Option(True, "--strict-answer/--no-strict-answer", help="启用回答完整性校验"),
    resume: bool = typer.Option(True, "--resume/--no-resume", help="已有合格报告时跳过该 ASIN"),
    fallback_serial: bool = typer.Option(True, "--fallback-serial/--no-fallback-serial", help="快跑失败后自动用 safe 串行兜底"),
    validate_report: bool = typer.Option(True, "--validate-report/--no-validate-report", help="写入后校验报告结构和空小节"),
    output_dir: Path = typer.Option(Path("output") / "amazon-rufus", "--output-dir", help="报告输出目录"),
    summary_output: Path | None = typer.Option(None, "--summary-output", help="将批量汇总 JSON 写入指定文件"),
    allow_partial: bool = typer.Option(False, "--allow-partial", help="部分 ASIN 失败时仍返回 0"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出 JSON"),
):
    """批量通过后端/headless 链路获取 Rufus 回答，支持快跑、resume 与 safe 兜底。"""
    try:
        if parallel_questions and serial_questions:
            raise ValueError("--parallel-questions 和 --serial-questions 不能同时使用")
        question_parallel = True if parallel_questions else False if serial_questions else None
        data = RufusBatchBackendRunner().run(
            BatchGetBackendOptions(
                asins=_load_batch_asins(asin, asin_file),
                country=country,
                questions=question,
                skills_dir=skills_dir,
                mode=mode,
                asin_concurrency=asin_concurrency,
                question_parallel=question_parallel,
                question_concurrency=question_concurrency,
                timeout_seconds=timeout_seconds,
                retry=retry,
                strict_answer=strict_answer,
                resume=resume,
                fallback_serial=fallback_serial,
                validate_report=validate_report,
                output_dir=output_dir,
            )
        )
        if summary_output is not None:
            summary_output.parent.mkdir(parents=True, exist_ok=True)
            summary_output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        _emit(_error_payload("amazon-rufus batch-get-backend", exc), pretty)
        raise typer.Exit(1)
    _emit(data, pretty)
    if not data.get("success") and not allow_partial:
        raise typer.Exit(1)


@app.command("init")
def init(
    country: str = typer.Argument(..., help="国家名，如 US、UK、DE、JP"),
    cdp_url: str = typer.Option("http://127.0.0.1:9222", "--cdp-url", help="Chrome DevTools 地址"),
    timeout_seconds: int = typer.Option(30, "--timeout", min=1, help="等待超时秒数"),
    chrome_path: str | None = typer.Option(None, "--chrome-path", help="指定 Chrome 可执行文件路径"),
    launch_if_needed: bool = typer.Option(True, "--launch-if-needed/--no-launch-if-needed", help="当 CDP 不可用时自动启动 Chrome"),
    pretty: bool = typer.Option(False, "--pretty", help="错误时格式化输出"),
):
    """打开对应国家站点，供用户登录 Amazon。"""
    manager = RufusManager()
    try:
        manager.init(
            country=country,
            cdp_url=cdp_url,
            timeout_seconds=timeout_seconds,
            chrome_path=chrome_path,
            launch_if_needed=launch_if_needed,
        )
    except Exception as exc:
        _emit(_error_payload("amazon-rufus init", exc), pretty)
        raise typer.Exit(1)
    typer.echo("请在新窗口中登录亚马逊")


@app.command("save-state")
def save_state(
    country: str = typer.Argument(..., help="国家名，如 US、UK、DE、JP"),
    cdp_url: str = typer.Option("http://127.0.0.1:9222", "--cdp-url", help="Chrome DevTools 地址"),
    timeout_seconds: int = typer.Option(30, "--timeout", min=1, help="等待超时秒数"),
    chrome_path: str | None = typer.Option(None, "--chrome-path", help="指定 Chrome 可执行文件路径"),
    launch_if_needed: bool = typer.Option(False, "--launch-if-needed/--no-launch-if-needed", help="当 CDP 不可用时自动启动 Chrome"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """捕获并保存当前国家站点的 Amazon 浏览器状态。"""
    manager = RufusManager()
    try:
        data = manager.save_state(
            country=country,
            cdp_url=cdp_url,
            timeout_seconds=timeout_seconds,
            chrome_path=chrome_path,
            launch_if_needed=launch_if_needed,
        )
    except Exception as exc:
        _emit(_error_payload("amazon-rufus save-state", exc), pretty)
        raise typer.Exit(1)
    _emit(
        {
            "success": True,
            "command": "amazon-rufus save-state",
            "data": data,
            "error": None,
        },
        pretty,
    )


@app.command("watch-login")
def watch_login(
    asin: str = typer.Argument(..., help="目标 ASIN"),
    country: str = typer.Argument(..., help="国家名，如 US、UK、DE、JP"),
    cdp_url: str = typer.Option("http://127.0.0.1:9222", "--cdp-url", help="Chrome DevTools 地址"),
    timeout_seconds: int = typer.Option(DEFAULT_RUFUS_TIMEOUT_SECONDS, "--timeout", min=1, help="监听登录与 Rufus 请求的总超时秒数"),
    chrome_path: str | None = typer.Option(None, "--chrome-path", help="指定 Chrome 可执行文件路径"),
    launch_if_needed: bool = typer.Option(True, "--launch-if-needed/--no-launch-if-needed", help="当 CDP 不可用时自动启动 Chrome"),
    close_browser: bool = typer.Option(False, "--close-browser/--keep-browser-open", help="采集完成后关闭本次由 opscli 启动的调试浏览器"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """监听登录页，自动捕获并保存 Rufus streaming 请求种子。"""
    manager = RufusManager()
    try:
        data = manager.watch_login(
            asin=asin,
            country=country,
            cdp_url=cdp_url,
            timeout_seconds=timeout_seconds,
            chrome_path=chrome_path,
            launch_if_needed=launch_if_needed,
            close_browser=close_browser,
        )
    except Exception as exc:
        _emit(_error_payload("amazon-rufus watch-login", exc), pretty)
        raise typer.Exit(1)
    _emit(
        {
            "success": True,
            "command": "amazon-rufus watch-login",
            "data": data,
            "error": None,
        },
        pretty,
    )


@app.command("logout")
def logout(
    country: str = typer.Argument(..., help="国家名，如 US、UK、DE、JP"),
    cdp_url: str = typer.Option("http://127.0.0.1:9222", "--cdp-url", help="Chrome DevTools 地址，用于定位 opscli 调试 profile"),
    include_browser_profile: bool = typer.Option(True, "--browser-profile/--no-browser-profile", help="是否清除 opscli Rufus 调试 Chrome profile"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """清除指定国家站点的 Amazon/Rufus 本地登录态。"""
    manager = RufusManager()
    try:
        data = manager.logout(
            country=country,
            cdp_url=cdp_url,
            include_browser_profile=include_browser_profile,
        )
    except Exception as exc:
        _emit(_error_payload("amazon-rufus logout", exc), pretty)
        raise typer.Exit(1)
    _emit(
        {
            "success": True,
            "command": "amazon-rufus logout",
            "data": data,
            "error": None,
        },
        pretty,
    )


@app.command("login-status")
def login_status(
    country: str = typer.Argument(..., help="国家名，如 US、UK、DE、JP"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """读取 Rufus 获取前可用的 Amazon 登录态脱敏摘要。"""
    manager = RufusManager()
    try:
        data = manager.login_status(country=country)
    except Exception as exc:
        _emit(_error_payload("amazon-rufus login-status", exc), pretty)
        raise typer.Exit(1)
    _emit(
        {
            "success": True,
            "command": "amazon-rufus login-status",
            "data": data,
            "error": None,
        },
        pretty,
    )


@remote_consent_app.command("status")
def remote_consent_status(
    country: str = typer.Argument(..., help="国家名，如 US、UK、DE、JP"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """读取指定国家站点的远程授权偏好。"""
    try:
        data = RemoteConsentStore().status(country)
    except Exception as exc:
        _emit(_error_payload("amazon-rufus remote-consent status", exc), pretty)
        raise typer.Exit(1)
    _emit(
        {
            "success": True,
            "command": "amazon-rufus remote-consent status",
            "data": data,
            "error": None,
        },
        pretty,
    )


@remote_consent_app.command("set")
def remote_consent_set(
    country: str = typer.Argument(..., help="国家名，如 US、UK、DE、JP"),
    allow: bool = typer.Option(False, "--allow", help="允许 MCP/headless 链路复用 Amazon 登录态"),
    deny: bool = typer.Option(False, "--deny", help="拒绝 MCP/headless 链路复用 Amazon 登录态"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """保存指定国家站点的远程授权偏好。"""
    try:
        if allow == deny:
            raise ValueError("必须且只能指定 --allow 或 --deny")
        data = RemoteConsentStore().save(country=country, allowed=allow, source="opscli")
    except Exception as exc:
        _emit(_error_payload("amazon-rufus remote-consent set", exc), pretty)
        raise typer.Exit(1)
    _emit(
        {
            "success": True,
            "command": "amazon-rufus remote-consent set",
            "data": data,
            "error": None,
        },
        pretty,
    )


@cookie_app.command("save")
def cookie_save(
    country: str = typer.Argument(..., help="国家名，如 US、UK、DE、JP"),
    from_stdin: bool = typer.Option(False, "--from-stdin", help="从标准输入读取 Cookie header"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """从安全输入通道保存 Rufus Cookie 本地状态。"""
    manager = RufusManager()
    try:
        if not from_stdin:
            raise InvalidRufusCookieError("请使用 --from-stdin 从标准输入读取 Cookie header")
        # Cookie 不允许通过命令行参数传入，避免进入 shell history 或进程列表。
        cookie_header = typer.get_text_stream("stdin").read()
        data = manager.save_cookie(country=country, cookie_header=cookie_header)
    except Exception as exc:
        _emit(_error_payload("amazon-rufus cookie save", exc), pretty)
        raise typer.Exit(1)
    _emit(
        {
            "success": True,
            "command": "amazon-rufus cookie save",
            "data": data,
            "error": None,
        },
        pretty,
    )


@cookie_app.command("status")
def cookie_status(
    country: str = typer.Argument(..., help="国家名，如 US、UK、DE、JP"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """读取 Rufus 本地 Cookie 状态的脱敏摘要。"""
    manager = RufusManager()
    try:
        data = manager.cookie_status(country=country)
    except Exception as exc:
        _emit(_error_payload("amazon-rufus cookie status", exc), pretty)
        raise typer.Exit(1)
    _emit(
        {
            "success": True,
            "command": "amazon-rufus cookie status",
            "data": data,
            "error": None,
        },
        pretty,
    )


@curl_app.command("save")
def curl_save(
    asin: str = typer.Argument(..., help="目标 ASIN"),
    country: str = typer.Argument(..., help="国家名，如 US、UK、DE、JP"),
    from_stdin: bool = typer.Option(False, "--from-stdin", help="从标准输入读取浏览器 Copy-as-cURL"),
    pretty: bool = typer.Option(False, "--pretty", help="格式化输出"),
):
    """从安全输入通道保存 Rufus Copy-as-cURL 本地状态。"""
    manager = RufusManager()
    try:
        if not from_stdin:
            raise InvalidRufusCurlError("请使用 --from-stdin 从标准输入读取 Copy-as-cURL")
        # cURL 可能包含 Cookie、csrf 和 payload，只允许从 stdin 读取并保存到本地状态。
        raw_curl = typer.get_text_stream("stdin").read()
        data = manager.save_curl(asin=asin, country=country, raw_curl=raw_curl)
    except Exception as exc:
        _emit(_error_payload("amazon-rufus curl save", exc), pretty)
        raise typer.Exit(1)
    _emit(
        {
            "success": True,
            "command": "amazon-rufus curl save",
            "data": data,
            "error": None,
        },
        pretty,
    )


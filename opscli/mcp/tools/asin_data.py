"""ASIN 数据 MCP 工具模块。

将 `opscli asin-data` 的巡检取数能力暴露为 MCP 工具：
- asin_data_live_data   — 实时获取基础数据 / BI 数据，并可上传 xlsx 到 OSS
- asin_data_fetch_file  — 读取历史拆包文件（卖家精灵 / Rufus / 历史 basic/bi）
- asin_data_report_url  — 查询历史报告文件 URL
"""

from __future__ import annotations

from .helpers import _err, _get_auth_pair, _get_credential_dir, _ok, _parse_json_arg


def _build_auth_client(session_id: str | None = None, jwt: str | None = None):
    """创建 MCP 隔离凭证感知的 AuthClient。"""
    from opscli.auth import AuthClient

    cred_dir = _get_credential_dir()
    base = AuthClient(base_dir=cred_dir) if cred_dir else AuthClient()
    if not session_id and not jwt:
        return base

    class _ProvidedAuthClient:
        """让仅传 session_id/jwt 的 MCP 调用也能复用现有 HTTP 客户端。"""

        def build_request_auth(self, alias: str) -> tuple[dict[str, str], dict[str, str]]:
            token = jwt
            if not token and session_id:
                token = base.get_token_by_session(session_id, alias)
            if token:
                headers = {"Authorization": f"Bearer {token}"}
                cookies = {"polarisUserToken": session_id} if session_id else {}
                return headers, cookies
            return base.build_request_auth(alias)

        def get_session(self, alias: str | None = None) -> str:
            if session_id:
                return session_id
            return base.get_session(alias)

        def get_device_code(self) -> str | None:
            return base.get_device_code()

        def get_token_by_session(self, sid: str, alias: str) -> str:
            return base.get_token_by_session(sid, alias)

    return _ProvidedAuthClient()


def _normalize_keywords(keywords: list[str] | str | None) -> list[str] | None:
    """兼容 MCP 客户端把 list 参数传成 JSON 字符串的情况。"""
    if keywords is None:
        return None
    if isinstance(keywords, list):
        return [str(item) for item in keywords]
    text = str(keywords).strip()
    if not text:
        return None
    if text.startswith("["):
        return [str(item) for item in _parse_json_arg(text, list)]
    return [text]


async def asin_data_live_data(
    asin: str | None = None,
    site: str = "US",
    data_scope: str = "all",
    sales_start: str | None = None,
    sales_end: str | None = None,
    upload_xlsx: bool = True,
    return_mode: str = "ai_ready",
    run_id: str | None = None,
    input_path: str | None = None,
    keywords: list[str] | str | None = None,
    asin_column: str = "asin",
    keyword_column: str = "keyword",
    site_column: str = "site",
    output_dir: str = "output/asin-data",
    query_chunk_size: int = 100,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """实时获取 ASIN 基础数据和/或 BI 数据。

    Args:
        asin: 单个 ASIN；与 input_path 二选一。
        site: 站点，默认 US。
        data_scope: 数据范围，支持 all/basic/bi/listing/listing_basic。
        sales_start: BI 销售开始日期，格式 YYYY-MM-DD。
        sales_end: BI 销售结束日期，格式 YYYY-MM-DD。
        upload_xlsx: 是否上传实时生成的 basic/bi xlsx 到 OSS，默认 true。
        return_mode: 返回模式，支持 content/url_only/both/ai_ready；MCP 默认 ai_ready，返回文件索引、数据集预览和诊断。
        run_id: 可选运行 ID。
        input_path: CSV/XLSX/JSON/JSONL 输入文件；与 asin 二选一。
        keywords: 单 ASIN 关键词列表，实时基础/BI 通常不需要。
        asin_column: 文件模式 ASIN 列名。
        keyword_column: 文件模式关键词列名。
        site_column: 文件模式站点列名。
        output_dir: 输出根目录。
        query_chunk_size: 每批 ASIN 数。
        session_id: 可选 OAuth session_id；为空则读取 MCP 隔离凭证。
        jwt: 可选 OPS JWT；为空则读取 MCP 隔离凭证。
    """
    call_params = {
        "asin": asin,
        "site": site,
        "data_scope": data_scope,
        "sales_start": sales_start,
        "sales_end": sales_end,
        "upload_xlsx": upload_xlsx,
        "return_mode": return_mode,
        "run_id": run_id,
        "input_path": input_path,
        "asin_column": asin_column,
        "keyword_column": keyword_column,
        "site_column": site_column,
        "output_dir": output_dir,
        "query_chunk_size": query_chunk_size,
    }
    try:
        sid, jw = _get_auth_pair("ops", session_id, jwt)
        auth_client = _build_auth_client(sid, jw)

        from opscli.asin_data.services.bi_report_data import AsinBiReportDataClient
        from opscli.asin_data.services.collector import AsinDataCollector
        from opscli.asin_data.services.live_data import AsinLiveDataService
        from opscli.shared.file_uploads import FileUploadClient

        collector = AsinDataCollector(
            bi_report_data_client=AsinBiReportDataClient(auth_client=auth_client),
            file_upload_client=FileUploadClient(auth_client=auth_client, jwt=jw, session_id=sid),
        )
        service = AsinLiveDataService(
            collector=collector,
            file_upload_client_factory=lambda: FileUploadClient(
                auth_client=auth_client,
                jwt=jw,
                session_id=sid,
            ),
        )
        data = service.run(
            input_path=input_path,
            asin=asin,
            keywords=_normalize_keywords(keywords),
            asin_column=asin_column,
            keyword_column=keyword_column,
            site_column=site_column,
            site=site,
            output_dir=output_dir,
            run_id=run_id,
            sales_start=sales_start,
            sales_end=sales_end,
            query_chunk_size=query_chunk_size,
            data_scope=data_scope,
            upload_xlsx=upload_xlsx,
            return_mode=return_mode,
        )
        return _ok(data)
    except Exception as exc:
        return _err(
            exc,
            tool="MCP → asin_data_live_data(...)",
            call_params=call_params,
        )


async def asin_data_fetch_file(
    asin: str,
    file_key: str,
    site: str = "US",
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """读取历史 ASIN 拆包文件并返回内容。

    Args:
        asin: ASIN。
        file_key: 文件类型，支持 basic/bi/keyword_reverse/keyword_miner/competitor/rufus。
        site: 站点，默认 US。
        session_id: 可选 OAuth session_id；为空则读取 MCP 隔离凭证。
        jwt: 可选 OPS JWT；为空则读取 MCP 隔离凭证。
    """
    call_params = {"asin": asin, "site": site, "file_key": file_key}
    try:
        sid, jw = _get_auth_pair("ops", session_id, jwt)
        auth_client = _build_auth_client(sid, jw)

        from opscli.asin_data.services.live_data import fetch_split_file
        from opscli.asin_data.services.report_files import AsinReportFileClient

        data = fetch_split_file(
            asin=asin,
            site=site,
            file_key=file_key,
            report_file_client=AsinReportFileClient(auth_client=auth_client),
        )
        return _ok(data)
    except Exception as exc:
        return _err(
            exc,
            tool="MCP → asin_data_fetch_file(...)",
            call_params=call_params,
        )


async def asin_data_report_url(
    asin: str,
    site: str = "US",
    report_type: str | None = None,
    session_id: str | None = None,
    jwt: str | None = None,
) -> dict:
    """查询历史 ASIN 报告文件 URL。"""
    call_params = {"asin": asin, "site": site, "report_type": report_type}
    try:
        sid, jw = _get_auth_pair("ops", session_id, jwt)
        auth_client = _build_auth_client(sid, jw)

        from opscli.asin_data.services.report_files import AsinReportFileClient, AsinReportFileNotFoundError

        report_file = AsinReportFileClient(auth_client=auth_client).fetch(
            asin=asin,
            site=site,
            report_type=report_type,
        )
        if not report_file.url:
            raise AsinReportFileNotFoundError(
                asin=asin.strip().upper(),
                site=site.strip().upper(),
            )
        return _ok(
            {
                "asin": report_file.asin,
                "site": report_file.site,
                "report_file_url": report_file.url,
                "record": report_file.record,
                "raw": report_file.raw,
            }
        )
    except Exception as exc:
        return _err(
            exc,
            tool="MCP → asin_data_report_url(...)",
            call_params=call_params,
        )


_ALL_TOOLS = [
    asin_data_live_data,
    asin_data_fetch_file,
    asin_data_report_url,
]


def register(mcp) -> None:
    """向指定 MCP 实例批量注册所有 asin_data_* 工具。"""
    for fn in _ALL_TOOLS:
        mcp.tool()(fn)

"""西柚 REST 入口，复用 MCP 查询、日限额和 Provider 审计日志。"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from opscli.api.deps import require_authenticated_user
from opscli.api.errors import error_response, xydc_result_response
from opscli.api.schemas.xydc import XydcRunRequest


router = APIRouter(prefix="/api/v1/xydc", tags=["xydc"])


async def _run_xydc_scenario(payload: XydcRunRequest) -> dict:
    """使用同名 MCP 入口计费，防止切换协议绕过同一用户的日限额。"""
    from opscli.mcp.instrumentation import quota_wrap, telemetry_wrap
    from opscli.mcp.tools.xydc import ext_xydc_openapi_call

    governed_run = telemetry_wrap(
        quota_wrap(ext_xydc_openapi_call),
        module="external_xydc",
        dimension_resolver=lambda arguments: {
            "scenario": arguments["operation"],
            "transport": "rest",
        },
    )
    # AppHub 依赖设置的请求上下文贯穿 Provider，日志仍记录真实调用用户。
    return await governed_run(**payload.model_dump())


@router.get("/scenarios")
async def xydc_scenarios() -> JSONResponse:
    """公开读取西柚操作目录；无需 MySQL 凭据，不请求供应商或消耗 Credit。"""
    from opscli.xiyou.providers.xydc_openapi import list_operations

    return JSONResponse({
        "success": True,
        "data": list_operations(),
        "error": None,
        "source": "xydc_openapi",
    })


@router.post("/run")
async def xydc_run(
    payload: XydcRunRequest,
    _user_email: str = Depends(require_authenticated_user),
) -> JSONResponse:
    """验证 AppHub 身份后执行查询，返回数据、供应商用量和共享日额度。"""
    try:
        result = await _run_xydc_scenario(payload)
    except Exception:
        # 未知内部异常不能包含数据库地址、认证头等部署细节。
        return error_response(
            code="XYDC_OPENAPI_REQUEST_FAILED",
            message="西柚查询服务执行失败，请稍后重试",
            status_code=502,
        )
    return xydc_result_response(result)

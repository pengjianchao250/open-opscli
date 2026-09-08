"""REST 认证预热路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from opscli.api.deps import require_authenticated_user
from opscli.api.errors import error_response, success_response

router = APIRouter(prefix="/api/v1", tags=["auth"])


@router.post("/auth/ensure")
async def auth_ensure(
    _user_email: str = Depends(require_authenticated_user),
) -> JSONResponse:
    """校验并预热当前 API Key 隔离的 OPS 凭据，不返回敏感凭证。"""
    from opscli.mcp.ops_credentials import (
        OpsCredentialBindingError,
        ensure_ops_credentials,
    )

    try:
        binding = await ensure_ops_credentials(require_jwt=True)
    except OpsCredentialBindingError as exc:
        return error_response(
            code=exc.code,
            message=str(exc) or "OPS 凭据建立失败，请稍后重试",
            status_code=502,
        )
    return success_response(
        {
            "authenticated": True,
            "refreshed": binding.refreshed,
        }
    )

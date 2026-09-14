"""健康检查路由。"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    """返回进程存活状态。"""
    return {"status": "live"}

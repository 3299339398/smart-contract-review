"""安全 API 路由 —— 审批管理和审计日志查询。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.common import ApiResponse
from app.middleware.auth_middleware import get_current_user_id
from app.security.human_gate import (
    list_pending_approvals, approve_approval, reject_approval, get_approval,
)
from app.models import SecurityAuditLog
from sqlalchemy import select

router = APIRouter(tags=["security"])


@router.get("/approvals", response_model=ApiResponse)
async def list_approvals(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        items = await list_pending_approvals(db, user_id)
        return ApiResponse(code=200, data={"content": items, "totalElements": len(items)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approvals/{approval_id}", response_model=ApiResponse)
async def get_single_approval(
    approval_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await get_approval(db, approval_id, user_id)
        if not data:
            raise HTTPException(status_code=404, detail="Approval not found")
        return ApiResponse(code=200, data=data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approvals/{approval_id}/approve", response_model=ApiResponse)
async def approve(
    approval_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    notes: str = Query("", alias="notes"),
):
    try:
        data = await approve_approval(db, approval_id, user_id, notes)
        return ApiResponse(code=200, message="审批已通过", data=data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/approvals/{approval_id}/reject", response_model=ApiResponse)
async def reject(
    approval_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    notes: str = Query("", alias="notes"),
):
    try:
        data = await reject_approval(db, approval_id, user_id, notes)
        return ApiResponse(code=200, message="审批已拒绝", data=data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/audit-logs", response_model=ApiResponse)
async def list_audit_logs(
    page: int = 1,
    size: int = 20,
    severity: str = None,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        query = select(SecurityAuditLog).where(
            SecurityAuditLog.user_id == user_id
        )
        if severity:
            query = query.where(SecurityAuditLog.severity == severity.upper())
        query = query.order_by(SecurityAuditLog.created_at.desc())

        offset = (page - 1) * size
        query = query.offset(offset).limit(size)
        result = await db.execute(query)
        logs = result.scalars().all()

        items = [
            {
                "id": log.id,
                "eventType": log.event_type,
                "severity": log.severity,
                "source": log.source,
                "summary": log.summary,
                "detail": log.detail,
                "createdAt": log.created_at.isoformat() if log.created_at else "",
            }
            for log in logs
        ]
        return ApiResponse(code=200, data={"content": items, "totalElements": len(items)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

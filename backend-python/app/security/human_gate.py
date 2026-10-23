"""第 4 层：高风险操作的人工确认关卡。

当安全管线标记内容为 SUSPICIOUS/MALICIOUS，
或审查产出 HIGH 等级风险时，创建待审批记录，
必须由用户人工确认后才能继续。

工作流：
  1. create_approval() → 写入 PendingApproval 到 DB，发送 SSE 告警
  2. 用户调用 approve/reject API
  3. approve_approval() → 标记 APPROVED，调用方恢复 agent 执行
  4. reject_approval() → 标记 REJECTED，调用方丢弃结果
  5. 超时审批（24h）在下一次检查时自动过期
"""

import datetime
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models import PendingApproval, ReviewTask
from app.security.schemas import ApprovalType, ApprovalStatus

logger = logging.getLogger(__name__)

APPROVAL_TIMEOUT_HOURS = 24


async def create_approval(
    db: AsyncSession,
    user_id: int,
    task_id: Optional[int],
    approval_type: str,
    risk_level: str,
    risk_reasoning: str,
    source_text: str,
    sse_task_id: str = "",
) -> dict:
    """创建待审批记录并发送 SSE 告警。返回审批信息字典。"""
    approval = PendingApproval(
        user_id=user_id,
        task_id=task_id,
        approval_type=approval_type,
        risk_level=risk_level,
        risk_reasoning=risk_reasoning,
        source_text=source_text[:5000],
        status=ApprovalStatus.PENDING.value,
    )
    db.add(approval)
    await db.commit()
    await db.refresh(approval)

    if sse_task_id:
        try:
            from app.services.sse_service import send_event
            send_event(
                int(sse_task_id),
                "SECURITY_ALERT",
                alertType=(
                    "PROMPT_INJECTION" if approval_type == "SECURITY_REVIEW"
                    else "HIGH_RISK_PAUSED"
                ),
                severity="WARNING" if risk_level == "SUSPICIOUS" else "CRITICAL",
                message=risk_reasoning[:200],
                approvalId=approval.id,
            )
        except Exception as e:
            logger.warning(f"SSE 安全告警发送失败: {e}")

    logger.info(f"创建审批 {approval.id}，用户 {user_id}，类型={approval_type}")
    return {
        "approvalId": approval.id,
        "userId": user_id,
        "taskId": task_id,
        "approvalType": approval_type,
        "riskLevel": risk_level,
        "riskReasoning": risk_reasoning,
        "sourceText": source_text[:500],
        "status": approval.status,
        "createdAt": approval.created_at.isoformat() if approval.created_at else "",
    }


async def approve_approval(db: AsyncSession, approval_id: int, user_id: int,
                           reviewer_notes: str = "") -> dict:
    """批准待审批记录。调用方应恢复 agent 管线执行。"""
    result = await db.execute(
        select(PendingApproval).where(
            PendingApproval.id == approval_id,
            PendingApproval.user_id == user_id,
        )
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise ValueError("审批记录不存在")
    if approval.status != ApprovalStatus.PENDING.value:
        raise ValueError(f"审批状态已为 {approval.status}")

    approval.status = ApprovalStatus.APPROVED.value
    approval.resolved_at = datetime.datetime.utcnow()
    await db.commit()
    await db.refresh(approval)

    await _write_human_audit_log(db, user_id, "HUMAN_APPROVE", approval, reviewer_notes)

    if approval.task_id:
        try:
            from app.services.review_service import ReviewService
            await ReviewService.resume_review(approval.task_id, user_id)
        except Exception as e:
            logger.error(f"审批通过后恢复审查失败: {e}")
            raise ValueError("审批已记录，但审查任务恢复失败，请重试") from e

    return {
        "approvalId": approval.id,
        "status": approval.status,
        "resolvedAt": approval.resolved_at.isoformat() if approval.resolved_at else "",
    }


async def reject_approval(db: AsyncSession, approval_id: int, user_id: int,
                          reviewer_notes: str = "") -> dict:
    """拒绝待审批记录。调用方应丢弃/降级对应结果。"""
    result = await db.execute(
        select(PendingApproval).where(
            PendingApproval.id == approval_id,
            PendingApproval.user_id == user_id,
        )
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise ValueError("审批记录不存在")
    if approval.status != ApprovalStatus.PENDING.value:
        raise ValueError(f"审批状态已为 {approval.status}")

    approval.status = ApprovalStatus.REJECTED.value
    approval.resolved_at = datetime.datetime.utcnow()
    await db.commit()
    await db.refresh(approval)

    await _write_human_audit_log(db, user_id, "HUMAN_REJECT", approval, reviewer_notes)

    if approval.task_id:
        task = await db.get(ReviewTask, approval.task_id)
        if task and task.user_id == user_id and task.status == "AWAITING_APPROVAL":
            task.status = "REJECTED"
            task.error_message = "人工安全审批拒绝"
            await db.commit()
            try:
                from app.services.sse_service import send_event, complete_task
                send_event(approval.task_id, "SECURITY_ALERT", alertType="PROMPT_INJECTION",
                           severity="CRITICAL", message=task.error_message)
                complete_task(approval.task_id)
            except Exception as e:
                logger.warning(f"发送审批拒绝事件失败: {e}")

    return {
        "approvalId": approval.id,
        "status": approval.status,
        "resolvedAt": approval.resolved_at.isoformat() if approval.resolved_at else "",
    }


async def list_pending_approvals(db: AsyncSession, user_id: int) -> list[dict]:
    """列出用户的所有待审批记录。自动过期超过 24h 的记录。"""
    await _expire_old_approvals(db, user_id)

    result = await db.execute(
        select(PendingApproval)
        .where(
            PendingApproval.user_id == user_id,
            PendingApproval.status == ApprovalStatus.PENDING.value,
        )
        .order_by(PendingApproval.created_at.desc())
    )
    approvals = result.scalars().all()

    return [
        {
            "approvalId": a.id,
            "taskId": a.task_id,
            "approvalType": a.approval_type,
            "riskLevel": a.risk_level,
            "riskReasoning": a.risk_reasoning,
            "sourceText": (a.source_text or "")[:500],
            "status": a.status,
            "createdAt": a.created_at.isoformat() if a.created_at else "",
        }
        for a in approvals
    ]


async def get_approval(db: AsyncSession, approval_id: int, user_id: int) -> dict | None:
    """按 ID 获取单条审批记录。"""
    result = await db.execute(
        select(PendingApproval).where(
            PendingApproval.id == approval_id,
            PendingApproval.user_id == user_id,
        )
    )
    a = result.scalar_one_or_none()
    if not a:
        return None
    return {
        "approvalId": a.id,
        "taskId": a.task_id,
        "approvalType": a.approval_type,
        "riskLevel": a.risk_level,
        "riskReasoning": a.risk_reasoning,
        "sourceText": (a.source_text or "")[:500],
        "status": a.status,
        "createdAt": a.created_at.isoformat() if a.created_at else "",
        "resolvedAt": a.resolved_at.isoformat() if a.resolved_at else None,
    }


async def _expire_old_approvals(db: AsyncSession, user_id: int) -> None:
    """自动将超过 24h 的待审批记录标记为过期。"""
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=APPROVAL_TIMEOUT_HOURS)
    await db.execute(
        update(PendingApproval)
        .where(
            PendingApproval.user_id == user_id,
            PendingApproval.status == ApprovalStatus.PENDING.value,
            PendingApproval.created_at < cutoff,
        )
        .values(status=ApprovalStatus.EXPIRED.value, resolved_at=datetime.datetime.utcnow())
    )
    await db.commit()


async def _write_human_audit_log(
    db: AsyncSession, user_id: int, event_type: str,
    approval: PendingApproval, notes: str = "",
) -> None:
    """写入人工决策的审计日志。"""
    try:
        from app.models import SecurityAuditLog
        log_entry = SecurityAuditLog(
            user_id=user_id,
            event_type=event_type,
            severity="INFO",
            source="agent_node",
            summary=f"{event_type} 审批 #{approval.id}: {approval.approval_type} / {approval.risk_level}",
            detail={
                "approval_id": approval.id,
                "task_id": approval.task_id,
                "approval_type": approval.approval_type,
                "risk_level": approval.risk_level,
                "reviewer_notes": notes,
            },
        )
        db.add(log_entry)
        await db.commit()
    except Exception as e:
        logger.warning(f"人工审计日志写入失败: {e}")

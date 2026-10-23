"""安全管线 —— Agent 操作的四层防御体系。

层级：
  1. 规则过滤器  — 静态模式匹配（快速，不消耗 LLM）
  2. AI 分类器   — LLM 注入检测（识别语义级攻击）
  3. 工具守卫    — MCP 工具 I/O 校验（执行前/后验证）
  4. 人工关卡    — 高风险操作需人工审批

用法：
  from app.security import SecurityPipeline

  # 文档审查
  verdict = await SecurityPipeline.check_document(text, db, user_id, task_id)

  # 咨询问答
  verdict = await SecurityPipeline.check_query(text, db, user_id)
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.security.schemas import (
    FilterResult, ClassifyResult, RiskClass, SecurityVerdict, ApprovalType,
)
from app.security.rule_filter import filter_text
from app.security.risk_classifier import classify_text

logger = logging.getLogger(__name__)


class SecurityPipeline:

    @staticmethod
    async def check_document(
        text: str,
        db: AsyncSession,
        user_id: int,
        task_id: int,
    ) -> SecurityVerdict:
        """对上传的文档文本执行安全管线。

        返回 SecurityVerdict：
        - blocked=True → 调用方必须停止审查
        - requires_approval=True → 调用方必须等待人工审批
        """
        # ── 第 1 层：规则过滤器 ──────────────────────────────────────
        filter_result = filter_text(text, source="document")
        if not filter_result.passed:
            await _log_security_event(
                db, user_id, "RULE_BLOCKED", "CRITICAL",
                "document_upload",
                f"文档被规则过滤器拦截: {filter_result.blocked_reason}",
                {"task_id": task_id, "reason": filter_result.blocked_reason},
            )
            return SecurityVerdict(
                passed=False, risk_class=RiskClass.MALICIOUS,
                blocked=True, requires_approval=False,
                filter_result=filter_result,
            )

        # ── 第 2 层：AI 风险分类器 ──────────────────────────────────
        classify_result = await classify_text(filter_result.sanitized_text)

        await _log_security_event(
            db, user_id, "AI_CLASSIFY",
            "WARNING" if classify_result.risk_class != RiskClass.SAFE else "INFO",
            "document_upload",
            f"AI 分类结果: {classify_result.risk_class.value} (score={classify_result.risk_score:.2f})",
            {
                "task_id": task_id,
                "risk_class": classify_result.risk_class.value,
                "risk_score": classify_result.risk_score,
                "reasoning": classify_result.reasoning,
            },
        )

        # ── 决策分发 ──────────────────────────────────────────────────
        if classify_result.risk_class == RiskClass.MALICIOUS:
            return SecurityVerdict(
                passed=False, risk_class=RiskClass.MALICIOUS,
                blocked=True, requires_approval=False,
                filter_result=filter_result, classify_result=classify_result,
            )

        if classify_result.risk_class == RiskClass.SUSPICIOUS:
            # 可疑内容需人工审批后才能继续
            from app.security.human_gate import create_approval
            try:
                approval = await create_approval(
                    db=db, user_id=user_id, task_id=task_id,
                    approval_type=ApprovalType.SECURITY_REVIEW.value,
                    risk_level="SUSPICIOUS",
                    risk_reasoning=classify_result.reasoning,
                    source_text=text[:2000],
                    sse_task_id=str(task_id),
                )
                return SecurityVerdict(
                    passed=False, risk_class=RiskClass.SUSPICIOUS,
                    blocked=False, requires_approval=True,
                    filter_result=filter_result, classify_result=classify_result,
                    approval_id=approval["approvalId"],
                )
            except Exception as e:
                logger.error(f"创建审批失败: {e}，保持阻断状态")
                return SecurityVerdict(
                    passed=False, risk_class=RiskClass.SUSPICIOUS,
                    blocked=True, requires_approval=False,
                    filter_result=filter_result, classify_result=classify_result,
                )

        # SAFE：放行
        return SecurityVerdict(
            passed=True, risk_class=RiskClass.SAFE,
            blocked=False, requires_approval=False,
            filter_result=filter_result, classify_result=classify_result,
        )

    @staticmethod
    async def check_query(
        text: str,
        db: AsyncSession,
        user_id: int,
    ) -> SecurityVerdict:
        """对用户咨询问题进行安全审查。

        返回 SecurityVerdict：
        - blocked=True → 拒绝该咨询
        - SUSPICIOUS/MALICIOUS 级别的问题会被阻止
        """
        # ── 第 1 层：规则过滤器 ──────────────────────────────────────
        filter_result = filter_text(text, source="query")
        if not filter_result.passed:
            await _log_security_event(
                db, user_id, "RULE_BLOCKED", "CRITICAL",
                "consultation",
                f"咨询问题被规则过滤器拦截: {filter_result.blocked_reason}",
                {"reason": filter_result.blocked_reason},
            )
            return SecurityVerdict(
                passed=False, risk_class=RiskClass.MALICIOUS,
                blocked=True, requires_approval=False,
                filter_result=filter_result,
            )

        # ── 第 2 层：AI 风险分类器 ──────────────────────────────────
        classify_result = await classify_text(filter_result.sanitized_text)

        await _log_security_event(
            db, user_id, "AI_CLASSIFY",
            "WARNING" if classify_result.risk_class != RiskClass.SAFE else "INFO",
            "consultation",
            f"AI 分类结果: {classify_result.risk_class.value}",
            {"risk_class": classify_result.risk_class.value, "reasoning": classify_result.reasoning},
        )

        if classify_result.risk_class != RiskClass.SAFE:
            return SecurityVerdict(
                passed=False, risk_class=classify_result.risk_class,
                blocked=True, requires_approval=False,
                filter_result=filter_result, classify_result=classify_result,
            )

        # 已通过分类的咨询才交给生成模型。
        return SecurityVerdict(
            passed=True,
            risk_class=classify_result.risk_class,
            blocked=False,
            requires_approval=False,
            filter_result=filter_result,
            classify_result=classify_result,
        )


async def _log_security_event(
    db: AsyncSession, user_id: int, event_type: str, severity: str,
    source: str, summary: str, detail: dict,
) -> None:
    """将安全事件写入审计日志。"""
    try:
        from app.models import SecurityAuditLog
        log_entry = SecurityAuditLog(
            user_id=user_id,
            event_type=event_type,
            severity=severity,
            source=source,
            summary=summary,
            detail=detail,
        )
        db.add(log_entry)
        await db.commit()
    except Exception as e:
        logger.warning(f"安全审计日志写入失败: {e}")

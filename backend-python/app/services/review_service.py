import asyncio
import logging
import datetime
import re
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import Document, ReviewTask, ReviewResult, RiskItem
from app.services.sse_service import send_event, complete_task

logger = logging.getLogger(__name__)


class ReviewService:

    @staticmethod
    async def create_review(db: AsyncSession, user_id: int, document_id: int,
                            review_type: str = "FULL") -> dict:
        # 校验文档归属
        result = await db.execute(
            select(Document).where(Document.id == document_id, Document.user_id == user_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise ValueError("Document not found")
        if not doc.content_text:
            raise ValueError("Document has no extractable text")

        # 创建审查任务
        task = ReviewTask(
            user_id=user_id,
            document_id=document_id,
            review_type=review_type,
            status="PENDING",
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        # 后台启动 Agent
        asyncio.create_task(ReviewService._run_review(task.id, user_id))

        return {
            "taskId": task.id,
            "documentId": task.document_id,
            "documentName": doc.original_filename,
            "reviewType": task.review_type,
            "status": task.status,
            "totalClauses": task.total_clauses or 0,
            "reviewedClauses": task.reviewed_clauses or 0,
            "riskCountHigh": task.risk_count_high or 0,
            "riskCountMedium": task.risk_count_medium or 0,
            "riskCountLow": task.risk_count_low or 0,
            "startedAt": task.started_at.isoformat() if task.started_at else None,
            "completedAt": task.completed_at.isoformat() if task.completed_at else None,
            "createdAt": task.created_at.isoformat() if task.created_at else "",
        }

    @staticmethod
    async def resume_review(task_id: int, user_id: int) -> None:
        """恢复已通过人工安全审批的任务，并跳过重复的安全分类。"""
        from app.database import async_session_factory
        async with async_session_factory() as db:
            result = await db.execute(select(ReviewTask).where(
                ReviewTask.id == task_id,
                ReviewTask.user_id == user_id,
                ReviewTask.status == "AWAITING_APPROVAL",
            ))
            task = result.scalar_one_or_none()
            if not task:
                raise ValueError("Review task is not awaiting approval")
            task.status = "PENDING"
            await db.commit()
        asyncio.create_task(ReviewService._run_review(task_id, user_id, skip_security=True))

    @staticmethod
    async def get_task(db: AsyncSession, task_id: int, user_id: int) -> dict:
        result = await db.execute(
            select(ReviewTask).where(ReviewTask.id == task_id, ReviewTask.user_id == user_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            raise ValueError("Review task not found")

        result = await db.execute(
            select(Document).where(Document.id == task.document_id)
        )
        doc = result.scalar_one_or_none()

        return {
            "taskId": task.id,
            "documentId": task.document_id,
            "documentName": doc.original_filename if doc else "",
            "reviewType": task.review_type,
            "status": task.status,
            "totalClauses": task.total_clauses or 0,
            "reviewedClauses": task.reviewed_clauses or 0,
            "riskCountHigh": task.risk_count_high or 0,
            "riskCountMedium": task.risk_count_medium or 0,
            "riskCountLow": task.risk_count_low or 0,
            "startedAt": task.started_at.isoformat() if task.started_at else None,
            "completedAt": task.completed_at.isoformat() if task.completed_at else None,
            "createdAt": task.created_at.isoformat() if task.created_at else "",
        }

    @staticmethod
    async def list_tasks(
        db: AsyncSession, user_id: int, page: int = 1, size: int = 10,
        status: Optional[str] = None
    ) -> tuple[list[dict], int]:
        query = select(ReviewTask).where(ReviewTask.user_id == user_id)
        if status:
            query = query.where(ReviewTask.status == status)
        query = query.order_by(ReviewTask.created_at.desc())

        offset = (page - 1) * size
        query = query.offset(offset).limit(size)
        result = await db.execute(query)
        tasks = result.scalars().all()

        # 获取总数
        count_query = select(ReviewTask).where(ReviewTask.user_id == user_id)
        if status:
            count_query = count_query.where(ReviewTask.status == status)
        count_result = await db.execute(count_query)
        total = len(list(count_result.scalars().all()))

        items = []
        for t in tasks:
            doc_result = await db.execute(select(Document).where(Document.id == t.document_id))
            doc = doc_result.scalar_one_or_none()
            items.append({
                "taskId": t.id,
                "documentId": t.document_id,
                "documentName": doc.original_filename if doc else "",
                "reviewType": t.review_type,
                "status": t.status,
                "totalClauses": t.total_clauses or 0,
                "reviewedClauses": t.reviewed_clauses or 0,
                "riskCountHigh": t.risk_count_high or 0,
                "riskCountMedium": t.risk_count_medium or 0,
                "riskCountLow": t.risk_count_low or 0,
                "startedAt": t.started_at.isoformat() if t.started_at else None,
                "completedAt": t.completed_at.isoformat() if t.completed_at else None,
                "createdAt": t.created_at.isoformat() if t.created_at else "",
            })
        return items, total

    @staticmethod
    async def delete_task(db: AsyncSession, task_id: int, user_id: int) -> None:
        result = await db.execute(
            select(ReviewTask).where(ReviewTask.id == task_id, ReviewTask.user_id == user_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            raise ValueError("Review task not found")

        # 级联删除风险条目和结果
        risk_result = await db.execute(
            select(RiskItem).where(RiskItem.review_task_id == task.id)
        )
        for ri in risk_result.scalars().all():
            await db.delete(ri)

        r_result = await db.execute(
            select(ReviewResult).where(ReviewResult.review_task_id == task.id)
        )
        rr = r_result.scalar_one_or_none()
        if rr:
            await db.delete(rr)

        await db.delete(task)
        await db.commit()

    @staticmethod
    async def get_result(db: AsyncSession, task_id: int, user_id: int) -> dict:
        # Always authorize before reading a shared cache entry.
        result = await db.execute(
            select(ReviewTask).where(ReviewTask.id == task_id, ReviewTask.user_id == user_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            raise ValueError("Review task not found")

        # ── 缓存检查 ────────────────────────────────────────────
        from app.cache import cache_manager
        cache_key = f"review_result:{user_id}:{task_id}"
        cached = cache_manager.get(cache_key)
        if cached is not None:
            import json
            logger.info(f"审查结果缓存命中 task {task_id}")
            return json.loads(cached)

        if task.status != "COMPLETED":
            raise ValueError("Review not yet completed")

        rr_result = await db.execute(
            select(ReviewResult).where(ReviewResult.review_task_id == task.id)
        )
        rr = rr_result.scalar_one_or_none()
        if not rr:
            raise ValueError("Review result not found")

        ri_result = await db.execute(
            select(RiskItem).where(RiskItem.review_task_id == task.id)
        )
        risk_items = []
        for ri in ri_result.scalars().all():
            risk_items.append({
                "clauseIndex": ri.clause_index,
                "clauseText": ri.clause_text or "",
                "riskType": ri.risk_type,
                "riskLevel": ri.risk_level,
                "riskDescription": ri.risk_description or "",
                "suggestedAmendment": ri.suggested_amendment or "",
                "legalBasis": ri.legal_basis or "",
            })

        result_data = {
            "taskId": task.id,
            "overallScore": float(rr.overall_score) if rr.overall_score else 0.0,
            "summary": rr.summary or "",
            "recommendations": rr.recommendations or [],
            "riskItems": risk_items,
        }

        # ── 缓存结果 ───────────────────────────────────────────
        import json
        from app.config import settings
        cache_manager.set(cache_key, json.dumps(result_data, ensure_ascii=False), settings.review_cache_ttl)

        return result_data

    @staticmethod
    async def _run_review(task_id: int, user_id: int, skip_security: bool = False):
        """后台任务：运行 LangGraph Agent 并将结果持久化到数据库。"""
        from app.database import async_session_factory

        async with async_session_factory() as db:
            try:
                task = await db.get(ReviewTask, task_id)
                if not task:
                    return
                doc = await db.get(Document, task.document_id)
                if not doc or not doc.content_text:
                    task.status = "FAILED"
                    task.error_message = "Document has no content"
                    await db.commit()
                    send_event(task_id, "ERROR", message="Document has no content")
                    complete_task(task_id)
                    return

                # 更新状态为处理中
                task.status = "PROCESSING"
                task.started_at = datetime.datetime.utcnow()
                await db.commit()

                send_event(task_id, "REVIEW_STARTED", reviewType=task.review_type)

                # ── 安全管线检查 ───────────────────────────
                from app.security import SecurityPipeline
                from app.security.schemas import RiskClass

                security_verdict = None
                if not skip_security:
                    security_verdict = await SecurityPipeline.check_document(
                        text=doc.content_text,
                        db=db,
                        user_id=user_id,
                        task_id=task_id,
                    )

                if security_verdict and security_verdict.blocked:
                    task.status = "REJECTED"
                    task.error_message = (
                        f"安全审查拦截: {security_verdict.filter_result.blocked_reason}"
                        if security_verdict.filter_result else "安全审查拦截"
                    )
                    await db.commit()
                    send_event(task_id, "SECURITY_ALERT",
                               alertType="PROMPT_INJECTION",
                               severity="CRITICAL",
                               message=task.error_message)
                    complete_task(task_id)
                    return

                if security_verdict and security_verdict.requires_approval:
                    task.status = "AWAITING_APPROVAL"
                    await db.commit()
                    send_event(
                        task_id, "SECURITY_ALERT",
                        alertType="PROMPT_INJECTION",
                        severity="WARNING",
                        message=(
                            security_verdict.classify_result.reasoning
                            if security_verdict.classify_result else "需要人工审核"
                        ),
                        approvalId=security_verdict.approval_id,
                    )
                    complete_task(task_id)
                    return

                # 优先使用安全清洗后的文本
                if (security_verdict and security_verdict.filter_result
                        and security_verdict.filter_result.warnings):
                    logger.warning(
                        f"Security warnings for task {task_id}: "
                        f"{security_verdict.filter_result.warnings}"
                    )

                # 使用安全管线清洗后的文本（已去除控制字符）
                sanitized_text = doc.content_text
                if (security_verdict and security_verdict.filter_result
                        and security_verdict.filter_result.sanitized_text):
                    sanitized_text = security_verdict.filter_result.sanitized_text

                # 运行 LangGraph Agent
                from app.agent.state import create_initial_state
                from app.agent.graph import build_review_graph

                state = create_initial_state(
                    document_text=sanitized_text,
                    review_type=task.review_type,
                    task_id=str(task_id),
                )

                from app.agent.checkpoint import get_checkpoint_saver, checkpoint_config
                graph = build_review_graph()
                checkpointer = await get_checkpoint_saver()
                compiled = graph.compile(checkpointer=checkpointer)
                from app.parser.chunker import ClauseLevelChunker
                estimated_clauses = len(ClauseLevelChunker().split_clauses(sanitized_text))
                if not estimated_clauses:
                    raise ValueError("Document has no reviewable clauses")
                config = checkpoint_config(task_id, user_id)
                config["recursion_limit"] = max(200, estimated_clauses * 8 + 20)

                # 流式执行 Agent，累积各节点输出到最终状态
                clause_count = 0
                final_state = dict(state)
                async for event in compiled.astream(state, config):
                    for node_name, node_state in event.items():
                        final_state.update(node_state)
                        if node_name == "parse_document":
                            clause_count = node_state.get("total_clauses", 0)
                            send_event(task_id, "DOCUMENT_PARSED",
                                       totalClauses=clause_count)
                        elif node_name == "extract_clauses":
                            clause_count = node_state.get("total_clauses", 0)
                        elif node_name == "risk_type_identify":
                            idx = node_state.get("current_clause_index", 0)
                            clauses = final_state.get("clauses", [])
                            preview = ""
                            if idx < len(clauses):
                                preview = clauses[idx].get("text", "")[:80]
                            send_event(task_id, "CLAUSE_ANALYZING",
                                       clauseIndex=idx, clausePreview=preview,
                                       totalClauses=clause_count)
                        elif node_name == "severity_check":
                            all_risks = final_state.get("all_risks", [])
                            if all_risks:
                                latest = all_risks[-1]
                                send_event(task_id, "RISK_FOUND",
                                           clauseIndex=latest.get("clause_index", 0),
                                           riskType=latest.get("risk_type", ""),
                                           riskLevel=latest.get("risk_level", ""),
                                           riskDescription=latest.get("risk_description", ""),
                                           suggestedAmendment=latest.get("suggested_amendment", ""),
                                           legalBasis=latest.get("legal_basis", ""))
                            # 进度更新
                            reviewed = final_state.get("current_clause_index", 0) + 1
                            total = clause_count
                            if total:
                                risks = final_state.get("all_risks", [])
                                hi = sum(1 for r in risks if r.get("risk_level") == "HIGH")
                                med = sum(1 for r in risks if r.get("risk_level") == "MEDIUM")
                                lo = sum(1 for r in risks if r.get("risk_level") == "LOW")
                                send_event(task_id, "PROGRESS_UPDATE",
                                           reviewedClauses=reviewed, totalClauses=total,
                                           percentage=round(reviewed / total * 100),
                                           riskCounts={"high": hi, "medium": med, "low": lo})

                # 保存审查结果
                all_risks = final_state.get("all_risks", [])
                high_count = sum(1 for r in all_risks if r.get("risk_level") == "HIGH")
                medium_count = sum(1 for r in all_risks if r.get("risk_level") == "MEDIUM")
                low_count = sum(1 for r in all_risks if r.get("risk_level") == "LOW")

                review_result = ReviewResult(
                    review_task_id=task.id,
                    overall_score=final_state.get("overall_score", 0.0),
                    summary=final_state.get("summary", ""),
                    recommendations=final_state.get("recommendations", []),
                )
                db.add(review_result)

                # 保存风险条目
                for risk in all_risks:
                    clause = next(
                        (c for c in final_state.get("clauses", [])
                         if c.get("index") == risk.get("clause_index")), {}
                    )
                    ri = RiskItem(
                        review_task_id=task.id,
                        clause_index=risk.get("clause_index", 0),
                        clause_text=risk.get("clause_text", ""),
                        risk_type=risk.get("risk_type", ""),
                        risk_level=risk.get("risk_level", "LOW"),
                        risk_description=risk.get("risk_description", ""),
                        suggested_amendment=(
                            risk.get("suggested_amendment")
                            or clause.get("suggested_amendment", "")
                        ),
                        legal_basis=risk.get("legal_basis") or clause.get("legal_basis", ""),
                    )
                    db.add(ri)

                # 更新任务状态
                task.status = "COMPLETED"
                task.total_clauses = clause_count
                task.reviewed_clauses = clause_count
                task.risk_count_high = high_count
                task.risk_count_medium = medium_count
                task.risk_count_low = low_count
                task.completed_at = datetime.datetime.utcnow()
                await db.commit()

                send_event(task_id, "REVIEW_COMPLETE",
                           overallScore=final_state.get("overall_score", 0.0),
                           summary=final_state.get("summary", ""),
                           riskCounts={"high": high_count, "medium": medium_count, "low": low_count})
                complete_task(task_id)

            except Exception as e:
                logger.exception(f"Review task {task_id} failed: {e}")
                try:
                    await db.rollback()
                    task = await db.get(ReviewTask, task_id)
                    if task:
                        task.status = "FAILED"
                        task.error_message = str(e)
                        await db.commit()
                except Exception:
                    pass
                send_event(task_id, "ERROR", message=str(e))
                complete_task(task_id)

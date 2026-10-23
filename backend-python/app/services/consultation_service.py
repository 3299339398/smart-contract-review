import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import ConsultationRecord, Document

logger = logging.getLogger(__name__)


class ConsultationService:

    @staticmethod
    async def ask(db: AsyncSession, user_id: int, question: str,
                  document_id: int | None = None) -> dict:
        # ── 安全管线检查 ───────────────────────────────────
        from app.security import SecurityPipeline
        security_verdict = await SecurityPipeline.check_query(
            text=question, db=db, user_id=user_id,
        )
        if security_verdict.blocked:
            raise ValueError(
                security_verdict.filter_result.blocked_reason
                if security_verdict.filter_result
                else "输入内容未通过安全检查"
            )

        # 获取文档条款（如提供了 document_id）
        clauses = []
        if document_id:
            result = await db.execute(
                select(Document).where(Document.id == document_id, Document.user_id == user_id)
            )
            doc = result.scalar_one_or_none()
            if not doc:
                raise ValueError("Document not found")
            if doc.content_text:
                clauses = _extract_clauses(doc.content_text)

        # 运行 RAG 智能咨询
        from app.rag.consultation_chain import answer_question
        result = await answer_question(
            question=question,
            clauses=clauses,
            document_id=document_id,
            top_k=5,
        )
        answer_text = result[0]
        source_clauses = result[1]
        pipeline_meta = result[2] if len(result) > 2 else {}
        citation_warnings = (pipeline_meta or {}).get("citation_warnings", [])

        # 保存咨询记录
        source_json = [{"clauseIndex": sc["clause_index"], "text": sc["text"]}
                       for sc in source_clauses] if source_clauses else []

        record = ConsultationRecord(
            user_id=user_id,
            document_id=document_id,
            question=question,
            answer=answer_text,
            source_clauses=source_json,
            token_count=len(question) + len(answer_text),
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)

        return {
            "consultId": record.id,
            "question": question,
            "answer": answer_text,
            "sourceClauses": [
                {"clauseIndex": sc["clause_index"], "text": sc["text"]}
                for sc in source_clauses
            ] if source_clauses else [],
            "citationWarnings": citation_warnings,
            "createdAt": record.created_at.isoformat() if record.created_at else "",
        }

    @staticmethod
    async def get_history(
        db: AsyncSession, user_id: int, document_id: int | None = None,
        page: int = 1, size: int = 10
    ) -> tuple[list[dict], int]:
        query = select(ConsultationRecord).where(
            ConsultationRecord.user_id == user_id
        )
        if document_id:
            query = query.where(ConsultationRecord.document_id == document_id)
        query = query.order_by(ConsultationRecord.created_at.desc())

        offset = (page - 1) * size
        query = query.offset(offset).limit(size)
        result = await db.execute(query)
        records = result.scalars().all()

        # 统计总数
        count_q = select(ConsultationRecord).where(ConsultationRecord.user_id == user_id)
        if document_id:
            count_q = count_q.where(ConsultationRecord.document_id == document_id)
        count_result = await db.execute(count_q)
        total = len(list(count_result.scalars().all()))

        items = []
        for r in records:
            sc = r.source_clauses or []
            items.append({
                "consultId": r.id,
                "question": r.question,
                "answer": r.answer,
                "sourceClauses": [
                    {"clauseIndex": s.get("clauseIndex", 0), "text": s.get("text", "")}
                    for s in sc
                ],
                "citationWarnings": [],
                "createdAt": r.created_at.isoformat() if r.created_at else "",
            })
        return items, total


def _extract_clauses(text: str) -> list[dict]:
    """从合同文本中提取条款（与 Java 端中文条款标记逻辑一致）。"""
    import re
    pattern = r'(?:第\s*[一二三四五六七八九十百千\d]+\s*[条节章款]|第\s*\d+\s*[条节章款])'
    parts = re.split(f'({pattern})', text)
    clauses = []
    idx = 0
    for i in range(1, len(parts), 2):
        if i + 1 < len(parts):
            clause_text = (parts[i] + parts[i + 1]).strip()
        else:
            clause_text = parts[i].strip()
        if clause_text:
            clauses.append({"clause_index": idx, "text": clause_text})
            idx += 1

    # 回退方案：段落拆分
    if not clauses:
        paras = [p.strip() for p in text.split("\n\n") if p.strip()]
        clauses = [{"clause_index": i, "text": p} for i, p in enumerate(paras)]

    return clauses

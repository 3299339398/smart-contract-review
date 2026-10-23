import os
import logging
import uuid
import datetime
from pathlib import Path
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models import Document
from app.services.file_validator import validate
from app.config import settings

logger = logging.getLogger(__name__)


class DocumentService:

    @staticmethod
    async def upload(db: AsyncSession, user_id: int, file_bytes: bytes,
                     filename: str, content_type: str = None) -> dict:
        # 校验文件
        file_type = validate(file_bytes, filename, content_type)

        # 保存到磁盘
        upload_dir = Path(settings.upload_dir) / str(user_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}_{filename}"
        stored_path = upload_dir / stored_name
        stored_path.write_bytes(file_bytes)

        # 解析文档文本
        raw_text = ""
        try:
            from app.parser.document_parser import DocumentParserFactory
            parser = DocumentParserFactory.create(str(stored_path))
            raw_text = parser.extract_text(str(stored_path))
        except Exception as e:
            logger.warning(f"Document text extraction failed: {e}")

        # 清洗文本（去控制字符、统一换行符、合并多余空白）
        from app.utils.text_utils import clean_document_text
        content_text = clean_document_text(raw_text) if raw_text else ""

        # 统计条款数量
        clause_count = 0
        if content_text:
            from app.parser.chunker import ClauseLevelChunker
            chunker = ClauseLevelChunker()
            clause_texts = chunker.split_clauses(content_text)
            clauses = [
                {"index": i + 1, "text": clause_text}
                for i, clause_text in enumerate(clause_texts)
            ]
            clause_count = len(clauses)

        # 存入数据库
        doc = Document(
            user_id=user_id,
            original_filename=filename,
            stored_path=str(stored_path),
            file_size=len(file_bytes),
            file_type=file_type,
            document_status="UPLOADED",
            content_text=content_text,
            clause_count=clause_count,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)

        # ── 上传时建立 RAG 索引（而非查询时） ─────
        if content_text and clause_count > 0:
            try:
                from app.embeddings.vector_store import vector_store
                from app.rag.hybrid_retriever import hybrid_retriever
                await vector_store.add_clauses(doc.id, clauses)
                hybrid_retriever.index_clauses(doc.id, clauses)
                logger.info(f"RAG index built for doc {doc.id}: {clause_count} clauses")
            except Exception as e:
                logger.warning(f"RAG indexing skipped for doc {doc.id}: {e}")

        return {
            "documentId": doc.id,
            "originalFilename": doc.original_filename,
            "fileSize": doc.file_size,
            "fileType": doc.file_type,
            "documentStatus": doc.document_status,
            "clauseCount": doc.clause_count,
            "contentPreview": (content_text[:500] if content_text else ""),
            "createdAt": doc.created_at.isoformat() if doc.created_at else "",
        }

    @staticmethod
    async def list_documents(
        db: AsyncSession, user_id: int, page: int = 1, size: int = 10,
        status: Optional[str] = None
    ) -> tuple[list[dict], int]:
        query = select(Document).where(Document.user_id == user_id)
        if status:
            query = query.where(Document.document_status == status)
        query = query.order_by(Document.created_at.desc())

        # 统计总数
        count_query = select(Document).where(Document.user_id == user_id)
        if status:
            count_query = count_query.where(Document.document_status == status)
        total = (await db.execute(count_query)).scalars().all()
        total_count = len(list(total))

        # 分页
        offset = (page - 1) * size
        query = query.offset(offset).limit(size)
        result = await db.execute(query)
        docs = result.scalars().all()

        items = []
        for d in docs:
            content_text = d.content_text or ""
            items.append({
                "documentId": d.id,
                "originalFilename": d.original_filename,
                "fileSize": d.file_size,
                "fileType": d.file_type,
                "documentStatus": d.document_status,
                "clauseCount": d.clause_count,
                "contentPreview": content_text[:500],
                "createdAt": d.created_at.isoformat() if d.created_at else "",
            })
        return items, total_count

    @staticmethod
    async def get_document(db: AsyncSession, doc_id: int, user_id: int) -> dict:
        result = await db.execute(
            select(Document).where(Document.id == doc_id, Document.user_id == user_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise ValueError("Document not found")
        content_text = doc.content_text or ""
        return {
            "documentId": doc.id,
            "originalFilename": doc.original_filename,
            "fileSize": doc.file_size,
            "fileType": doc.file_type,
            "documentStatus": doc.document_status,
            "clauseCount": doc.clause_count,
            "contentPreview": content_text[:2000],
            "createdAt": doc.created_at.isoformat() if doc.created_at else "",
        }

    @staticmethod
    async def delete_document(db: AsyncSession, doc_id: int, user_id: int) -> None:
        result = await db.execute(
            select(Document).where(Document.id == doc_id, Document.user_id == user_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise ValueError("Document not found")

        # 从磁盘删除文件
        try:
            os.remove(doc.stored_path)
        except Exception as e:
            logger.warning(f"Failed to delete file {doc.stored_path}: {e}")

        # 清理向量索引
        try:
            from app.embeddings.vector_store import vector_store
            await vector_store.delete_document(doc.id)
        except Exception as e:
            logger.warning(f"Failed to delete vector index for doc {doc.id}: {e}")

        await db.delete(doc)
        await db.commit()

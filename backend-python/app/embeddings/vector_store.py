"""ChromaDB 向量存储包装器 —— 合同条款的存储与检索。"""

import logging
from typing import List, Dict, Optional
import app.main

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self):
        self._collection_name = "contract_clauses"
        self._collection = None

    def _get_collection(self):
        if self._collection is None and app.main.chroma_client is not None:
            try:
                self._collection = app.main.chroma_client.get_or_create_collection(
                    name=self._collection_name,
                    metadata={"description": "Contract clause embeddings for RAG"}
                )
            except Exception as e:
                logger.error(f"Failed to get ChromaDB collection: {e}")
        return self._collection

    async def add_clauses(self, doc_id: int, clauses: List[Dict]) -> int:
        """批量编码条款并存入 ChromaDB 向量库。"""
        collection = self._get_collection()
        if collection is None:
            logger.warning("ChromaDB not available, skipping vector storage")
            return 0

        from app.embeddings.embedding_service import embedding_service

        # 检查是否已索引（幂等）
        existing = collection.get(where={"doc_id": doc_id})
        if existing and existing.get("ids") and len(existing["ids"]) >= len(clauses):
            logger.info(f"Document {doc_id} already indexed, skipping")
            return len(existing["ids"])

        # 批量编码所有条款文本
        texts = [c.get("text", "") for c in clauses]
        embeddings = await embedding_service.embed_texts(texts)

        count = 0
        ids = []
        emb_list = []
        metas = []
        docs = []
        for i, clause in enumerate(clauses):
            text = clause.get("text", "")
            idx = clause.get("index", i + 1)
            if not text or len(text) < 10:
                continue
            ids.append(f"doc_{doc_id}_clause_{idx}")
            emb_list.append(embeddings[i])
            metas.append({
                "doc_id": doc_id,
                "clause_index": idx,
                "clause_text": text[:500]
            })
            docs.append(text)
            count += 1

        if ids:
            try:
                collection.add(ids=ids, embeddings=emb_list, metadatas=metas, documents=docs)
                logger.info(f"Indexed {count} clauses for doc_id={doc_id}")
            except Exception as e:
                logger.error(f"Failed to add clauses to vector store: {e}")

        return count

    async def similarity_search(self, query: str, doc_id: Optional[int] = None, k: int = 5) -> List[Dict]:
        """搜索相似条款。"""
        collection = self._get_collection()
        if collection is None:
            return []

        from app.embeddings.embedding_service import embedding_service

        query_embedding = await embedding_service.embed_query(query)

        where_filter = {"doc_id": doc_id} if doc_id else None
        try:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=k,
                where=where_filter
            )

            clauses = []
            if results and results.get("metadatas"):
                for i, meta in enumerate(results["metadatas"][0]):
                    clauses.append({
                        "clause_index": meta.get("clause_index", 0),
                        "text": meta.get("clause_text", ""),
                        "score": results["distances"][0][i] if results.get("distances") else 0
                    })
            return clauses
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    async def delete_document(self, doc_id: int):
        """删除指定文档的所有条款向量。"""
        collection = self._get_collection()
        if collection:
            try:
                collection.delete(where={"doc_id": doc_id})
            except Exception as e:
                logger.error(f"Failed to delete document vectors: {e}")


vector_store = VectorStore()

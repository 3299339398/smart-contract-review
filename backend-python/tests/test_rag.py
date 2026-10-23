"""Tests for RAG pipeline — embedding, BM25, hybrid retriever.

Run: python -m pytest tests/test_rag.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import asyncio


class TestEmbeddingService:
    def test_embed_query_returns_normalized_vector(self):
        from app.embeddings.embedding_service import embedding_service
        vec = asyncio.run(embedding_service.embed_query("违约责任条款"))
        assert len(vec) == 384, f"Expected 384-dim, got {len(vec)}"
        # Check normalization: ||v|| ≈ 1.0
        norm = sum(v * v for v in vec) ** 0.5
        assert 0.99 <= norm <= 1.01, f"Vector should be normalized, norm={norm}"

    def test_embed_texts_batch(self):
        from app.embeddings.embedding_service import embedding_service
        texts = ["违约责任", "付款条款", "保密义务"]
        vecs = asyncio.run(embedding_service.embed_texts(texts))
        assert len(vecs) == 3
        assert all(len(v) == 384 for v in vecs)

    def test_similar_texts_have_higher_similarity(self):
        from app.embeddings.embedding_service import embedding_service
        v1 = asyncio.run(embedding_service.embed_query("违约金过高"))
        v2 = asyncio.run(embedding_service.embed_query("违约金超过造成损失的30%"))
        v3 = asyncio.run(embedding_service.embed_query("员工上下班时间"))
        sim_12 = sum(a * b for a, b in zip(v1, v2))
        sim_13 = sum(a * b for a, b in zip(v1, v3))
        assert sim_12 > sim_13, f"Similar legal texts should have higher cosine similarity"


class TestBM25Retriever:
    def test_index_and_search(self):
        from app.rag.bm25_retriever import bm25_retriever
        clauses = [
            {"index": 1, "text": "违约方应赔偿守约方全部直接损失。"},
            {"index": 2, "text": "员工应遵守公司保密制度。"},
            {"index": 3, "text": "租赁期满前30日应通知对方是否续租。"},
        ]
        bm25_retriever.index(clauses)
        results = bm25_retriever.search("违约责任赔偿")
        assert len(results) >= 1
        assert results[0]["clause_index"] == 1  # First clause should match

    def test_no_results_for_unrelated_query(self):
        from app.rag.bm25_retriever import bm25_retriever
        clauses = [
            {"index": 1, "text": "付款条款：乙方应在每月5日前支付上月服务费。"},
        ]
        bm25_retriever.index(clauses)
        results = bm25_retriever.search("xyz不存在query")
        assert len(results) == 0


class TestHybridRetriever:
    def test_index_and_search(self):
        from app.rag.hybrid_retriever import hybrid_retriever
        clauses = [
            {"index": 1, "text": "违约方应赔偿守约方全部直接损失，但赔偿总额以合同金额为上限。"},
            {"index": 2, "text": "员工在任职期间完成的发明创造，其知识产权归属公司所有。"},
            {"index": 3, "text": "服务提供方应在收到发票后15个工作日内支付服务费。"},
            {"index": 4, "text": "租赁物的维修义务由出租人承担。"},
            {"index": 5, "text": "竞业限制期限为离职后二十四个月。"},
        ]
        # Indexing requires ChromaDB — search will fall back to BM25 only
        hybrid_retriever.index_clauses(999, clauses)
        results = asyncio.run(hybrid_retriever.search("知识产权归属"))
        assert len(results) >= 1, f"Expected >=1 result, got {len(results)}"
        # Should find clause 2 about IP ownership
        found_ip = any(r["clause_index"] == 2 for r in results)
        assert found_ip, f"Expected clause 2 in results, got {results}"

    def test_rrf_fusion_produces_scores(self):
        from app.rag.hybrid_retriever import hybrid_retriever
        clauses = [
            {"index": 1, "text": "违约金不得超过实际损失的30%。"},
            {"index": 2, "text": "双方应友好协商解决争议。"},
            {"index": 3, "text": "服务提供方应在收到发票后15个工作日内支付服务费。"},
            {"index": 4, "text": "租赁物的维修义务由出租人承担，承租人应妥善使用租赁物。"},
            {"index": 5, "text": "竞业限制期限为离职后二十四个月，补偿金按月支付。"},
        ]
        hybrid_retriever.index_clauses(998, clauses)
        results = asyncio.run(hybrid_retriever.search("违约金上限"))
        assert len(results) >= 1
        for r in results:
            assert "hybrid_score" in r, f"Missing hybrid_score in {r}"
            assert 0 <= r["hybrid_score"] <= 1, f"Score out of range: {r['hybrid_score']}"

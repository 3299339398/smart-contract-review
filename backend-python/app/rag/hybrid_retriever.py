"""混合检索器：RRF 融合 BM25 关键词 + 向量语义搜索结果。

RRF（倒数秩融合）公式：
    score(d) = sum_{r in rankings} 1 / (k + rank(d, r))
其中 k=60 为平滑常数（学术界标准取值）。

Enhancements:
  - Content-level deduplication via SHA256 hash
  - Score calibration (min-max) before RRF fusion
  - Per-query weight overrides (driven by question routing)
  - Config-driven defaults via app.config.settings
"""

import logging
from typing import List, Dict, Optional

from app.embeddings.vector_store import vector_store
from app.rag.bm25_retriever import bm25_retriever
from app.config import settings

logger = logging.getLogger(__name__)


class HybridRetriever:
    """通过 RRF 融合 BM25 关键词检索与向量语义检索。"""

    def __init__(self, vector_weight: float = None, bm25_weight: float = None):
        self.vector_weight = vector_weight or settings.rag_default_vector_weight
        self.bm25_weight = bm25_weight or settings.rag_default_bm25_weight
        self._indexed_doc_id: Optional[int] = None

    def index_clauses(self, doc_id: int, clauses: List[Dict]):
        """将条款索引到 BM25（内存级）。向量索引在上传时完成。"""
        bm25_retriever.index(clauses, doc_id=doc_id)
        self._indexed_doc_id = doc_id
        logger.info(f"Hybrid index built: doc_id={doc_id}, {len(clauses)} clauses")

    async def search(self, query: str, doc_id: Optional[int] = None,
                     top_k: int = 5,
                     vector_weight: Optional[float] = None,
                     bm25_weight: Optional[float] = None) -> List[Dict]:
        """BM25 与向量检索的 RRF 融合。

        Args:
            query: 检索查询文本
            doc_id: 可选的文档 ID，用于限定向量检索范围
            top_k: 返回结果数量
            vector_weight: 单次查询的向量权重覆盖值（由路由器提供）
            bm25_weight: 单次查询的 BM25 权重覆盖值（由路由器提供）
        """
        vw = vector_weight if vector_weight is not None else self.vector_weight
        bw = bm25_weight if bm25_weight is not None else self.bm25_weight
        rrf_k = settings.rag_rrf_k

        # 并行执行 BM25 与向量检索
        pool_size = top_k * 2
        effective_doc_id = doc_id if doc_id is not None else self._indexed_doc_id
        bm25_results = bm25_retriever.search(
            query, top_k=pool_size, doc_id=effective_doc_id
        )

        vector_results = []
        try:
            vector_results = await vector_store.similarity_search(
                query, doc_id=effective_doc_id, k=pool_size
            )
        except Exception as e:
            logger.warning(f"Vector search unavailable, falling back to BM25-only: {e}")

        # ── 按内容哈希去重 ──────────────────────────────
        bm25_results = self._deduplicate(bm25_results)
        vector_results = self._deduplicate(vector_results)

        # ── 分数校准（各通道 min-max 归一化） ──────────────────
        bm25_results = self._calibrate_scores(bm25_results, "bm25_score")
        vector_results = self._calibrate_scores(vector_results, "score")

        # ── RRF 融合 ───────────────────────────────────────────────
        fused: Dict[int, dict] = {}

        for rank, item in enumerate(bm25_results):
            idx = item["clause_index"]
            rrf = 1.0 / (rrf_k + rank + 1) * bw
            fused[idx] = {"clause": item, "score": rrf}

        for rank, item in enumerate(vector_results):
            idx = item["clause_index"]
            rrf = 1.0 / (rrf_k + rank + 1) * vw
            if idx in fused:
                fused[idx]["score"] += rrf
            else:
                fused[idx] = {"clause": item, "score": rrf}

        # 按融合分数降序排列
        sorted_clauses = sorted(fused.values(), key=lambda x: x["score"], reverse=True)
        top = sorted_clauses[:top_k]

        results = []
        for entry in top:
            results.append({
                "clause_index": entry["clause"]["clause_index"],
                "text": entry["clause"].get("text", ""),
                "hybrid_score": round(entry["score"], 4)
            })

        return results

    # ── 内部辅助方法 ─────────────────────────────────────────────────

    @staticmethod
    def _deduplicate(results: List[Dict]) -> List[Dict]:
        """使用 SHA256 哈希按内容去重。"""
        from app.embeddings.content_hash import clause_hash
        seen = set()
        unique = []
        for r in results:
            h = clause_hash(r.get("text", ""))
            if h not in seen:
                seen.add(h)
                unique.append(r)
        return unique

    @staticmethod
    def _calibrate_scores(results: List[Dict], score_key: str) -> List[Dict]:
        """Min-max 归一化至 [0, 1]，保证跨通道公平比较。"""
        if not results:
            return results
        scores = [r.get(score_key, 0) for r in results]
        min_s, max_s = min(scores), max(scores)
        if max_s == min_s:
            for r in results:
                r["_calibrated"] = 0.5
            return results
        for r in results:
            r["_calibrated"] = round((r.get(score_key, 0) - min_s) / (max_s - min_s), 4)
        return results


hybrid_retriever = HybridRetriever()

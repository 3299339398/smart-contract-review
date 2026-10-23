"""低置信度二次检索 —— 首次检索结果较弱时的后备方案。

当所有 Top-K 混合检索得分低于可配置阈值时，触发第二轮检索，
使用以下替代策略：
  - query_expansion: Search with all rewritten query variants, merge via RRF
  - drop_filter: Remove doc_id scope for cross-document search
  - mmr_diversity: Maximal Marginal Relevance for diverse results
"""

import logging
from enum import Enum
from typing import List, Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class SecondaryStrategy(Enum):
    QUERY_EXPANSION = "query_expansion"
    DROP_FILTER = "drop_filter"
    MMR_DIVERSITY = "mmr_diversity"


class SecondaryRetriever:
    """首次检索结果质量不足时触发替代检索策略。"""

    def __init__(self, threshold: float = None):
        self._threshold = threshold or settings.rag_secondary_score_threshold

    def should_retry(self, results: List[Dict]) -> bool:
        """检查所有得分是否都低于置信度阈值。"""
        if not settings.rag_secondary_enabled:
            return False
        if not results:
            return True
        max_score = max(r.get("hybrid_score", 0) for r in results)
        should = max_score < self._threshold
        if should:
            logger.info(f"Low confidence: max_hybrid_score={max_score:.4f} < threshold={self._threshold}")
        return should

    async def retrieve(self, original_query: str,
                       rewritten_queries: List[str],
                       doc_id: Optional[int],
                       top_k: int,
                       strategy: SecondaryStrategy = None) -> List[Dict]:
        """使用选定策略执行二次检索。"""
        if strategy is None:
            try:
                strategy = SecondaryStrategy(settings.rag_secondary_strategy)
            except ValueError:
                strategy = SecondaryStrategy.QUERY_EXPANSION

        logger.info(f"Secondary retrieval triggered: strategy={strategy.value}, "
                    f"queries={len(rewritten_queries)}")
        try:
            if strategy == SecondaryStrategy.QUERY_EXPANSION:
                return await self._query_expansion(rewritten_queries, doc_id, top_k)
            elif strategy == SecondaryStrategy.DROP_FILTER:
                return await self._drop_filter(original_query, doc_id, top_k)
            elif strategy == SecondaryStrategy.MMR_DIVERSITY:
                return await self._mmr_diversity(original_query, doc_id, top_k)
        except Exception as e:
            logger.warning(f"Secondary retrieval failed: {e}")
        return []

    # ── 策略实现 ─────────────────────────────────────────

    async def _query_expansion(self, queries: List[str],
                                doc_id: Optional[int], top_k: int) -> List[Dict]:
        """使用所有查询变体分别检索，通过加权 RRF 合并结果。"""
        from app.rag.hybrid_retriever import hybrid_retriever

        query_results = []
        for q in queries[:4]:  # 最多使用 4 个变体
            results = await hybrid_retriever.search(
                q, doc_id=doc_id, top_k=top_k
            )
            query_results.append(results)

        # 按 clause_index 合并，分数按查询重要度衰减加权
        merged: Dict[int, dict] = {}
        for q_idx, results in enumerate(query_results):
            # queries[0] 始终为原始查询
            for rank, r in enumerate(results):
                idx = r["clause_index"]
                rrf = 1.0 / (settings.rag_rrf_k + rank + 1) * (0.8 ** q_idx)
                if idx in merged:
                    merged[idx]["score"] += rrf
                else:
                    merged[idx] = {"clause": r, "score": rrf}

        sorted_clauses = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        return [
            {
                "clause_index": e["clause"]["clause_index"],
                "text": e["clause"].get("text", ""),
                "hybrid_score": round(e["score"], 4),
                "source": "secondary_query_expansion",
            }
            for e in sorted_clauses[:top_k]
        ]

    async def _drop_filter(self, query: str, doc_id: Optional[int], top_k: int) -> List[Dict]:
        """放宽检索策略，同时保留当前文档范围，避免跨租户泄露。"""
        from app.rag.hybrid_retriever import hybrid_retriever
        results = await hybrid_retriever.search(
            query, doc_id=doc_id, top_k=top_k
        )
        for r in results:
            r["source"] = "secondary_drop_filter"
        return results

    async def _mmr_diversity(self, query: str, doc_id: Optional[int],
                              top_k: int) -> List[Dict]:
        """MMR：平衡查询相关性与已选结果的差异性。"""
        from app.embeddings.vector_store import vector_store
        from app.embeddings.embedding_service import embedding_service

        # 获取更大候选池
        candidates = await vector_store.similarity_search(
            query, doc_id=doc_id, k=top_k * 3
        )
        if not candidates:
            return []

        query_emb = await embedding_service.embed_query(query)

        selected = []
        remaining = list(range(len(candidates)))

        # 计算查询与候选条款的余弦相似度
        import math
        def cos_sim(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(y * y for y in b))
            return dot / (na * nb) if na and nb else 0

        query_sims = []
        for c in candidates:
            c_emb = await embedding_service.embed_query(c.get("text", ""))
            query_sims.append(cos_sim(query_emb, c_emb))

        lambda_param = 0.7  # 相关性与多样性的权衡系数

        while len(selected) < top_k and remaining:
            best_idx = None
            best_score = -float("inf")

            for i in remaining:
                relevance = query_sims[i]
                diversity = 0
                for j in selected:
                    c_emb = await embedding_service.embed_query(
                        candidates[i].get("text", "")
                    )
                    s_emb = await embedding_service.embed_query(
                        candidates[j].get("text", "")
                    )
                    sim = cos_sim(c_emb, s_emb)
                    diversity = max(diversity, sim)
                mmr_score = lambda_param * relevance - (1 - lambda_param) * diversity
                if mmr_score > best_score:
                    best_score = mmr_score
                    best_idx = i

            if best_idx is None:
                break
            selected.append(best_idx)
            remaining.remove(best_idx)

        results = []
        for i in selected:
            results.append({
                "clause_index": candidates[i].get("clause_index", i),
                "text": candidates[i].get("text", ""),
                "hybrid_score": round(float(query_sims[i]), 4),
                "source": "secondary_mmr",
            })
        return results


secondary_retriever = SecondaryRetriever()

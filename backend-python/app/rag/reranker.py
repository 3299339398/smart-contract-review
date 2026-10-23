"""检索后重排序器 —— 提升 Top-K 结果精度。

两种策略：
  - cross_encoder: Local BGE-reranker model (BAAI/bge-reranker-base)
    No API cost, ~300MB download cached by sentence-transformers.
  - llm: DeepSeek batch scoring on 1-10 scale, cached per query+text pair.

The cross-encoder is the recommended default. It typically delivers
15-30% improvement in top-3 precision — the highest single-ROI
optimization in RAG pipelines.
"""

import logging
from enum import Enum
from typing import List, Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class RerankStrategy(Enum):
    CROSS_ENCODER = "cross_encoder"
    LLM = "llm"
    NONE = "none"


class Reranker:
    """按语义相关性对检索到的候选条款进行重排序。"""

    def __init__(self, strategy: Optional[RerankStrategy] = None):
        self._cross_encoder = None
        if strategy is None:
            try:
                self._strategy = RerankStrategy(settings.rag_rerank_strategy)
            except ValueError:
                self._strategy = RerankStrategy.CROSS_ENCODER
        else:
            self._strategy = strategy

    async def rerank(self, query: str, candidates: List[Dict],
                     top_k: int = 5) -> List[Dict]:
        """对候选条款重排序，返回 top_k 并附加 'rerank_score' 字段。

        Args:
            query: 用户原始问题
            candidates: 混合检索召回的条款列表
            top_k: 重排序后返回的结果数量
        """
        if not candidates or self._strategy == RerankStrategy.NONE:
            return candidates[:top_k]

        if not settings.rag_rerank_enabled:
            return candidates[:top_k]

        pool = candidates[:settings.rag_rerank_candidate_pool_size]

        if self._strategy == RerankStrategy.CROSS_ENCODER:
            return self._rerank_cross_encoder(query, pool, top_k)
        elif self._strategy == RerankStrategy.LLM:
            return await self._rerank_llm(query, pool, top_k)
        else:
            return pool[:top_k]

    # ── Cross-Encoder 重排序 ────────────────────────────────────────────────────

    def _get_cross_encoder(self):
        """延迟加载 cross-encoder 模型。"""
        if self._cross_encoder is None:
            from sentence_transformers import CrossEncoder
            model_name = "BAAI/bge-reranker-base"
            logger.info(f"Loading cross-encoder: {model_name}")
            self._cross_encoder = CrossEncoder(model_name, max_length=512)
        return self._cross_encoder

    def _rerank_cross_encoder(self, query: str, candidates: List[Dict],
                              top_k: int) -> List[Dict]:
        """使用 cross-encoder 对每个 (query, clause_text) 对打分。"""
        try:
            model = self._get_cross_encoder()
            pairs = [(query, c.get("text", "")[:512]) for c in candidates]
            scores = model.predict(pairs, show_progress_bar=False)
            for c, s in zip(candidates, scores):
                c["rerank_score"] = round(max(0.0, float(s)), 4)
            candidates.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
            return candidates[:top_k]
        except Exception as e:
            logger.warning(f"Cross-encoder rerank failed, returning original order: {e}")
            return candidates[:top_k]

    # ── LLM 重排序 ────────────────────────────────────────────────────────

    async def _rerank_llm(self, query: str, candidates: List[Dict],
                          top_k: int) -> List[Dict]:
        """使用 LLM 按 1-10 分制为每个候选打分，按对缓存。"""
        from app.cache import cache_manager
        import hashlib

        scored = []
        for c in candidates:
            text = c.get("text", "")[:300]
            cache_key = "rr:" + hashlib.sha256(
                f"{query}|{text}".encode()
            ).hexdigest()[:32]

            cached = cache_manager.get(cache_key)
            if cached is not None:
                try:
                    c["rerank_score"] = float(cached)
                    scored.append(c)
                    continue
                except ValueError:
                    pass

            try:
                from app.llm.client import llm_client
                prompt = (
                    f"查询：{query}\n文档片段：{text}\n\n"
                    "请评估这个文档片段与查询的相关性，打分1-10（10=完全相关）。只输出数字。"
                )
                raw = await llm_client.chat(
                    "你是一个搜索相关性评估专家。只输出1-10的数字。",
                    prompt, max_tokens=8
                )
                score = float(raw.strip()) / 10.0
                score = round(max(0.0, min(1.0, score)), 4)
                cache_manager.set(cache_key, str(score), ttl=3600)
                c["rerank_score"] = score
            except Exception as e:
                logger.warning(f"LLM rerank pair failed: {e}")
                c["rerank_score"] = c.get("hybrid_score", 0.5)
            scored.append(c)

        scored.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        return scored[:top_k]


reranker = Reranker()

"""问题路由器 —— RAG 检索策略选择。

将用户问题分类为 5 种类型并调整混合搜索通道权重：
  - EXACT_LOOKUP: "第几条" → BM25-heavy (keyword matching)
  - SEMANTIC: "公平吗/是否合规" → vector-heavy (semantic understanding)
  - KEYWORD: "列出所有/有哪些" → BM25-dominant (exhaustive keyword match)
  - COMPARISON: "有何不同/对比" → balanced (both channels broad)
  - CONCEPTUAL: fallback → vector-biased (default behavior)

Regex rules are zero-cost and cover ~80% of real queries. LLM classification
is gated by config for the remaining ambiguous cases.
"""

import logging
import re
from enum import Enum
from typing import Tuple, Optional
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)


class QuestionType(str, Enum):
    EXACT_LOOKUP = "exact_lookup"
    SEMANTIC = "semantic"
    KEYWORD = "keyword"
    CONCEPTUAL = "conceptual"
    COMPARISON = "comparison"


@dataclass
class RouteResult:
    question_type: QuestionType
    vector_weight: float
    bm25_weight: float
    top_k_multiplier: float
    reasoning: str


class QuestionRouter:
    """基于正则的问题分类器，可选 LLM 兜底。"""

    def __init__(self):
        self._patterns: dict[QuestionType, list[str]] = {
            QuestionType.EXACT_LOOKUP: [
                r"第[一二三四五六七八九十百千\d]+条",
                r"条款.*编号", r"哪[一\w]*条", r"哪个条款", r"第几",
                r"第.*款", r"具体.*条款", r"原文.*是什么",
            ],
            QuestionType.SEMANTIC: [
                r"公平", r"合理", r"是否", r"合法", r"合规",
                r"风险", r"有问题", r"不利", r"偏向", r"失衡",
                r"单方", r"不.*合理", r"过[分于].*",
                r"安全", r"保障", r"保护",
            ],
            QuestionType.KEYWORD: [
                r"找出所有", r"列出", r"有哪些", r"包含",
                r"涉及.*的条款", r"关于.*的规定", r"所有.*条款",
                r"哪些条款", r"查找.*条款", r"搜索",
            ],
            QuestionType.COMPARISON: [
                r"区别", r"不同", r"对比", r"比较", r"vs",
                r"和.*有什么.*异同", r"哪[一\w]*.*更",
                r"差异", r"相较于",
            ],
        }

    def route(self, question: str) -> RouteResult:
        """分类问题并返回含通道权重的路由决策。"""
        if not settings.rag_question_routing_enabled:
            return RouteResult(
                question_type=QuestionType.CONCEPTUAL,
                vector_weight=settings.rag_default_vector_weight,
                bm25_weight=settings.rag_default_bm25_weight,
                top_k_multiplier=1.0,
                reasoning="routing disabled"
            )

        # 尝试正则分类（快速路径）
        qtype, reason = self._classify_regex(question)
        weights = self._get_weights(qtype)

        logger.debug(f"Question routed: type={qtype.value}, vw={weights[0]}, bw={weights[1]}, reason={reason}")

        return RouteResult(
            question_type=qtype,
            vector_weight=weights[0],
            bm25_weight=weights[1],
            top_k_multiplier=self._get_multiplier(qtype),
            reasoning=reason,
        )

    async def route_with_llm(self, question: str) -> RouteResult:
        """正则优先分类，模糊场景启用 LLM，结果已缓存。"""
        base = self.route(question)

        # 仅当正则分类为 CONCEPTUAL 时才调用 LLM
        if base.question_type != QuestionType.CONCEPTUAL or not settings.rag_question_routing_llm:
            return base

        from app.cache import cache_manager
        import hashlib
        cache_key = "route:" + hashlib.sha256(question.encode()).hexdigest()[:32]
        cached = cache_manager.get(cache_key)
        if cached is not None:
            qtype = QuestionType(cached)
            weights = self._get_weights(qtype)
            return RouteResult(
                question_type=qtype,
                vector_weight=weights[0], bm25_weight=weights[1],
                top_k_multiplier=self._get_multiplier(qtype),
                reasoning=f"llm_classified: {cached}"
            )

        try:
            from app.llm.client import llm_client
            types_desc = "\n".join(
                f"- {t.value}: {self._describe_type(t)}" for t in QuestionType
            )
            prompt = (
                f"将以下用户问题分类为以下类型之一，只输出类型名：\n\n{types_desc}\n\n"
                f"用户问题：{question}\n\n类型："
            )
            raw = await llm_client.chat(
                "你是一个查询分类专家。只输出类型名，不要解释。",
                prompt, max_tokens=32
            )
            raw = raw.strip().lower()
            try:
                qtype = QuestionType(raw)
            except ValueError:
                qtype = QuestionType.CONCEPTUAL

            cache_manager.set(cache_key, qtype.value, ttl=3600)
            weights = self._get_weights(qtype)
            return RouteResult(
                question_type=qtype,
                vector_weight=weights[0], bm25_weight=weights[1],
                top_k_multiplier=self._get_multiplier(qtype),
                reasoning=f"llm_classified: {qtype.value}"
            )
        except Exception as e:
            logger.warning(f"LLM question routing failed: {e}")
            return base

    # ── 内部方法 ─────────────────────────────────────────────────────────

    def _classify_regex(self, question: str) -> Tuple[QuestionType, str]:
        """尝试正则分类，匹配失败则回退到 CONCEPTUAL。"""
        for qtype, patterns in self._patterns.items():
            for pat in patterns:
                if re.search(pat, question):
                    return qtype, f"regex_match: {pat}"
        return QuestionType.CONCEPTUAL, "no_match"

    @staticmethod
    def _get_weights(qtype: QuestionType) -> Tuple[float, float]:
        """将问题类型映射为 (vector_weight, bm25_weight)。"""
        weights = {
            QuestionType.EXACT_LOOKUP: (0.3, 0.7),
            QuestionType.SEMANTIC: (0.85, 0.15),
            QuestionType.KEYWORD: (0.2, 0.8),
            QuestionType.CONCEPTUAL: (0.7, 0.3),
            QuestionType.COMPARISON: (0.5, 0.5),
        }
        return weights.get(qtype, (0.7, 0.3))

    @staticmethod
    def _get_multiplier(qtype: QuestionType) -> float:
        """获取该问题类型的候选池大小倍增系数。"""
        multipliers = {
            QuestionType.COMPARISON: 1.5,
            QuestionType.KEYWORD: 1.2,
        }
        return multipliers.get(qtype, 1.0)

    @staticmethod
    def _describe_type(qtype: QuestionType) -> str:
        descriptions = {
            QuestionType.EXACT_LOOKUP: "精确查找某一条款，如'第5条是什么'",
            QuestionType.SEMANTIC: "语义判断，如'这个条款公平吗'",
            QuestionType.KEYWORD: "关键词搜索，如'列出所有保密条款'",
            QuestionType.CONCEPTUAL: "概念性问题，如'什么是竞业限制'",
            QuestionType.COMPARISON: "对比分析，如'条款A和B有何不同'",
        }
        return descriptions.get(qtype, "通用问题")


question_router = QuestionRouter()

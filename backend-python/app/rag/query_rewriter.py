"""Query 改写器 —— 优化 RAG 检索查询。

将口语化的用户问题转换为更适合检索的变体：
  - Static legal terminology expansion (zero-cost, covers ~70% of queries)
  - LLM-based one-shot rewriting (cached, gated by config)
  - Compound question decomposition on Chinese conjunctions
"""

import logging
import re
from enum import Enum
from typing import List, Dict
import jieba

from app.config import settings

logger = logging.getLogger(__name__)


class QueryRewriteStrategy(Enum):
    EXPAND = "expand"
    DECOMPOSE = "decompose"
    NONE = "none"


class QueryRewriter:
    """生成 1-N 个面向检索优化的查询变体。"""

    def __init__(self):
        self._term_map: Dict[str, List[str]] = {
            "违约金": ["违约责任", "损害赔偿", "罚金", "逾期违约责任"],
            "保密": ["保密义务", "商业秘密", "机密信息", "保密条款"],
            "解约": ["解除合同", "终止协议", "合同终止"],
            "仲裁": ["争议解决", "仲裁条款", "仲裁机构"],
            "不可抗力": ["免责事由", "例外情况", "不可抗力条款"],
            "竞业": ["竞业限制", "竞业禁止", "非竞争义务"],
            "赔偿": ["损害赔偿", "补偿", "赔偿责任", "损失赔偿"],
            "知识产权": ["著作权", "专利权", "商标权", "商业秘密"],
            "付款": ["支付", "价款", "报酬", "费用结算"],
            "续约": ["续签", "合同延期", "自动续期", "合同期限"],
            "终止": ["解除", "到期", "终止条件", "合同解除"],
            "管辖": ["争议管辖", "法院管辖", "仲裁管辖", "诉讼管辖"],
            "责任": ["法律责任", "违约责任", "赔偿责任", "责任限制"],
            "修改": ["变更", "补充协议", "合同变更", "条款修订"],
        }
        self._compound_markers = re.compile(r"[并且；;，而且同时以及]+")

    def rewrite(self, question: str, strategy: QueryRewriteStrategy = None) -> List[str]:
        """生成查询变体列表。原始问题始终作为第一个变体返回。"""
        if strategy is None:
            strategy = QueryRewriteStrategy.EXPAND

        if not settings.rag_query_rewrite_enabled:
            return [question]

        variants = [question]

        if strategy == QueryRewriteStrategy.EXPAND:
            expanded = self._expand_legal_terms(question)
            if expanded != question:
                variants.append(expanded)
        elif strategy == QueryRewriteStrategy.DECOMPOSE:
            subs = self._decompose(question)
            if len(subs) > 1:
                variants.extend(subs)

        # 截断至最大变体数
        variants = variants[:settings.rag_query_rewrite_max_variants]
        return variants

    async def rewrite_with_llm(self, question: str) -> List[str]:
        """基于 LLM 的查询扩展，适用于模糊或短查询，结果已缓存。"""
        if not settings.rag_query_rewrite_llm:
            return self.rewrite(question, QueryRewriteStrategy.EXPAND)

        from app.cache import cache_manager
        import hashlib
        cache_key = "rewrite:" + hashlib.sha256(question.encode()).hexdigest()[:32]
        cached = cache_manager.get(cache_key)
        if cached is not None:
            return cached.split("\x00")

        try:
            from app.llm.client import llm_client
            prompt = (
                "将以下用户问题改写为1-3个更适合法律文档检索的查询。"
                "添加相关法律术语，但保持原意。只输出改写后的查询，每行一个，不要编号。\n\n"
                f"用户问题：{question}"
            )
            raw = await llm_client.chat(
                "你是一个搜索查询优化专家，擅长将口语化问题改写为精准的检索查询。",
                prompt, max_tokens=256
            )
            variants = [question]
            for line in raw.strip().split("\n"):
                line = line.strip()
                if line and line != question and len(line) > 3:
                    variants.append(line)
            result = variants[:settings.rag_query_rewrite_max_variants]
            cache_manager.set(cache_key, "\x00".join(result), ttl=3600)
            return result
        except Exception as e:
            logger.warning(f"LLM query rewrite failed: {e}")
            return self.rewrite(question, QueryRewriteStrategy.EXPAND)

    # ── 内部方法 ─────────────────────────────────────────────────────────

    def _expand_legal_terms(self, text: str) -> str:
        """为查询中匹配到的已知合同法术语追加同义词。"""
        tokens = set(t.strip() for t in jieba.lcut(text) if len(t.strip()) >= 2)
        expansions = []
        for token in tokens:
            if token in self._term_map:
                expansions.extend(self._term_map[token])
        if not expansions:
            return text
        unique = list(dict.fromkeys(expansions))[:5]
        return f"{text} {' '.join(unique)}"

    def _decompose(self, question: str) -> List[str]:
        """按中文连词标记拆分复合问题。"""
        parts = self._compound_markers.split(question)
        parts = [p.strip() for p in parts if len(p.strip()) > 4]
        return parts if len(parts) > 1 else [question]


query_rewriter = QueryRewriter()

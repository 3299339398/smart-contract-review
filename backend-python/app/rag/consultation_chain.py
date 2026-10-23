"""RAG 合同咨询 —— 7 步检索管线驱动的智能问答。

检索管线：
  1. Query Rewriting → expand legal terminology
  2. Question Routing → classify and adjust channel weights
  3. Multi-channel Recall → BM25 + vector via RRF fusion (enhanced)
  4. Rerank → cross-encoder re-scoring of top candidates
  5. Context Assembly → token-budget-aware prompt packing
  6. LLM Generation → answer with source citations
  7. Citation Verification → detect hallucinated clause references

Low-confidence secondary retrieval triggers when hybrid scores are all below threshold.
Results are cached via the layered cache manager.
"""

import hashlib
import logging
from typing import List, Tuple, Dict, Any, Optional

from app.llm.client import llm_client
from app.rag.hybrid_retriever import hybrid_retriever
from app.embeddings.vector_store import vector_store
from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位专业的合同法律顾问，精通中国合同法。根据检索到的相关合同条款，回答用户的问题。

要求：
1. 回答必须基于下方提供的合同条款，明确引用条款编号
2. 如果检索到的条款不足以回答问题，诚实说明并基于法律常识给出通用建议
3. 使用专业但易懂的中文
4. 回答长度适中，一般不超过300字
5. 引用条款时使用格式："根据第X条..." """


async def answer_question(
    question: str,
    clauses: List[Dict[str, Any]] = None,
    document_id: int = None,
    top_k: int = 5,
) -> Tuple[str, List[Dict], Optional[Dict[str, Any]]]:
    """RAG 管线：改写 → 路由 → 召回 → 重排序 → 组装 → 生成 → 校验。

    条款应已在上传时完成 ChromaDB 索引。
    若提供了条款，将用于 BM25 索引（如尚未缓存）。

    Returns:
        answer: LLM 生成的回答文本
        source_clauses: 检索并使用的条款及其分数
        pipeline_meta: 可选元数据字典（改写变体、路由、重排序、引用校验信息）
    """
    pipeline_meta = {
        "rewrite_variants": [],
        "route_type": None,
        "rerank_applied": False,
        "secondary_triggered": False,
        "citation_warnings": [],
    }

    # ── 缓存检查 ───────────────────────────────────────────────────
    cache_key = _make_rag_cache_key(question, document_id, top_k)
    from app.cache import cache_manager
    cached = cache_manager.get(cache_key)
    if cached is not None:
        logger.info(f"RAG cache hit for question: {question[:50]}...")
        parts = cached.split("\x00RAG_SEP\x00", 3)
        if len(parts) >= 3:
            answer = parts[0]
            sources = _parse_cached_sources(parts[1])
            meta = _parse_cached_meta(parts[2]) if len(parts) > 3 else {}
            return answer, sources, meta

    # ── 处理无条款情况 ──────────────────────────────────────────────
    if not clauses:
        stored = []
        if document_id:
            stored = await vector_store.similarity_search(
                "合同条款 法律责任 义务", doc_id=document_id, k=20
            )
        if not stored:
            answer, _ = await _answer_general(question)
            return answer, [], pipeline_meta
        clauses = stored

    # ── 确保 BM25 索引就绪 ──────────────────────────────────────────────
    doc_id = document_id or 0
    try:
        hybrid_retriever.index_clauses(doc_id, clauses)
    except Exception as e:
        logger.warning(f"BM25 indexing skipped: {e}")

    # ══════════════════════════════════════════════════════════════════
    # 步骤1：查询改写
    # ══════════════════════════════════════════════════════════════════
    from app.rag.query_rewriter import query_rewriter

    if settings.rag_query_rewrite_llm:
        query_variants = await query_rewriter.rewrite_with_llm(question)
    else:
        query_variants = query_rewriter.rewrite(question)

    pipeline_meta["rewrite_variants"] = query_variants
    primary_query = query_variants[0]

    # ══════════════════════════════════════════════════════════════════
    # 步骤2：问题路由
    # ══════════════════════════════════════════════════════════════════
    from app.rag.question_router import question_router

    if settings.rag_question_routing_llm:
        route_result = await question_router.route_with_llm(primary_query)
    else:
        route_result = question_router.route(primary_query)

    pipeline_meta["route_type"] = route_result.question_type.value

    # ══════════════════════════════════════════════════════════════════
    # 步骤3：多通道召回（含路由权重增强）
    # ══════════════════════════════════════════════════════════════════
    fetch_k = max(top_k * 3, int(settings.rag_rerank_candidate_pool_size))
    retrieved = await hybrid_retriever.search(
        primary_query,
        doc_id=doc_id,
        top_k=fetch_k,
        vector_weight=route_result.vector_weight,
        bm25_weight=route_result.bm25_weight,
    )

    # ══════════════════════════════════════════════════════════════════
    # 步骤7b：低置信度二次检索
    # ══════════════════════════════════════════════════════════════════
    from app.rag.secondary_retriever import secondary_retriever

    if secondary_retriever.should_retry(retrieved):
        logger.info("Triggering secondary retrieval due to low confidence")
        pipeline_meta["secondary_triggered"] = True
        secondary = await secondary_retriever.retrieve(
            original_query=question,
            rewritten_queries=query_variants[1:],
            doc_id=doc_id,
            top_k=fetch_k,
        )
        if secondary:
            # 合并：追加二次检索结果，按 clause_index 去重
            seen = {r["clause_index"] for r in retrieved}
            for r in secondary:
                if r["clause_index"] not in seen:
                    retrieved.append(r)
                    seen.add(r["clause_index"])

    # 兜底：仍无结果则使用原始条款
    if not retrieved:
        retrieved = [
            {"clause_index": c.get("index", i + 1), "text": c.get("text", ""),
             "hybrid_score": 0.1}
            for i, c in enumerate(clauses[:3])
        ]

    # ══════════════════════════════════════════════════════════════════
    # 步骤4：重排序
    # ══════════════════════════════════════════════════════════════════
    from app.rag.reranker import reranker

    if settings.rag_rerank_enabled and len(retrieved) > top_k:
        retrieved = await reranker.rerank(primary_query, retrieved, top_k=top_k)
        pipeline_meta["rerank_applied"] = True
    else:
        retrieved = retrieved[:top_k]

    # ══════════════════════════════════════════════════════════════════
    # 步骤5：上下文组装
    # ══════════════════════════════════════════════════════════════════
    from app.rag.context_assembler import context_assembler

    ctx = context_assembler.assemble(retrieved, question, SYSTEM_PROMPT)

    if not ctx.included_indices and not ctx.prompt_text.startswith("("):
        # 组装后上下文为空
        answer, _ = await _answer_general(question)
        return answer, [], pipeline_meta

    user_prompt = f"""以下是检索到的最相关合同条款：

{ctx.prompt_text}

用户问题：{question}

请基于上述合同条款回答用户问题。如果条款信息不足，请诚实说明并给出通用法律建议。"""

    # ══════════════════════════════════════════════════════════════════
    # 步骤6：LLM 生成
    # ══════════════════════════════════════════════════════════════════
    try:
        answer = await llm_client.chat(SYSTEM_PROMPT, user_prompt, max_tokens=1024)
    except Exception as e:
        logger.error(f"LLM consultation failed: {e}")
        return ("抱歉，AI 咨询服务暂时不可用，请稍后重试。", [], pipeline_meta)

    # ══════════════════════════════════════════════════════════════════
    # 步骤7：引用校验
    # ══════════════════════════════════════════════════════════════════
    from app.rag.citation_verifier import citation_verifier

    if settings.rag_citation_verify_enabled:
        cit_result = citation_verifier.verify(answer, retrieved)
        if cit_result.hallucinated:
            pipeline_meta["citation_warnings"] = [
                f"引用编号 {idx} 未在检索结果中找到" for idx in cit_result.hallucinated
            ]
            answer = f"{answer}\n\n{cit_result.warning_message}"

    # ── 构建引用来源 ─────────────────────────────────────────
    source_clauses = [
        {
            "clause_index": r["clause_index"],
            "text": r["text"][:300],
            "hybrid_score": r.get("hybrid_score", 0),
            "rerank_score": r.get("rerank_score"),
        }
        for r in retrieved
    ]

    # ── 缓存结果 ───────────────────────────────────────────────────
    import json
    sources_json = json.dumps(source_clauses, ensure_ascii=False)
    meta_json = json.dumps(pipeline_meta, ensure_ascii=False)
    cache_value = f"{answer}\x00RAG_SEP\x00{sources_json}\x00RAG_SEP\x00{len(retrieved)}\x00RAG_SEP\x00{meta_json}"
    cache_manager.set(cache_key, cache_value, settings.rag_cache_ttl)

    logger.info(
        f"RAG complete: retrieved={len(retrieved)}, route={route_result.question_type.value}, "
        f"rerank={pipeline_meta['rerank_applied']}, secondary={pipeline_meta['secondary_triggered']}, "
        f"answer_len={len(answer)}, citations={[s['clause_index'] for s in source_clauses]}"
    )

    return answer, source_clauses, pipeline_meta


async def _answer_general(question: str) -> Tuple[str, List[Dict]]:
    """无合同文档上下文时，基于法律常识回答通用合同法问题。"""
    user_prompt = f"""用户提出了一个关于合同的问题，但没有提供具体的合同条款：

{question}

请基于你的合同法和商业法律知识，给出专业、实用的回答。
要求：
1. 使用专业但易懂的中文
2. 回答长度适中，一般不超过300字
3. 如果问题涉及需要具体合同条款才能准确判断的内容，请说明并建议用户上传合同文档"""

    try:
        answer = await llm_client.chat(SYSTEM_PROMPT, user_prompt, max_tokens=1024)
    except Exception as e:
        logger.error(f"LLM general consultation failed: {e}")
        return ("抱歉，AI 咨询服务暂时不可用，请稍后重试。", [])

    return answer, []


def _make_rag_cache_key(question: str, doc_id, top_k: int) -> str:
    key = f"rag:{doc_id}:{top_k}:{question.strip().lower()}"
    return hashlib.sha256(key.encode()).hexdigest()[:48]


def _parse_cached_sources(sources_json: str) -> list:
    import json
    try:
        return json.loads(sources_json)
    except json.JSONDecodeError:
        return []


def _parse_cached_meta(meta_json: str) -> dict:
    import json
    try:
        return json.loads(meta_json)
    except json.JSONDecodeError:
        return {}

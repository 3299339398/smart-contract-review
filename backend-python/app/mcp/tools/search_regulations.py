"""MCP 工具：search_legal_regulations —— 法规语义检索。

使用 Embedding 语义搜索匹配相关法规条文，返回 Pydantic 模型以保证类型安全及自动 Schema 生成。
"""

import json
import logging
from pathlib import Path
from app.embeddings.embedding_service import embedding_service
from app.schemas.mcp import RegulationEntry, RegulationSearchResult
from app.core.tool_registry import register_tool

logger = logging.getLogger(__name__)

_regulations_cache: list[dict] | None = None


def _load_all_regulations() -> list[dict]:
    global _regulations_cache
    if _regulations_cache is not None:
        return _regulations_cache

    entries = []
    data_dir = Path(__file__).parent.parent.parent.parent / "data" / "regulations"
    if data_dir.exists():
        for f in data_dir.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as file:
                    data = json.load(file)
                    for risk_type, items in data.items():
                        for item in items:
                            item["_risk_type"] = risk_type
                            entries.append(item)
            except Exception as e:
                logger.warning(f"Failed to load {f}: {e}")

    if not entries:
        builtin = {
            "LIABILITY_UNLIMITED": [{"name": "民法典", "article": "第584条", "text": "损失赔偿额应当相当于因违约所造成的损失，但不得超过违约方订立合同时预见到或者应当预见到的因违约可能造成的损失。"}],
            "EXCESSIVE_LIQUIDATED_DAMAGES": [{"name": "民法典", "article": "第585条", "text": "约定的违约金过分高于造成的损失的，当事人可以请求人民法院或者仲裁机构予以适当减少。"}],
            "NON_COMPETE_OVERBROAD": [{"name": "劳动合同法", "article": "第24条", "text": "竞业限制期限不得超过二年。"}],
            "IP_OWNERSHIP_UNCLEAR": [{"name": "著作权法", "article": "第27条", "text": "委托创作的作品，著作权的归属由委托人和受托人通过合同约定。"}],
            "ONE_SIDED_TERMINATION": [{"name": "民法典", "article": "第563条", "text": "因不可抗力致使不能实现合同目的、一方根本违约等情形下当事人可以解除合同。"}],
            "DATA_PRIVACY_VIOLATION": [{"name": "个人信息保护法", "article": "第13条", "text": "处理个人信息应当取得个人同意。"}],
        }
        for risk_type, items in builtin.items():
            for item in items:
                item["_risk_type"] = risk_type
                entries.append(item)

    _regulations_cache = entries
    logger.info(f"Loaded {len(entries)} regulation entries")
    return entries


def _keyword_filter(query: str, entries: list[dict], limit: int = 20) -> list[dict]:
    keywords = query.lower().split()
    scored = []
    for e in entries:
        text = e.get("text", "")
        score = sum(1 for kw in keywords if kw in text.lower())
        if score > 0:
            scored.append((score, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:limit]]


@register_tool("search_legal_regulations", description="Semantic search for Chinese legal regulations")
async def handler(query: str, risk_type: str = None, jurisdiction: str = "CN") -> RegulationSearchResult:
    """语义检索法规条文，返回 Pydantic 模型。"""
    entries = _load_all_regulations()

    # 按风险类型直接匹配
    if risk_type and risk_type in {e.get("_risk_type", "") for e in entries}:
        candidates = [e for e in entries if e.get("_risk_type") == risk_type]
        result_entries = [
            RegulationEntry(name=e["name"], article=e["article"], text=e["text"], relevance_score=0.9)
            for e in candidates
        ]
        return RegulationSearchResult(
            results=result_entries, total=len(result_entries), search_method="direct_match"
        )

    # 关键词预筛选 → 语义排序
    candidates = _keyword_filter(query, entries, limit=15)
    if not candidates:
        candidates = entries[:10]

    if len(candidates) <= 1:
        result_entries = [
            RegulationEntry(name=e["name"], article=e["article"], text=e["text"], relevance_score=0.8)
            for e in candidates
        ]
        return RegulationSearchResult(
            results=result_entries, total=len(result_entries), search_method="keyword"
        )

    # 语义相似度排序
    try:
        query_emb = await embedding_service.embed_query(query)
        candidate_texts = [f"{e['name']} {e['article']}: {e['text'][:200]}" for e in candidates]
        candidate_embs = await embedding_service.embed_texts(candidate_texts)

        scored = []
        for i, emb in enumerate(candidate_embs):
            dot = sum(a * b for a, b in zip(query_emb, emb))
            scored.append((dot, candidates[i]))
        scored.sort(key=lambda x: x[0], reverse=True)

        result_entries = []
        for score, e in scored[:5]:
            normalized = round(max(0.0, min(1.0, (score + 1) / 2)), 4)
            result_entries.append(RegulationEntry(
                name=e["name"], article=e["article"], text=e["text"], relevance_score=normalized
            ))
    except Exception as ex:
        logger.error(f"Semantic search failed, falling back to keyword: {ex}")
        result_entries = [
            RegulationEntry(name=e["name"], article=e["article"], text=e["text"], relevance_score=0.5)
            for e in candidates[:5]
        ]

    return RegulationSearchResult(
        results=result_entries, total=len(result_entries),
        search_method="semantic_embedding", jurisdiction=jurisdiction
    )

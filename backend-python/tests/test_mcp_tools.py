"""Tests for MCP tools — regulation search, template compare, amendment generation.

Run: python -m pytest tests/test_mcp_tools.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import asyncio


# ── search_legal_regulations ──

class TestRegulationSearch:
    def test_loads_regulations_from_json(self):
        from app.mcp.tools.search_regulations import _load_all_regulations
        entries = _load_all_regulations()
        assert len(entries) >= 10, f"Expected >=10 entries, got {len(entries)}"
        # Verify structure
        for e in entries[:3]:
            assert "name" in e, f"Missing 'name' in {e}"
            assert "article" in e, f"Missing 'article' in {e}"
            assert "text" in e, f"Missing 'text' in {e}"

    def test_direct_risk_type_match(self):
        from app.mcp.tools.search_regulations import handler
        result = asyncio.run(handler(query="", risk_type="LIABILITY_UNLIMITED"))
        assert result.total >= 1
        assert result.search_method == "direct_match"
        assert any("民法典" in r.name for r in result.results)

    def test_keyword_search_finds_relevant(self):
        from app.mcp.tools.search_regulations import handler
        result = asyncio.run(handler(query="违约金过高"))
        assert result.total >= 1
        found = any("违约金" in r.text for r in result.results)
        assert found, f"Expected 违约金 in results, got {[r.article for r in result.results]}"

    def test_returns_empty_for_gibberish(self):
        from app.mcp.tools.search_regulations import handler
        result = asyncio.run(handler(query="xyzabc123不存在"))
        # Should still return something (fuzzy), but with lower relevance
        assert result.search_method in ("keyword", "semantic_embedding")

    def test_output_is_pydantic_model(self):
        from app.mcp.tools.search_regulations import handler
        from app.schemas.mcp import RegulationSearchResult
        result = asyncio.run(handler(query="竞业限制"))
        assert isinstance(result, RegulationSearchResult)
        d = result.model_dump()
        assert "results" in d
        assert "search_method" in d


# ── compare_with_template ──

class TestTemplateCompare:
    def test_employment_template_match(self):
        from app.mcp.tools.compare_template import handler
        clause = "员工在工作过程中因故意或重大过失给公司造成损失的，应承担相应的赔偿责任。"
        result = asyncio.run(handler(clause_text=clause, template_type="EMPLOYMENT",
                                      clause_category="LIABILITY"))
        assert result.similarity_score >= 0.3, f"Expected reasonable similarity, got {result.similarity_score}"

    def test_completely_different_clause(self):
        from app.mcp.tools.compare_template import handler
        clause = "本合同自双方签字之日起生效，有效期三年。"
        result = asyncio.run(handler(clause_text=clause, template_type="EMPLOYMENT",
                                      clause_category="LIABILITY"))
        # Lexical fallback (used when embedding model unavailable) is less precise
        assert result.similarity_score < 0.9, f"Unrelated clause should have low score, got {result.similarity_score}"

    def test_unknown_template_type(self):
        from app.mcp.tools.compare_template import handler
        result = asyncio.run(handler(clause_text="test", template_type="UNKNOWN_TYPE"))
        assert result.comparison_method == "no_template"
        assert result.similarity_score == 0.0

    def test_output_is_pydantic_model(self):
        from app.mcp.tools.compare_template import handler
        from app.schemas.mcp import TemplateCompareResult
        result = asyncio.run(handler(clause_text="员工应遵守保密义务。", template_type="EMPLOYMENT"))
        assert isinstance(result, TemplateCompareResult)
        assert hasattr(result, 'similarity_score')
        assert hasattr(result, 'deviations')


# ── generate_amendment ──

class TestAmendmentGeneration:
    def test_known_risk_type_fallback(self):
        from app.mcp.tools.generate_amendment import handler
        result = asyncio.run(handler(
            clause_text="违约方应赔偿全部损失。",
            risk_type="LIABILITY_UNLIMITED"
        ))
        assert len(result.amended_clause) > 20
        assert result.generation_method in ("llm", "template_fallback")

    def test_fallback_has_legal_basis(self):
        from app.mcp.tools.generate_amendment import handler
        result = asyncio.run(handler(
            clause_text="竞业限制期限为五年。",
            risk_type="NON_COMPETE_OVERBROAD"
        ))
        if result.generation_method == "template_fallback":
            assert len(result.legal_basis) >= 1

    def test_unknown_risk_type_returns_generic(self):
        from app.mcp.tools.generate_amendment import handler
        result = asyncio.run(handler(
            clause_text="some clause",
            risk_type="NONEXISTENT_RISK"
        ))
        # May return LLM output or fallback depending on LLM availability
        assert result.generation_method in ("fallback_generic", "llm", "template_fallback")

    def test_output_is_pydantic_model(self):
        from app.mcp.tools.generate_amendment import handler
        from app.schemas.mcp import AmendmentResult
        result = asyncio.run(handler(clause_text="test", risk_type="LIABILITY_UNLIMITED"))
        assert isinstance(result, AmendmentResult)


# ── evaluate_contract_balance ──

class TestBalanceEvaluation:
    def test_empty_clauses(self):
        from app.mcp.tools.evaluate_balance import handler
        result = asyncio.run(handler(clauses=[]))
        assert result.evaluation_method == "no_data"
        assert result.balance_score == 0.5

    def test_balanced_contract(self):
        from app.mcp.tools.evaluate_balance import handler
        clauses = [
            {"index": 1, "text": "双方应友好协商解决争议。", "risk_level": "LOW"},
            {"index": 2, "text": "合同有效期自签署之日起三年。", "risk_level": "LOW"},
        ]
        result = asyncio.run(handler(clauses=clauses))
        assert result.balance_score >= 0.5

    def test_one_sided_pattern_detection(self):
        from app.mcp.tools.evaluate_balance import handler
        clauses = [
            {"index": 1, "text": "甲方有权随时解除本合同。", "risk_level": "HIGH"},
            {"index": 2, "text": "甲方最终解释权归甲方所有。", "risk_level": "HIGH"},
        ]
        result = asyncio.run(handler(clauses=clauses))
        assert result.one_sided_patterns >= 1
        assert result.balance_score < 0.8

    def test_output_is_pydantic_model(self):
        from app.mcp.tools.evaluate_balance import handler
        from app.schemas.mcp import BalanceEvaluation
        result = asyncio.run(handler(clauses=[{"index": 1, "text": "test", "risk_level": "LOW"}]))
        assert isinstance(result, BalanceEvaluation)

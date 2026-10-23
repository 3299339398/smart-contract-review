"""MCP 工具：evaluate_contract_balance —— 合同公平性评估。

启发式模式扫描 + LLM 深度分析，返回 Pydantic BalanceEvaluation。
"""

import json
import logging
from app.schemas.mcp import OneSidedClause, BalanceEvaluation
from app.core.tool_registry import register_tool

logger = logging.getLogger(__name__)

BALANCE_SYSTEM_PROMPT = """你是一位合同审查专家，擅长识别合同中双方权利义务的平衡性。

从以下维度评估合同公平性：
1. 权利义务对等性：双方的义务、责任、赔偿条款是否对称
2. 风险分配合理性：主要风险（违约、终止、不可抗力）如何分配
3. 争议解决公平性：管辖、仲裁条款是否给了一方过分优势
4. 单方权利识别：是否存在仅一方可行使的终止权、解释权、修改权

按JSON格式输出：
{
  "balance_score": 0.0-1.0, 1.0=完全公平,
  "party_a_advantages": ["甲方优势1"],
  "party_b_disadvantages": ["乙方劣势1"],
  "one_sided_clauses": [{"clause_index": 1, "description": "描述", "severity": "HIGH"}],
  "recommendations": ["改进建议1"],
  "overall_assessment": "综合评价200字以内"
}"""

ONE_SIDED_INDICATORS = [
    ("甲方有权随时", "单方任意解除权"),
    ("甲方最终解释权", "格式条款解释权垄断"),
    ("不得向", "单方限制对方权利"),
    ("乙方不得追究", "豁免条款"),
    ("概不负责", "完全免责声明"),
    ("甲方不承担任何", "责任豁免"),
    ("甲方可自行决定", "单方裁量权"),
    ("甲方单方", "单方权利条款"),
    ("视为乙方放弃", "默示弃权条款"),
]


@register_tool("evaluate_contract_balance", description="Evaluate overall contract fairness and balance between parties")
async def handler(clauses: list, contract_type: str = None,
                   favored_party: str = None) -> BalanceEvaluation:
    """评估合同公平性，返回 Pydantic 模型。"""
    if not clauses:
        return BalanceEvaluation(
            balance_score=0.5,
            recommendations=["合同条款为空，无法进行公平性评估。请先上传合同并完成条款提取。"],
            overall_assessment="无足够信息评估合同公平性",
            evaluation_method="no_data"
        )

    # 启发式扫描
    high_risk = [c for c in clauses if c.get("risk_level") == "HIGH"]
    medium_risk = [c for c in clauses if c.get("risk_level") == "MEDIUM"]

    pattern_matches = []
    for clause in clauses:
        text = clause.get("text", "")
        idx = clause.get("index", clause.get("clause_index", 0))
        for pattern, desc in ONE_SIDED_INDICATORS:
            if pattern in text:
                pattern_matches.append(OneSidedClause(
                    clause_index=idx, pattern=pattern, description=desc,
                    severity="HIGH" if "有权" in pattern or "不承担" in pattern else "MEDIUM"
                ))

    total = len(clauses)
    penalty = (len(high_risk) * 0.15 + len(medium_risk) * 0.05 + len(pattern_matches) * 0.1)
    heuristic_score = round(max(0.1, 1.0 - penalty), 2)

    result = BalanceEvaluation(
        balance_score=heuristic_score,
        total_clauses=total,
        high_risk_clauses=len(high_risk),
        medium_risk_clauses=len(medium_risk),
        one_sided_patterns=len(pattern_matches),
        party_a_advantages=[m.description for m in pattern_matches[:5]],
        party_b_disadvantages=(
            [f"需接受{len(high_risk)}条高风险条款和{len(pattern_matches)}条单方条款"]
            if pattern_matches or high_risk else []
        ),
        one_sided_clauses=pattern_matches[:10],
        evaluation_method="heuristic",
        contract_type=contract_type
    )

    # 对可疑合同进行 LLM 深度分析
    if total >= 3 and (high_risk or len(pattern_matches) >= 2):
        try:
            from app.llm.client import llm_client
            clause_summary = "\n".join(
                f"条款{c.get('index', i+1)} [{c.get('risk_level', 'UNKNOWN')}]: {c.get('text', '')[:150]}"
                for i, c in enumerate(clauses[:10])
            )
            user_prompt = f"""合同类型：{contract_type or '通用合同'}
起草方：{favored_party or '未知'}

合同条款摘要：
{clause_summary}

请评估该合同的公平性并输出JSON。"""

            raw = await llm_client.chat_json(BALANCE_SYSTEM_PROMPT, user_prompt, max_tokens=2048)
            import re
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                parsed = json.loads(json_match.group())
                llm_clauses = [
                    OneSidedClause(
                        clause_index=c.get("clause_index", 0),
                        description=c.get("description", ""),
                        severity=c.get("severity", "MEDIUM")
                    )
                    for c in parsed.get("one_sided_clauses", [])
                ]
                return BalanceEvaluation(
                    balance_score=parsed.get("balance_score", heuristic_score),
                    total_clauses=total,
                    high_risk_clauses=len(high_risk),
                    medium_risk_clauses=len(medium_risk),
                    one_sided_patterns=len(pattern_matches),
                    party_a_advantages=parsed.get("party_a_advantages", []),
                    party_b_disadvantages=parsed.get("party_b_disadvantages", []),
                    one_sided_clauses=llm_clauses,
                    recommendations=parsed.get("recommendations", []),
                    overall_assessment=parsed.get("overall_assessment", ""),
                    evaluation_method="llm_deep_analysis",
                    heuristic_score=heuristic_score,
                    contract_type=contract_type
                )
        except Exception as e:
            logger.warning(f"LLM balance evaluation failed, using heuristic: {e}")

    result.recommendations = _generate_recommendations(high_risk, pattern_matches)
    result.overall_assessment = _summarize(heuristic_score, len(high_risk), len(pattern_matches))
    return result


def _generate_recommendations(high_risk: list, pattern_matches: list) -> list:
    recs = []
    if len(high_risk) > 3:
        recs.append("合同存在大量高风险条款，建议逐条审查并要求修改核心义务条款")
    if pattern_matches:
        recs.append("发现多处单方权利条款，建议增加双方对等权利，删除单方最终解释权等不公平条款")
    if not recs:
        recs.append("合同整体较为平衡，建议重点关注争议解决条款和违约责任条款的对等性")
    recs.append("建议在签署前由专业律师进行最终审查")
    return recs


def _summarize(score: float, high_count: int, pattern_count: int) -> str:
    if score >= 0.8:
        return f"合同整体较为公平（平衡度评分{score}），权利义务相对均衡。"
    elif score >= 0.5:
        return f"合同存在一定失衡（平衡度评分{score}），发现{high_count}条高风险条款和{pattern_count}处单方条款，建议谈判修改后再签署。"
    else:
        return f"合同严重失衡（平衡度评分{score}），存在{high_count}条高风险条款和{pattern_count}处单方有利条款。强烈建议重新谈判核心条款，或考虑拒绝签署。"

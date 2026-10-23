import logging
from app.agent.state import AgentState
from app.utils.json_utils import parse_json
from app.llm.client import llm_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位资深合同审查律师，负责撰写合同审查总结报告。

根据所有已识别的风险条款，生成：
1. 综合评分（0-100分，高风险-15分，中风险-5分，低风险-2分）
2. 总结摘要（100字以内，概述整体风险状况）
3. 建议事项列表（3-5条行动建议）"""

COT_STEPS = [
    "统计风险分布：清点高风险、中风险、低风险条款的数量和占比",
    "识别风险集中领域：分析风险集中在合同的哪些方面（违约责任、付款、保密等）",
    "评估整体风险水平：根据各等级风险数量和严重程度，综合判断合同整体风险",
    "计算综合评分：按高风险-15分、中风险-5分、低风险-2分的规则计算，确保分数在0-100之间",
    "排序行动建议：按优先级排序建议事项，高风险相关的建议排在前面",
]

OUTPUT_FORMAT = """【最终答案】段落必须是合法JSON：
{"overall_score": 85.0, "summary": "总结摘要（100字以内）", "recommendations": ["建议1", "建议2", ...]}"""


async def aggregate_report_node(state: AgentState) -> AgentState:
    """汇总报告节点（终点节点）：统计所有风险，生成综合评分、摘要和行动建议。"""
    all_risks = state.get("all_risks", [])
    total_clauses = state.get("total_clauses", 0)

    high_count = sum(1 for r in all_risks if r.get("risk_level") == "HIGH")
    medium_count = sum(1 for r in all_risks if r.get("risk_level") == "MEDIUM")
    low_count = sum(1 for r in all_risks if r.get("risk_level") == "LOW")

    risk_summary_lines = []
    for r in all_risks:
        risk_summary_lines.append(
            f"条款{r['clause_index']}: [{r.get('risk_level','?')}] {r.get('risk_type','?')} — {r.get('risk_description','')}"
        )
    risk_summary = "\n".join(risk_summary_lines)

    try:
        user_prompt = f"""合同共{total_clauses}条，发现高风险{high_count}条、中风险{medium_count}条、低风险{low_count}条。

各条款风险详情：
{risk_summary}

请生成综合评分、总结摘要和建议事项。"""
        reasoning, answer = await llm_client.chat_with_cot(
            SYSTEM_PROMPT, user_prompt, COT_STEPS, OUTPUT_FORMAT, max_tokens=4096
        )
        result = parse_json(answer)
        if result is None:
            raise ValueError("Failed to parse LLM output as JSON")

        state["overall_score"] = float(result.get("overall_score", 70.0))
        state["summary"] = result.get("summary", "")
        state["recommendations"] = result.get("recommendations", [])
    except Exception as e:
        logger.warning(f"LLM 汇总报告失败: {e}，使用启发式兜底")
        score = 100.0 - (high_count * 15) - (medium_count * 5) - (low_count * 2)
        state["overall_score"] = round(max(0.0, min(100.0, score)), 2)

        if high_count == 0 and medium_count == 0:
            state["summary"] = f"本次审查共分析{total_clauses}个条款，未发现高风险或中风险条款。合同整体合规性良好。"
        elif high_count == 0:
            state["summary"] = f"本次审查共分析{total_clauses}个条款，发现{medium_count}处中风险、{low_count}处低风险。合同风险可控。"
        else:
            state["summary"] = f"本次审查共分析{total_clauses}个条款，发现{high_count}处高风险、{medium_count}处中风险、{low_count}处低风险。建议在签署前完成高风险条款修改。"

        recommendations = []
        if high_count > 0:
            recommendations.append(f"优先处理{high_count}处高风险条款")
        if medium_count > 0:
            recommendations.append(f"对{medium_count}处中风险条款进行修订")
        if low_count > 0:
            recommendations.append(f"对{low_count}处低风险条款进行人工复核")
        recommendations.append("建议在签署前由持证律师进行最终审核")
        state["recommendations"] = recommendations

    state["should_continue"] = False
    return state

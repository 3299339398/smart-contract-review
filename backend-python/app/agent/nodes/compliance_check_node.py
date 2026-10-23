"""合规审查节点。

流程: MCP 法规检索 → 获取真实法律条文 → LLM 综合合规分析。
"""

import logging
from app.agent.state import AgentState
from app.llm.client import llm_client

logger = logging.getLogger(__name__)

SYNTHESIS_PROMPT = """你是一位精通中国法律法规的合规律师。

以下是通过法规检索系统找到的与当前合同条款最相关的法律法规，以及当前条款信息。
请综合这些信息，写一段简洁的合规分析。

要求：
1. 引用具体的法律名称和条款号
2. 说明该法规对当前合同条款的具体影响
3. 指出是否存在合规风险
4. 总计不超过150字"""

COT_STEPS = [
    "解读法规条文：逐条理解检索到的法律法规的核心含义和适用范围",
    "关联条款内容：将法规要求与当前合同条款的具体内容进行对照分析",
    "判断合规性：判断当前条款是否符合法律规定，是否存在冲突或不足",
    "归纳结论：总结合规分析要点，包括引用的法规名称和条款号",
]

OUTPUT_FORMAT = """【最终答案】段落是合规分析的纯文本（150字以内），引用具体法律名称和条款号。"""


async def compliance_check_node(state: AgentState) -> AgentState:
    """合规审查节点（仅 FULL 模式）：调 MCP 法规检索获取真实法律条文，交由 LLM 综合做合规分析。"""
    idx = state.get("current_clause_index", 0)
    clauses = state["clauses"]

    if idx >= len(clauses):
        return state

    clause = clauses[idx]
    risk_type = clause.get("risk_type", "NONE")

    if risk_type == "NONE":
        clause["legal_basis"] = ""
        clause["compliance_issues"] = []
        state["clauses"][idx] = clause
        return state

    clause_text = clause.get("text", "")

    # MCP 法规检索
    regulations = []
    try:
        from app.mcp.tools.search_regulations import handler as search_regs
        from app.security.tool_guard import guard_tool_call
        reg_result = await guard_tool_call(
            tool_name="search_legal_regulations",
            handler=search_regs,
            params={"query": clause_text[:500], "risk_type": risk_type},
            task_id=state.get("task_id", ""),
        )
        regulations = reg_result.results if hasattr(reg_result, 'results') else reg_result.get("results", [])
        regulations = [r.model_dump() if hasattr(r, 'model_dump') else r for r in regulations]
        logger.info(f"合规审查 条款{idx}: 通过 MCP 检索到 {len(regulations)} 条法规")
    except Exception as e:
        logger.warning(f"MCP 法规检索失败 条款{idx}: {e}")

    # LLM 综合合规分析
    if regulations:
        reg_context = "\n".join(
            f"- {r['name']} {r['article']}: {r['text'][:150]}"
            for r in regulations[:3]
        )
        user_prompt = f"""法规检索结果：
{reg_context}

当前条款风险类型: {risk_type}
条款原文: {clause_text[:300]}

请综合法规检索结果，写出合规分析。"""
    else:
        user_prompt = f"""风险类型: {risk_type}
条款原文: {clause_text[:300]}

请基于你的法律知识列出与此条款相关的中国法律法规依据。如不确定请明确说明。"""

    try:
        reasoning, answer = await llm_client.chat_with_cot(
            SYNTHESIS_PROMPT, user_prompt, COT_STEPS, OUTPUT_FORMAT, max_tokens=4096
        )
        clause["legal_basis"] = answer.strip()
        clause["compliance_issues"] = [answer.strip()] if answer.strip() else []
        clause["reasoning_compliance"] = reasoning

        if regulations:
            clause["retrieved_regulations"] = regulations

    except Exception as e:
        logger.warning(f"LLM 合规分析失败 条款{idx}: {e}")
        if regulations:
            clause["legal_basis"] = "; ".join(
                f"{r['name']}{r['article']}" for r in regulations[:2]
            )
        else:
            clause["legal_basis"] = "需进一步核实相关法规"
        clause["compliance_issues"] = []

    state["clauses"][idx] = clause
    return state

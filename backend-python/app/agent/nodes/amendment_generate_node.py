"""修改建议生成节点。

流程: MCP 生成结构化修改方案 → LLM 润色为可直接替换的法律文本。
三层降级：MCP 模板修改 → LLM 润色失败用 MCP 原文 → 全部失败用 LLM 直接生成。
"""

import logging
from app.agent.state import AgentState
from app.llm.client import llm_client

logger = logging.getLogger(__name__)

POLISH_PROMPT = """你是一位资深合同律师。以下是自动生成的条款修改建议（JSON格式）。

请基于此JSON输出最终修改建议，格式如下：
修改建议：[具体修改后的条款文本]

要求：
1. 修改后的条款可直接替换原文使用
2. 保持语言专业、符合中文法律文书规范
3. 保留原条款中不应修改的商业条款
4. 总计不超过200字"""

COT_STEPS = [
    "分析原条款结构：拆解原文中的关键要素（主体、义务、时限、金额、例外等）",
    "识别需要修改的部分：对照风险描述和法律依据，确定需要改写的具体内容",
    "设计修改方案：在保留合法商业条款的前提下，重构有问题部分",
    "润色定稿：确保修改后的文本专业、可替换、符合法律文书规范",
]

OUTPUT_FORMAT = """【最终答案】段落格式：
修改建议：[具体修改后的条款文本]"""


async def amendment_generate_node(state: AgentState) -> AgentState:
    """修改建议生成节点：每条有风险的条款的最终节点。"""
    idx = state.get("current_clause_index", 0)
    clauses = state["clauses"]

    if idx >= len(clauses):
        return state

    clause = clauses[idx]
    risk_level = clause.get("risk_level", "LOW")

    if risk_level == "NONE":
        clause["suggested_amendment"] = ""
        state["clauses"][idx] = clause
        return state

    clause_text = clause.get("text", "")
    risk_type = clause.get("risk_type", "")
    risk_description = clause.get("risk_description", "")
    legal_basis = clause.get("legal_basis", "")
    regulations = clause.get("retrieved_regulations", [])

    # MCP 生成结构化修改方案
    mcp_result = None
    try:
        from app.mcp.tools.generate_amendment import handler as gen_amendment
        from app.security.tool_guard import guard_tool_call
        am_model = await guard_tool_call(
            tool_name="generate_amendment",
            handler=gen_amendment,
            params={
                "clause_text": clause_text,
                "risk_type": risk_type,
                "risk_description": risk_description,
                "reference_regulations": regulations[:3] if regulations else None,
            },
            task_id=state.get("task_id", ""),
        )
        mcp_result = am_model.model_dump() if hasattr(am_model, 'model_dump') else am_model
        logger.info(f"修改建议 条款{idx}: MCP 生成成功, 方法={mcp_result.get('generation_method')}")
    except Exception as e:
        logger.warning(f"MCP 修改建议生成失败 条款{idx}: {e}")

    # LLM 润色 MCP 结果，或降级为 LLM 直接生成
    if mcp_result and mcp_result.get("amended_clause"):
        amended = mcp_result["amended_clause"]

        if mcp_result.get("generation_method") == "llm":
            try:
                polish_input = f"""MCP生成的结构化修改建议：
{amended}
修改理由：{mcp_result.get('change_summary', '')}
原条款：{clause_text[:300]}
法律依据：{legal_basis[:200]}

请输出最终的修改建议文本。"""
                reasoning, polished = await llm_client.chat_with_cot(
                    POLISH_PROMPT, polish_input, COT_STEPS, OUTPUT_FORMAT, max_tokens=4096
                )
                clause["suggested_amendment"] = polished.strip()
                clause["reasoning_amendment"] = reasoning
            except Exception as e:
                logger.warning(f"LLM 润色失败: {e}")
                clause["suggested_amendment"] = amended
        else:
            try:
                template_input = f"""模板修改建议：
{amended}
修改理由：{mcp_result.get('change_summary', '')}
原条款：{clause_text[:300]}
风险类型：{risk_type}

请基于模板生成最终修改建议文本。"""
                reasoning, enhanced = await llm_client.chat_with_cot(
                    POLISH_PROMPT, template_input, COT_STEPS, OUTPUT_FORMAT, max_tokens=4096
                )
                clause["suggested_amendment"] = enhanced.strip()
                clause["reasoning_amendment"] = reasoning
            except Exception as e:
                logger.warning(f"LLM 增强失败: {e}")
                clause["suggested_amendment"] = amended

        clause["amendment_legal_basis"] = mcp_result.get("legal_basis", [])
        clause["amendment_modifications"] = mcp_result.get("modifications", [])
    else:
        # MCP 完全失败，LLM 直接生成
        try:
            user_prompt = f"""风险等级: {risk_level}
风险类型: {risk_type}
风险描述: {risk_description}
法律依据: {legal_basis}
原条款: {clause_text}

请撰写修改建议。"""
            reasoning, response = await llm_client.chat_with_cot(
                POLISH_PROMPT, user_prompt, COT_STEPS, OUTPUT_FORMAT, max_tokens=4096
            )
            clause["suggested_amendment"] = response.strip()
            clause["reasoning_amendment"] = reasoning
        except Exception as e:
            logger.warning(f"LLM 直接生成修改建议失败 条款{idx}: {e}")
            clause["suggested_amendment"] = "建议人工审核并修改该条款以降低风险。"

    state["clauses"][idx] = clause
    return state

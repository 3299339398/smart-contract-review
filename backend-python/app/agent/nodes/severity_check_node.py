"""严重等级评估节点。

流程: MCP 模板对比 → 获取客观偏差数据 → LLM 综合判定严重等级。
"""

import logging
from app.agent.state import AgentState
from app.utils.json_utils import parse_json
from app.llm.client import llm_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位资深合同审查律师。根据以下信息，判断合同条款的风险严重等级：

1. 已识别的风险类型
2. 与标准行业模板的对比结果（如有）
3. 条款原文

严重等级定义：
- HIGH: 可能导致重大经济损失、法律纠纷、合同无效或违反强制性法规
- MEDIUM: 存在一定法律风险或权益失衡，建议修改
- LOW: 轻微的措辞不当或可优化之处"""

COT_STEPS = [
    "评估风险类型的固有严重程度：该风险类型本身通常属于何种等级",
    "评估模板对比结果：如与标准模板有显著偏差，结合偏差严重度判断影响",
    "评估条款的实际影响范围：涉及的金额、期限、权利范围等因素",
    "综合判定：结合以上因素，按 HIGH/MEDIUM/LOW 定义给出最终等级",
]

OUTPUT_FORMAT = """【最终答案】段落必须是合法JSON：
{"risk_level": "HIGH/MEDIUM/LOW", "risk_description": "详细的风险描述（100字以内，中文）"}"""

TEMPLATE_TYPE_MAP = {
    "NON_COMPETE_OVERBROAD": ("EMPLOYMENT", "NON_COMPETE"),
    "EXCESSIVE_LIQUIDATED_DAMAGES": ("SERVICE", "LIABILITY"),
    "LIABILITY_UNLIMITED": ("SERVICE", "LIABILITY"),
    "ONE_SIDED_TERMINATION": ("EMPLOYMENT", "TERMINATION"),
    "IP_OWNERSHIP_UNCLEAR": ("EMPLOYMENT", "IP_OWNERSHIP"),
    "CONFIDENTIALITY_WEAK": ("NDA", "CONFIDENTIALITY"),
    "DISPUTE_RESOLUTION_VAGUE": ("NDA", "DISPUTE_RESOLUTION"),
}


async def severity_check_node(state: AgentState) -> AgentState:
    """严重等级评估节点：先调 MCP 模板对比获取客观偏差数据，再交给 LLM 综合判定。"""
    idx = state.get("current_clause_index", 0)
    clauses = state["clauses"]

    if idx >= len(clauses):
        return state

    clause = clauses[idx]
    risk_type = clause.get("risk_type", "NONE")

    if risk_type == "NONE":
        clause["risk_level"] = "LOW"
        clause["risk_description"] = "未发现显著风险，建议人工复核确认。"
        state["clauses"][idx] = clause
        return state

    clause_text = clause.get("text", "")

    # MCP 模板对比
    template_result = None
    template_info = TEMPLATE_TYPE_MAP.get(risk_type)
    if template_info:
        try:
            from app.mcp.tools.compare_template import handler as compare_tmpl
            from app.security.tool_guard import guard_tool_call
            tmpl_model = await guard_tool_call(
                tool_name="compare_with_template",
                handler=compare_tmpl,
                params={
                    "clause_text": clause_text,
                    "template_type": template_info[0],
                    "clause_category": template_info[1],
                },
                task_id=state.get("task_id", ""),
            )
            #model_dump()：Pydantic 官方方法，把模型实例转为 Python 字典，方便序列化、存入 state、传给 LLM 上下文
            template_result = tmpl_model.model_dump() if hasattr(tmpl_model, 'model_dump') else tmpl_model
            logger.info(f"严重等级评估 条款{idx}: 模板相似度={template_result.get('similarity_score')}")
        except Exception as e:
            logger.warning(f"MCP 模板对比失败 条款{idx}: {e}")

    # LLM 综合判定
    context_parts = [f"风险类型: {risk_type}", f"条款原文: {clause_text}"]
    if template_result and template_result.get("deviations"):
        devs = template_result["deviations"]
        context_parts.append(
            f"与标准模板对比，语义相似度: {template_result.get('similarity_score', 'N/A')}，"
            f"发现{len(devs)}处偏差: " +
            "; ".join(f"{d['element']}(严重度:{d['severity']})" for d in devs[:3])
        )

    user_prompt = "\n".join(context_parts)

    try:
        reasoning, answer = await llm_client.chat_with_cot(
            SYSTEM_PROMPT, user_prompt, COT_STEPS, OUTPUT_FORMAT
        )
        result = parse_json(answer)
        clause["risk_level"] = result.get("risk_level", "MEDIUM") if result else "MEDIUM"
        clause["risk_description"] = result.get("risk_description", "")
        clause["reasoning_severity"] = reasoning
    except Exception as e:
        logger.warning(f"LLM 严重等级评估失败 条款{idx}: {e}")
        clause["risk_level"] = "MEDIUM"
        clause["risk_description"] = f"条款存在{risk_type}类型风险，建议进一步审查。"

    if template_result:
        clause["template_similarity"] = template_result.get("similarity_score")
        clause["template_deviations"] = template_result.get("deviations", [])

    risk_item = {
        "clause_index": clause["index"],
        "clause_text": clause.get("text", ""),
        "risk_type": risk_type,
        "risk_level": clause["risk_level"],
        "risk_description": clause["risk_description"]
    }
    state["all_risks"].append(risk_item)
    state["clauses"][idx] = clause
    return state

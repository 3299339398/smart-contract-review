import logging
from app.agent.state import AgentState
from app.utils.json_utils import parse_json
from app.llm.client import llm_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位资深合同审查律师，精通中国合同法。你的任务是分析合同条款，识别潜在的法律风险类型。

风险类型必须从以下列表中选择：
- LIABILITY_UNLIMITED: 违约责任无限、无上限
- MISSING_TERM_DATE: 缺少合同期限或有效期约定
- AMBIGUOUS_PAYMENT_TERMS: 付款/支付条款模糊不清
- ONE_SIDED_TERMINATION: 单方解约权条款不公平
- IP_OWNERSHIP_UNCLEAR: 知识产权归属约定不明
- CONFIDENTIALITY_WEAK: 保密条款保护力度不足
- DATA_PRIVACY_VIOLATION: 个人信息收集使用违规
- DISPUTE_RESOLUTION_VAGUE: 争议解决方式约定不明
- FORCE_MAJEURE_MISSING: 缺少不可抗力条款
- GOVERNING_LAW_MISSING: 未约定适用法律
- AUTO_RENEWAL_TRAP: 自动续约条款存在陷阱
- EXCESSIVE_LIQUIDATED_DAMAGES: 违约金过高或不合理
- NON_COMPETE_OVERBROAD: 竞业限制范围过宽
- NONE: 无显著风险"""

COT_STEPS = [
    "识别条款类型：判断该条款涉及合同的哪个方面（付款、违约、保密、知识产权等）",
    "分析条款内容：拆解条款中的关键权利义务，找出可能的法律风险点",
    "对照风险类型：将发现的风险点与13种预定义风险类型逐一比对",
    "判断风险等级倾向：初步判断属于哪一风险类型，确定最匹配的类型",
]

OUTPUT_FORMAT = """【最终答案】段落必须是合法JSON：
{"risk_type": "选择的风险类型", "reason": "简要分析理由（50字以内）"}"""

RISK_TYPES = {
    "LIABILITY_UNLIMITED", "MISSING_TERM_DATE", "AMBIGUOUS_PAYMENT_TERMS",
    "ONE_SIDED_TERMINATION", "IP_OWNERSHIP_UNCLEAR", "CONFIDENTIALITY_WEAK",
    "DATA_PRIVACY_VIOLATION", "DISPUTE_RESOLUTION_VAGUE", "FORCE_MAJEURE_MISSING",
    "GOVERNING_LAW_MISSING", "AUTO_RENEWAL_TRAP", "EXCESSIVE_LIQUIDATED_DAMAGES",
    "NON_COMPETE_OVERBROAD", "NONE",
}


async def risk_type_identify_node(state: AgentState) -> AgentState:
    """风险类型识别节点：用 LLM + 思维链分析当前条款，从 13 种预定义类型中判定风险类型。"""
    idx = state.get("current_clause_index", 0)
    clauses = state["clauses"]

    if idx >= len(clauses):
        return state#当下标大于条框总数就返回状态

    clause = clauses[idx]
    clause_text = clause.get("text", "")

    if not clause_text.strip():
        clause["risk_type"] = "NONE"
        state["clauses"][idx] = clause
        return state

    try:
        reasoning, answer = await llm_client.chat_with_cot(
            SYSTEM_PROMPT, f"请分析以下合同条款的风险类型：\n\n{clause_text}",
            COT_STEPS, OUTPUT_FORMAT
        )
        result = parse_json(answer)
        if not isinstance(result, dict) or result.get("risk_type") not in RISK_TYPES:
            raise ValueError("模型未返回有效风险类型")
        clause["risk_type"] = result["risk_type"]
        clause["reasoning_risk_type"] = reasoning
    except Exception as e:
        logger.error(f"风险识别失败，条款 {idx}: {e}")
        raise RuntimeError(f"条款 {clause.get('index', idx)} 风险识别失败，审查未完成") from e

    state["clauses"][idx] = clause
    return state

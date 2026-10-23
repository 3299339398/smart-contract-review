"""MCP 工具：generate_amendment —— LLM 驱动的条款修改建议。

优先 LLM 上下文感知生成，回退使用内置模板，返回 Pydantic AmendmentResult 模型。
"""

import json
import logging
from app.llm.client import llm_client
from app.schemas.mcp import ClauseModification, AmendmentResult
from app.core.tool_registry import register_tool

logger = logging.getLogger(__name__)

AMENDMENT_SYSTEM_PROMPT = """你是一位专业的合同法律师，精通中国合同法。修改合同条款以降低法律风险。

按以下JSON格式输出：
{
  "amended_clause": "修改后的完整条款文本",
  "change_summary": "一句话概括主要修改内容",
  "modifications": [
    {"original_phrase": "原文片段", "modified_phrase": "修改后片段", "reason": "法律依据和理由"}
  ],
  "legal_basis": ["引用的法条1"],
  "risk_mitigation": "修改如何降低风险的说明"
}

要求：修改必须符合中国法律、保持商业意图、语言专业可替换使用。"""

FALLBACK_AMENDMENTS = {
    "LIABILITY_UNLIMITED": {
        "amended_clause": "违约方承担的赔偿总额以本合同总金额为上限，且不包括间接损失和预期利益损失。双方确认该责任上限是根据本合同的交易额合理确定的。",
        "change_summary": "增加赔偿责任上限，排除间接损失",
        "modifications": [ClauseModification(
            original_phrase="全部损失", modified_phrase="直接损失，赔偿总额以合同总金额为上限",
            reason="避免无限责任，符合《民法典》第584条的可预见性规则"
        )],
        "legal_basis": ["民法典第584条", "民法典第585条"],
        "risk_mitigation": "通过合同金额上限限制赔偿范围"
    },
    "EXCESSIVE_LIQUIDATED_DAMAGES": {
        "amended_clause": "违约方应按逾期天数支付违约金，每日违约金不超过合同总金额的千分之五，累计违约金总额不超过合同总金额的百分之二十。如该违约金仍不足以弥补守约方实际损失的，守约方有权就超出部分另行主张。",
        "change_summary": "设定违约金计算方式和上限",
        "modifications": [ClauseModification(
            original_phrase="违约金条款", modified_phrase="违约金日率≤千分之五，总额≤20%",
            reason="避免超过实际损失30%，符合民法典第585条及司法解释第69条"
        )],
        "legal_basis": ["民法典第585条", "民法典合同编司法解释第69条"],
        "risk_mitigation": "设定违约金上限20%，低于司法实践中30%的调减阈值"
    },
    "NON_COMPETE_OVERBROAD": {
        "amended_clause": "竞业限制期限为离职后不超过二十四个月，限制地域以公司实际经营区域为限。公司应在竞业限制期内按月支付不低于员工离职前十二个月平均工资30%的经济补偿。如公司连续三个月未支付经济补偿，竞业限制自动解除。",
        "change_summary": "明确竞业限制期限上限和补偿标准",
        "modifications": [ClauseModification(
            original_phrase="竞业限制条款", modified_phrase="期限≤24个月，补偿≥30%月均工资",
            reason="符合《劳动合同法》第24条强制性规定"
        )],
        "legal_basis": ["劳动合同法第23条", "劳动合同法第24条", "劳动争议司法解释（一）第36条"],
        "risk_mitigation": "符合法定竞业限制要件，避免因无补偿或期限过长导致条款无效"
    },
    "ONE_SIDED_TERMINATION": {
        "amended_clause": "任何一方需提前三十日书面通知对方并说明解约理由。如因对方根本违约导致解约的，守约方有权主张相应赔偿。双方对合同解除有争议的，可协商解决或提交有管辖权的人民法院裁决。",
        "change_summary": "将单方解约权修改为双方平等解约权",
        "modifications": [ClauseModification(
            original_phrase="单方解约条款", modified_phrase="双方平等解约权+提前通知+违约赔偿",
            reason="平衡双方利益，避免格式条款无效（民法典第497条）"
        )],
        "legal_basis": ["民法典第562条", "民法典第563条", "民法典第497条"],
        "risk_mitigation": "从单方解约权改为双方平等权利，避免认定为不公平格式条款"
    }
}


@register_tool("generate_amendment", description="Generate amendment suggestions for a risky contract clause")
async def handler(clause_text: str, risk_type: str, risk_description: str = None,
                   reference_regulations: list = None,
                   template_suggestions: dict = None) -> AmendmentResult:
    """生成修改建议，优先 LLM，回退模板，返回 Pydantic 模型。"""

    # 尝试 LLM 生成
    try:
        context_parts = [f"待修改条款：{clause_text}", f"风险类型：{risk_type}"]
        if risk_description:
            context_parts.append(f"风险描述：{risk_description}")
        if reference_regulations:
            regs_text = "; ".join(
                f"{r.get('name', '')} {r.get('article', '')}: {r.get('text', '')[:100]}"
                for r in reference_regulations[:3]
            )
            context_parts.append(f"相关法规：{regs_text}")
        if template_suggestions:
            context_parts.append(f"模板建议：{json.dumps(template_suggestions, ensure_ascii=False)}")

        raw = await llm_client.chat_json(AMENDMENT_SYSTEM_PROMPT, "\n\n".join(context_parts), max_tokens=2048)

        import re
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            parsed = json.loads(json_match.group())
            mods = [
                ClauseModification(
                    original_phrase=m.get("original_phrase", ""),
                    modified_phrase=m.get("modified_phrase", ""),
                    reason=m.get("reason", "")
                )
                for m in parsed.get("modifications", [])
            ]
            return AmendmentResult(
                amended_clause=parsed.get("amended_clause", ""),
                change_summary=parsed.get("change_summary", ""),
                modifications=mods,
                legal_basis=parsed.get("legal_basis", []),
                risk_mitigation=parsed.get("risk_mitigation"),
                generation_method="llm"
            )
    except Exception as e:
        logger.warning(f"LLM amendment failed, using fallback: {e}")

    # 回退方案：硬编码模板
    if risk_type in FALLBACK_AMENDMENTS:
        result = FALLBACK_AMENDMENTS[risk_type]
        return AmendmentResult(
            amended_clause=result["amended_clause"],
            change_summary=result["change_summary"],
            modifications=result["modifications"],
            legal_basis=result.get("legal_basis", []),
            risk_mitigation=result.get("risk_mitigation"),
            generation_method="template_fallback"
        )

    return AmendmentResult(
        amended_clause=f"针对{risk_type}风险，建议委托专业律师拟定修改方案。原条款：{clause_text[:200]}",
        change_summary=f"风险类型{risk_type}需结合具体合同背景人工审查",
        modifications=[],
        legal_basis=[],
        risk_mitigation="此风险类型暂未包含在自动修改模板中，建议人工法律审查",
        generation_method="fallback_generic"
    )

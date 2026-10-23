"""MCP 工具：compare_with_template —— 条款语义对比。

使用 Embedding 相似度 + LLM 分析，返回 Pydantic 模型。
"""

import json
import logging
from app.embeddings.embedding_service import embedding_service
from app.llm.client import llm_client
from app.schemas.mcp import TemplateDeviation, TemplateCompareResult
from app.core.tool_registry import register_tool

logger = logging.getLogger(__name__)

TEMPLATES = {
    "EMPLOYMENT": {
        "LIABILITY": "员工在工作过程中因故意或重大过失给公司造成损失的，应承担相应的赔偿责任，但赔偿金额不超过员工一个月工资。",
        "PAYMENT": "公司应于每月[__]日前以银行转账方式支付上月工资。工资构成包括基本工资、绩效工资及各项补贴。",
        "TERMINATION": "双方均可提前30日书面通知对方解除合同。试用期内提前3日通知即可解除。",
        "CONFIDENTIALITY": "员工对工作期间知悉的公司商业秘密负有保密义务，该义务不因劳动合同的终止而终止。",
        "NON_COMPETE": "员工离职后[__]年内不得在与公司业务构成竞争关系的企业任职。公司应支付不低于员工离职前12个月平均工资30%的经济补偿。",
        "IP_OWNERSHIP": "员工在任职期间完成的与公司业务相关的发明创造，其知识产权归属公司所有。"
    },
    "NDA": {
        "CONFIDENTIALITY": "接收方对披露方的保密信息承担严格的保密义务。保密期限为本协议签署后[__]年。",
        "DISPUTE_RESOLUTION": "因本协议发生的争议，双方应友好协商解决。协商不成的，提交[__]仲裁委员会仲裁。",
        "NON_SOLICITATION": "接收方不得在保密期内直接或间接招揽披露方的员工或客户。"
    },
    "LEASE": {
        "LIABILITY": "因承租方使用不当造成租赁物损坏的，承租方应负责维修或赔偿。出租方应保证租赁物符合约定用途。",
        "TERMINATION": "租赁期满前[__]个月书面通知对方是否续租。",
        "REPAIR_OBLIGATION": "出租人应当履行租赁物的维修义务，但当事人另有约定的除外。"
    },
    "SERVICE": {
        "LIABILITY": "服务提供方因过错导致服务质量不达标的，应在合理期限内免费重新服务或予以补救。",
        "PAYMENT": "委托方应在收到发票后[__]个工作日内支付服务费。逾期每日按应付金额的千分之一加付滞纳金。",
        "ACCEPTANCE": "委托方应在服务完成后[__]个工作日内验收。逾期未提出异议视为验收合格。"
    }
}

COMPARISON_SYSTEM_PROMPT = """你是一位合同法律专家。将用户提供的合同条款与标准行业模板进行对比分析。
请从差异、法律风险、缺失要素、改进建议四个方面分析。

用JSON格式输出：
{"differences": [{"element": "要素名", "difference": "差异描述", "severity": "HIGH/MEDIUM/LOW"}], "missing_elements": ["缺失要素1"], "risk_assessment": "风险评估文本", "improvement_suggestions": ["建议1"]}"""


@register_tool("compare_with_template", description="Compare contract clause against standard industry templates")
async def handler(clause_text: str, template_type: str,
                   clause_category: str = None) -> TemplateCompareResult:
    """将条款与标准模板进行对比，返回 Pydantic 模型。"""
    template_type = template_type.upper()
    if template_type not in TEMPLATES:
        return TemplateCompareResult(
            similarity_score=0.0, missing_elements=[], deviations=[],
            standard_clause="", comparison_method="no_template"
        )

    templates = TEMPLATES[template_type]

    # Step 1: 嵌入向量相似度计算
    try:
        clause_emb = await embedding_service.embed_query(clause_text)
    except Exception as e:
        logger.warning(f"Embedding failed, using lexical fallback: {e}")
        return _lexical_fallback(clause_text, templates, clause_category)

    category_scores = {}
    standard_texts = {}
    for category, standard_text in templates.items():
        if clause_category and category != clause_category:
            continue
        try:
            std_emb = await embedding_service.embed_query(standard_text)
            similarity = sum(a * b for a, b in zip(clause_emb, std_emb))
            category_scores[category] = round(max(0.0, min(1.0, (similarity + 1) / 2)), 4)
            standard_texts[category] = standard_text
        except Exception as e:
            logger.error(f"Embedding comparison failed for {category}: {e}")

    # Step 2: 构建结构化偏差
    sorted_categories = sorted(category_scores.items(), key=lambda x: x[1])
    deviations = []
    missing_elements = []
    combined_standard = ""

    for category, score in sorted_categories:
        standard = standard_texts.get(category, "")
        combined_standard += f"[{category}] {standard}\n"
        if score < 0.5:
            deviations.append(TemplateDeviation(
                element=category, expected=standard[:120], actual=clause_text[:120],
                similarity=score,
                severity="HIGH" if score < 0.3 else "MEDIUM"
            ))
            missing_elements.append(f"Missing or insufficient {category} clause (similarity={score})")

    overall_similarity = round(sum(category_scores.values()) / len(category_scores), 2) if category_scores else 0.0

    # Step 3: LLM 深度分析
    llm_analysis = None
    low_categories = [c for c, s in sorted_categories if s < 0.5]
    if low_categories and len(clause_text) > 20:
        try:
            template_context = "\n".join(f"[{c}] {standard_texts.get(c, '')}" for c in low_categories)
            user_prompt = f"""标准模板条款：{template_context}
            待审查的合同条款：{clause_text}
            请进行对比分析，输出JSON。"""
            raw = await llm_client.chat(COMPARISON_SYSTEM_PROMPT, user_prompt, max_tokens=1024)
            import re
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                llm_analysis = json_match.group()
        except Exception as e:
            logger.warning(f"LLM comparison failed: {e}")

    return TemplateCompareResult(
        similarity_score=overall_similarity,
        category_scores=category_scores,
        missing_elements=missing_elements,
        deviations=deviations,
        standard_clause=combined_standard.strip(),
        llm_analysis=llm_analysis,
        comparison_method="embedding_semantic"
    )


def _lexical_fallback(clause_text: str, templates: dict, clause_category: str = None) -> TemplateCompareResult:
    """Embedding 不可用时的字符重叠度回退方案。"""
    deviations = []
    missing_elements = []
    combined = ""
    for category, standard in templates.items():
        if clause_category and category != clause_category:
            continue
        combined += f"[{category}] {standard}\n"
        std_set = set(standard)
        clause_set = set(clause_text)
        overlap = len(std_set & clause_set) / len(std_set) if std_set else 0
        if overlap < 0.3:
            deviations.append(TemplateDeviation(
                element=category, expected=standard[:100], actual=clause_text[:100],
                severity="MEDIUM" if overlap < 0.1 else "LOW"
            ))
            missing_elements.append(f"Missing or insufficient {category} clause")
    score = max(0.0, 1.0 - len(deviations) * 0.35)
    return TemplateCompareResult(
        similarity_score=round(score, 2), missing_elements=missing_elements,
        deviations=deviations, standard_clause=combined.strip(),
        comparison_method="lexical_fallback"
    )

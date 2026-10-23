"""10 manually annotated contract review test cases.

Each case is a real-world Chinese contract clause with expected risk type,
risk level, and key findings. Used as golden dataset for evaluation.
"""

TEST_CASES = [
    {
        "id": 1,
        "category": "违约责任",
        "clause_text": "如一方违反本协议任何条款，应赔偿对方因此遭受的全部损失，包括但不限于直接损失、间接损失、预期利益损失及律师费，赔偿金额不设上限。",
        "expected_risk_type": "LIABILITY_UNLIMITED",
        "expected_risk_level": "HIGH",
        "expected_keywords": ["无限责任", "不设上限", "间接损失"],
        "description": "违约责任无限条款 — 赔偿范围包含间接损失且不设上限，违反民法典第584条"
    },
    {
        "id": 2,
        "category": "违约金",
        "clause_text": "若乙方逾期交付标的物，每逾期一日，应向甲方支付合同总价款20%的违约金，逾期超过五日的，甲方有权解除合同并没收全部预付款。",
        "expected_risk_type": "EXCESSIVE_LIQUIDATED_DAMAGES",
        "expected_risk_level": "HIGH",
        "expected_keywords": ["违约金过高", "20%", "每日"],
        "description": "过高违约金 — 每日20%的违约金远超实际损失，违反民法典第585条"
    },
    {
        "id": 3,
        "category": "竞业限制",
        "clause_text": "乙方在离职后五年内，不得在中国境内从事与甲方业务相同或相似的任何工作，包括但不限于直接雇佣、间接参股、提供咨询服务等方式。竞业限制期间甲方无需支付任何补偿。",
        "expected_risk_type": "NON_COMPETE_OVERBROAD",
        "expected_risk_level": "HIGH",
        "expected_keywords": ["五年", "中国境内", "无需支付补偿", "竞业限制"],
        "description": "过宽竞业限制 — 5年远超法定2年上限，无补偿违反劳动合同法第23-24条"
    },
    {
        "id": 4,
        "category": "知识产权",
        "clause_text": "乙方在履行本合同过程中产生的所有技术成果、专利、著作权、商业秘密等知识产权，无论是否与甲方业务相关，均无条件归甲方所有，乙方不得保留任何权利。",
        "expected_risk_type": "IP_OWNERSHIP_UNCLEAR",
        "expected_risk_level": "HIGH",
        "expected_keywords": ["知识产权", "无条件归甲方", "不得保留"],
        "description": "知识产权归属不公 — 所有成果无条件归甲方，违反著作权法第27条"
    },
    {
        "id": 5,
        "category": "解约权",
        "clause_text": "甲方有权在任何时候以任何理由单方面解除本合同，且无需向乙方承担任何赔偿责任。乙方不得以任何理由提前解除本合同，否则应赔偿甲方全部损失。",
        "expected_risk_type": "ONE_SIDED_TERMINATION",
        "expected_risk_level": "HIGH",
        "expected_keywords": ["单方面解除", "任何理由", "无需赔偿"],
        "description": "单方解约权 — 甲方可任意解约而乙方被完全限制，严重失衡"
    },
    {
        "id": 6,
        "category": "数据隐私",
        "clause_text": "乙方同意甲方收集其员工的个人信息（包括身份证号、人脸识别数据、健康信息等），甲方可将该等数据用于商业分析和向第三方合作伙伴共享，乙方对此不得有任何异议。",
        "expected_risk_type": "DATA_PRIVACY_VIOLATION",  # falls back to closest match
        "expected_risk_level": "HIGH",
        "expected_keywords": ["个人信息", "人脸识别", "第三方共享", "个人同意"],
        "description": "个人信息违规收集 — 未经个人同意的敏感信息收集与共享，违反个人信息保护法第13条"
    },
    {
        "id": 7,
        "category": "保密条款",
        "clause_text": "乙方应对在工作中知悉的甲方商业秘密予以保密，保密期限为合同终止后一年。保密范围以甲方书面告知的具体内容为限。",
        "expected_risk_type": "CONFIDENTIALITY_WEAK",
        "expected_risk_level": "MEDIUM",
        "expected_keywords": ["保密期限一年", "以甲方书面告知为限"],
        "description": "保密条款过弱 — 保密期仅1年且范围由甲方单方确定，保护不足"
    },
    {
        "id": 8,
        "category": "争议解决",
        "clause_text": "因本合同引起的任何争议，双方应通过友好协商解决。本条款为最终争议解决方式。",
        "expected_risk_type": "DISPUTE_RESOLUTION_VAGUE",
        "expected_risk_level": "MEDIUM",
        "expected_keywords": ["友好协商", "未约定管辖", "仲裁"],
        "description": "争议解决约定不明 — 仅约定协商但未约定仲裁或诉讼管辖"
    },
    {
        "id": 9,
        "category": "付款条款",
        "clause_text": "乙方完成服务后，甲方应在合理期限内支付服务费用。具体金额和支付时间双方另行协商确定。",
        "expected_risk_type": "AMBIGUOUS_PAYMENT_TERMS",
        "expected_risk_level": "MEDIUM",
        "expected_keywords": ["合理期限", "另行协商", "金额未定"],
        "description": "付款条款模糊 — 金额和时间均未确定，构成'待商议'条款"
    },
    {
        "id": 10,
        "category": "自动续约",
        "clause_text": "本合同期满前三十日，如乙方未书面提出不再续约，则本合同自动续期三年，续约条件按甲方届时公布的最新标准执行。",
        "expected_risk_type": "AUTO_RENEWAL_TRAP",
        "expected_risk_level": "HIGH",
        "expected_keywords": ["自动续期", "未提出", "甲方届时公布"],
        "description": "自动续约陷阱 — 沉默即续约且条件由甲方单方决定，存在不公平风险"
    },
]

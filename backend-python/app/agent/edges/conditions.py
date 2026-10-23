from app.agent.state import AgentState


def has_risk(state: AgentState) -> str:
    """risk_type_identify 之后：当前条款是否有风险？

    有风险 → 进入 severity_check 评估严重等级
    无风险(NONE) → 走 amend_or_next 分流，跳过后续 LLM 调用
    """
    clauses = state.get("clauses", [])
    idx = state.get("current_clause_index", 0)
    if idx < len(clauses):
        clause = clauses[idx]
        risk_type = clause.get("risk_type", "")
        if risk_type and risk_type != "NONE":
            return "severity_check"
    return "next_clause"


def more_clauses(state: AgentState) -> str:
    """当前条款处理完毕后：是否还有更多条款？

    有更多 → 回到 next_clause 继续循环
    已处理完 → 进入 aggregate_report 汇总
    """
    idx = state.get("current_clause_index", 0)
    total = state.get("total_clauses", 0)
    if idx < total - 1:
        return "next_clause"
    return "aggregate"


def check_review_type(state: AgentState) -> str:
    """severity_check 之后的分流：是否需要合规检查？

    RISK_ONLY 模式 → 跳过 compliance_check，直接进入 amendment_generate
    FULL 模式 → 先走 compliance_check 再做修改建议
    """
    review_type = state.get("review_type", "FULL")
    if review_type == "RISK_ONLY":
        return "amendment"
    return "compliance_check"

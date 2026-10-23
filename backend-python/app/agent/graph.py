import logging
from langgraph.graph import StateGraph, END
from app.agent.state import AgentState, create_initial_state
from app.agent.nodes.parse_node import parse_document_node
from app.agent.nodes.extract_clauses_node import extract_clauses_node
from app.agent.nodes.risk_type_identify_node import risk_type_identify_node
from app.agent.nodes.severity_check_node import severity_check_node
from app.agent.nodes.compliance_check_node import compliance_check_node
from app.agent.nodes.amendment_generate_node import amendment_generate_node
from app.agent.nodes.aggregate_report_node import aggregate_report_node
from app.agent.edges.conditions import has_risk, more_clauses, check_review_type

logger = logging.getLogger(__name__)


def increment_clause_index(state: AgentState) -> AgentState:
    """游标移动到下一个条款。"""
    state["current_clause_index"] = state.get("current_clause_index", 0) + 1
    return state


def build_review_graph() -> StateGraph:
    """构建合同审查 StateGraph：8 个节点 + 3 条条件边 + 1 个入口。

    主流程：
      parse → extract → next_clause → risk_type_identify
        → [有风险] severity_check → [FULL] compliance_check → amendment_generate
        → [更多条款] next_clause (循环) 或 aggregate_report (结束)
    """
    graph = StateGraph(AgentState)

    # 注册所有节点
    graph.add_node("parse_document", parse_document_node)
    graph.add_node("extract_clauses", extract_clauses_node)
    graph.add_node("risk_type_identify", risk_type_identify_node)
    graph.add_node("severity_check", severity_check_node)
    graph.add_node("compliance_check", compliance_check_node)
    graph.add_node("amendment_generate", amendment_generate_node)
    graph.add_node("aggregate_report", aggregate_report_node)
    graph.add_node("next_clause", increment_clause_index)

    # 入口
    graph.set_entry_point("parse_document")

    # parse → extract
    graph.add_edge("parse_document", "extract_clauses")

    # extract → next_clause（初始化游标后再进入识别） → risk_type_identify
    graph.add_edge("extract_clauses", "next_clause")
    graph.add_edge("next_clause", "risk_type_identify")

    # 条件边：识别到风险 → 进入严重度评估；无风险 → 跳过分流
    graph.add_conditional_edges(
        "risk_type_identify",
        has_risk,
        {
            "severity_check": "severity_check",
            "next_clause": "amend_or_next"
        }
    )

    # 条件边：FULL 模式 → 先做合规检查；RISK_ONLY 模式 → 直接进入修改建议
    graph.add_conditional_edges(
        "severity_check",
        check_review_type,
        {
            "compliance_check": "compliance_check",
            "amendment": "amendment_generate"
        }
    )

    graph.add_edge("compliance_check", "amendment_generate")

    # 条件边：修改建议后 → 还有条款继续循环，否则进入汇总
    graph.add_conditional_edges(
        "amendment_generate",
        more_clauses,
        {
            "next_clause": "next_clause",
            "aggregate": "aggregate_report"
        }
    )

    # 无风险条款的分流节点（空操作），直接判断是否还有更多条款
    graph.add_node("amend_or_next", lambda s: s)
    graph.add_conditional_edges(
        "amend_or_next",
        more_clauses,
        {
            "next_clause": "next_clause",
            "aggregate": "aggregate_report"
        }
    )

    # 汇总 → 结束
    graph.add_edge("aggregate_report", END)

    return graph


def build_compiled_graph(checkpointer=None):
    """编译并返回 (编译后的图, 运行时配置)。"""
    graph = build_review_graph()
    compiled = graph.compile(checkpointer=checkpointer)
    config = {"recursion_limit": 200}
    return compiled, config

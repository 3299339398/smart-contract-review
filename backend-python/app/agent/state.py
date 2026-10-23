"""Agent 状态定义 — LangGraph 共享状态的 TypedDict。

使用 TypedDict（而非 Pydantic），因为 LangGraph 的 StateGraph
要求使用 TypedDict 作为类型参数和 add_conditional_edges 的类型。
API 边界使用 Pydantic 模型做序列化；图内部使用 TypedDict 做状态传递。
"""

from typing import TypedDict, List, Optional, Dict, Any
from typing_extensions import NotRequired


class RegulationRef(TypedDict, total=False):
    """MCP search_regulations 检索到的法规引用。"""
    name: str
    article: str
    text: str
    relevance_score: float


class TemplateDeviation(TypedDict, total=False):
    """MCP compare_template 发现的模板偏差。"""
    element: str
    expected: str
    actual: str
    similarity: float
    severity: str


class Clause(TypedDict, total=False):
    """合同条款。total=False 表示所有字段可选，各节点增量填充。"""
    index: int
    text: str
    # ── risk_type_identify 产出 ──
    risk_type: NotRequired[str]
    # ── severity_check 产出 ──
    risk_level: NotRequired[str]
    risk_description: NotRequired[str]
    # ── amendment_generate 产出 ─
    suggested_amendment: NotRequired[str]
    # ── compliance_check 产出 ──
    legal_basis: NotRequired[str]
    compliance_issues: NotRequired[List[str]]
    # ── 各节点的思维链推理记录 ──
    reasoning_risk_type: NotRequired[str]
    reasoning_severity: NotRequired[str]
    reasoning_compliance: NotRequired[str]
    reasoning_amendment: NotRequired[str]
    # ── MCP 工具注入的字段 ──
    retrieved_regulations: NotRequired[List[RegulationRef]]
    template_similarity: NotRequired[float]
    template_deviations: NotRequired[List[TemplateDeviation]]
    amendment_legal_basis: NotRequired[List[str]]
    amendment_modifications: NotRequired[List[Dict[str, str]]]


class RiskItem(TypedDict):
    """结构化风险条目，供 aggregate_report 汇总使用。与 schemas/review.py 的 RiskItem 对应。"""
    clause_index: int
    clause_text: str
    risk_type: str
    risk_level: str
    risk_description: str
    suggested_amendment: NotRequired[str]
    legal_basis: NotRequired[str]


class AgentState(TypedDict):
    """合同审查 Agent 的全局共享状态。在整个图中传递，各节点读/写其中部分字段。"""
    # ── API 入参（create_initial_state 填充，之后只读） ──
    document_text: str
    review_type: str
    task_id: str
    contract_type: str

    # ── 文档处理阶段产出 ──
    parsed_text: str
    clauses: List[Clause]

    # ── 循环控制 ──
    current_clause_index: int
    total_clauses: int

    # ── 逐条款风险积累 ──
    all_risks: List[RiskItem]

    # ── 最终报告产出 ──
    overall_score: float
    summary: str
    recommendations: List[str]

    # ── 控制流 ──
    error: str
    should_continue: bool


def create_initial_state(document_text: str, review_type: str, task_id: str) -> AgentState:
    """创建初始状态，由 API 层调用。用传入参数填充出参字段，内部字段置为空。"""
    return AgentState(
        document_text=document_text,
        review_type=review_type,
        task_id=task_id,
        contract_type="GENERAL",
        parsed_text="",
        clauses=[],
        current_clause_index=0,
        total_clauses=0,
        all_risks=[],
        overall_score=0.0,
        summary="",
        recommendations=[],
        error="",
        should_continue=True
    )

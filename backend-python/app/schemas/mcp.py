"""4 个 MCP 工具输入/输出的 Pydantic Schema 定义。

使用 Pydantic 而非原始字典的原因：
- 运行时字段级校验
- 自动生成 JSON Schema 用于 MCP 工具注册
- IDE 自动补全与类型检查
- 通过 .model_dump() / .model_validate() 进行序列化/反序列化
"""

from pydantic import BaseModel, Field
from typing import Optional, List


# ── search_legal_regulations ──

class RegulationEntry(BaseModel):
    name: str = Field(..., description="法律/法规名称", examples=["民法典"])
    article: str = Field(..., description="条款号", examples=["第584条"])
    text: str = Field(..., description="条款原文")
    relevance_score: float = Field(default=1.0, ge=0.0, le=1.0, description="语义相关度 0-1")

class RegulationSearchResult(BaseModel):
    results: List[RegulationEntry] = Field(default_factory=list)
    total: int = Field(default=0)
    search_method: str = Field(default="keyword", description="keyword / semantic_embedding / direct_match")
    jurisdiction: Optional[str] = Field(default="CN")


# ── compare_with_template ──

class TemplateDeviation(BaseModel):
    element: str = Field(..., description="缺失或偏离的要素名")
    expected: str = Field(default="", description="标准模板内容摘要")
    actual: str = Field(default="", description="实际条款内容摘要")
    similarity: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="语义相似度")
    severity: str = Field(default="MEDIUM", description="HIGH / MEDIUM / LOW")

class TemplateCompareResult(BaseModel):
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    category_scores: dict[str, float] = Field(default_factory=dict)
    missing_elements: List[str] = Field(default_factory=list)
    deviations: List[TemplateDeviation] = Field(default_factory=list)
    standard_clause: str = Field(default="")
    llm_analysis: Optional[str] = Field(default=None, description="LLM 深度对比 JSON")
    comparison_method: str = Field(default="lexical_fallback")


# ── generate_amendment ──

class ClauseModification(BaseModel):
    original_phrase: str = Field(default="", description="原文片段")
    modified_phrase: str = Field(default="", description="修改后片段")
    reason: str = Field(default="", description="修改的法律理由")

class AmendmentResult(BaseModel):
    amended_clause: str = Field(..., description="修改后的完整条款文本")
    change_summary: str = Field(default="", description="修改摘要")
    modifications: List[ClauseModification] = Field(default_factory=list)
    legal_basis: List[str] = Field(default_factory=list)
    risk_mitigation: Optional[str] = Field(default=None)
    generation_method: str = Field(default="template_fallback", description="llm / template_fallback / fallback_generic")


# ── evaluate_contract_balance ──

class OneSidedClause(BaseModel):
    clause_index: int = Field(..., description="条款序号")
    description: str = Field(default="")
    pattern: Optional[str] = Field(default=None, description="匹配到的单方条款模式")
    severity: str = Field(default="MEDIUM", description="HIGH / MEDIUM / LOW")

class BalanceEvaluation(BaseModel):
    balance_score: float = Field(default=0.5, ge=0.0, le=1.0, description="0=严重失衡, 1=完全公平")
    total_clauses: int = Field(default=0)
    high_risk_clauses: int = Field(default=0)
    medium_risk_clauses: int = Field(default=0)
    one_sided_patterns: int = Field(default=0)
    party_a_advantages: List[str] = Field(default_factory=list)
    party_b_disadvantages: List[str] = Field(default_factory=list)
    one_sided_clauses: List[OneSidedClause] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    overall_assessment: str = Field(default="")
    evaluation_method: str = Field(default="heuristic", description="heuristic / llm_deep_analysis / no_data")
    heuristic_score: Optional[float] = Field(default=None)
    contract_type: Optional[str] = Field(default=None)

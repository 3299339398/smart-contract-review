from pydantic import BaseModel, Field
from typing import Optional, List

# 内部数据模型（Agent 管线使用）
class ReviewRequest(BaseModel):
    document_text: str = Field(..., min_length=1, max_length=500_000)
    review_type: str = "FULL"
    correlation_id: str = Field("", max_length=100)

class RiskItem(BaseModel):
    clause_index: int
    clause_text: str
    risk_type: str
    risk_level: str
    risk_description: str
    suggested_amendment: Optional[str] = None
    legal_basis: Optional[str] = None

class ReviewResult(BaseModel):
    task_id: str
    overall_score: float
    summary: str
    recommendations: List[str] = []
    total_clauses: int = 0
    risk_count_high: int = 0
    risk_count_medium: int = 0
    risk_count_low: int = 0
    risk_items: List[RiskItem] = []

class ReviewStatusResponse(BaseModel):
    task_id: str
    status: str
    result: Optional[ReviewResult] = None
    error: Optional[str] = None

class ParseRequest(BaseModel):
    document_id: int
    correlation_id: str = Field("", max_length=100)

class ParseResponse(BaseModel):
    document_id: int
    content_text: str
    clause_count: int
    status: str
    error: Optional[str] = None

# 前端 API 数据模型（严格对应 types/*.ts）
class ReviewCreateRequest(BaseModel):
    documentId: int
    reviewType: str = "FULL"

class ReviewTaskResponse(BaseModel):
    taskId: int
    documentId: int
    documentName: str = ""
    reviewType: str
    status: str
    totalClauses: int = 0
    reviewedClauses: int = 0
    riskCountHigh: int = 0
    riskCountMedium: int = 0
    riskCountLow: int = 0
    startedAt: Optional[str] = None
    completedAt: Optional[str] = None
    createdAt: str = ""

class RiskItemDto(BaseModel):
    clauseIndex: int
    clauseText: str
    riskType: str
    riskLevel: str
    riskDescription: str
    suggestedAmendment: str = ""
    legalBasis: str = ""

class ReviewResultResponse(BaseModel):
    taskId: int
    overallScore: float
    summary: str
    recommendations: List[str]
    riskItems: List[RiskItemDto]

"""评测系统 Pydantic Schema — API 请求/响应模型。"""

from pydantic import BaseModel
from typing import Optional, List


class EvalRunRequest(BaseModel):
    mode: str = "quick"  # "quick" | "full"
    withLlmJudge: bool = True


class EvalCaseDetail(BaseModel):
    caseId: int
    description: str
    expectedRiskType: str
    expectedRiskLevel: str
    predictedRiskType: str
    predictedRiskLevel: str
    riskTypeMatch: bool
    riskLevelMatch: bool
    llmJudgeScore: Optional[float] = None
    llmJudgeReasoning: Optional[str] = None
    predictedReasoning: Optional[str] = None


class EvalReportResponse(BaseModel):
    reportId: str
    mode: str
    totalCases: int
    riskTypePrecision: float
    riskTypeRecall: float
    riskTypeF1: float
    riskLevelAccuracy: float
    avgLlmJudgeScore: float
    details: List[EvalCaseDetail]
    createdAt: str


class EvalRunResponse(BaseModel):
    reportId: str
    status: str  # "running" | "completed" | "failed"

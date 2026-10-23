from pydantic import BaseModel
from typing import Optional, List

# 内部数据模型
class SourceClause(BaseModel):
    clause_index: int
    text: str

class ConsultationRequest(BaseModel):
    document_id: Optional[int] = None
    clauses: List[dict] = []
    question: str
    correlation_id: str = ""

class ConsultationResponse(BaseModel):
    answer: str
    source_clauses: List[SourceClause] = []

# 前端 API 数据模型（对应 types/*.ts）
class ConsultationApiRequest(BaseModel):
    documentId: Optional[int] = None
    question: str

class SourceClauseDto(BaseModel):
    clauseIndex: int
    text: str

class ConsultationApiResponse(BaseModel):
    consultId: int
    question: str
    answer: str
    sourceClauses: List[SourceClauseDto]
    citationWarnings: List[str] = []
    createdAt: str = ""

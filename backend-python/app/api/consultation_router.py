import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.database import get_db
from app.schemas.common import ApiResponse
from app.schemas.consultation import (
    ConsultationRequest, ConsultationResponse, SourceClause,
    ConsultationApiRequest,
)
from app.services.consultation_service import ConsultationService
from app.services.rate_limit_service import rate_limit, RateLimitExceededException
from app.middleware.auth_middleware import get_current_user_id

logger = logging.getLogger(__name__)
consultation_router = APIRouter()
frontend_consult_router = APIRouter()


# ---- 旧版内部接口 ----

@consultation_router.post("/ask")
async def ask_question(
    request: ConsultationRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        rate_limit(user_id, "consultation:legacy_ask", max_requests=20, window_seconds=60)
        result = await ConsultationService.ask(db, user_id, request.question, request.document_id)
        source_clauses = [
            SourceClause(clause_index=s.get("clauseIndex", 0), text=s.get("text", ""))
            for s in result.get("sourceClauses", [])
        ]
        return ConsultationResponse(answer=result["answer"], source_clauses=source_clauses)
    except RateLimitExceededException as e:
        raise HTTPException(status_code=429, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Consultation failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---- 新版前端接口 ----

@frontend_consult_router.post("/consultations", response_model=ApiResponse)
async def ask_question_api(
    req: ConsultationApiRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        rate_limit(user_id, "consultation:ask", max_requests=20, window_seconds=60)
        data = await ConsultationService.ask(
            db, user_id, req.question, req.documentId
        )
        return ApiResponse(code=200, data=data)
    except RateLimitExceededException as e:
        raise HTTPException(status_code=429, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@frontend_consult_router.get("/consultations", response_model=ApiResponse)
async def get_consultation_history(
    page: int = 1, size: int = 10,
    documentId: Optional[int] = None,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    items, total = await ConsultationService.get_history(
        db, user_id, documentId, page, size
    )
    return ApiResponse(code=200, data={"content": items, "totalElements": total})

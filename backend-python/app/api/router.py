from fastapi import APIRouter
from app.api.review_router import review_router, frontend_router as review_frontend_router
from app.api.consultation_router import consultation_router, frontend_consult_router
from app.api.auth_router import router as auth_router
from app.api.document_router import router as document_router
from app.api.security_router import router as security_router
from app.api.eval_router import router as eval_router

api_router = APIRouter()

# 旧版内部端点（向后兼容）
api_router.include_router(review_router, prefix="/review", tags=["review"])
api_router.include_router(consultation_router, prefix="/consult", tags=["consult"])

# 新版前端端点（匹配 Java 控制器路径）
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(document_router, prefix="/documents", tags=["documents"])
api_router.include_router(review_frontend_router, tags=["reviews"])
api_router.include_router(frontend_consult_router, tags=["consultations"])
api_router.include_router(security_router, prefix="/security", tags=["security"])
api_router.include_router(eval_router, prefix="/eval", tags=["eval"])

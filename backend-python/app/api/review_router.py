import asyncio
import uuid
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.database import get_db
from app.models import ReviewTask
from sqlalchemy import select
from app.schemas.common import ApiResponse
from app.schemas.review import (
    ReviewRequest, ReviewStatusResponse, ParseRequest, ParseResponse,
    ReviewCreateRequest,
)
from app.agent.graph import build_review_graph
from app.agent.state import create_initial_state
from app.parser.document_parser import DocumentParserFactory
from app.parser.chunker import ClauseLevelChunker
from app.services.review_service import ReviewService
from app.services.rate_limit_service import rate_limit, RateLimitExceededException
from app.services.sse_service import create_sse_stream
from app.middleware.auth_middleware import get_current_user_id

logger = logging.getLogger(__name__)
review_router = APIRouter()
frontend_router = APIRouter()

# 内存任务存储（旧端点向后兼容）
_tasks: dict[str, dict] = {}


def _extract_result(final_state: dict) -> dict:
    clauses = final_state.get("clauses", [])
    all_risks = final_state.get("all_risks", [])
    risk_items = []
    for r in all_risks:
        idx = r["clause_index"]
        clause = clauses[idx - 1] if idx <= len(clauses) else {}
        risk_items.append({
            "clause_index": idx,
            "clause_text": clause.get("text", ""),
            "risk_type": r.get("risk_type", "NONE"),
            "risk_level": r.get("risk_level", "LOW"),
            "risk_description": r.get("risk_description", ""),
            "suggested_amendment": clause.get("suggested_amendment", ""),
            "legal_basis": clause.get("legal_basis", "")
        })
    return {
        "task_id": final_state.get("task_id", ""),
        "overall_score": final_state.get("overall_score", 0.0),
        "summary": final_state.get("summary", ""),
        "recommendations": final_state.get("recommendations", []),
        "total_clauses": final_state.get("total_clauses", 0),
        "risk_count_high": sum(1 for r in all_risks if r.get("risk_level") == "HIGH"),
        "risk_count_medium": sum(1 for r in all_risks if r.get("risk_level") == "MEDIUM"),
        "risk_count_low": sum(1 for r in all_risks if r.get("risk_level") == "LOW"),
        "risk_items": risk_items
    }


# ---- 旧版内部接口（向后兼容） ----

@review_router.post("/start")
async def start_review(
    request: ReviewRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        rate_limit(user_id, "review:legacy_start", max_requests=10, window_seconds=60)
    except RateLimitExceededException as e:
        raise HTTPException(status_code=429, detail=str(e))
    from app.security import SecurityPipeline
    verdict = await SecurityPipeline.check_query(request.document_text, db, user_id)
    if not verdict.passed:
        raise HTTPException(status_code=400, detail="安全检查未通过，请使用文档审查接口进行人工复核")
    task_id = str(uuid.uuid4())
    _tasks[task_id] = {
        "status": "PROCESSING", "result": None, "error": None,
        "user_id": user_id,
        "progress": {"stage": "STARTING", "total_clauses": 0, "reviewed_clauses": 0,
                     "current_clause_index": 0, "current_clause_preview": "",
                     "risks_found": [], "percentage": 0}
    }

    async def _run():
        try:
            from app.agent.checkpoint import get_checkpoint_saver, checkpoint_config
            graph = build_review_graph()
            checkpointer = await get_checkpoint_saver()
            compiled = graph.compile(checkpointer=checkpointer)
            config = checkpoint_config(task_id, user_id)
            config["recursion_limit"] = max(200, len(ClauseLevelChunker().split_clauses(request.document_text)) * 8 + 20)
            initial_state = create_initial_state(request.document_text, request.review_type, task_id)
            last_state = initial_state
            async for chunk in compiled.astream(initial_state, config):
                for node_name, node_output in chunk.items():
                    last_state.update(node_output)
            result = _extract_result(last_state)
            _tasks[task_id] = {"status": "COMPLETED", "result": result, "error": None,
                               "user_id": user_id,
                               "progress": _tasks[task_id]["progress"]}
        except Exception as e:
            logger.exception(f"Review failed for task {task_id}")
            _tasks[task_id] = {"status": "FAILED", "result": None, "error": str(e),
                               "user_id": user_id,
                               "progress": _tasks[task_id]["progress"]}

    asyncio.create_task(_run())
    return {"task_id": task_id, "status": "PROCESSING"}


@review_router.get("/status/{task_id}")
async def get_status(task_id: str, user_id: int = Depends(get_current_user_id)):
    task = _tasks.get(task_id)
    if not task or task.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task_id, "status": task["status"], "result": task["result"],
            "error": task["error"], "progress": task.get("progress", {})}


@review_router.post("/parse")
async def parse_document(
    request: ParseRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    # The legacy parser used to accept an arbitrary server-side file path.
    # Parse only a document owned by the caller and use its stored path.
    try:
        from app.models import Document
        result = await db.execute(select(Document).where(
            Document.id == request.document_id, Document.user_id == user_id
        ))
        document = result.scalar_one_or_none()
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        parser = DocumentParserFactory.create(document.stored_path)
        text = parser.extract_text(document.stored_path)
        chunker = ClauseLevelChunker()
        clauses = chunker.split_clauses(text)
        return ParseResponse(document_id=request.document_id, content_text=text,
                             clause_count=len(clauses), status="PARSED")
    except HTTPException:
        raise
    except Exception as e:
        return ParseResponse(document_id=request.document_id, content_text="",
                             clause_count=0, status="FAILED", error=str(e))


# ---- 新版前端接口（与 Java 端 Controller API 对齐） ----

@frontend_router.post("/reviews", response_model=ApiResponse)
async def create_review(
    req: ReviewCreateRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        rate_limit(user_id, "review:create", max_requests=10, window_seconds=60)
        data = await ReviewService.create_review(db, user_id, req.documentId, req.reviewType)
        return ApiResponse(code=200, message="审查已启动", data=data)
    except RateLimitExceededException as e:
        raise HTTPException(status_code=429, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@frontend_router.get("/reviews/{task_id}", response_model=ApiResponse)
async def get_review_task(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await ReviewService.get_task(db, task_id, user_id)
        return ApiResponse(code=200, data=data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@frontend_router.get("/reviews", response_model=ApiResponse)
async def list_reviews(
    page: int = 1, size: int = 10, status: Optional[str] = None,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    items, total = await ReviewService.list_tasks(db, user_id, page, size, status)
    return ApiResponse(code=200, data={"content": items, "totalElements": total})


@frontend_router.delete("/reviews/{task_id}", response_model=ApiResponse)
async def delete_review(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        await ReviewService.delete_task(db, task_id, user_id)
        return ApiResponse(code=200, message="删除成功")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@frontend_router.get("/reviews/{task_id}/result", response_model=ApiResponse)
async def get_review_result(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await ReviewService.get_result(db, task_id, user_id)
        return ApiResponse(code=200, data=data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@frontend_router.get("/reviews/{task_id}/stream")
async def stream_review(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ReviewTask).where(
        ReviewTask.id == task_id, ReviewTask.user_id == user_id
    ))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Review task not found")
    return await create_sse_stream(task_id)

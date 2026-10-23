from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.database import get_db
from app.schemas.common import ApiResponse
from app.schemas.document import DocumentResponse
from app.services.document_service import DocumentService
from app.middleware.auth_middleware import get_current_user_id

router = APIRouter(tags=["documents"])


@router.post("/upload", response_model=ApiResponse)
async def upload_document(
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        file_bytes = await file.read()
        data = await DocumentService.upload(
            db, user_id, file_bytes, file.filename or "unknown", file.content_type
        )
        return ApiResponse(code=200, message="上传成功", data=data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=ApiResponse)
async def list_documents(
    page: int = 1, size: int = 10, status: Optional[str] = None,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    items, total = await DocumentService.list_documents(
        db, user_id, page, size, status
    )
    return ApiResponse(code=200, data={"content": items, "totalElements": total})


@router.get("/{document_id}", response_model=ApiResponse)
async def get_document(
    document_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await DocumentService.get_document(db, document_id, user_id)
        return ApiResponse(code=200, data=data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{document_id}", response_model=ApiResponse)
async def delete_document(
    document_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        await DocumentService.delete_document(db, document_id, user_id)
        return ApiResponse(code=200, message="删除成功")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

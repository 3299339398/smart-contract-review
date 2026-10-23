from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.common import ApiResponse
from app.schemas.auth import RegisterRequest, LoginRequest, RefreshRequest, LoginResponse
from app.services.auth_service import AuthService

router = APIRouter(tags=["auth"])


@router.post("/register", response_model=ApiResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    try:
        user = await AuthService.register(db, req.username, req.email, req.password)
        return ApiResponse(code=200, message="注册成功", data=user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login", response_model=ApiResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        data = await AuthService.login(db, req.email, req.password)
        return ApiResponse(code=200, message="登录成功", data=data)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/refresh", response_model=ApiResponse)
async def refresh(req: RefreshRequest):
    try:
        data = await AuthService.refresh(req.refreshToken)
        return ApiResponse(code=200, message="Token refreshed", data=data)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/logout", response_model=ApiResponse)
async def logout(request: Request, req: RefreshRequest):
    try:
        authorization = request.headers.get("authorization", "")
        scheme, _, access_token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not access_token:
            raise HTTPException(status_code=401, detail="Access token required")
        await AuthService.logout(access_token, req.refreshToken)
        return ApiResponse(code=200, message="已登出")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

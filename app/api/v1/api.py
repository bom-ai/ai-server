"""
API v1 라우터 집합
"""
from fastapi import APIRouter

from app.api.v1.endpoints import bomatic_pipeline, auth

api_router = APIRouter()

# 각 엔드포인트 그룹을 라우터에 포함
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(bomatic_pipeline.router, prefix="/bomatic_pipeline", tags=["Pipeline"])

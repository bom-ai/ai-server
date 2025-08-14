"""
bo:matic server - FastAPI 애플리케이션 진입점
"""
import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from app.core.config import settings
from app.api.v1.api import api_router
from app.models.schemas import HealthResponse

# 환경변수 파일 로드
load_dotenv()


def create_application() -> FastAPI:
    """FastAPI 애플리케이션을 생성하고 설정합니다."""
    
    app = FastAPI(
        title=settings.app_name,
        description=settings.app_description,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc"
    )

    origins = [
        "https://bomatic.vercel.app",      # 배포된 프론트엔드 주소
        "http://localhost:5173",         # 로컬에서 개발할 때 사용하는 주소
        # 필요하다면 다른 주소도 추가
    ]
    
    # CORS 미들웨어 설정
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # API 라우터 포함
    app.include_router(api_router, prefix="/api")
    
    return app


# FastAPI 앱 인스턴스 생성
app = create_application()


# 기본 엔드포인트들
@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {
        "message": "Welcome to bo:matic service!", 
        "status": "running",
        "version": settings.app_version
    }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """헬스체크 엔드포인트"""
    return HealthResponse(
        status="healthy", 
        timestamp=pd.Timestamp.now().isoformat()
    )


# 개발 서버 실행용 (프로덕션에서는 gunicorn 등 사용)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )

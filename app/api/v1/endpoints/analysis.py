"""
텍스트 분석 API 엔드포인트
"""
from fastapi import APIRouter, HTTPException, Depends

from app.models.schemas import AnalysisRequest, AnalysisResponse
from app.services.gemini_service import gemini_service
from app.api.deps import get_current_user
from app.models.database import User

router = APIRouter()


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_text(
    request: AnalysisRequest,
    current_user: User = Depends(get_current_user)
):
    """FGD 전사 텍스트를 분석합니다. (인증 필요)"""
    try:
        result = await gemini_service.analyze_text(
            request.text_content, 
            request.analysis_type
        )
        
        return AnalysisResponse(
            status="completed",
            message="분석이 완료되었습니다.",
            result=result
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

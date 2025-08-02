"""
Gemini AI 서비스
"""
import google.generativeai as genai
from fastapi import HTTPException

from app.core.config import settings
from app.core.prompts import SYSTEM_PROMPTS


class GeminiService:
    """Google Gemini AI 서비스"""
    
    def __init__(self):
        self.api_key = settings.gemini_api_key
        self._initialized = False
    
    def _initialize(self) -> bool:  # 클래스 내부 전용 Private 메서드 (호출은 가능하지만 _ 붙인 건 관례상 내부에서만!)
        """Gemini API를 초기화합니다."""
        if not self.api_key:
            return False
        
        try:
            genai.configure(api_key=self.api_key)
            self._initialized = True
            return True
        except Exception:
            return False
    
    async def analyze_text(
        self, 
        text_content: str, 
        analysis_type: str = "phase1"
    ) -> str:
        """Gemini API를 사용하여 텍스트를 분석합니다."""
        if not self._initialized and not self._initialize():
            raise HTTPException(
                status_code=500, 
                detail="Gemini API 키가 설정되지 않았습니다."
            )
        
        try:
            system_prompt = SYSTEM_PROMPTS.get(analysis_type, SYSTEM_PROMPTS["phase1"])
            
            model = genai.GenerativeModel(
                model_name='gemini-2.5-pro',
                system_instruction=system_prompt
            )
            
            response = model.generate_content(text_content)
            return response.text
        except Exception as e:
            raise HTTPException(
                status_code=500, 
                detail=f"Gemini 분석 실패: {str(e)}"
            )


# 전역 Gemini 서비스 인스턴스
gemini_service = GeminiService()

"""
Gemini AI 서비스
"""
import asyncio
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from fastapi import HTTPException
from typing import List, Optional, Literal

from app.core.config import settings
from app.core.prompts import generate_system_prompt_from_docx


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
        custom_items: Optional[List[str]] = None,
        template_type: Literal["raw", "refined"] = "refined"
    ) -> str:
        """Gemini API - custom_items를 사용하여 텍스트를 분석합니다."""
        import logging
        logger = logging.getLogger(__name__)
        
        if not self._initialized and not self._initialize():
            raise HTTPException(
                status_code=500, 
                detail="Gemini API 키가 설정되지 않았습니다."
            )
        
        max_retries = 3
        base_retry_delay = 5
        
        # 안전 설정을 최대한 완화
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Gemini API call attempt {attempt + 1}/{max_retries}")
                
                # custom_items를 기반으로 시스템 프롬프트 생성
                system_prompt = generate_system_prompt_from_docx(
                    file_content=(custom_items or []),
                    template_type=template_type
                )
                
                model = genai.GenerativeModel(
                    model_name='gemini-2.5-pro',
                    system_instruction=system_prompt
                )
                
                logger.info(f"Generating content with text length: {len(text_content)}")
                
                # 안전 설정과 함께 요청
                response = model.generate_content(
                    text_content,
                    safety_settings=safety_settings
                )
                
                # 응답 검증
                if response.candidates and response.candidates[0].content.parts:
                    logger.info(f"Gemini API call successful on attempt {attempt + 1}")
                    return response.text
                else:
                    # finish_reason 확인
                    finish_reason = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
                    logger.warning(f"No valid response parts. Finish reason: {finish_reason}")
                    
                    # 안전 필터링인 경우 특별 처리
                    if finish_reason == 1:  # SAFETY
                        logger.warning("Content blocked by safety filter. Trying with modified prompt...")
                        # 다음 시도에서 사용할 대체 프롬프트나 전처리 로직 추가 가능
                        raise Exception(f"Content blocked by safety filter (finish_reason: {finish_reason})")
                    else:
                        raise Exception(f"Invalid response format (finish_reason: {finish_reason})")
                
            except Exception as e:
                logger.error(f"Gemini API call failed on attempt {attempt + 1}: {str(e)}")
                
                # Rate limiting 관련 에러인지 확인
                if "quota" in str(e).lower() or "rate" in str(e).lower() or "limit" in str(e).lower() or "429" in str(e):
                    if attempt < max_retries - 1:
                        wait_time = 10 + (base_retry_delay * (2 ** attempt))
                        logger.info(f"Rate limiting detected, waiting {wait_time} seconds before retry")
                        await asyncio.sleep(wait_time)
                        continue
                
                # 안전 필터링인 경우
                elif "safety" in str(e).lower() or "finish_reason" in str(e).lower():
                    if attempt < max_retries - 1:
                        wait_time = base_retry_delay
                        logger.info(f"Safety filter detected, waiting {wait_time} seconds before retry")
                        await asyncio.sleep(wait_time)
                        continue
                
                # 마지막 시도였거나 다른 에러인 경우
                if attempt == max_retries - 1:
                    raise HTTPException(
                        status_code=500, 
                        detail=f"Gemini 분석 실패 (모든 재시도 실패): {str(e)}"
                    )
                else:
                    wait_time = base_retry_delay * (attempt + 1)
                    logger.info(f"General error, waiting {wait_time} seconds before retry")
                    await asyncio.sleep(wait_time)
                    continue


# 전역 Gemini 서비스 인스턴스
gemini_service = GeminiService()

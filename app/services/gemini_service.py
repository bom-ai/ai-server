"""
Gemini AI 서비스
"""
import asyncio
from google import genai
from fastapi import HTTPException
from typing import List, Optional, Literal

from app.core.config import settings
from app.core.prompts import generate_system_prompt_from_docx


class GeminiService:
    """Google Gemini AI 서비스"""
    
    def __init__(self):
        self.api_key = settings.gemini_api_key
        self._client = None
        self._initialized = False
    
    def _initialize(self) -> bool:
        """Gemini API를 초기화합니다."""
        if not self.api_key:
            return False
        
        try:
            self._client = genai.Client(api_key=self.api_key)
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
        
        # 안전 설정을 최대한 완화 (google-genai 방식)
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"}
        ]
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Gemini API call attempt {attempt + 1}/{max_retries}")
                
                # custom_items를 기반으로 시스템 프롬프트 생성
                system_prompt = generate_system_prompt_from_docx(
                    file_content=(custom_items or []),
                    template_type=template_type
                )
                
                logger.info(f"Generating content with text length: {len(text_content)}")
                
                # google-genai 방식으로 요청
                response = await self._client.aio.models.generate_content(
                    model="models/gemini-2.5-pro",
                    contents=[
                        {"role": "model", "parts": [{"text": system_prompt}]},
                        {"role": "user", "parts": [{"text": text_content}]}
                    ],
                    config={
                        "safety_settings": safety_settings,
                        "temperature": 0.1,
                        "max_output_tokens": 65535
                    }
                )
                
                # 응답 상세 로깅
                logger.info(f"Response candidates count: {len(response.candidates) if response.candidates else 0}")
                
                # 응답 검증 개선
                if response.candidates and len(response.candidates) > 0:
                    candidate = response.candidates[0]
                    finish_reason = candidate.finish_reason if hasattr(candidate, 'finish_reason') else "UNKNOWN"
                    
                    logger.info(f"Candidate finish_reason: {finish_reason}")
                    
                    # STOP은 정상 완료이므로 처리
                    if finish_reason in ["STOP", "MAX_TOKENS"]:
                        if candidate.content and candidate.content.parts and len(candidate.content.parts) > 0:
                            text_content_result = candidate.content.parts[0].text
                            if text_content_result and text_content_result.strip():
                                logger.info(f"Gemini API call successful on attempt {attempt + 1}")
                                return text_content_result.strip()
                            else:
                                logger.warning("Response text is empty or None")
                                raise Exception("Response text is empty")
                        else:
                            logger.warning("No content parts in response")
                            raise Exception("No content parts in response")
                    
                    # 안전 필터링인 경우
                    elif finish_reason == "SAFETY":
                        logger.warning("Content blocked by safety filter")
                        raise Exception(f"Content blocked by safety filter (finish_reason: {finish_reason})")
                    
                    # 기타 이유
                    else:
                        logger.warning(f"Unexpected finish_reason: {finish_reason}")
                        raise Exception(f"Unexpected finish_reason: {finish_reason}")
                else:
                    logger.warning("No candidates in response")
                    raise Exception("No candidates in response")
                
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

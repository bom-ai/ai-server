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
        
        # 모델 우선순위 리스트 (높은 성능 -> 낮은 성능 순)
        self.model_fallback_chain = [
            "models/gemini-2.5-pro",
            "models/gemini-2.5-flash", 
            "models/gemini-1.5-pro"
        ]
        
        # 모델별 성공률 추적
        self.model_stats = {
            "models/gemini-2.5-pro": {"attempts": 0, "successes": 0},
            "models/gemini-2.5-flash": {"attempts": 0, "successes": 0},
            "models/gemini-1.5-pro": {"attempts": 0, "successes": 0}
        }
    
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
        
        # 각 모델을 순차적으로 시도
        for model_index, model_name in enumerate(self.model_fallback_chain):
            try:
                logger.info(f"Trying model: {model_name} (attempt {model_index + 1}/{len(self.model_fallback_chain)})")
                print(f"Trying model: {model_name} (attempt {model_index + 1}/{len(self.model_fallback_chain)})")
                
                result = await self._try_model_analysis(
                    model_name=model_name,
                    text_content=text_content,
                    custom_items=custom_items,
                    template_type=template_type,
                    logger=logger
                )
                
                if result:
                    logger.info(f"Successfully analyzed with model: {model_name}")
                    return result
                    
            except Exception as e:
                logger.error(f"Model {model_name} failed: {str(e)}")
                
                # 마지막 모델도 실패한 경우
                if model_index == len(self.model_fallback_chain) - 1:
                    logger.error("All models failed, returning fallback response")
                    return self._generate_fallback_response(custom_items, str(e))
                
                # 다음 모델 시도 전 대기
                await asyncio.sleep(2)
                continue
        
        # 모든 모델 실패 시 fallback
        return self._generate_fallback_response(custom_items, "All models exhausted")

    async def _try_model_analysis(
        self,
        model_name: str,
        text_content: str,
        custom_items: Optional[List[str]],
        template_type: str,
        logger,
        max_retries: int = 2
    ) -> Optional[str]:
        """특정 모델로 분석을 시도합니다."""
        
        # 모델별 설정 조정
        model_config = self._get_model_config(model_name)
        
        # 안전 설정을 최대한 완화
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"}
        ]
        
        # 시도 횟수 기록
        if model_name in self.model_stats:
            self.model_stats[model_name]["attempts"] += 1
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Model {model_name} attempt {attempt + 1}/{max_retries}")
                
                # custom_items를 기반으로 시스템 프롬프트 생성
                system_prompt = generate_system_prompt_from_docx(
                    file_content=(custom_items or []),
                    template_type=template_type
                )
                
                # API 호출
                response = await self._client.aio.models.generate_content(
                    model=model_name,
                    contents=[
                        {"role": "model", "parts": [{"text": system_prompt}]},
                        {"role": "user", "parts": [{"text": text_content}]}
                    ],
                    config={
                        "safety_settings": safety_settings,
                        **model_config
                    }
                )
                
                # 응답 검증
                if response.candidates and len(response.candidates) > 0:
                    candidate = response.candidates[0]
                    finish_reason = candidate.finish_reason if hasattr(candidate, 'finish_reason') else "UNKNOWN"
                    
                    logger.info(f"Model {model_name} finish_reason: {finish_reason}")
                    
                    # 성공적인 응답 처리
                    if finish_reason in ["STOP", "MAX_TOKENS"]:
                        if (candidate.content and 
                            candidate.content.parts and 
                            len(candidate.content.parts) > 0 and
                            candidate.content.parts[0].text):
                            
                            result_text = candidate.content.parts[0].text.strip()
                            if result_text:
                                logger.info(f"Model {model_name} successful response")
                                
                                # 성공 시 기록
                                if model_name in self.model_stats:
                                    self.model_stats[model_name]["successes"] += 1
                                
                                return result_text
                    
                    # STOP 에러나 기타 문제인 경우 다음 시도
                    logger.warning(f"Model {model_name} finish_reason: {finish_reason}, trying next attempt or model")
                    print(f"Model {model_name} finish_reason: {finish_reason}, trying next attempt or model")
                    
                    # STOP 에러가 반복되면 다음 모델로
                    if finish_reason == "STOP" and attempt == max_retries - 1:
                        raise Exception(f"Model {model_name} consistently returning STOP without content")
                        
                else:
                    logger.warning(f"Model {model_name} returned no candidates")
                
                # 재시도 전 대기
                if attempt < max_retries - 1:
                    await asyncio.sleep(3)
                    
            except Exception as e:
                logger.error(f"Model {model_name} attempt {attempt + 1} failed: {str(e)}")
                
                # Rate limiting인 경우 더 오래 대기
                if "quota" in str(e).lower() or "rate" in str(e).lower() or "429" in str(e):
                    if attempt < max_retries - 1:
                        wait_time = 10 * (attempt + 1)
                        logger.info(f"Rate limiting for {model_name}, waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                        continue
                
                # 마지막 시도인 경우 예외 발생
                if attempt == max_retries - 1:
                    raise
                
                await asyncio.sleep(2)
        
        return None

    def _get_model_config(self, model_name: str) -> dict:
        """모델별 최적화된 설정을 반환합니다."""
        base_config = {
            "temperature": 0.1,
            "max_output_tokens": 65535,
        }
        if "gemini-2.5-pro" in model_name:
            return {
                "temperature": 0.1,
                "max_output_tokens": 65535,
            }
        elif "gemini-2.5-flash" in model_name:
            return {
                "temperature": 0.1,
                "max_output_tokens": 65535,
            }
        elif "gemini-1.5-pro" in model_name:
            return {
                "temperature": 0.1,
                "max_output_tokens": 8192,
            }
        
        return base_config

    def _generate_fallback_response(self, custom_items: Optional[List[str]], error_msg: str) -> str:
        """모든 모델이 실패했을 때 fallback 응답을 생성합니다."""
        items_text = ""
        if custom_items:
            items_text = f"\n\n요청된 분석 항목:\n" + "\n".join([f"- {item}" for item in custom_items[:10]])
        
        return f"""
            [자동 분석 제한됨]
            죄송합니다. 현재 AI 분석 서비스에 일시적인 문제가 발생했습니다.

            상황 정보:
            - 여러 AI 모델을 시도했으나 모두 실패
            - 마지막 오류: {error_msg}
            - 음성 인식은 정상적으로 완료됨

            권장사항:
            1. 잠시 후 다시 시도해주세요
            2. 음성 내용을 수동으로 검토하세요
            3. 필요시 고객 지원팀에 문의하세요 
            {items_text}

            이 문제는 일시적이며, 시스템이 곧 정상화될 예정입니다.
            """


# 전역 Gemini 서비스 인스턴스
gemini_service = GeminiService()

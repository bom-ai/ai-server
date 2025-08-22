"""
OpenAI GPT API 서비스
"""
import asyncio
from openai import OpenAI
from fastapi import HTTPException
from typing import List, Optional, Literal, Dict
import logging
from tenacity import (
    retry,
    stop_after_attempt,
    retry_if_exception_type,
    before_sleep_log,
    after_log,
)

from app.utils.rate_limit_manager import RateLimitManager, create_openai_rate_limiter
from app.core.config import settings
from app.core.prompts import generate_system_prompt_from_docx

# 모듈 레벨에서 로거 생성
logger = logging.getLogger(__name__)


class OpenAIService:
    """OpenAI GPT API 서비스"""
    
    def __init__(self):
        self.api_key = settings.openai_api_key
        self._client = None
        self._initialized = False
        self.rate_limit_manager = create_openai_rate_limiter()
        
        # 모델 우선순위 리스트 (높은 성능 -> 낮은 성능 순)
        self.model_fallback_chain = [
            "gpt-5",
            "gpt-4o"
        ]
        
        # 모델별 성공률 추적
        self.model_stats = {
            "gpt-5": {"attempts": 0, "successes": 0, "rate_limited": 0},
            "gpt-4o": {"attempts": 0, "successes": 0, "rate_limited": 0}
        }
    
    def _initialize(self) -> bool:
        """OpenAI API를 초기화합니다."""
        if not self.api_key:
            logger.error("OpenAI API key not provided")
            return False
        
        try:
            self._client = OpenAI(api_key=self.api_key)
            self._initialized = True
            logger.info("OpenAI client initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            return False

    async def analyze_text(
        self,
        text_content: str,
        custom_items: Optional[List[str]] = None,
        template_type: Literal["raw", "refined"] = "refined"
    ) -> str:
        """OpenAI GPT API - custom_items를 사용하여 텍스트를 분석합니다."""
        
        if not self._initialized and not self._initialize():
            raise HTTPException(
                status_code=500, 
                detail="OpenAI API 키가 설정되지 않았습니다."
            )
        
        logger.info(f"Starting text analysis with {len(self.model_fallback_chain)} models")
        logger.info(f"Text length: {len(text_content)} characters")
        
        # 각 모델을 순차적으로 시도
        for model_index, model_name in enumerate(self.model_fallback_chain):
            try:
                logger.info(f"Trying model: {model_name} (attempt {model_index + 1}/{len(self.model_fallback_chain)})")
                
                result = await self._try_model_analysis(
                    model_name=model_name,
                    text_content=text_content,
                    custom_items=custom_items,
                    template_type=template_type
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
                
                # 다음 모델로 즉시 이동
                logger.info(f"Moving to next model after {model_name} failure")
                continue
        
        # 모든 모델 실패 시 fallback
        return self._generate_fallback_response(custom_items, "All models exhausted")

    async def _try_model_analysis(
        self,
        model_name: str,
        text_content: str,
        custom_items: Optional[List[str]],
        template_type: str
    ) -> Optional[str]:  # logger 매개변수 제거
        """특정 모델로 분석을 시도합니다."""
        
        logger.info(f"Starting analysis attempt with model: {model_name}")
        
        # 시도 횟수 기록
        if model_name in self.model_stats:
            self.model_stats[model_name]["attempts"] += 1
        
        try:
            # custom_items를 기반으로 시스템 프롬프트 생성
            system_prompts = generate_system_prompt_from_docx(
                file_content=(custom_items or []),
                template_type=template_type
            )
            
            # Tenacity를 사용한 재시도 API 호출
            result = await self._make_api_call_with_retry(
                model_name=model_name,
                system_prompts=system_prompts,
                text_content=text_content
            )
            
            if result:
                # 성공 시 기록
                if model_name in self.model_stats:
                    self.model_stats[model_name]["successes"] += 1
                return result
                
        except Exception as e:
            logger.error(f"Model {model_name} analysis failed after all retries: {str(e)}")
            
        return None

    @retry(
        stop=stop_after_attempt(3),
        wait=lambda retry_state: RateLimitManager.custom_wait_strategy(retry_state),
        retry=retry_if_exception_type((Exception,)),
        before_sleep=before_sleep_log(logger, logging.INFO),
        after=after_log(logger, logging.INFO)
    )
    async def _make_api_call_with_retry(
        self,
        model_name: str,
        system_prompts: Dict[str, str],
        text_content: str
    ) -> Optional[str]:  # logger 매개변수 제거
        """Tenacity를 사용한 재시도 로직이 포함된 API 호출"""
        
        # Rate Limit 관리 - tiktoken을 사용한 정확한 토큰 계산
        total_text = system_prompts.analysis_prompt + text_content
        estimated_tokens = self.rate_limit_manager.estimate_tokens(total_text, model_name)
        
        logger.info(f"Accurate token count for {model_name}: {estimated_tokens} tokens")
        
        # 에러 방지를 위해 텍스트 반으로 자르기
        (text_content_p1, text_content_p2) = self.rate_limit_manager.split_transcript(text_content)
        
        # Rate Limit 대기
        await self.rate_limit_manager.wait_for_rate_limit(model_name, estimated_tokens)
        
        # 변수 초기화 (중요!)
        result_text_p1 = None
        result_text_p2 = None
        
        # 세마포어로 동시성 제어
        async with self.rate_limit_manager.acquire_slot_context(model_name):
            logger.info(f"Making API call to {model_name} with {estimated_tokens} estimated tokens")
            logger.info(f"Available slots for {model_name}: {self.rate_limit_manager.get_available_slots(model_name)}")
            
            try:
                # ========== Part 1 분석 ==========
                logger.info(f"Starting Part 1 analysis for {model_name}")
                response_p1 = await asyncio.to_thread(
                    self._client.responses.create,
                    model=model_name,
                    input=[
                        {"role": "developer", "content": system_prompts.analysis_prompt},
                        {"role": "user", "content": text_content_p1}
                    ]
                )
                
                # Part 1 응답 검증
                if response_p1.output and len(response_p1.output) > 0:
                    last_output = response_p1.output[-1]
                    if hasattr(last_output, 'type') and last_output.type == 'message':
                        status = response_p1.status
                        logger.info(f"Part 1 Model {model_name} status: {status}")
                        
                        if status == "completed":
                            if (hasattr(last_output, 'content') and 
                                last_output.content and 
                                len(last_output.content) > 0):
                                
                                content_item = last_output.content[0]
                                if hasattr(content_item, 'text') and content_item.text:
                                    result_text_p1 = content_item.text.strip()
                                    logger.info(f"Part 1 SUCCESS: {len(result_text_p1)} characters")
                                else:
                                    raise Exception(f"Part 1: No text content")
                            else:
                                raise Exception(f"Part 1: No content in message")
                        else:
                            raise Exception(f"Part 1: Model returned status: {status}")
                    else:
                        raise Exception(f"Part 1: Invalid output type")
                else:
                    raise Exception(f"Part 1: No output from model")

                # ========== Part 2 분석 ==========
                logger.info(f"Starting Part 2 analysis for {model_name}")
                response_p2 = await asyncio.to_thread(  # 타이포 수정
                    self._client.responses.create,
                    model=model_name,
                    input=[
                        {"role": "developer", "content": system_prompts.analysis_prompt},
                        {"role": "user", "content": text_content_p2}
                    ]
                )
                
                # Part 2 응답 검증
                if response_p2.output and len(response_p2.output) > 0:
                    last_output = response_p2.output[-1]
                    if hasattr(last_output, 'type') and last_output.type == 'message':
                        status = response_p2.status
                        logger.info(f"Part 2 Model {model_name} status: {status}")
                        
                        if status == "completed":
                            if (hasattr(last_output, 'content') and 
                                last_output.content and 
                                len(last_output.content) > 0):
                                
                                content_item = last_output.content[0]
                                if hasattr(content_item, 'text') and content_item.text:
                                    result_text_p2 = content_item.text.strip()
                                    logger.info(f"Part 2 SUCCESS: {len(result_text_p2)} characters")
                                else:
                                    raise Exception(f"Part 2: No text content")
                            else:
                                raise Exception(f"Part 2: No content in message")
                        else:
                            raise Exception(f"Part 2: Model returned status: {status}")
                    else:
                        raise Exception(f"Part 2: Invalid output type")
                else:
                    raise Exception(f"Part 2: No output from model")
                
                # ========== 결과 검증 ==========
                if not result_text_p1 or not result_text_p2:
                    raise Exception(f"Missing analysis results: p1={bool(result_text_p1)}, p2={bool(result_text_p2)}")

                # ========== 결과 병합 ==========
                logger.info(f"Starting merge analysis for {model_name}")
                combined_analysis_input = f"""
[ANALYSIS PART 1 START]
{result_text_p1}
[ANALYSIS PART 1 END]

[ANALYSIS PART 2 START]
{result_text_p2}
[ANALYSIS PART 2 END]
"""

                response_merge = await asyncio.to_thread(  # 타이포 수정
                    self._client.responses.create,
                    model=model_name,
                    input=[
                        {"role": "developer", "content": system_prompts.merge_prompt},
                        {"role": "user", "content": combined_analysis_input}
                    ]
                )

                # 병합 응답 검증
                if response_merge.output and len(response_merge.output) > 0:
                    last_output = response_merge.output[-1]
                    if hasattr(last_output, 'type') and last_output.type == 'message':
                        status = response_merge.status
                        logger.info(f"Merge Model {model_name} status: {status}")
                        
                        if status == "completed":
                            if (hasattr(last_output, 'content') and 
                                last_output.content and 
                                len(last_output.content) > 0):
                                
                                content_item = last_output.content[0]
                                if hasattr(content_item, 'text') and content_item.text:
                                    result_text = content_item.text.strip()
                                    if result_text:
                                        logger.info(f"Model {model_name} COMPLETE SUCCESS: {len(result_text)} characters")
                                        return result_text
                                    else:
                                        raise Exception(f"Merge: Empty result")
                                else:
                                    raise Exception(f"Merge: No text content")
                            else:
                                raise Exception(f"Merge: No content in message")
                        else:
                            raise Exception(f"Merge: Model returned status: {status}")
                    else:
                        raise Exception(f"Merge: Invalid output type")
                else:
                    raise Exception(f"Merge: No output from model")
            
            except Exception as e:
                error_msg = str(e)
                
                # Rate Limit 통계 기록
                if self.rate_limit_manager.is_rate_limit_error(e):
                    if model_name in self.model_stats:
                        self.model_stats[model_name]["rate_limited"] += 1
                    logger.warning(f"Rate limit hit for {model_name}: {error_msg}")
                
                logger.error(f"API call failed for {model_name}: {error_msg}")
                raise

    def _generate_fallback_response(self, custom_items: Optional[List[str]], error_msg: str) -> str:
        """모든 모델이 실패했을 때 fallback 응답을 생성합니다."""
        logger.warning(f"Generating fallback response due to: {error_msg}")
        
        items_text = ""
        if custom_items:
            items_text = f"\n\n요청된 분석 항목:\n" + "\n".join([f"- {item}" for item in custom_items[:10]])
        
        return f"""[자동 분석 제한됨]
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

이 문제는 일시적이며, 시스템이 곧 정상화될 예정입니다."""


# 전역 OpenAI 서비스 인스턴스
openai_service = OpenAIService()

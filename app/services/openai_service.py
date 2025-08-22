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
            return False
        
        try:
            self._client = OpenAI(api_key=self.api_key)
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
        """OpenAI GPT API - custom_items를 사용하여 텍스트를 분석합니다."""
        logger = logging.getLogger(__name__)
        
        if not self._initialized and not self._initialize():
            raise HTTPException(
                status_code=500, 
                detail="OpenAI API 키가 설정되지 않았습니다."
            )
        
        # 각 모델을 순차적으로 시도
        for model_index, model_name in enumerate(self.model_fallback_chain):
            try:
                logger.info(f"Trying model: {model_name} (attempt {model_index + 1}/{len(self.model_fallback_chain)})")
                # print(f"Trying model: {model_name} (attempt {model_index + 1}/{len(self.model_fallback_chain)})")
                
                result = await self._try_model_analysis(
                    model_name=model_name,
                    text_content=text_content,
                    custom_items=custom_items,
                    template_type=template_type,
                    logger=logger
                )
                
                if result:
                    logger.info(f"Successfully analyzed with model: {model_name}")
                    print(f"Successfully analyzed with model: {model_name}")
                    return result
                    
            except Exception as e:
                logger.error(f"Model {model_name} failed: {str(e)}")
                print(f"Model {model_name} failed: {str(e)}")
                
                # 마지막 모델도 실패한 경우
                if model_index == len(self.model_fallback_chain) - 1:
                    logger.error("All models failed, returning fallback response")
                    print("All models failed, returning fallback response")
                    return self._generate_fallback_response(custom_items, str(e))
                
                # 다음 모델로 즉시 이동 (Tenacity가 이미 적절히 대기했음)
                continue
        
        # 모든 모델 실패 시 fallback
        return self._generate_fallback_response(custom_items, "All models exhausted")

    async def _try_model_analysis(
        self,
        model_name: str,
        text_content: str,
        custom_items: Optional[List[str]],
        template_type: str,
        logger
    ) -> Optional[str]:
        """특정 모델로 분석을 시도합니다."""
        
        # 시도 횟수 기록
        if model_name in self.model_stats:
            self.model_stats[model_name]["attempts"] += 1
        
        try:
            # custom_items를 기반으로 시스템 프롬프트 생성 (분석용과 병합용 두 개 반환)
            system_prompts = generate_system_prompt_from_docx(
                file_content=(custom_items or []),
                template_type=template_type
            )
            
            # Tenacity를 사용한 재시도 API 호출
            result = await self._make_api_call_with_retry(
                model_name=model_name,
                system_prompts=system_prompts,
                text_content=text_content,
                logger=logger
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
        stop=stop_after_attempt(3),  # 최대 3번 재시도
        wait=lambda retry_state: RateLimitManager.custom_wait_strategy(retry_state),
        retry=retry_if_exception_type((Exception,)),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.INFO),
        after=after_log(logging.getLogger(__name__), logging.INFO)
    )
    async def _make_api_call_with_retry(
        self,
        model_name: str,
        system_prompts: Dict[str, str],
        text_content: str,
        logger
    ) -> Optional[str]:
        """Tenacity를 사용한 재시도 로직이 포함된 API 호출"""
        
        # Rate Limit 관리 - tiktoken을 사용한 정확한 토큰 계산
        total_text = system_prompts.analysis_prompt + text_content
        estimated_tokens = self.rate_limit_manager.estimate_tokens(total_text, model_name)
        
        logger.info(f"Accurate token count for {model_name}: {estimated_tokens} tokens")
        print(f"Accurate token count for {model_name}: {estimated_tokens} tokens")
        
        # 에러 방지를 위해 텍스트 반으로 자르기 (수정된 부분)
        (text_content_p1, text_content_p2) = self.rate_limit_manager.split_transcript(text_content)
        
        # Rate Limit 대기
        await self.rate_limit_manager.wait_for_rate_limit(model_name, estimated_tokens)
        
        # 세마포어로 동시성 제어 (안전한 context manager 사용)
        async with self.rate_limit_manager.acquire_slot_context(model_name):
            logger.info(f"Making API call to {model_name} with {estimated_tokens} estimated tokens")
            # print(f"Making API call to {model_name} with {estimated_tokens} estimated tokens")
            logger.info(f"Available slots for {model_name}: {self.rate_limit_manager.get_available_slots(model_name)}")
            # print(f"Available slots for {model_name}: {self.rate_limit_manager.get_available_slots(model_name)}")
            
            try:
                # OpenAI API 호출 -> 앞쪽 절반 part 분석 수행
                response_p1 = await asyncio.to_thread(
                    self._client.responses.create,
                    model=model_name,
                    input=[
                        {"role": "developer", "content": system_prompts.analysis_prompt},
                        {"role": "user", "content": text_content_p1}
                    ]
                )
                
                # 응답 검증 (responses API)
                if response_p1.output and len(response_p1.output) > 0:
                    # 마지막 출력이 메시지인지 확인
                    last_output = response_p1.output[-1]
                    if hasattr(last_output, 'type') and last_output.type == 'message':
                        status = response_p1.status
                        
                        logger.info(f"Model {model_name} status: {status}")
                        
                        # 성공적인 응답 처리
                        if status == "completed":
                            if (hasattr(last_output, 'content') and 
                                last_output.content and 
                                len(last_output.content) > 0):
                                
                                # 텍스트 내용 추출
                                content_item = last_output.content[0]
                                if hasattr(content_item, 'text') and content_item.text:
                                    result_text_p1 = content_item.text.strip()
                        
                        # 기타 문제인 경우 예외 발생하여 재시도
                        raise Exception(f"Model {model_name} returned status: {status}")
                            
                else:
                    raise Exception(f"Model {model_name} returned no output")

                # OpenAI API 호출 -> 뒷쪽 절반 part 분석 수행
                rseponse_p2 = await asyncio.to_thread(
                    self._client.responses.create,
                    model=model_name,
                    input=[
                        {"role": "developer", "content": system_prompts.analysis_prompt},
                        {"role": "user", "content": text_content_p2}
                    ]
                )
                
                # 응답 검증 (responses API)
                if rseponse_p2.output and len(rseponse_p2.output) > 0:
                    # 마지막 출력이 메시지인지 확인
                    last_output = rseponse_p2.output[-1]
                    if hasattr(last_output, 'type') and last_output.type == 'message':
                        status = rseponse_p2.status
                        
                        logger.info(f"Model {model_name} status: {status}")
                        
                        # 성공적인 응답 처리
                        if status == "completed":
                            if (hasattr(last_output, 'content') and 
                                last_output.content and 
                                len(last_output.content) > 0):
                                
                                # 텍스트 내용 추출
                                content_item = last_output.content[0]
                                if hasattr(content_item, 'text') and content_item.text:
                                    result_text_p2 = content_item.text.strip()
                        
                        # 기타 문제인 경우 예외 발생하여 재시도
                        raise Exception(f"Model {model_name} returned status: {status}")
                
                combined_analysis_input = f"""
                [ANALYSIS PART 1 START]
                {result_text_p1}
                [ANALYSIS PART 1 END]

                [ANALYSIS PART 2 START]
                {result_text_p2}
                [ANALYSIS PART 2 END]
                """

                rseponse = await asyncio.to_thread(
                    self._client.responses.create,
                    model=model_name,
                    input=[
                        {"role": "developer", "content": system_prompts.merge_prompt},
                        {"role": "user", "content": combined_analysis_input}
                    ]
                )

                # 응답 검증 (responses API)
                if rseponse.output and len(rseponse.output) > 0:
                    # 마지막 출력이 메시지인지 확인
                    last_output = rseponse.output[-1]
                    if hasattr(last_output, 'type') and last_output.type == 'message':
                        status = rseponse.status
                        
                        logger.info(f"Model {model_name} status: {status}")
                        
                        # 성공적인 응답 처리
                        if status == "completed":
                            if (hasattr(last_output, 'content') and 
                                last_output.content and 
                                len(last_output.content) > 0):
                                
                                # 텍스트 내용 추출
                                content_item = last_output.content[0]
                                if hasattr(content_item, 'text') and content_item.text:
                                    result_text = content_item.text.strip()
                                    if result_text:
                                        logger.info(f"Model {model_name} successful response")
                                        print(f"Model {model_name} successful response")
                                        return result_text
                        
                        # 기타 문제인 경우 예외 발생하여 재시도
                        raise Exception(f"Model {model_name} returned status: {status}")
            
            except Exception as e:
                error_msg = str(e)
                
                # Rate Limit 통계 기록 (수정된 부분)
                if self.rate_limit_manager.is_rate_limit_error(e):
                    if model_name in self.model_stats:
                        self.model_stats[model_name]["rate_limited"] += 1
                    logger.warning(f"Rate limit hit for {model_name}: {error_msg}")
                
                logger.error(f"API call failed for {model_name}: {error_msg}")
                raise  # Tenacity가 재시도를 처리함

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


# 전역 OpenAI 서비스 인스턴스
openai_service = OpenAIService()

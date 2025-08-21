"""
OpenAI GPT API 서비스
"""
import asyncio
from contextlib import asynccontextmanager
from openai import OpenAI
from fastapi import HTTPException
from typing import List, Optional, Literal
import logging
from tenacity import (
    retry,
    stop_after_attempt,
    retry_if_exception_type,
    before_sleep_log,
    after_log,
)
import time

from app.core.config import settings
from app.core.prompts import generate_system_prompt_from_docx


def is_rate_limit_error(exception):
    """Rate Limit 에러인지 확인"""
    error_msg = str(exception)
    return ("429" in error_msg or 
            "rate_limit_exceeded" in error_msg or
            "tokens per min" in error_msg or
            "requests per min" in error_msg)


def get_rate_limit_wait_time(exception):
    """Rate Limit 에러 타입에 따른 대기 시간 결정"""
    error_msg = str(exception)
    if "tokens per min" in error_msg:
        return 60  # TPM 에러는 1분 대기
    elif "requests per min" in error_msg:
        return 30  # RPM 에러는 30초 대기
    else:
        return 20  # 기타 429 에러는 20초 대기


def custom_wait_strategy(retry_state):
    """커스텀 대기 전략: Rate Limit 에러는 특별 처리, 나머지는 지수 백오프"""
    if retry_state.outcome and retry_state.outcome.failed:
        exception = retry_state.outcome.exception()
        if is_rate_limit_error(exception):
            wait_time = get_rate_limit_wait_time(exception)
            logging.getLogger(__name__).warning(
                f"Rate limit detected, waiting {wait_time}s (attempt {retry_state.attempt_number})"
            )
            return wait_time
    
    # Rate Limit가 아닌 경우 지수 백오프 (최소 4초, 최대 60초)
    base_wait = min(60, 4 * (2 ** (retry_state.attempt_number - 1)))
    return base_wait


class RateLimitManager:
    """OpenAI API Rate Limit 관리자"""
    
    def __init__(self):
        # 모델별 동시 요청 제한 (세마포어)
        self.semaphores = {
            "gpt-5": asyncio.Semaphore(2),  # gpt-5는 동시 요청 2개로 제한
            "gpt-4o": asyncio.Semaphore(3),  # gpt-4o는 동시 요청 3개로 제한
        }
        
        # 모델별 최근 요청 시간 추적 (토큰/분 제한 관리)
        self.last_request_times = {
            "gpt-5": [],
            "gpt-4o": []
        }
        
        # 모델별 토큰 제한 정보
        self.token_limits = {
            "gpt-5": {"tpm": 30000, "rpm": 500},  # Tokens Per Minute, Requests Per Minute
            "gpt-4o": {"tpm": 30000, "rpm": 500}
        }
    
    async def acquire_slot(self, model_name: str):
        """모델별 슬롯 획득 (await 필요)"""
        if model_name in self.semaphores:
            await self.semaphores[model_name].acquire()
        
    def release_slot(self, model_name: str):
        """모델별 슬롯 해제"""
        if model_name in self.semaphores:
            self.semaphores[model_name].release()
            
    def get_available_slots(self, model_name: str) -> int:
        """모델별 사용 가능한 슬롯 수 반환"""
        if model_name in self.semaphores:
            return self.semaphores[model_name]._value
        return 0
    
    @asynccontextmanager
    async def acquire_slot_context(self, model_name: str):
        """세마포어 슬롯을 안전하게 획득/해제하는 컨텍스트 매니저"""
        await self.acquire_slot(model_name)
        try:
            yield
        finally:
            self.release_slot(model_name)
    
    def estimate_tokens(self, text: str) -> int:
        """텍스트의 대략적인 토큰 수 추정 (1토큰 ≈ 4글자)"""
        return len(text) // 4
    
    async def wait_for_rate_limit(self, model_name: str, estimated_tokens: int):
        """Rate Limit을 고려한 사전 대기 (예방적 조치)"""
        if model_name not in self.token_limits:
            return
        
        current_time = time.time()
        limit_info = self.token_limits[model_name]
        
        # 1분 이내의 요청들만 유지
        self.last_request_times[model_name] = [
            req_time for req_time in self.last_request_times[model_name] 
            if current_time - req_time < 60
        ]
        
        recent_requests = len(self.last_request_times[model_name])
        
        # RPM 제한의 90%에 도달하면 대기
        if recent_requests >= limit_info["rpm"] * 0.9:
            wait_time = 60 - (current_time - min(self.last_request_times[model_name])) + 1
            if wait_time > 0:
                logging.info(f"Approaching RPM limit for {model_name}, preemptive wait {wait_time:.2f}s")
                print(f"Approaching RPM limit for {model_name}, preemptive wait {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
        
        # 추정 토큰이 TPM 제한의 90%를 초과하면 경고만 로그
        if estimated_tokens > limit_info["tpm"] * 0.9:
            logging.warning(f"Large request for {model_name} ({estimated_tokens} tokens)")
            print(f"Large request for {model_name} ({estimated_tokens} tokens)")
        
        # 요청 시간 기록
        self.last_request_times[model_name].append(current_time)


class OpenAIService:
    """OpenAI GPT API 서비스"""
    
    def __init__(self):
        self.api_key = settings.openai_api_key
        self._client = None
        self._initialized = False
        self.rate_limit_manager = RateLimitManager()
        
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

    @retry(
        stop=stop_after_attempt(5),  # 최대 5번 재시도
        wait=custom_wait_strategy,  # 커스텀 대기 전략 사용
        retry=retry_if_exception_type((Exception,)),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.INFO),
        after=after_log(logging.getLogger(__name__), logging.INFO)
    )
    async def _make_api_call_with_retry(
        self,
        model_name: str,
        system_prompt: str,
        text_content: str,
        logger
    ) -> Optional[str]:
        """Tenacity를 사용한 재시도 로직이 포함된 API 호출"""
        
        # Rate Limit 관리
        total_text = system_prompt + text_content
        estimated_tokens = self.rate_limit_manager.estimate_tokens(total_text)
        
        # 토큰 수가 너무 많으면 텍스트 축소
        if estimated_tokens > 28000:  # TPM: 30000 토큰
            logger.warning(f"Text too long ({estimated_tokens} tokens), truncating...")
            print(f"Text too long ({estimated_tokens} tokens), truncating...")
            # 텍스트 길이를 80%로 축소
            max_length = int(len(text_content) * 0.8)
            text_content = text_content[:max_length] + "\n\n[텍스트가 길어 일부 내용이 생략되었습니다.]"
            estimated_tokens = self.rate_limit_manager.estimate_tokens(system_prompt + text_content)
            logger.info(f"Truncated to {estimated_tokens} tokens")
            print(f"Truncated to {estimated_tokens} tokens")
        
        # Rate Limit 대기
        await self.rate_limit_manager.wait_for_rate_limit(model_name, estimated_tokens)
        
        # 세마포어로 동시성 제어 (안전한 context manager 사용)
        async with self.rate_limit_manager.acquire_slot_context(model_name):
            logger.info(f"Making API call to {model_name} with {estimated_tokens} estimated tokens")
            print(f"Making API call to {model_name} with {estimated_tokens} estimated tokens")
            logger.info(f"Available slots for {model_name}: {self.rate_limit_manager.get_available_slots(model_name)}")
            print(f"Available slots for {model_name}: {self.rate_limit_manager.get_available_slots(model_name)}")
            
            try:
                # OpenAI API 호출 -> 먼저 responses API 시도 (사용자가 제공한 코드 기반)
                try:
                    response = await asyncio.to_thread(
                        self._client.responses.create,
                        model=model_name,
                        input=[
                            {"role": "developer", "content": system_prompt},
                            {"role": "user", "content": text_content}
                        ]
                    )
                    
                    # 응답 검증 (responses API)
                    if response.output and len(response.output) > 0:
                        # 마지막 출력이 메시지인지 확인
                        last_output = response.output[-1]
                        if hasattr(last_output, 'type') and last_output.type == 'message':
                            status = response.status
                            
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
                                            return result_text
                            
                            # 기타 문제인 경우 예외 발생하여 재시도
                            raise Exception(f"Model {model_name} returned status: {status}")
                                
                    else:
                        raise Exception(f"Model {model_name} returned no output")
                        
                except AttributeError:
                    # responses API가 없는 경우 일반 chat API 사용
                    logger.info(f"Model {model_name}: responses API not available, trying chat API")
                    response = await asyncio.to_thread(
                        self._client.chat.completions.create,
                        model=model_name,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": text_content}
                        ],
                        temperature=0.1,
                        max_tokens=min(4096, 30000 - estimated_tokens)  # 응답 토큰 제한
                    )
                    
                    # 응답 검증 (chat API)
                    if response.choices and len(response.choices) > 0:
                        choice = response.choices[0]
                        finish_reason = choice.finish_reason
                        
                        logger.info(f"Model {model_name} finish_reason: {finish_reason}")
                        
                        # 성공적인 응답 처리
                        if finish_reason in ["stop", "length"]:
                            if choice.message and choice.message.content:
                                result_text = choice.message.content.strip()
                                if result_text:
                                    logger.info(f"Model {model_name} successful response")
                                    return result_text
                        
                        # 기타 문제인 경우 예외 발생하여 재시도
                        raise Exception(f"Model {model_name} finish_reason: {finish_reason}")
                            
                    else:
                        raise Exception(f"Model {model_name} returned no choices")
            
            except Exception as e:
                error_msg = str(e)
                
                # Rate Limit 통계 기록
                if is_rate_limit_error(e):
                    if model_name in self.model_stats:
                        self.model_stats[model_name]["rate_limited"] += 1
                    logger.warning(f"Rate limit hit for {model_name}: {error_msg}")
                
                logger.error(f"API call failed for {model_name}: {error_msg}")
                raise  # Tenacity가 재시도를 처리함

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
            # custom_items를 기반으로 시스템 프롬프트 생성
            system_prompt = generate_system_prompt_from_docx(
                file_content=(custom_items or []),
                template_type=template_type
            )
            
            # Tenacity를 사용한 재시도 API 호출
            result = await self._make_api_call_with_retry(
                model_name=model_name,
                system_prompt=system_prompt,
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

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
import tiktoken

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

def split_transcript_with_overlap(full_transcript, overlap_lines=5):
    """
    전체 녹취록 텍스트를 두 부분으로 나누고, 두 번째 부분에 문맥 유지를 위한 중첩 부분을 추가합니다.

    :param full_transcript: 전체 녹취록 문자열
    :param overlap_lines: 겹치게 할 라인 수 (기본값: 5)
    :return: (첫 번째 부분, 겹쳐진 두 번째 부분) 튜플
    """
    lines = full_transcript.strip().split('\n')
    if len(lines) < 20: # 너무 짧으면 굳이 나누지 않음
        return full_transcript, ""

    # 전체 라인의 약 절반 지점 찾기
    mid_point = len(lines) // 2

    # 첫 번째 부분
    part1_lines = lines[:mid_point]
    part1 = '\n'.join(part1_lines)

    # 중첩될 부분 (첫 번째 부분의 마지막 N라인)
    overlap_start_index = max(0, mid_point - overlap_lines)

    # 두 번째 부분 (중첩 부분 + 나머지)
    part2_lines = lines[overlap_start_index:]
    part2_with_overlap = '\n'.join(part2_lines)

    return part1, part2_with_overlap


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
        
        # tiktoken 인코더 캐시 (성능 최적화)
        self._encoders = {}
    
    def _get_encoder(self, model_name: str):
        """모델별 tiktoken 인코더를 가져옵니다 (캐싱됨)"""
        if model_name not in self._encoders:
            try:
                encoder_model = model_name
                self._encoders[model_name] = tiktoken.encoding_for_model(encoder_model)
            except KeyError:
                # 지원되지 않는 모델인 경우 cl100k_base 인코더 사용 (GPT-4 계열)
                logging.warning(f"Model {model_name} not supported by tiktoken, using cl100k_base")
                self._encoders[model_name] = tiktoken.get_encoding("cl100k_base")
        return self._encoders[model_name]
    
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
    
    def estimate_tokens(self, text: str, model_name: str = "gpt-4o") -> int:
        """tiktoken을 사용한 정확한 토큰 수 계산"""
        try:
            encoder = self._get_encoder(model_name)
            tokens = encoder.encode(text)
            return len(tokens)
        except Exception as e:
            # tiktoken 실패 시 fallback to 보수적 추정
            logging.warning(f"tiktoken failed for model {model_name}: {e}, using fallback estimation")
            # 한국어 특성을 고려한 보수적 추정 (2글자 ≈ 1토큰)
            return len(text) // 2
    
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
        stop=stop_after_attempt(3),  # 최대 3번 재시도
        wait=custom_wait_strategy,  # 커스텀 대기 전략 사용
        retry=retry_if_exception_type((Exception,)),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.INFO),
        after=after_log(logging.getLogger(__name__), logging.INFO)
    )
    async def _make_api_call_with_retry(
        self,
        model_name: str,
        system_prompt: tuple[str, str],
        text_content: str,
        logger
    ) -> Optional[str]:
        """Tenacity를 사용한 재시도 로직이 포함된 API 호출"""
        
        # Rate Limit 관리 - tiktoken을 사용한 정확한 토큰 계산
        total_text = system_prompt[0] + text_content
        estimated_tokens = self.rate_limit_manager.estimate_tokens(total_text, model_name)
        
        logger.info(f"Accurate token count for {model_name}: {estimated_tokens} tokens")
        print(f"Accurate token count for {model_name}: {estimated_tokens} tokens")
        
        # 에러 방지를 위해 텍스트 반으로 자르기
        (text_content_p1, text_content_p2) = split_transcript_with_overlap(text_content)
        
        # Rate Limit 대기
        await self.rate_limit_manager.wait_for_rate_limit(model_name, estimated_tokens)
        
        # 세마포어로 동시성 제어 (안전한 context manager 사용)
        async with self.rate_limit_manager.acquire_slot_context(model_name):
            logger.info(f"Making API call to {model_name} with {estimated_tokens} estimated tokens")
            print(f"Making API call to {model_name} with {estimated_tokens} estimated tokens")
            logger.info(f"Available slots for {model_name}: {self.rate_limit_manager.get_available_slots(model_name)}")
            print(f"Available slots for {model_name}: {self.rate_limit_manager.get_available_slots(model_name)}")
            
            try:
                # OpenAI API 호출 -> 앞쪽 절반 part 분석 수행
                response_p1 = await asyncio.to_thread(
                    self._client.responses.create,
                    model=model_name,
                    input=[
                        {"role": "developer", "content": system_prompt[0]},
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
                        {"role": "developer", "content": system_prompt[0]},
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
                        {"role": "developer", "content": system_prompt[1]},
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
                                        return result_text
                        
                        # 기타 문제인 경우 예외 발생하여 재시도
                        raise Exception(f"Model {model_name} returned status: {status}")
            
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
            # custom_items를 기반으로 시스템 프롬프트 생성 (분석용과 병합용 두 개 반환)
            (analysis_prompt, merge_prompt) = generate_system_prompt_from_docx(
                file_content=(custom_items or []),
                template_type=template_type
            )
            
            # Tenacity를 사용한 재시도 API 호출
            result = await self._make_api_call_with_retry(
                model_name=model_name,
                system_prompt=(analysis_prompt, merge_prompt),
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

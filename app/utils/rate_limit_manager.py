"""
Rate Limit 관리 유틸리티
"""
import asyncio
import time
import logging
from contextlib import asynccontextmanager
from typing import Dict
import tiktoken
import re


class RateLimitManager:
    """API Rate Limit 관리자 (범용)"""
    
    def __init__(self, model_configs: Dict[str, Dict] = None):
        """
        Args:
            model_configs: 모델별 설정
            예: {
                "gpt-5": {"semaphore": 2, "tpm": 30000, "rpm": 500},
                "gpt-4o": {"semaphore": 3, "tpm": 30000, "rpm": 500}
            }
        """
        self.model_configs = model_configs or {}
        
        # 모델별 동시 요청 제한 (세마포어)
        # self.semaphores = {
        #     "gpt-5": asyncio.Semaphore(2),  # gpt-5는 동시 요청 2개로 제한
        #     "gpt-4o": asyncio.Semaphore(3),  # gpt-4o는 동시 요청 3개로 제한
        # }
        self.semaphores = {}
        
        # 모델별 최근 요청 시간 추적 (토큰/분 제한 관리)
        # self.last_request_times = {
        #     "gpt-5": [],
        #     "gpt-4o": []
        # }
        self.last_request_times = {}
        
        # 모델별 토큰 제한 정보
        # self.token_limits = {
        #     "gpt-5": {"tpm": 30000, "rpm": 500},  # Tokens Per Minute, Requests Per Minute
        #     "gpt-4o": {"tpm": 30000, "rpm": 500}
        # }
        self.token_limits = {}
        
        # tiktoken 인코더 캐시 (성능 최적화)
        self._encoders = {}
        
        # 설정 초기화
        self._initialize_from_config()
    
    def _initialize_from_config(self):
        """설정에서 초기화"""
        for model_name, config in self.model_configs.items():
            # 세마포어 설정
            semaphore_count = config.get("semaphore", 1)
            self.semaphores[model_name] = asyncio.Semaphore(semaphore_count)
            
            # 요청 시간 추적 초기화
            self.last_request_times[model_name] = []
            
            # 토큰 제한 설정
            self.token_limits[model_name] = {
                "tpm": config.get("tpm", 30000),
                "rpm": config.get("rpm", 500)
            }
    
    def add_model(self, model_name: str, semaphore_count: int = 1, tpm: int = 30000, rpm: int = 500):
        """동적으로 모델 추가"""
        self.semaphores[model_name] = asyncio.Semaphore(semaphore_count)
        self.last_request_times[model_name] = []
        self.token_limits[model_name] = {"tpm": tpm, "rpm": rpm}
    
    def _get_encoder(self, model_name: str):
        """모델별 tiktoken 인코더를 가져옵니다 (캐싱됨)"""
        if model_name not in self._encoders:
            try:
                self._encoders[model_name] = tiktoken.encoding_for_model(model_name)
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
                await asyncio.sleep(wait_time)
        
        # 추정 토큰이 TPM 제한의 90%를 초과하면 경고만 로그
        if estimated_tokens > limit_info["tpm"] * 0.9:
            logging.warning(f"Large request for {model_name} ({estimated_tokens} tokens)")
        
        # 요청 시간 기록
        self.last_request_times[model_name].append(current_time)
    
    # ========== Rate Limit 에러 처리 관련 메서드들 (새로 추가) ==========
    
    @staticmethod
    def is_rate_limit_error(exception) -> bool:
        """Rate Limit 에러인지 확인"""
        error_msg = str(exception)
        return ("429" in error_msg or 
                "rate_limit_exceeded" in error_msg or
                "tokens per min" in error_msg or
                "requests per min" in error_msg)
    
    @staticmethod
    def get_rate_limit_wait_time(exception) -> int:
        """Rate Limit 에러 타입에 따른 대기 시간 결정"""
        error_msg = str(exception)
        if "tokens per min" in error_msg:
            return 60  # TPM 에러는 1분 대기
        elif "requests per min" in error_msg:
            return 30  # RPM 에러는 30초 대기
        else:
            return 20  # 기타 429 에러는 20초 대기
    
    @staticmethod
    def custom_wait_strategy(retry_state) -> float:
        """커스텀 대기 전략: Rate Limit 에러는 특별 처리, 나머지는 지수 백오프"""
        if retry_state.outcome and retry_state.outcome.failed:
            exception = retry_state.outcome.exception()
            if RateLimitManager.is_rate_limit_error(exception):
                wait_time = RateLimitManager.get_rate_limit_wait_time(exception)
                logging.getLogger(__name__).warning(
                    f"Rate limit detected, waiting {wait_time}s (attempt {retry_state.attempt_number})"
                )
                return wait_time
        
        # Rate Limit가 아닌 경우 지수 백오프 (최소 4초, 최대 60초)
        base_wait = min(60, 4 * (2 ** (retry_state.attempt_number - 1)))
        return base_wait
    
    # ========== 텍스트 분할 관련 메서드 (새로 추가) ==========
    
    @staticmethod
    def split_transcript(full_transcript: str, overlap_sentences: int = 5) -> tuple[str, str]:
      """
      전체 녹취록 텍스트를 문장 기준으로 두 부분으로 나누고, 문맥 유지를 위한 중첩 부분을 추가합니다.

      :param full_transcript: 전체 녹취록 문자열
      :param overlap_sentences: 겹치게 할 문장 수 (기본값: 3)
      :return: (첫 번째 부분, 겹쳐진 두 번째 부분) 튜플
      """
      # 문장 끝(.?!) 뒤에 오는 공백을 기준으로 텍스트를 문장 리스트로 분할합니다.
      # 정규식의 'lookbehind' ((?<=...))를 사용하여 문장 부호는 그대로 남깁니다.
      sentences = re.split(r'(?<=[.?!])\s+', full_transcript.strip())
      
      # 문장 수가 너무 적으면 나누지 않음
      if len(sentences) < 20:
          return full_transcript, ""

      # 전체 문장의 약 절반 지점 찾기
      mid_point = len(sentences) // 2

      # 첫 번째 부분
      part1_sentences = sentences[:mid_point]
      part1 = ' '.join(part1_sentences)

      # 중첩될 부분의 시작 인덱스 계산
      overlap_start_index = max(0, mid_point - overlap_sentences)

      # 두 번째 부분 (중첩 부분 + 나머지)
      part2_sentences = sentences[overlap_start_index:]
      part2_with_overlap = ' '.join(part2_sentences)

      return part1, part2_with_overlap
    
    def get_stats(self) -> Dict[str, Dict]:
        """현재 상태 통계 반환"""
        stats = {}
        for model_name in self.semaphores.keys():
            stats[model_name] = {
                "available_slots": self.get_available_slots(model_name),
                "recent_requests": len(self.last_request_times.get(model_name, [])),
                "token_limit": self.token_limits.get(model_name, {})
            }
        return stats


# OpenAI용 기본 설정
OPENAI_DEFAULT_CONFIG = {
    "gpt-5": {"semaphore": 1, "tpm": 30000, "rpm": 500},
    "gpt-4o": {"semaphore": 1, "tpm": 30000, "rpm": 500}
}


def create_openai_rate_limiter() -> RateLimitManager:
    """OpenAI용 Rate Limiter 생성"""
    return RateLimitManager(OPENAI_DEFAULT_CONFIG)
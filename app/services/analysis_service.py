"""
분석 서비스 - STT와 Gemini를 결합한 비즈니스 로직
"""
import asyncio
from typing import Dict, Any, List, Optional

from app.services.stt_service import stt_service
from app.services.gemini_service import gemini_service


class AnalysisService:
    """텍스트 분석 통합 서비스"""
    
    def __init__(self):
        self.stt_service = stt_service
        self.gemini_service = gemini_service
    
    async def bomatic_pipeline(
        self,
        audio_url: str,
        language: str = "ko",
        enable_speaker_diarization: bool = True,
        custom_items: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """음성 변환부터 텍스트 분석까지 전체 파이프라인을 실행합니다."""
        
        # 1단계: STT 요청
        stt_result = await self.stt_service.request_stt(
            audio_url, language, enable_speaker_diarization
        )
        rid = stt_result.get("rid")
        
        if not rid:
            raise ValueError("STT 요청 ID를 받지 못했습니다.")
        
        # 2단계: STT 완료까지 대기
        transcribed_text = await self.stt_service.wait_for_completion(rid)
        
        # 3단계: Gemini 분석 (커스텀 Items 전달)
        analysis_result = await self.gemini_service.analyze_text(
            transcribed_text, custom_items
        )
        
        return {
            "stt_rid": rid,
            "transcribed_text": transcribed_text,
            "analysis_result": analysis_result
        }


# 전역 분석 서비스 인스턴스
analysis_service = AnalysisService()

"""
STT(Speech-to-Text) 서비스
"""
import requests
import asyncio
from typing import Dict, Any
from fastapi import HTTPException

from app.core.config import settings


class STTService:
    """다글로 STT API 서비스"""
    
    def __init__(self):
        self.base_url = "https://apis.daglo.ai/stt/v1/async/transcripts"
        self.api_key = settings.daglo_api_key
        
    async def request_stt(
        self, 
        audio_url: str, 
        language: str = "ko", 
        enable_speaker_diarization: bool = True
    ) -> Dict[str, Any]:
        """Daglo STT API에 음성 변환 요청을 보냅니다."""
        if not self.api_key:
            raise HTTPException(
                status_code=500, 
                detail="DAGLO API 키가 설정되지 않았습니다."
            )
        
        try:
            response = requests.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "audio": {
                        "source": {
                            "url": audio_url
                        }
                    },
                    "language": language,
                    "sttConfig": {
                        "speakerDiarization": {
                            "enable": enable_speaker_diarization
                        }
                    }
                }
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise HTTPException(
                status_code=500, 
                detail=f"다글로 STT 요청 실패: {str(e)}"
            )

    async def poll_stt_result(self, rid: str) -> Dict[str, Any]:
        """STT 작업 결과를 폴링합니다."""
        if not self.api_key:
            raise HTTPException(
                status_code=500, 
                detail="DAGLO API 키가 설정되지 않았습니다."
            )
        
        try:
            response = requests.get(
                f"{self.base_url}/{rid}",
                headers={"Authorization": f"Bearer {self.api_key}"}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise HTTPException(
                status_code=500, 
                detail=f"다글로 STT 결과 조회 실패: {str(e)}"
            )
    
    async def wait_for_completion(self, rid: str) -> str:
        """STT 완료까지 대기하고 결과를 반환합니다."""
        max_attempts = settings.stt_max_attempts
        attempt = 0
        
        while attempt < max_attempts:
            try:
                result = await self.poll_stt_result(rid)
                status = result.get("status")
                
                if status == "transcribed":
                    stt_results = result.get("sttResults", [])
                    if stt_results:
                        return " ".join([r.get("transcript", "") for r in stt_results])
                    else:
                        return "(인식된 텍스트가 없습니다.)"
                elif status == "failed":
                    error_msg = result.get("errorMessage", "알 수 없는 오류")
                    raise HTTPException(
                        status_code=500, 
                        detail=f"STT 변환 실패: {error_msg}"
                    )
                
                attempt += 1
                await asyncio.sleep(settings.stt_poll_interval)
                
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=500, 
                    detail=f"STT 처리 중 오류: {str(e)}"
                )
        
        raise HTTPException(status_code=408, detail="STT 처리 시간 초과")


# 전역 STT 서비스 인스턴스
stt_service = STTService()

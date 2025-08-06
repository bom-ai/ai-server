"""
STT(Speech-to-Text) 서비스
"""
import requests
import asyncio
from typing import Dict, Any, BinaryIO
from fastapi import HTTPException, UploadFile

from app.core.config import settings


class STTService:
    """다글로 STT API 서비스"""
    
    def __init__(self):
        self.base_url = "https://apis.daglo.ai/stt/v1/async/transcripts"
        self.api_key = settings.daglo_api_key

    
    async def request_stt_with_file_upload(
        self, 
        file: UploadFile, 
        language: str = "ko", 
        enable_speaker_diarization: bool = True
    ) -> Dict[str, Any]:
        """multipart/form-data 형식으로 파일을 직접 업로드하여 STT 요청"""
        if not self.api_key:
            raise HTTPException(
                status_code=500, 
                detail="DAGLO API 키가 설정되지 않았습니다."
            )
        
        try:
            import logging
            logger = logging.getLogger(__name__)
            
            # 파일 내용을 읽어서 multipart/form-data로 전송
            file_content = await file.read()
            
            logger.info(f"파일 업로드 시도: {file.filename}, 크기: {len(file_content)} bytes")
            logger.info(f"Content-Type: {file.content_type}")
            
            # 수정: 이미 읽은 file_content를 사용
            files = {
                "file": (file.filename, file_content, file.content_type or "audio/mpeg")
            }
            
            data = {
                "language": language,
                "enable_speaker_diarization": str(enable_speaker_diarization).lower()
            }
            
            logger.info(f"요청 URL: {self.base_url}")
            logger.info(f"데이터: {data}")
            
            response = requests.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                },
                files=files,
                data=data,
            )
            
            logger.info(f"응답 상태: {response.status_code}")
            logger.info(f"응답 헤더: {dict(response.headers)}")
            logger.info(f"응답 내용: {response.text[:500]}...")
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"요청 실패: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"에러 응답: {e.response.text}")
            raise HTTPException(
                status_code=500, 
                detail=f"다글로 STT 파일 업로드 요청 실패: {str(e)}"
            )
        except Exception as e:
            logger.error(f"기타 오류: {e}")
            raise HTTPException(
                status_code=500, 
                detail=f"다글로 STT 파일 업로드 요청 실패: {str(e)}"
            )

        
    async def request_stt_with_audio_url(
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

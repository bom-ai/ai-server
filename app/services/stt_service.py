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
        
            '''
            에러 발생 
            {
                "detail": "500: 다글로 STT 결과 조회 실패: 403 Client Error: Forbidden for url: https://apis.daglo.ai/stt/v1/async/transcripts/y-AvwZ8tajhJo3AvnaY7e"
            }
            URL 들어가면 나오는 결과 : {"code":"UNAUTHORIZED","message":"Unauthorized"}
            '''
    
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

    async def request_stt_with_file(
        self, 
        file: UploadFile, 
        language: str = "ko", 
        enable_speaker_diarization: bool = True
    ) -> Dict[str, Any]:
        """multipart/form-data 방식으로 파일을 직접 업로드하여 STT 요청을 보냅니다."""
        if not self.api_key:
            raise HTTPException(
                status_code=500, 
                detail="DAGLO API 키가 설정되지 않았습니다."
            )
        
        try:
            # 파일 내용을 읽어서 multipart/form-data로 전송
            file_content = await file.read()
            
            files = {
                'audio_file': (file.filename, file_content, file.content_type or 'audio/wav')
            }
            
            data = {
                'language': language,
                'speakerDiarization': str(enable_speaker_diarization).lower()
            }
            
            response = requests.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    # Content-Type은 multipart/form-data에서 자동 설정됨
                },
                files=files,
                data=data
            )
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            raise HTTPException(
                status_code=500, 
                detail=f"다글로 STT 파일 업로드 요청 실패: {str(e)}"
            )

    async def request_stt_with_file_path(
        self, 
        file_path: str, 
        language: str = "ko", 
        enable_speaker_diarization: bool = True
    ) -> Dict[str, Any]:
        """로컬 파일 경로를 사용하여 multipart/form-data 방식으로 STT 요청을 보냅니다."""
        if not self.api_key:
            raise HTTPException(
                status_code=500, 
                detail="DAGLO API 키가 설정되지 않았습니다."
            )
        
        try:
            with open(file_path, 'rb') as audio_file:
                files = {
                    'audio_file': (file_path.split('/')[-1], audio_file, 'audio/wav')
                }
                
                data = {
                    'language': language,
                    'speakerDiarization': str(enable_speaker_diarization).lower()
                }
                
                response = requests.post(
                    self.base_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        # Content-Type은 multipart/form-data에서 자동 설정됨
                    },
                    files=files,
                    data=data
                )
                response.raise_for_status()
                return response.json()
                
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, 
                detail=f"파일을 찾을 수 없습니다: {file_path}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500, 
                detail=f"다글로 STT 파일 업로드 요청 실패: {str(e)}"
            )


# 전역 STT 서비스 인스턴스
stt_service = STTService()

"""
STT(Speech-to-Text) 서비스
"""
import httpx
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

        
    async def request_stt_with_audio_url(
        self, 
        audio_url: str, 
        language: str = "ko", 
        enable_speaker_diarization: bool = True
    ) -> Dict[str, Any]:
        """Daglo STT API에 음성 변환 요청을 보냅니다. (비동기 httpx 사용)"""
        if not self.api_key:
            raise HTTPException(
                status_code=500, 
                detail="DAGLO API 키가 설정되지 않았습니다."
            )
        
        # httpx.AsyncClient를 사용하여 비동기 요청을 보냅니다.
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
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
                    },
                    # 타임아웃을 설정하여 무한정 기다리는 것을 방지합니다. (예: 30초)
                    timeout=30.0 
                )
                response.raise_for_status()  # 2xx 이외의 상태 코드일 경우 예외 발생
                return response.json()
            
            # httpx에서 발생하는 네트워크 관련 예외를 구체적으로 처리하는 것이 좋습니다.
            except httpx.RequestError as e:
                raise HTTPException(
                    status_code=503, 
                    detail=f"다글로 STT 서비스에 연결할 수 없습니다: {e}"
                )
            except Exception as e:
                # 그 외의 예외 처리
                raise HTTPException(
                    status_code=500, 
                    detail=f"다글로 STT 요청 중 알 수 없는 오류 발생: {str(e)}"
                )

    async def poll_stt_result(self, rid: str) -> Dict[str, Any]:
        """STT 작업 결과를 비동기적으로 폴링합니다."""
        if not self.api_key:
            raise HTTPException(
                status_code=500, 
                detail="DAGLO API 키가 설정되지 않았습니다."
            )
        
         # httpx.AsyncClient를 사용하여 비동기 요청
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/{rid}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=10.0 # 타임아웃 설정
                )
                response.raise_for_status() # 2xx 외 상태 코드에서 예외 발생
                return response.json()
            
            # HTTP 상태 코드에 따른 구체적인 예외 처리
            except httpx.HTTPStatusError as e:
                # 4xx 클라이언트 오류 (ex: 403, 404)는 재시도해도 소용없으므로 즉시 실패 처리
                if 400 <= e.response.status_code < 500:
                    raise HTTPException(
                        status_code=e.response.status_code,
                        detail=f"STT 결과 조회 중 클라이언트 오류 발생: {e.response.text}"
                    )
                # 5xx 서버 오류는 일시적일 수 있으므로 재시도 대상이 됨
                else:
                    # wait_for_completion에서 이 예외를 잡아서 재시도하도록 그대로 전달
                    raise e 
        

            except httpx.RequestError as e:
            # 네트워크 연결 관련 오류
                raise HTTPException(status_code=503, detail=f"Daglo 서비스 연결 실패: {e}")
            
    
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



    # async def request_stt_with_file_content(
    #     self, 
    #     file_content: bytes, 
    #     filename: str,
    #     language: str = "ko",
    #     enable_speaker_diarization: bool = True
    # ) -> Dict[str, Any]:
    #     """파일 내용(바이트)을 사용하여 STT 요청"""
        
    #     if not self.api_key:
    #         raise HTTPException(
    #             status_code=500, 
    #             detail="DAGLO API 키가 설정되지 않았습니다."
    #         )
        
    #     # Content-Type을 파일 확장자에 따라 설정
    #     if filename.lower().endswith('.mp3'):
    #         content_type = 'audio/mpeg'
    #     elif filename.lower().endswith('.wav'):
    #         content_type = 'audio/wav'
    #     elif filename.lower().endswith('.m4a'):
    #         content_type = 'audio/mp4'
    #     else:
    #         content_type = 'audio/mpeg'  # 기본값
        
    #     files = {
    #         'file': (filename, file_content, content_type)
    #     }
        
    #     data = {
    #         'language': language,
    #         'enable_speaker_diarization': str(enable_speaker_diarization).lower()
    #     }
        
    #     # headers를 직접 정의 (self.headers 대신)
    #     headers = {
    #         "Authorization": f"Bearer {self.api_key}"
    #     }
        
    #     try:
    #         async with httpx.AsyncClient(timeout=120.0) as client:
    #             response = await client.post(
    #                 self.base_url,  # 올바른 URL 사용
    #                 headers=headers,
    #                 files=files,
    #                 data=data
    #             )
                
    #             if response.status_code == 200:
    #                 return response.json()
    #             else:
    #                 error_detail = response.text
    #                 raise HTTPException(
    #                     status_code=response.status_code,
    #                     detail=f"STT API 오류: {error_detail}"
    #                 )
                    
    #     except httpx.RequestError as e:
    #         raise HTTPException(
    #             status_code=500,
    #             detail=f"STT API 연결 오류: {str(e)}"
    #         )

    # async def request_stt_with_file_upload(
    #     self, 
    #     file: UploadFile, 
    #     language: str = "ko", 
    #     enable_speaker_diarization: bool = True
    # ) -> Dict[str, Any]:
    #     """multipart/form-data 형식으로 파일을 직접 업로드하여 STT 요청"""
    #     if not self.api_key:
    #         raise HTTPException(
    #             status_code=500, 
    #             detail="DAGLO API 키가 설정되지 않았습니다."
    #         )
        
    #     try:
    #         import logging
    #         logger = logging.getLogger(__name__)
            
    #         # 파일 내용을 읽어서 multipart/form-data로 전송
    #         file_content = await file.read()
            
    #         logger.info(f"파일 업로드 시도: {file.filename}, 크기: {len(file_content)} bytes")
    #         logger.info(f"Content-Type: {file.content_type}")
            
    #         # 수정: 이미 읽은 file_content를 사용
    #         files = {
    #             "file": (file.filename, file_content, file.content_type or "audio/mpeg")
    #         }
            
    #         data = {
    #             "language": language,
    #             "enable_speaker_diarization": str(enable_speaker_diarization).lower()
    #         }
            
    #         logger.info(f"요청 URL: {self.base_url}")
    #         logger.info(f"데이터: {data}")
            
    #         response = requests.post(
    #             self.base_url,
    #             headers={
    #                 "Authorization": f"Bearer {self.api_key}",
    #             },
    #             files=files,
    #             data=data,
    #         )
            
    #         logger.info(f"응답 상태: {response.status_code}")
    #         logger.info(f"응답 헤더: {dict(response.headers)}")
    #         logger.info(f"응답 내용: {response.text[:500]}...")
            
    #         response.raise_for_status()
    #         return response.json()
            
    #     except requests.exceptions.RequestException as e:
    #         logger.error(f"요청 실패: {e}")
    #         if hasattr(e, 'response') and e.response is not None:
    #             logger.error(f"에러 응답: {e.response.text}")
    #         raise HTTPException(
    #             status_code=500, 
    #             detail=f"다글로 STT 파일 업로드 요청 실패: {str(e)}"
    #         )
    #     except Exception as e:
    #         logger.error(f"기타 오류: {e}")
    #         raise HTTPException(
    #             status_code=500, 
    #             detail=f"다글로 STT 파일 업로드 요청 실패: {str(e)}"
    #         )
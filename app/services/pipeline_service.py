"""
파이프라인 서비스 - bo:matic 애플리케이션의 전체 파이프라인 로직
"""
import asyncio
import uuid
import os
from dotenv import load_dotenv
from typing import Dict, Any, List, Optional, Literal
from datetime import timedelta
from google.cloud import storage

from app.services.stt_service import stt_service
from app.services.gemini_service import gemini_service
from app.core.config import settings
from app.utils.docx_processor import (
    extract_text_with_separated_tables, 
    extract_table_headers_with_subitems,
    format_items_for_prompt
)


class PipelineService:
    """bo:matic 파이프라인 서비스"""
    
    def __init__(self):
        self.stt_service = stt_service
        self.gemini_service = gemini_service
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        # 배치 작업 저장소
        self.batch_jobs = {}
        # Cloud Storage 클라이언트 초기화
        self.storage_client = storage.Client(project=project_id)
        # 버킷 이름 설정에서 가져오기
        self.bucket_name = settings.gcs_bucket_name
    
    def generate_signed_url(self, blob_name: str) -> str:
        bucket = self.storage_client.bucket(self.bucket_name)
        blob = bucket.blob(blob_name)

        # URL은 15분 동안 유효합니다.
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=15),
            method="PUT",
            content_type="application/octet-stream", 
        )
        return url
    
    async def request_batch_analysis_job(
        self,
        frame_content: bytes,
        filenames: List[str],
        mapping: dict,
        template_type: Literal["raw", "refined"],
        user_id: str
    ) -> Dict[str, Any]:
        """분석 작업을 위한 job_id와 서명된 URL들을 생성하고 반환합니다."""
        job_id = str(uuid.uuid4())
        
        # 각 파일에 대한 GCS 경로와 서명된 URL 생성
        upload_urls = {}
        gcs_object_names = {}
        for filename in filenames:
            # 사용자별, 작업별로 고유한 경로 생성
            object_name = f"audio/{user_id}/{job_id}/{filename}"
            signed_url = self.generate_signed_url(object_name)
            upload_urls[filename] = signed_url
            gcs_object_names[filename] = object_name

        # 작업 정보 저장 (상태: pending_upload)
        self.batch_jobs[job_id] = {
            "status": "pending_upload",
            "message": "파일 업로드를 기다리는 중입니다.",
            "user_id": user_id,
            "frame_content": frame_content,
            "mapping": mapping,
            "gcs_object_names": gcs_object_names, # GCS 경로 저장
            "template_type": template_type,
            "total_files": len(filenames),
            "processed_files": 0,
            "results": {},
            "errors": {}
        }
        
        return {
            "job_id": job_id,
            "upload_urls": upload_urls
        }
    
    async def start_batch_analysis(self, job_id: str, user_id: str):
        """업로드가 완료된 파일들의 분석을 시작합니다."""
        if job_id not in self.batch_jobs:
            raise ValueError("해당 작업을 찾을 수 없습니다.")
        
        job_info = self.batch_jobs[job_id]
        
        if job_info.get("user_id") != user_id:
            raise ValueError("작업에 대한 권한이 없습니다.")
            
        if job_info["status"] != "pending_upload":
            raise ValueError("이미 처리 중이거나 완료된 작업입니다.")

        job_info["status"] = "processing"
        job_info["message"] = "배치 분석 작업 진행 중..."

        # 백그라운드에서 배치 처리 작업 시작
        asyncio.create_task(self._batch_analysis_task(job_id))
        
        return job_id

    async def _batch_analysis_task(self, job_id: str):
        """배치 분석 작업을 백그라운드에서 처리합니다."""
        import logging
        logger = logging.getLogger(__name__)

        job_info = self.batch_jobs[job_id]
        frame_content = job_info["frame_content"]
        mapping = job_info["mapping"]
        gcs_object_names = job_info["gcs_object_names"]
        template_type = job_info["template_type"]

        try:
            # 프레임 파일 처리
            structured_items = extract_table_headers_with_subitems(frame_content)
            custom_items = format_items_for_prompt(structured_items)
            
            logger.info(f"Job {job_id}: Processing {len(gcs_object_names)} audio files")
            
            # gcs_object_names를 리스트로 변환하여 순서를 보장
            filenames_to_process = list(gcs_object_names.keys())

            for i, filename in enumerate(filenames_to_process):
                object_name = gcs_object_names[filename]
                group_name = mapping.get(filename, "Unknown Group")
                
                logger.info(f"Job {job_id}: Processing file {i+1}/{len(filenames_to_process)}: {filename}")
                
                try:
                    ## CHANGED: GCS URI를 직접 사용 (업로드 과정 삭제)
                    # GCS URI 형식: gs://<bucket_name>/<object_name>
                    audio_uri = f"gs://{self.bucket_name}/{object_name}"
                    
                    # STT 처리 - GCS URI 사용
                    logger.info(f"Job {job_id}: Starting STT for {audio_uri}")
                    stt_result = await self.stt_service.request_stt_with_audio_url(audio_uri)
                    rid = stt_result.get("rid")
                    
                    if rid:
                        transcribed_text = await self.stt_service.wait_for_completion(rid)
                        logger.info(f"Job {job_id}: STT completed for {filename}")
                        
                        # (필요 시 Rate Limiting 대기 시간 추가)
                        if i > 0: await asyncio.sleep(min(5, i * 2))
                        
                        # Gemini 분석
                        analysis_result = await self.gemini_service.analyze_text(
                            text_content=transcribed_text,
                            custom_items=custom_items,
                            template_type=template_type
                        )
                        
                        job_info["results"][filename] = {
                            "group": group_name,
                            "gcs_uri": audio_uri, # GCS URI 저장
                            "transcribed_text": transcribed_text,
                            "analysis": analysis_result
                        }
                    else:
                        raise Exception("STT 요청 ID를 받지 못했습니다.")

                except Exception as e:
                    error_msg = str(e)
                    job_info["errors"][filename] = error_msg
                    logger.error(f"Job {job_id}: Error processing {filename}: {error_msg}", exc_info=True)
                
                job_info["processed_files"] = i + 1

            job_info["status"] = "completed"
            job_info["message"] = "배치 분석 작업이 완료되었습니다."
            
        except Exception as e:
            job_info["status"] = "failed"
            job_info["message"] = f"배치 분석 중 오류 발생: {str(e)}"
            logger.error(f"Job {job_id}: Batch analysis failed: {str(e)}", exc_info=True)
    
    async def get_batch_status(self, job_id: str) -> Dict[str, Any]:
        """배치 분석 작업 상태를 확인합니다."""
        if job_id not in self.batch_jobs:
            raise ValueError("해당 작업을 찾을 수 없습니다.")
        
        return self.batch_jobs[job_id]
    
    async def get_batch_results(self, job_id: str) -> Dict[str, Any]:
        """완료된 배치 분석 결과를 반환합니다."""
        if job_id not in self.batch_jobs:
            raise ValueError("해당 작업을 찾을 수 없습니다.")
        
        job_completed = self.batch_jobs[job_id]
        if job_completed["status"] != "completed":
            raise ValueError("작업이 아직 완료되지 않았습니다.")
        
        return job_completed


# bo:matic 파이프라인 서비스 인스턴스
pipeline_service = PipelineService()

"""
Google Cloud Firestore 설정 및 모델
"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from google.cloud import firestore
from app.core.config import get_settings
import os

settings = get_settings()

class FirestoreClient:
    """Google Cloud Firestore 클라이언트"""
    
    def __init__(self):
        # Cloud Run에서는 자동으로 프로젝트 ID가 설정됨
        self.project_id = settings.google_cloud_project

        # Firestore 클라이언트 초기화 (특정 데이터베이스 지정)
        if self._is_running_on_cloud_run():
            # Cloud Run 환경: 기본 서비스 계정 사용
            self.client = firestore.Client(
                project=self.project_id,
                database="bomatic-auth"  # 기존 데이터베이스 이름 사용
            )
        elif os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            # 로컬 개발 환경: 서비스 계정 키 파일 사용
            self.client = firestore.Client(
                project=self.project_id,
                database="bomatic-auth"  # 기존 데이터베이스 이름 사용
            )
        else:
            # 개발/테스트 환경
            self.client = firestore.Client(
                project=self.project_id,
                database="bomatic-auth"  # 기존 데이터베이스 이름 사용
            )
    
    def _is_running_on_cloud_run(self) -> bool:
        """Cloud Run 환경에서 실행 중인지 확인합니다."""
        return os.getenv("K_SERVICE") is not None


# 전역 Firestore 클라이언트
firestore_client = FirestoreClient()


class BaseCollection:
    """Firestore 컬렉션 기본 클래스"""
    
    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.client = firestore_client.client
        self.collection = self.client.collection(collection_name)
    
    def create(self, doc_id: Optional[str], data: Dict[str, Any]) -> firestore.DocumentReference:
        """문서 생성"""
        # 타임스탬프 자동 추가
        now = datetime.now(timezone.utc)
        data.update({
            'created_at': now,
            'updated_at': now
        })
        
        if doc_id:
            doc_ref = self.collection.document(doc_id)
            doc_ref.set(data)
        else:
            doc_ref = self.collection.add(data)[1]
        
        return doc_ref
    
    def get(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """문서 조회"""
        doc_ref = self.collection.document(doc_id)
        doc = doc_ref.get()
        
        if doc.exists:
            data = doc.to_dict()
            data['id'] = doc.id
            return data
        return None
    
    def update(self, doc_id: str, updates: Dict[str, Any]) -> None:
        """문서 업데이트"""
        updates['updated_at'] = datetime.now(timezone.utc)
        doc_ref = self.collection.document(doc_id)
        doc_ref.update(updates)
    
    def delete(self, doc_id: str) -> None:
        """문서 삭제"""
        doc_ref = self.collection.document(doc_id)
        doc_ref.delete()
    
    def query(self, field: str, operator: str, value: Any) -> List[Dict[str, Any]]:
        """쿼리 실행"""
        query_ref = self.collection.where(field, operator, value)
        docs = query_ref.stream()
        
        results = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            results.append(data)
        
        return results


class UserCollection(BaseCollection):
    """사용자 컬렉션"""
    
    def __init__(self):
        super().__init__('users')
    
    def create_user(self, email: str, hashed_password: str) -> Dict[str, Any]:
        """사용자 생성"""
        user_data = {
            'email': email,
            'hashed_password': hashed_password,
            'is_active': False,
            'is_verified': False
        }
        
        # 이메일을 문서 ID로 사용 (특수문자 처리)
        doc_id = email.replace('.', '_').replace('@', '_at_')
        doc_ref = self.create(doc_id, user_data)
        
        # 생성된 사용자 데이터 반환
        user_data['id'] = doc_id
        return user_data
    
    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """이메일로 사용자 조회"""
        doc_id = email.replace('.', '_').replace('@', '_at_')
        return self.get(doc_id)
    
    def update_user(self, email: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """사용자 정보 업데이트"""
        doc_id = email.replace('.', '_').replace('@', '_at_')
        
        try:
            self.update(doc_id, updates)
            return self.get(doc_id)
        except Exception:
            return None
    
    def activate_user(self, email: str) -> Optional[Dict[str, Any]]:
        """사용자 계정 활성화"""
        return self.update_user(email, {
            'is_active': True,
            'is_verified': True
        })


class RefreshTokenCollection(BaseCollection):
    """리프레시 토큰 컬렉션"""
    
    def __init__(self):
        super().__init__('refresh_tokens')
    
    def store_refresh_token(self, user_email: str, token: str, expires_at: datetime) -> Dict[str, Any]:
        """리프레시 토큰 저장"""
        # 기존 사용자 토큰들을 모두 무효화
        self.revoke_user_tokens(user_email)
        
        token_data = {
            'token': token,
            'user_email': user_email,
            'expires_at': expires_at,
            'is_revoked': False
        }
        
        # 토큰을 문서 ID로 사용
        doc_ref = self.create(token, token_data)
        token_data['id'] = token
        
        return token_data
    
    def get_refresh_token(self, token: str) -> Optional[Dict[str, Any]]:
        """토큰으로 리프레시 토큰 조회"""
        return self.get(token)
    
    def verify_refresh_token(self, token: str) -> Optional[Dict[str, Any]]:
        """리프레시 토큰 검증"""
        token_doc = self.get_refresh_token(token)
        
        if not token_doc:
            return None
        
        # 토큰이 취소되지 않았고 만료되지 않았는지 확인
        if (not token_doc.get('is_revoked', False) and 
            token_doc.get('expires_at') > datetime.now(timezone.utc)):
            return token_doc
        
        return None
    
    def revoke_refresh_token(self, token: str):
        """리프레시 토큰 무효화"""
        try:
            self.update(token, {'is_revoked': True})
        except Exception:
            pass  # 토큰이 존재하지 않으면 무시
    
    def revoke_user_tokens(self, user_email: str):
        """특정 사용자의 모든 토큰 무효화"""
        try:
            # 사용자의 모든 활성 토큰 조회
            active_tokens = self.query('user_email', '==', user_email)
            
            for token_doc in active_tokens:
                if not token_doc.get('is_revoked', False):
                    self.update(token_doc['id'], {'is_revoked': True})
        except Exception:
            pass  # 에러가 발생해도 계속 진행


# 전역 컬렉션 인스턴스들
user_entity = UserCollection()
refresh_token_entity = RefreshTokenCollection()


def get_firestore():
    """Firestore 클라이언트 의존성"""
    return firestore_client.client
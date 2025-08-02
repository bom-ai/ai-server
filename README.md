# bo:matic server

FGD(Focus Group Discussion) 전사 텍스트 분석을 위한 FastAPI 서버입니다.

## 프로젝트 구조

```
bo:matic_server/
├── app/                           # 메인 애플리케이션 패키지
│   ├── __init__.py
│   ├── main.py                    # FastAPI 앱 인스턴스 및 설정
│   ├── core/                      # 핵심 설정 및 유틸리티
│   │   ├── __init__.py
│   │   ├── config.py              # 환경설정 및 Pydantic Settings
│   │   └── prompts.py             # AI 분석용 시스템 프롬프트
│   ├── models/                    # Pydantic 모델 및 데이터베이스
│   │   ├── __init__.py
│   │   ├── schemas.py             # 요청/응답 모델 정의
│   │   └── database.py            # 데이터베이스 모델 (SQLAlchemy)
│   ├── api/                       # API 라우터
│   │   ├── __init__.py
│   │   ├── deps.py                # 의존성 관리 (인증 포함)
│   │   └── v1/                    # API v1
│   │       ├── __init__.py
│   │       ├── api.py             # 라우터 집합
│   │       └── endpoints/         # 개별 엔드포인트
│   │           ├── __init__.py
│   │           ├── auth.py        # 인증 관련 API
│   │           ├── stt.py         # STT 관련 API
│   │           ├── analysis.py    # 텍스트 분석 API
│   │           └── pipeline.py    # 전체 파이프라인 API
│   └── services/                  # 비즈니스 로직
│       ├── __init__.py
│       ├── auth_service.py        # JWT 인증 서비스
│       ├── email_service.py       # 이메일 서비스
│       ├── stt_service.py         # Daglo STT 서비스
│       ├── gemini_service.py      # Google Gemini AI 서비스
│       └── analysis_service.py    # 통합 분석 서비스
├── main.py                        # 레거시 호환용 진입점
├── requirements.txt               # 의존성 패키지
├── .env                          # 환경변수 (API 키 등)
├── .env.example                  # 환경변수 예시 파일
└── README.md                     # 프로젝트 문서
```

## 주요 기능

### 1. 인증 시스템 (JWT)

- JWT 기반 토큰 인증
- Access Token (1시간) + Refresh Token (7일)
- 이메일 기반 회원가입 및 인증
- 보안이 적용된 API 엔드포인트

### 2. STT (Speech-to-Text)

- Daglo STT API를 사용한 음성-텍스트 변환
- 화자 분리(Speaker Diarization) 지원
- 비동기 처리 및 상태 추적

### 3. AI 텍스트 분석

- Google Gemini AI를 사용한 FGD 텍스트 분석
- **가변적 분석 항목 지원**: 클라이언트가 제공하는 커스텀 Items로 분석 가능
- 기본 12개 주제 분류 또는 클라이언트 맞춤형 분석 항목 사용
- Phase1/Phase2 분석 모드 지원

### 4. 통합 파이프라인

- 음성 파일 → STT → AI 분석의 전체 워크플로우
- 단일 API 호출로 전체 과정 실행
- 커스텀 분석 항목을 포함한 전체 파이프라인 지원

## 설치 및 실행

### 1. 의존성 설치

```bash
# 가상환경 생성 및 활성화 (이미 있다면 생략)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 패키지 설치
pip install -r requirements.txt
```

### 2. 환경변수 설정

`.env` 파일에 다음 변수들을 설정하세요:

```bash
# API Keys
GEMINI_API_KEY=your_gemini_api_key_here
DAGLO_API_KEY=your_daglo_api_key_here

# JWT Settings
SECRET_KEY=your-super-secret-key-change-this-in-production
ALGORITHM=HS256

# Database - MySQL
DATABASE_URL=mysql+pymysql://username:password@localhost:3306/bo_matic_db
# For SQLite (development): DATABASE_URL=sqlite:///./auth.db

# Email Settings (선택사항)
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=your_email@gmail.com
MAIL_PASSWORD=your_app_password
MAIL_FROM=your_email@gmail.com
MAIL_USE_TLS=true
```

### 3. MySQL 데이터베이스 설정

MySQL 서버가 실행 중이어야 하며, 데이터베이스를 생성해야 합니다:

```sql
CREATE DATABASE bo_matic_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'bo_matic_user'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON bo_matic_db.* TO 'bo_matic_user'@'localhost';
FLUSH PRIVILEGES;
```

그 후 환경변수를 다음과 같이 설정하세요:

```bash
DATABASE_URL=mysql+pymysql://bo_matic_user:your_password@localhost:3306/bo_matic_db
```

### 4. 서버 실행

```bash
# 새로운 구조화된 방식 (권장)
python -m app.main

# 또는 레거시 호환 방식
python main.py
```

서버는 기본적으로 `http://localhost:8000`에서 실행됩니다.

## API 엔드포인트

### 기본 엔드포인트

- `GET /` - 서버 상태 확인
- `GET /health` - 헬스체크
- `GET /docs` - API 문서 (Swagger UI)

### 인증 API

- `POST /api/v1/auth/register` - 회원가입
- `POST /api/v1/auth/login` - 로그인
- `POST /api/v1/auth/refresh` - 토큰 갱신
- `GET /api/v1/auth/verify` - 이메일 인증
- `GET /api/v1/auth/me` - 현재 사용자 정보 조회
- `POST /api/v1/auth/logout` - 로그아웃

### STT API

- `POST /api/v1/stt/start` - STT 작업 시작
- `GET /api/v1/stt/status/{rid}` - STT 작업 상태 조회
- `DELETE /api/v1/stt/jobs/{rid}` - STT 작업 삭제

### 텍스트 분석 API (🔒 인증 필요)

- `POST /api/v1/analysis/analyze` - FGD 텍스트 분석

### 통합 파이프라인 API

- `POST /api/v1/pipeline/full-analysis` - 음성→분석 전체 파이프라인

## 인증 사용법

### 1. 회원가입

```bash
curl -X POST "http://localhost:8000/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@rh-bom.com",
    "password": "your_password"
  }'
```

### 2. 로그인

```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@rh-bom.com",
    "password": "your_password"
  }'
```

응답:

```json
{
  "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refreshToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expiresIn": 3600
}
```

### 3. 인증이 필요한 API 호출

#### 기본 분석 (기본 Items 사용)

```bash
curl -X POST "http://localhost:8000/api/v1/analysis/analyze" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -d '{
    "text_content": "분석할 텍스트",
    "analysis_type": "phase1"
  }'
```

#### 커스텀 Items로 분석

```bash
curl -X POST "http://localhost:8000/api/v1/analysis/analyze" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -d '{
    "text_content": "분석할 텍스트",
    "analysis_type": "phase1",
    "custom_items": [
      "브랜드 인지도 및 선호도",
      "제품 사용 경험 및 만족도",
      "가격 대비 가치 평가",
      "경쟁사 대비 차별점",
      "향후 구매 의향"
    ]
  }'
```

#### 전체 파이프라인 (STT + 분석) - 커스텀 Items 포함

```bash
curl -X POST "http://localhost:8000/api/v1/pipeline/full-analysis" \
  -H "Content-Type: application/json" \
  -d '{
    "audio_url": "https://example.com/audio.wav",
    "language": "ko",
    "enable_speaker_diarization": true,
    "analysis_type": "phase1",
    "custom_items": [
      "브랜드 인지도",
      "제품 경험",
      "만족도 평가"
    ]
  }'
```

### 4. 토큰 갱신

```bash
curl -X POST "http://localhost:8000/api/v1/auth/refresh" \
  -H "Content-Type: application/json" \
  -d '{
    "refreshToken": "YOUR_REFRESH_TOKEN"
  }'
```

## FastAPI 구조화 및 컨벤션

이 프로젝트는 FastAPI 공식 권장사항을 따라 구조화되었습니다:

### 1. 계층별 분리

- **API Layer**: 엔드포인트 정의 및 요청/응답 처리
- **Service Layer**: 비즈니스 로직 및 외부 API 연동
- **Model Layer**: 데이터 구조 및 검증

### 2. 설정 관리

- `pydantic-settings`를 사용한 환경변수 관리
- 타입 안전성 및 자동 검증
- `.env` 파일 지원

### 3. 의존성 주입

- 서비스 인스턴스의 싱글톤 패턴
- 설정 의존성 관리

### 4. API 버전 관리

- `/api/v1/` 접두사로 버전 관리
- 태그별 엔드포인트 그룹화

### 5. 에러 핸들링

- HTTPException을 통한 표준화된 에러 응답
- 서비스 레벨에서의 예외 처리

## 개발 모드

개발 모드에서는 다음 기능이 활성화됩니다:

- 자동 리로드 (코드 변경 시)
- 디버그 모드
- CORS 모든 오리진 허용

프로덕션 배포 시에는 `app/core/config.py`에서 설정을 조정하세요.

## 마이그레이션 가이드

기존 `main.py`를 사용하던 코드는 수정 없이 계속 작동합니다. 새로운 구조화된 방식을 사용하려면:

```python
# 기존
from main import app

# 새로운 방식
from app.main import app
```

## 기술 스택

- **FastAPI**: 고성능 웹 프레임워크
- **Pydantic**: 데이터 검증 및 설정 관리
- **Uvicorn**: ASGI 서버
- **PyJWT**: JWT 토큰 인증
- **SQLAlchemy**: ORM (Object-Relational Mapping)
- **MySQL**: 데이터베이스 (PyMySQL 드라이버)
- **Passlib**: 비밀번호 해싱
- **Google Generative AI**: 텍스트 분석
- **Daglo STT API**: 음성-텍스트 변환
- **Pandas**: 데이터 처리

## 라이선스

이 프로젝트는 회사 내부용으로 개발되었습니다.

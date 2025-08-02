app/
├── **init**.py
├── main.py # FastAPI 앱 인스턴스 및 설정
├── core/ # 핵심 설정 및 유틸리티
│ ├── **init**.py
│ ├── config.py # 환경설정
│ └── prompts.py # 동적 시스템 프롬프트 (커스텀 Items 지원)
├── models/ # Pydantic 모델
│ ├── **init**.py
│ ├── database.py # 데이터베이스 모델
│ └── schemas.py # API 요청/응답 스키마 (커스텀 Items 필드 포함)
├── api/ # API 라우터
│ ├── **init**.py
│ ├── deps.py # 의존성
│ └── v1/
│ ├── **init**.py
│ ├── api.py # 라우터 집합
│ └── endpoints/
│ ├── **init**.py
│ ├── auth.py # 인증 API
│ ├── stt.py # 음성 텍스트 변환
│ ├── analysis.py # 텍스트 분석 (커스텀 Items 지원)
│ ├── bomatic_pipeline.py # 전체 파이프라인 (커스텀 Items 지원)
│ └── ...
└── services/ # 비즈니스 로직
├── **init**.py
├── auth_service.py # 인증 서비스
├── email_service.py # 이메일 서비스
├── stt_service.py # STT 서비스
├── analysis_service.py # 통합 분석 서비스 (커스텀 Items 전달)
└── gemini_service.py # Gemini AI 서비스 (동적 프롬프트 생성)

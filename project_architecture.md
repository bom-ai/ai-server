app/
├── **init**.py
├── main.py # FastAPI 앱 인스턴스 및 설정
├── core/ # 핵심 설정 및 유틸리티
│ ├── **init**.py
│ ├── config.py # 환경설정
│ └── prompts.py # 시스템 프롬프트
├── models/ # Pydantic 모델
│ ├── **init**.py
│ └── schemas.py
├── api/ # API 라우터
│ ├── **init**.py
│ ├── deps.py # 의존성
│ └── v1/
│ ├── **init**.py
│ ├── api.py # 라우터 집합
│ └── endpoints/
│ ├── **init**.py
│ ├── stt.py
│ ├── analysis.py
│ └── pipeline.py
└── services/ # 비즈니스 로직
├── **init**.py
├── stt_service.py
├── analysis_service.py
└── gemini_service.py

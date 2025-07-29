"""
bo:matic server - 레거시 호환성을 위한 진입점

이 파일은 기존 main.py를 사용하는 코드와의 호환성을 위해 유지됩니다.
새로운 구조화된 애플리케이션은 app/main.py에서 실행됩니다.
"""

import uvicorn
from app.main import app
from app.core.config import settings

# 기존 방식으로 실행 시 새로운 구조화된 앱을 사용
if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
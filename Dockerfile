# 멀티스테이지 빌드로 이미지 크기 최적화
# Stage 1: 빌드 스테이지
FROM python:3.10-slim as builder

# 시스템 패키지 업데이트 및 빌드 종속성 설치
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 작업 디렉터리 설정
WORKDIR /app

# Python 패키지 의존성 파일 복사
COPY requirements.txt .

# pip 업그레이드 및 의존성 설치
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: 런타임 스테이지
FROM python:3.10-slim

# 비루트 사용자 생성 (보안 강화)
RUN groupadd -r appuser && useradd -r -g appuser appuser

# 필수 런타임 패키지만 설치
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 작업 디렉터리 설정
WORKDIR /app

# 빌드 스테이지에서 설치된 Python 패키지 복사
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 애플리케이션 코드 복사
COPY app/ ./app/
COPY main.py .

# 앱 디렉터리 소유권을 appuser로 변경
RUN chown -R appuser:appuser /app

# 비루트 사용자로 전환
USER appuser

# 환경변수 설정
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

# Cloud Run 포트 설정 (Cloud Run은 PORT 환경변수를 제공)
ENV PORT=8080
EXPOSE $PORT

# 헬스체크 설정
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:$PORT/health || exit 1

# Gunicorn을 사용하여 프로덕션 서버 실행
# Cloud Run은 단일 CPU 코어를 제공하므로 워커 수를 1로 설정
CMD exec gunicorn --bind :$PORT --workers 1 --worker-class uvicorn.workers.UvicornWorker --timeout 0 app.main:app

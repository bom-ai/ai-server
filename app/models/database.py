"""
데이터베이스 설정 및 모델
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings

settings = get_settings()

Base = declarative_base()

class User(Base):
    """사용자 모델"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class RefreshToken(Base):
    """리프레시 토큰 모델"""
    __tablename__ = "refresh_tokens"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    token = Column(Text, unique=True, index=True, nullable=False)
    user_id = Column(Integer, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))


# 데이터베이스 엔진 설정 (MySQL을 기본으로 사용)
SQLALCHEMY_DATABASE_URL = settings.database_url or "mysql+pymysql://user:password@localhost/bo_matic_db"

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    # SQLite 사용 시
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
    )
elif SQLALCHEMY_DATABASE_URL.startswith("mysql"):
    # MySQL 사용 시
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        echo=True  # SQL 쿼리 로깅 (개발 시에만 True로 설정)
    )
else:
    engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 데이터베이스 테이블 생성
Base.metadata.create_all(bind=engine)

def get_db():
    """데이터베이스 세션 의존성"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

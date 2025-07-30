#!/usr/bin/env python3
"""
JWT 인증 시스템 테스트 스크립트
"""
import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.append('/home/chanheo/bo:matic_server')

try:
    # JWT 토큰 생성 테스트
    import jwt
    from datetime import datetime, timedelta
    
    # 테스트용 비밀키
    secret_key = "test-secret-key"
    algorithm = "HS256"
    
    # 토큰 생성
    payload = {
        "sub": "test@example.com",
        "user_id": 1,
        "exp": datetime.utcnow() + timedelta(hours=1)
    }
    
    token = jwt.encode(payload, secret_key, algorithm=algorithm)
    print(f"✅ JWT 토큰 생성 성공: {token[:50]}...")
    
    # 토큰 검증
    decoded = jwt.decode(token, secret_key, algorithms=[algorithm])
    print(f"✅ JWT 토큰 검증 성공: {decoded}")
    
    # PyMySQL 연결 테스트 (실제 DB 없이)
    import pymysql
    print("✅ PyMySQL 임포트 성공")
    
    # SQLAlchemy 테스트
    from sqlalchemy import create_engine, text
    print("✅ SQLAlchemy 임포트 성공")
    
    # 비밀번호 해싱 테스트
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    test_password = "test123"
    hashed = pwd_context.hash(test_password)
    verified = pwd_context.verify(test_password, hashed)
    
    print(f"✅ 비밀번호 해싱 성공: {verified}")
    
    print("\n🎉 모든 인증 관련 라이브러리가 정상적으로 작동합니다!")
    
except Exception as e:
    print(f"❌ 오류 발생: {e}")
    import traceback
    traceback.print_exc()

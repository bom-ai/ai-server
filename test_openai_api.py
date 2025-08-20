"""
OpenAI API 테스트 스크립트
"""
import os
from openai import OpenAI

# 환경 변수에서 API 키 가져오기
api_key = os.getenv("OPENAI_API_KEY")

if api_key:
    client = OpenAI(api_key=api_key)
    
    # 사용 가능한 메서드들 확인
    print("OpenAI client available methods:")
    print([method for method in dir(client) if not method.startswith('_')])
    
    # responses 메서드 확인
    if hasattr(client, 'responses'):
        print("\nclient.responses available methods:")
        print([method for method in dir(client.responses) if not method.startswith('_')])
    else:
        print("\nclient.responses is not available")
        
    # chat 메서드 확인 (기존 API)
    if hasattr(client, 'chat'):
        print("\nclient.chat available methods:")
        print([method for method in dir(client.chat) if not method.startswith('_')])
        
        if hasattr(client.chat, 'completions'):
            print("\nclient.chat.completions available methods:")
            print([method for method in dir(client.chat.completions) if not method.startswith('_')])
else:
    print("OPENAI_API_KEY not found in environment variables")

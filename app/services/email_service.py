"""
이메일 서비스
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from app.core.config import get_settings

settings = get_settings()

class EmailService:
    """이메일 서비스 클래스"""
    
    @staticmethod
    def send_verification_email(email: str, verification_token: str) -> bool:
        """인증 이메일 전송"""
        try:
            # 이메일 설정이 없으면 콘솔에 출력만 하고 성공으로 처리
            if not all([settings.mail_server, settings.mail_username, settings.mail_password]):
                print(f"[EMAIL DEBUG] Verification email for {email}")
                print(f"[EMAIL DEBUG] Verification link: http://localhost:8000/api/auth/verify?token={verification_token}")
                return True
            
            # 실제 이메일 전송
            msg = MIMEMultipart()
            msg['From'] = settings.mail_from or settings.mail_username
            msg['To'] = email
            msg['Subject'] = "이메일 인증"
            
            # 이메일 본문
            body = f"""
            안녕하세요!
            
            아래 링크를 클릭하여 이메일 인증을 완료해주세요:
            
            http://localhost:8000/api/auth/verify?token={verification_token}
            
            감사합니다.
            """
            
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            # SMTP 서버 연결 및 전송
            server = smtplib.SMTP(settings.mail_server, settings.mail_port)
            if settings.mail_use_tls:
                server.starttls()
            server.login(settings.mail_username, settings.mail_password)
            text = msg.as_string()
            server.sendmail(settings.mail_username, email, text)
            server.quit()
            
            return True
            
        except Exception as e:
            print(f"이메일 전송 실패: {str(e)}")
            return False

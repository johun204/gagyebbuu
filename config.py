import os

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise RuntimeError('SECRET_KEY environment variable is required.')

KAKAO_CLIENT_ID = os.environ.get('KAKAO_CLIENT_ID', '')
KAKAO_CLIENT_SECRET = os.environ.get('KAKAO_CLIENT_SECRET', '')

# 웹 푸시(VAPID). 미설정이면 구독/발송 라우트가 조용히 비활성화된다.
VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY', '')
VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY', '')
VAPID_CLAIM_EMAIL = os.environ.get('VAPID_CLAIM_EMAIL', 'mailto:admin@example.com')


def get_database_uri():
    db_url = os.environ.get("DATABASE_URL", "sqlite:///ledger.db")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return db_url

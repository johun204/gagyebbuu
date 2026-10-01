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
    # 설치된 드라이버(psycopg2)를 명시한다. SQLAlchemy 버전에 따라 postgresql:// 의 기본 드라이버가
    # 달라질 수 있어서(2.1부터 psycopg3) 명시하지 않으면 배포 환경에 따라 DB 연결이 실패할 수 있다.
    for prefix in ("postgres://", "postgresql://"):
        if db_url.startswith(prefix):
            return "postgresql+psycopg2://" + db_url[len(prefix):]
    return db_url

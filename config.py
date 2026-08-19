import os

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise RuntimeError('SECRET_KEY environment variable is required.')

KAKAO_CLIENT_ID = os.environ.get('KAKAO_CLIENT_ID', '')
KAKAO_CLIENT_SECRET = os.environ.get('KAKAO_CLIENT_SECRET', '')


def get_database_uri():
    db_url = os.environ.get("DATABASE_URL", "sqlite:///ledger.db")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return db_url

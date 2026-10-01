"""DB 스키마 마이그레이션 실행기 (PostgreSQL 전용).

사용법:
    DATABASE_URL=postgresql://... python migrate.py           # 미적용 마이그레이션 적용
    DATABASE_URL=postgresql://... python migrate.py --status  # 적용 현황만 출력

migrations/ 폴더의 NNNN_*.sql 파일을 이름 순서대로, 아직 적용하지 않은 것만 파일 단위
트랜잭션으로 적용하고 schema_migrations 테이블에 기록한다. 하나라도 실패하면 그 파일은
전부 롤백되고 실행이 중단된다.

규칙: 마이그레이션은 이전 버전 앱 코드가 계속 동작하도록 "추가/확장"만 하고, 여러 번
실행해도 안전하게(IF NOT EXISTS 등) 작성한다. 새 DB는 app.py 의 db.create_all() 이 최신
모델 기준으로 만들기 때문에, 여기 있는 마이그레이션을 다시 적용해도 아무 변화가 없어야 한다.
"""
import os
import sys

import psycopg2

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'migrations')


def _migration_files():
    return sorted(f for f in os.listdir(MIGRATIONS_DIR) if f.endswith('.sql'))


def main():
    # config.py 는 SECRET_KEY 가 없으면 import 단계에서 실패하므로 여기서는 직접 읽는다.
    db_url = os.environ.get('DATABASE_URL', '')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    if not db_url.startswith('postgresql://'):
        sys.exit('PostgreSQL DATABASE_URL 이 필요합니다. (SQLite는 db.create_all()로 최신 스키마가 만들어집니다)')

    conn = psycopg2.connect(db_url)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL DEFAULT now())""")
            cur.execute('SELECT version FROM schema_migrations')
            applied = {r[0] for r in cur.fetchall()}

        pending = [f for f in _migration_files() if f not in applied]
        if '--status' in sys.argv:
            for f in _migration_files():
                print(('applied ' if f in applied else 'PENDING ') + f)
            return

        if not pending:
            print('적용할 마이그레이션이 없습니다.')
            return

        for f in pending:
            with open(os.path.join(MIGRATIONS_DIR, f), encoding='utf-8') as fp:
                sql = fp.read()
            with conn, conn.cursor() as cur:  # 파일 단위 트랜잭션
                cur.execute(sql)
                cur.execute('INSERT INTO schema_migrations (version) VALUES (%s)', (f,))
            print('applied', f)
    finally:
        conn.close()


if __name__ == '__main__':
    main()

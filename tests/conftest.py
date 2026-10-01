"""테스트 공용 설정.

TEST_DATABASE_URL 을 주면 그 DB(PostgreSQL 권장)에서, 없으면 메모리 SQLite 에서 실행한다.
운영과 같은 PostgreSQL 에서 돌려야 외래키/문자열 길이 제한 위반까지 잡을 수 있다.
    TEST_DATABASE_URL=postgresql://postgres:pg@localhost/gagyebbuu_test python -m pytest
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ['SECRET_KEY'] = 'test-secret'
os.environ['DATABASE_URL'] = os.environ.get('TEST_DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('VAPID_PRIVATE_KEY', '')

import jwt  # noqa: E402
from app import app as flask_app  # noqa: E402
from models import db, User, Ledger, Category  # noqa: E402


@pytest.fixture
def app():
    flask_app.config['TESTING'] = True
    with flask_app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


def token_for(user_id):
    return jwt.encode({'user_id': user_id}, 'test-secret', algorithm='HS256')


class Client:
    """로그인 토큰과 SPA 헤더를 붙여 요청하는 얇은 래퍼."""

    def __init__(self, app, user_id):
        self.c = app.test_client()
        self.h = {'Authorization': 'Bearer ' + token_for(user_id), 'X-Requested-With': 'XMLHttpRequest'}

    def get(self, url, **kw):
        return self.c.get(url, headers=self.h, **kw)

    def post(self, url, **kw):
        return self.c.post(url, headers=self.h, **kw)


@pytest.fixture
def make_ledger(app):
    """가계부 + 기본 분류(미분류/외식/카페) + 참여자들을 만든다."""
    def _make(nicknames=('철수', '영희'), name='우리집'):
        ledger = Ledger(name=name, together_color='#22B57F', monthly_budget=0)
        db.session.add(ledger)
        db.session.flush()
        cats = {}
        for i, cname in enumerate(['미분류', '외식', '카페']):
            c = Category(ledger_id=ledger.id, name=cname, sort_order=i - 1, budget=0, is_default=True, color='#F0A94E')
            db.session.add(c)
            cats[cname] = c
        users = []
        colors = ['#3FADD6', '#C876C2']
        for i, n in enumerate(nicknames):
            u = User(kakao_id=f'k-{name}-{n}', nickname=n, ledger_id=ledger.id, color=colors[i % 2])
            db.session.add(u)
            users.append(u)
        db.session.commit()
        return ledger, users, cats
    return _make


@pytest.fixture
def client_for(app):
    return lambda user: Client(app, user.id)

"""suggest_category_id 자동분류 우선순위 로직 검증 (프레임워크 없이 단독 실행)."""
import os
os.environ.setdefault('SECRET_KEY', 'test')

from datetime import datetime, timedelta
from flask import Flask
from models import db, Ledger, User, Category, Transaction
from blueprints.transactions import suggest_category_id

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
db.init_app(app)

with app.app_context():
    db.create_all()
    L = Ledger(name='t'); db.session.add(L); db.session.flush()
    uncat = Category(ledger_id=L.id, name='미분류', sort_order=-1)
    food = Category(ledger_id=L.id, name='외식', sort_order=1)
    cafe = Category(ledger_id=L.id, name='카페', sort_order=2)
    db.session.add_all([uncat, food, cafe]); db.session.flush()
    u = User(kakao_id='k', nickname='n', ledger_id=L.id); db.session.add(u); db.session.flush()

    now = datetime(2026, 9, 1, 12, 0)

    def tx(title, amount, cat, days_ago):
        db.session.add(Transaction(
            ledger_id=L.id, user_id=u.id, tx_type='지출', transactor='n',
            title=title, amount=amount, category_id=cat.id,
            datetime_val=now - timedelta(days=days_ago)))

    tx('스타벅스', 4500, cafe, 10)
    tx('스타벅스', 9000, food, 5)     # 제목 동일, 금액 상이, 더 최근
    tx('김밥천국', 8000, food, 200)   # 최근 3개월 밖
    tx('편의점', 3000, uncat, 3)      # 미분류만 존재
    db.session.flush()

    # 1순위: 제목+금액 일치
    assert suggest_category_id(L.id, '지출', '스타벅스', 4500, uncat.id, before_dt=now) == cafe.id
    # 2순위: 금액 불일치 -> 제목만 일치하는 가장 최근(food)
    assert suggest_category_id(L.id, '지출', '스타벅스', 1234, uncat.id, before_dt=now) == food.id
    # 금액 없이 호출 -> 제목만으로 2순위
    assert suggest_category_id(L.id, '지출', '스타벅스', None, uncat.id, before_dt=now) == food.id
    # 3개월 밖 내역은 무시
    assert suggest_category_id(L.id, '지출', '김밥천국', 8000, uncat.id, before_dt=now) is None
    # 미분류 내역만 있으면 추정 안 함
    assert suggest_category_id(L.id, '지출', '편의점', 3000, uncat.id, before_dt=now) is None
    # 이력 없는 제목
    assert suggest_category_id(L.id, '지출', '없는가게', 100, uncat.id, before_dt=now) is None

    print('suggest_category_id OK')

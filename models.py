from flask_sqlalchemy import SQLAlchemy
import uuid
from datetime import datetime

db = SQLAlchemy()

class Ledger(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    invite_hash = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    monthly_budget = db.Column(db.BigInteger, default=0)
    together_color = db.Column(db.String(7), nullable=True)  # '함께' 거래자를 나타내는 색상
    users = db.relationship('User', backref='ledger', lazy=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    kakao_id = db.Column(db.String(100), unique=True, nullable=False)
    nickname = db.Column(db.String(100), nullable=False)
    ledger_id = db.Column(db.Integer, db.ForeignKey('ledger.id'), nullable=True)
    color = db.Column(db.String(7), nullable=True)  # 프로필 색상 (가계부 참여 시 랜덤 배정)

class Category(db.Model):
    __table_args__ = (
        db.Index('ix_category_ledger_id', 'ledger_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    ledger_id = db.Column(db.Integer, db.ForeignKey('ledger.id'), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    budget = db.Column(db.BigInteger, default=0)
    sort_order = db.Column(db.Integer, default=0)
    color = db.Column(db.String(7), nullable=True)  # 분류 색상 (첫 배정 시 랜덤)

class Transaction(db.Model):
    __table_args__ = (
        db.Index('ix_transaction_ledger_datetime', 'ledger_id', 'datetime_val'),
        db.Index('ix_transaction_transactor_user_id', 'transactor_user_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    ledger_id = db.Column(db.Integer, db.ForeignKey('ledger.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # 등록한 사람

    tx_type = db.Column(db.String(10), nullable=False, default='지출')
    # 화면에 표시되는 거래자 이름('함께' 또는 닉네임). 닉네임 변경 시 '과거 내역도 변경'을 고른 경우에만 갱신된다.
    transactor = db.Column(db.String(50), nullable=False, default='')
    # 거래자가 특정 사용자일 때 그 사용자 id ('함께'이거나 예전 데이터라 매칭이 안 되면 NULL).
    # 닉네임이 바뀌어도 색상/참여자별 집계가 끊기지 않도록 이름 대신 이 값으로 사람을 식별한다.
    transactor_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    title = db.Column(db.String(100), nullable=False, default='')
    memo = db.Column(db.String(255), nullable=True, default='')
    amount = db.Column(db.BigInteger, nullable=False)
    exclude_analysis = db.Column(db.Boolean, default=False) # 지출 분석(차트/총계)에서 제외
    exclude_budget = db.Column(db.Boolean, default=False) # 예산 진행률 계산에서만 제외

    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    datetime_val = db.Column(db.DateTime, nullable=False, default=datetime.now)

    category = db.relationship('Category')
    user = db.relationship('User', foreign_keys=[user_id])

class PushSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    endpoint = db.Column(db.String(500), nullable=False, unique=True)
    p256dh = db.Column(db.String(255), nullable=False)
    auth = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ledger_id = db.Column(db.Integer, db.ForeignKey('ledger.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    is_read = db.Column(db.Boolean, default=False)

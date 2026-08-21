from flask_sqlalchemy import SQLAlchemy
import uuid
from datetime import datetime

db = SQLAlchemy()

class Ledger(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    invite_hash = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    monthly_budget = db.Column(db.Integer, default=0)
    users = db.relationship('User', backref='ledger', lazy=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    kakao_id = db.Column(db.String(100), unique=True, nullable=False)
    nickname = db.Column(db.String(100), nullable=False)
    ledger_id = db.Column(db.Integer, db.ForeignKey('ledger.id'), nullable=True)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ledger_id = db.Column(db.Integer, db.ForeignKey('ledger.id'), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    budget = db.Column(db.Integer, default=0)
    sort_order = db.Column(db.Integer, default=0)

class Transaction(db.Model):
    __table_args__ = (
        db.Index('ix_transaction_ledger_datetime', 'ledger_id', 'datetime_val'),
    )

    id = db.Column(db.Integer, primary_key=True)
    ledger_id = db.Column(db.Integer, db.ForeignKey('ledger.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    tx_type = db.Column(db.String(10), nullable=False, default='지출')
    transactor = db.Column(db.String(50), nullable=False, default='') 
    title = db.Column(db.String(100), nullable=False, default='')
    memo = db.Column(db.String(255), nullable=True, default='')
    amount = db.Column(db.Integer, nullable=False)
    exclude_analysis = db.Column(db.Boolean, default=False) # 지출 분석(차트/총계)에서 제외
    exclude_budget = db.Column(db.Boolean, default=False) # 예산 진행률 계산에서만 제외
    
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    datetime_val = db.Column(db.DateTime, nullable=False, default=datetime.now)
    
    category = db.relationship('Category')
    user = db.relationship('User')

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
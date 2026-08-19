import os
import time

# Vercel 등 서버리스 환경에서 한국 시간대(KST)로 시스템 시간 강제 설정
os.environ['TZ'] = 'Asia/Seoul'
if hasattr(time, 'tzset'):
    time.tzset()

import jwt
from flask import Flask, request, jsonify, render_template

import config
from models import db, User, Ledger

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

app.config['SQLALCHEMY_DATABASE_URI'] = config.get_database_uri()
# 서버리스 함수가 재사용될 때 Neon 쪽에서 이미 끊긴 커넥션을 그대로 쓰다가
# "SSL connection has been closed unexpectedly" 로 죽는 문제 방지 (사용 전 핑 체크 후 재연결)
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
db.init_app(app)

with app.app_context():
    db.create_all()

from blueprints.auth import auth_bp
from blueprints.home import home_bp
from blueprints.calendar_routes import calendar_bp
from blueprints.transactions import transactions_bp
from blueprints.settings import settings_bp
from blueprints.push import push_bp

app.register_blueprint(auth_bp)
app.register_blueprint(home_bp)
app.register_blueprint(calendar_bp)
app.register_blueprint(transactions_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(push_bp)

@app.route('/sw.js')
def serve_sw():
    return app.send_static_file('sw.js')


@app.context_processor
def inject_user():
    user_id = getattr(request, 'user_id', None)
    has_ledger = False
    if user_id:
        try:
            user = User.query.get(user_id)
            if user and user.ledger_id:
                has_ledger = True
        except:
            pass
    return dict(current_user_id=user_id, has_ledger=has_ledger)


@app.before_request
def require_login():
    public_endpoints = ['auth.login', 'auth.kakao_callback', 'static', 'serve_sw', 'auth.logout']
    if request.endpoint in public_endpoints:
        return

    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        try:
            payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
            request.user_id = payload['user_id']
            return
        except Exception:
            pass

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept') == 'application/json':
        return jsonify({'error': 'Unauthorized'}), 401

    og_title = '가계쀼 - 공유 가계부'
    og_desc = '부부가 함께 쓰는 귀여운 가계부, 수입과 지출을 쉽고 투명하게 관리해보세요.'

    if request.path.startswith('/invite/'):
        hash_val = request.path.split('/')[-1]
        ledger = Ledger.query.filter_by(invite_hash=hash_val).first()
        if ledger:
            og_title = f"[{ledger.name}] 가계부에 초대되었습니다."
            og_desc = "링크를 눌러 공유 가계부에 참여해보세요!"

    return render_template('bootstrap.html', og_title=og_title, og_desc=og_desc)


@app.errorhandler(500)
def internal_server_error(e):
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept') == 'application/json':
        return jsonify({'error': '서버 지연이 발생했습니다. 다시 시도해주세요.'}), 500
    return "<h2 style='text-align:center; margin-top:50px;'>서버 접속이 원활하지 않습니다.<br>새로고침을 눌러주세요.</h2>", 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=False)

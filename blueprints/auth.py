import secrets
import jwt
import requests
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session

import config
from models import db, User, Ledger, Category, Transaction, Notification
from helpers import spa_redirect, get_kakao_redirect_uri

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login')
def login():
    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state
    return render_template('login.html', client_id=config.KAKAO_CLIENT_ID, redirect_uri=get_kakao_redirect_uri(), state=state)


@auth_bp.route('/logout')
def logout():
    return """<script>
        localStorage.removeItem('jwt_token');
        if ('caches' in window) {
            caches.keys().then(keys => Promise.all(keys.map(k => caches.delete(k)))).finally(() => window.location.href='/login');
        } else {
            window.location.href='/login';
        }
    </script>"""


@auth_bp.route('/oauth/kakao/callback')
def kakao_callback():
    if request.args.get('error'): return redirect(url_for('auth.login'))
    code = request.args.get('code')
    if not code: return redirect(url_for('auth.login'))

    expected_state = session.pop('oauth_state', None)
    if not expected_state or request.args.get('state') != expected_state:
        return redirect(url_for('auth.login'))

    token_url = "https://kauth.kakao.com/oauth/token"
    token_data = {
        "grant_type": "authorization_code", "client_id": config.KAKAO_CLIENT_ID,
        "redirect_uri": get_kakao_redirect_uri(), "code": code
    }
    if config.KAKAO_CLIENT_SECRET: token_data["client_secret"] = config.KAKAO_CLIENT_SECRET

    token_res = requests.post(token_url, data=token_data, headers={"Content-type": "application/x-www-form-urlencoded;charset=utf-8"}).json()
    access_token = token_res.get('access_token')
    if not access_token: return redirect(url_for('auth.login'))

    user_info = requests.get("https://kapi.kakao.com/v2/user/me", headers={"Authorization": f"Bearer {access_token}"}).json()
    kakao_id = str(user_info.get('id'))
    nickname = user_info.get('kakao_account', {}).get('profile', {}).get('nickname', '카카오사용자')

    user = User.query.filter_by(kakao_id=kakao_id).first()
    if not user:
        user = User(kakao_id=kakao_id, nickname=nickname)
        db.session.add(user)
        db.session.commit()

    token = jwt.encode({'user_id': user.id, 'exp': datetime.utcnow() + timedelta(days=365)}, config.SECRET_KEY, algorithm='HS256')
    return render_template('token_save.html', token=token)


@auth_bp.route('/onboarding', methods=['GET', 'POST'])
def onboarding():
    user = User.query.get(request.user_id)
    if not user: return spa_redirect(url_for('auth.logout'))
    if user.ledger_id: return spa_redirect(url_for('home.home'))

    error_msg = None
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'create':
            new_ledger = Ledger(name=request.form.get('ledger_name'))
            db.session.add(new_ledger)
            db.session.flush()

            db.session.add(Category(ledger_id=new_ledger.id, name='미분류', is_default=True, sort_order=-1))
            default_cats = ['급여', '용돈', '외식비', '교통/차량', '마트', '문화생활', '주거', '통신']
            for i, cat_name in enumerate(default_cats):
                db.session.add(Category(ledger_id=new_ledger.id, name=cat_name, is_default=True, sort_order=i+1))

            user.ledger_id = new_ledger.id
            db.session.commit()
            return spa_redirect(url_for('home.home'))

        elif action == 'join':
            invite_code = request.form.get('invite_code', '').strip()
            ledger = Ledger.query.filter_by(invite_hash=invite_code).first()
            if ledger and len(ledger.users) < 2:
                user.ledger_id = ledger.id
                db.session.commit()
                return spa_redirect(url_for('home.home'))
            else:
                error_msg = "유효하지 않거나 이미 2명이 참여 중인 초대 코드입니다."

    return render_template('onboarding.html', error=error_msg)


@auth_bp.route('/invite_process')
def invite_process():
    hash = request.args.get('hash')
    user = User.query.get(request.user_id)
    if not user: return spa_redirect(url_for('auth.logout'))
    if user.ledger_id:
        return "<script>localStorage.removeItem('pending_invite'); alert('이미 가계부에 참여 중입니다.'); window.location.href='/home';</script>"

    ledger = Ledger.query.filter_by(invite_hash=hash).first()
    if ledger and len(ledger.users) < 2:
        user.ledger_id = ledger.id
        db.session.commit()
        return "<script>localStorage.removeItem('pending_invite'); window.location.href='/home';</script>"
    else:
        return "<script>localStorage.removeItem('pending_invite'); alert('유효하지 않거나 이미 인원이 가득 찬 초대 링크입니다.'); window.location.href='/onboarding';</script>"


@auth_bp.route('/invite/<hash>')
def invite(hash):
    user = User.query.get(request.user_id)
    if not user: return spa_redirect(url_for('auth.logout'))
    if user.ledger_id:
        return "<script>alert('이미 가계부에 참여 중입니다. 설정에서 기존 가계부를 나간 후 초대를 수락해주세요.'); window.location.href='/home';</script>"

    ledger = Ledger.query.filter_by(invite_hash=hash).first()
    if ledger and len(ledger.users) < 2:
        user.ledger_id = ledger.id
        db.session.commit()
        return redirect(url_for('home.home'))
    else:
        return "<script>alert('유효하지 않거나 이미 인원이 가득 찬 초대 링크입니다.'); window.location.href='/home';</script>"


@auth_bp.route('/leave_ledger', methods=['POST'])
def leave_ledger():
    user = User.query.get(request.user_id)
    if not user: return spa_redirect(url_for('auth.logout'))
    if not user.ledger_id:
        return spa_redirect(url_for('auth.onboarding'))

    ledger = Ledger.query.get(user.ledger_id)
    if ledger:
        if len(ledger.users) <= 1:
            Transaction.query.filter_by(ledger_id=ledger.id).delete()
            Category.query.filter_by(ledger_id=ledger.id).delete()
            Notification.query.filter_by(ledger_id=ledger.id).delete()
            user.ledger_id = None
            db.session.delete(ledger)
        else:
            user.ledger_id = None
        db.session.commit()

    return spa_redirect(url_for('auth.onboarding'))

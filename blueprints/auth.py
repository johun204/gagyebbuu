import json
import secrets
import uuid
import jwt
import requests
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, g
from itsdangerous import URLSafeTimedSerializer, BadData

import config
from models import db, User, Ledger, Category, Transaction, Notification
from helpers import (spa_redirect, get_kakao_redirect_uri, pick_random_color, require_ledger, clean_text,
                     TOGETHER, UNCATEGORIZED, MAX_LEDGER_NAME_LEN, MAX_NICKNAME_LEN)

# OAuth CSRF용 state를 서버 세션(쿠키) 대신 SECRET_KEY로 서명한 무상태 토큰으로 발급한다.
# 서버리스/PWA 캐시 환경에서 세션 쿠키가 왕복되지 않아 로그인 루프가 생기던 문제를 막기 위함.
_state_serializer = URLSafeTimedSerializer(config.SECRET_KEY, salt='kakao-oauth-state')
_STATE_MAX_AGE = 600  # 10분
_KAKAO_TIMEOUT = 5  # 초. 카카오 응답이 늦어도 서버리스 함수가 멈춰 있지 않도록

_LEDGER_FULL_MSG = '유효하지 않거나 이미 2명이 참여 중인 초대 코드입니다.'


def _make_oauth_state():
    return _state_serializer.dumps(secrets.token_urlsafe(8))


def _valid_oauth_state(value):
    if not value:
        return False
    try:
        _state_serializer.loads(value, max_age=_STATE_MAX_AGE)
        return True
    except BadData:
        return False


def _unique_nickname(nickname, other_nicknames):
    """'함께' 또는 같은 가계부의 다른 사람과 겹치지 않는 닉네임으로 바꾼다 (겹치면 뒤에 숫자)."""
    taken = set(other_nicknames) | {TOGETHER}
    if nickname not in taken:
        return nickname
    base = nickname[:MAX_NICKNAME_LEN - 3]
    n = 2
    while f"{base} {n}" in taken:
        n += 1
    return f"{base} {n}"


def _join_ledger(user, invite_hash):
    """초대 코드로 가계부에 참여시킨다. 성공하면 True.
    두 사람이 동시에 같은 초대로 참여해 3명이 되는 일을 막기 위해 가계부 행을 잠그고 인원을 다시 센다."""
    if not invite_hash:
        return False
    ledger = Ledger.query.filter_by(invite_hash=invite_hash).with_for_update().first()
    if not ledger:
        return False
    members = User.query.filter(User.ledger_id == ledger.id).all()
    if len(members) >= 2:
        db.session.rollback()
        return False

    existing_colors = [u.color for u in members if u.color]
    if ledger.together_color:
        existing_colors.append(ledger.together_color)
    user.color = pick_random_color(existing_colors)
    user.nickname = _unique_nickname(user.nickname, [u.nickname for u in members])
    user.ledger_id = ledger.id
    db.session.commit()
    return True


auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login')
def login():
    state = _make_oauth_state()
    return render_template('login.html', client_id=config.KAKAO_CLIENT_ID, redirect_uri=get_kakao_redirect_uri(),
                           state=state, auth_error=request.args.get('err') == 'auth')


@auth_bp.route('/logout')
def logout():
    # 같은 기기에서 다른 사람이 로그인했을 때 이전 사용자 앞으로 푸시 알림이 계속 오지 않도록
    # 이 기기의 푸시 구독을 서버와 브라우저 양쪽에서 해제한 뒤 토큰/캐시를 지운다.
    # 푸시 해제가 실패하거나 오래 걸려도(최대 2초) 로그아웃 자체는 반드시 진행된다.
    return """<script>
    (function() {
        var finish = function() {
            localStorage.removeItem('jwt_token');
            var go = function() { window.location.href = '/login'; };
            if ('caches' in window) {
                caches.keys().then(function(keys) { return Promise.all(keys.map(function(k) { return caches.delete(k); })); }).finally(go);
            } else { go(); }
        };
        var done = false;
        var once = function() { if (!done) { done = true; finish(); } };
        setTimeout(once, 2000);
        try {
            var token = localStorage.getItem('jwt_token');
            if (!('serviceWorker' in navigator) || !('PushManager' in window)) { once(); return; }
            navigator.serviceWorker.getRegistration().then(function(reg) {
                return reg ? reg.pushManager.getSubscription() : null;
            }).then(function(sub) {
                if (!sub) return;
                var req = token ? fetch('/api/push/unsubscribe', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token, 'X-Requested-With': 'XMLHttpRequest' },
                    body: JSON.stringify({ endpoint: sub.endpoint })
                }).catch(function() {}) : Promise.resolve();
                return req.then(function() { return sub.unsubscribe(); });
            }).catch(function() {}).finally(once);
        } catch (e) { once(); }
    })();
    </script>"""


@auth_bp.route('/oauth/kakao/callback')
def kakao_callback():
    if request.args.get('error'): return redirect(url_for('auth.login', err='auth'))
    code = request.args.get('code')
    if not code: return redirect(url_for('auth.login', err='auth'))

    if not _valid_oauth_state(request.args.get('state')):
        return redirect(url_for('auth.login', err='auth'))

    token_url = "https://kauth.kakao.com/oauth/token"
    token_data = {
        "grant_type": "authorization_code", "client_id": config.KAKAO_CLIENT_ID,
        "redirect_uri": get_kakao_redirect_uri(), "code": code
    }
    if config.KAKAO_CLIENT_SECRET: token_data["client_secret"] = config.KAKAO_CLIENT_SECRET

    try:
        token_res = requests.post(token_url, data=token_data, timeout=_KAKAO_TIMEOUT,
                                  headers={"Content-type": "application/x-www-form-urlencoded;charset=utf-8"}).json()
        access_token = token_res.get('access_token')
        if not access_token: return redirect(url_for('auth.login', err='auth'))

        user_info = requests.get("https://kapi.kakao.com/v2/user/me", timeout=_KAKAO_TIMEOUT,
                                 headers={"Authorization": f"Bearer {access_token}"}).json()
    except (requests.RequestException, ValueError):
        return redirect(url_for('auth.login', err='auth'))

    if not user_info.get('id'):
        return redirect(url_for('auth.login', err='auth'))
    kakao_id = str(user_info.get('id'))
    nickname = clean_text((user_info.get('kakao_account') or {}).get('profile', {}).get('nickname'), MAX_NICKNAME_LEN) or '카카오사용자'

    user = User.query.filter_by(kakao_id=kakao_id).first()
    if not user:
        user = User(kakao_id=kakao_id, nickname=_unique_nickname(nickname, []))
        db.session.add(user)
        db.session.commit()

    token = jwt.encode({'user_id': user.id, 'exp': datetime.utcnow() + timedelta(days=365)}, config.SECRET_KEY, algorithm='HS256')
    return render_template('token_save.html', token=token)


@auth_bp.route('/onboarding', methods=['GET', 'POST'])
def onboarding():
    user = db.session.get(User, request.user_id)
    if not user: return spa_redirect(url_for('auth.logout'))
    if user.ledger_id: return spa_redirect(url_for('home.home'))

    error_msg = None
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'create':
            ledger_name = clean_text(request.form.get('ledger_name'), MAX_LEDGER_NAME_LEN)
            if not ledger_name:
                error_msg = "가계부 이름을 입력해주세요."
            else:
                new_ledger = Ledger(name=ledger_name, together_color=pick_random_color([]))
                db.session.add(new_ledger)
                db.session.flush()

                used_colors = [new_ledger.together_color]
                uncat_color = pick_random_color(used_colors)
                used_colors.append(uncat_color)
                db.session.add(Category(ledger_id=new_ledger.id, name=UNCATEGORIZED, is_default=True, sort_order=-1, color=uncat_color))
                default_cats = ['급여', '용돈', '외식비', '교통/차량', '마트', '문화생활', '주거', '통신']
                for i, cat_name in enumerate(default_cats):
                    cat_color = pick_random_color(used_colors)
                    used_colors.append(cat_color)
                    db.session.add(Category(ledger_id=new_ledger.id, name=cat_name, is_default=True, sort_order=i+1, color=cat_color))

                user.ledger_id = new_ledger.id
                user.color = pick_random_color([new_ledger.together_color])
                user.nickname = _unique_nickname(user.nickname, [])
                db.session.commit()
                return spa_redirect(url_for('home.home'))

        elif action == 'join':
            if _join_ledger(user, request.form.get('invite_code', '').strip()):
                return spa_redirect(url_for('home.home'))
            error_msg = _LEDGER_FULL_MSG

    return render_template('onboarding.html', error=error_msg)


def _alert_and_go(message, target, clear_pending=False):
    js = "localStorage.removeItem('pending_invite');" if clear_pending else ''
    if message:
        js += f"alert({json.dumps(message, ensure_ascii=False)});"
    js += f"window.location.href={json.dumps(target)};"
    return f"<script>{js}</script>"


@auth_bp.route('/invite_process')
def invite_process():
    user = db.session.get(User, request.user_id)
    if not user: return spa_redirect(url_for('auth.logout'))
    if user.ledger_id:
        return _alert_and_go('이미 가계부에 참여 중입니다.', '/home', clear_pending=True)

    if _join_ledger(user, request.args.get('hash')):
        return _alert_and_go(None, '/home', clear_pending=True)
    return _alert_and_go('유효하지 않거나 이미 인원이 가득 찬 초대 링크입니다.', '/onboarding', clear_pending=True)


@auth_bp.route('/invite/<hash>')
def invite(hash):
    user = db.session.get(User, request.user_id)
    if not user: return spa_redirect(url_for('auth.logout'))
    if user.ledger_id:
        return _alert_and_go('이미 가계부에 참여 중입니다. 설정에서 기존 가계부를 나간 후 초대를 수락해주세요.', '/home', clear_pending=True)

    if _join_ledger(user, hash):
        return _alert_and_go(None, '/home', clear_pending=True)
    return _alert_and_go('유효하지 않거나 이미 인원이 가득 찬 초대 링크입니다.', '/home', clear_pending=True)


@auth_bp.route('/regenerate_invite', methods=['POST'])
@require_ledger
def regenerate_invite():
    """초대 링크/코드를 새로 발급한다. 이전 링크는 더 이상 쓸 수 없다."""
    g.ledger.invite_hash = str(uuid.uuid4())
    db.session.commit()
    return spa_redirect(url_for('settings.mypage', msg='invite_regenerated'))


@auth_bp.route('/leave_ledger', methods=['POST'])
def leave_ledger():
    user = db.session.get(User, request.user_id)
    if not user: return spa_redirect(url_for('auth.logout'))
    if not user.ledger_id:
        return spa_redirect(url_for('auth.onboarding'))

    ledger = Ledger.query.filter_by(id=user.ledger_id).with_for_update().first()
    if ledger:
        remaining = User.query.filter(User.ledger_id == ledger.id, User.id != user.id).count()
        if remaining == 0:
            Transaction.query.filter_by(ledger_id=ledger.id).delete()
            Category.query.filter_by(ledger_id=ledger.id).delete()
            Notification.query.filter_by(ledger_id=ledger.id).delete()
            user.ledger_id = None
            db.session.delete(ledger)
        else:
            user.ledger_id = None
            # 나간 사람(또는 예전 링크를 가진 누구든)이 옛 초대 링크로 다시 들어와
            # 남은 사람의 내역을 보지 못하도록 초대 링크를 새로 발급한다.
            ledger.invite_hash = str(uuid.uuid4())
        db.session.commit()
    else:
        user.ledger_id = None
        db.session.commit()

    return spa_redirect(url_for('auth.onboarding'))

import os
import time
import jwt

# Vercel 등 서버리스 환경에서 한국 시간대(KST)로 시스템 시간 강제 설정
os.environ['TZ'] = 'Asia/Seoul'
if hasattr(time, 'tzset'):
    time.tzset()

from flask import Flask, render_template, request, redirect, url_for, jsonify, Response, render_template_string
from datetime import datetime, timedelta
import csv
import io
import requests
from models import db, User, Ledger, Category, Transaction, Notification

app = Flask(__name__)

# JWT 암호화에 사용될 시크릿 키 (Vercel 환경변수에서 설정 권장)
app.secret_key = os.environ.get('SECRET_KEY', 'gagye_bbu_fallback_secret_key_987654321')

db_url = os.environ.get("DATABASE_URL", "sqlite:///ledger.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
db.init_app(app)

with app.app_context():
    db.create_all()

KAKAO_CLIENT_ID = os.environ.get('KAKAO_CLIENT_ID', '')
KAKAO_CLIENT_SECRET = os.environ.get('KAKAO_CLIENT_SECRET', '')

BOOTSTRAP_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>가계쀼 - 공유 가계부</title>
    
    <meta property="og:title" content="가계쀼 - 공유 가계부">
    <meta property="og:description" content="부부가 함께 쓰는 귀여운 가계부, 수입과 지출을 쉽고 투명하게 관리해보세요.">
    <meta property="og:image" content="{{ request.host_url }}static/icon-512.png">
    <meta property="og:url" content="{{ request.host_url }}">
    
    <link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css" />
    <style>
        :root {
            --color-primary: #13bd7e; --color-action: #06a96c; --color-canvas: #ffffff;
            --color-foreground: #111111; --color-secondary: #555c68; --color-muted: #9fa4b0; --color-line: #f0f2f5;
            --font-sans: Pretendard, -apple-system, BlinkMacSystemFont, system-ui, "Segoe UI", Roboto, sans-serif;
            --spacing-sm: 8px; --spacing-md: 12px; --spacing-base: 16px; --spacing-lg: 24px;
            --radius-chip: 6px; --radius-action: 16px; --radius-card: 24px; --radius-full: 9999px;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: var(--font-sans); background-color: var(--color-canvas); color: var(--color-foreground); line-height: 1.5; padding: var(--spacing-base); padding-bottom: 130px; max-width: 768px; margin: 0 auto; }
        
        .card { background-color: var(--color-canvas); border: 1px solid var(--color-line); border-radius: var(--radius-card); padding: var(--spacing-lg); margin-bottom: var(--spacing-lg); }
        .month-selector { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--spacing-base); }
        .month-selector h3 { font-size: 20px; font-weight: 700; padding: 4px 12px; border-radius: 8px; background: rgba(0,0,0,0.03); }
        .month-selector a { text-decoration: none; color: var(--color-foreground); font-size: 24px; padding: 0 10px; }
        
        .bottom-nav { position: fixed; bottom: 0; left: 0; right: 0; background-color: rgba(255, 255, 255, 0.95); backdrop-filter: blur(10px); border-top: 1px solid var(--color-line); display: flex; justify-content: space-around; align-items: center; z-index: 1000; padding-bottom: calc(env(safe-area-inset-bottom) + 16px); padding-top: 10px; box-sizing: content-box; }
        .bottom-nav a { text-decoration: none; color: var(--color-muted); font-size: 12px; font-weight: 500; display: flex; flex-direction: column; align-items: center; gap: 4px; flex: 1; text-align: center; }
        .bottom-nav a.active { color: var(--color-foreground); font-weight: 700; }

        .skeleton { background: #e0e0e0; background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%); background-size: 200% 100%; animation: shimmer 1.5s infinite; border-radius: 4px; }
        @keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
        .skeleton-text { height: 20px; margin-bottom: 12px; width: 100%; }
        .skeleton-text.short { width: 50%; }
    </style>
</head>
<body>
    <main>
        <div class="month-selector"><a href="#" style="visibility:hidden;">◀</a><h3><div class="skeleton skeleton-text short" style="margin:0 auto;height:24px;"></div></h3><a href="#" style="visibility:hidden;">▶</a></div>
        <div class="card">
            <h2 style="font-size: 18px; font-weight: 700; margin-bottom: 16px;">이번 달 요약</h2>
            <div style="display: flex; gap: 12px; margin-bottom: 16px;">
                <div class="skeleton" style="flex:1; height:76px; border-radius:16px;"></div><div class="skeleton" style="flex:1; height:76px; border-radius:16px;"></div>
            </div>
            <div style="padding-top: 16px; border-top: 1px solid var(--color-line);">
                <div class="skeleton skeleton-text short" style="height:14px; margin-bottom: 4px;"></div>
                <div class="skeleton" style="width: 100%; height: 10px; border-radius: 4px; margin-bottom: 16px;"></div>
                <div style="display: flex; justify-content: space-between; margin-bottom: 2px;"><div class="skeleton skeleton-text" style="width: 20%; height:12px;"></div><div class="skeleton skeleton-text" style="width: 30%; height:12px;"></div></div>
                <div class="skeleton" style="width: 100%; height: 6px; border-radius: 3px; margin-bottom: 8px;"></div>
                <div style="display: flex; justify-content: space-between; margin-bottom: 2px;"><div class="skeleton skeleton-text" style="width: 25%; height:12px;"></div><div class="skeleton skeleton-text" style="width: 20%; height:12px;"></div></div>
                <div class="skeleton" style="width: 100%; height: 6px; border-radius: 3px; margin-bottom: 8px;"></div>
            </div>
        </div>
        <div class="card"><h3 style="font-size: 18px; font-weight: 700; margin-bottom: 16px;">지출 분석</h3><div class="skeleton" style="width:100%; height:150px; border-radius:8px;"></div></div>
    </main>

    <div class="bottom-nav">
        <a href="#" class="nav-link active"><span style="font-size:20px;">🏠</span>홈</a>
        <a href="#" class="nav-link"><span style="font-size:20px;">📅</span>달력</a>
        <a href="#" class="nav-link"><span style="font-size:20px;">📝</span>내역</a>
        <a href="#" class="nav-link"><span style="font-size:20px;">⚙️</span>설정</a>
    </div>

    <script>
        const token = localStorage.getItem('jwt_token');
        const currentUrl = window.location.href;
        
        if (window.location.pathname.startsWith('/invite/')) {
            const hash = window.location.pathname.split('/').pop();
            localStorage.setItem('pending_invite', hash);
        }

        if (token) {
            fetch(currentUrl, {
                headers: { 'Authorization': 'Bearer ' + token, 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(res => {
                if (res.status === 401) {
                    localStorage.removeItem('jwt_token');
                    window.location.href = '/login';
                } else { return res.text(); }
            })
            .then(html => {
                if(html) {
                    document.open(); document.write(html); document.close();
                }
            }).catch(() => { window.location.href = '/login'; });
        } else {
            window.location.href = '/login';
        }
    </script>
</body>
</html>
"""

TOKEN_SAVE_HTML = """
<!DOCTYPE html>
<html>
<head><title>로그인 처리 중...</title></head>
<body>
    <script>
        localStorage.setItem('jwt_token', '{{ token }}');
        const pending = localStorage.getItem('pending_invite');
        if (pending) {
            window.location.href = '/invite_process?hash=' + pending;
        } else {
            window.location.href = '/home';
        }
    </script>
</body>
</html>
"""

@app.route('/sw.js')
def serve_sw():
    return app.send_static_file('sw.js')

@app.context_processor
def inject_user():
    # 사용자가 가계부에 가입되어 있는지 여부를 하단 메뉴바 표시 등에 활용합니다.
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
    public_endpoints = ['login', 'kakao_callback', 'static', 'serve_sw', 'logout']
    if request.endpoint in public_endpoints:
        return

    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        try:
            payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
            request.user_id = payload['user_id']
            return  
        except jwt.ExpiredSignatureError:
            pass
        except jwt.InvalidTokenError:
            pass

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept') == 'application/json':
        return jsonify({'error': 'Unauthorized'}), 401

    return render_template_string(BOOTSTRAP_HTML)

@app.errorhandler(500)
def internal_server_error(e):
    return redirect(url_for('login'))

def get_target_date():
    now = datetime.now()
    req_year = request.args.get('year')
    req_month = request.args.get('month')
    
    target_year = now.year
    target_month = now.month
    
    if req_year and req_month and req_year != 'today' and req_month != 'today':
        try:
            target_year = int(req_year)
            target_month = int(req_month)
        except ValueError:
            pass
    
    p_m = target_month - 1 if target_month > 1 else 12
    p_y = target_year if target_month > 1 else target_year - 1
    n_m = target_month + 1 if target_month < 12 else 1
    n_y = target_year if target_month < 12 else target_year + 1
    
    return target_year, target_month, p_y, p_m, n_y, n_m

def get_kakao_redirect_uri():
    return f"{request.host_url.rstrip('/')}/oauth/kakao/callback"

def get_or_create_uncategorized(ledger_id):
    cat = Category.query.filter_by(ledger_id=ledger_id, name='미분류').first()
    if not cat:
        cat = Category(ledger_id=ledger_id, name='미분류', is_default=True, sort_order=-1)
        db.session.add(cat)
        db.session.flush()
    return cat.id

@app.route('/login')
def login():
    return render_template('login.html', client_id=KAKAO_CLIENT_ID, redirect_uri=get_kakao_redirect_uri())

@app.route('/logout')
def logout():
    return "<script>localStorage.removeItem('jwt_token'); window.location.href='/login';</script>"

@app.route('/oauth/kakao/callback')
def kakao_callback():
    if request.args.get('error'): return redirect(url_for('login'))
    code = request.args.get('code')
    if not code: return redirect(url_for('login'))

    token_url = "https://kauth.kakao.com/oauth/token"
    token_data = {
        "grant_type": "authorization_code", "client_id": KAKAO_CLIENT_ID,
        "redirect_uri": get_kakao_redirect_uri(), "code": code
    }
    if KAKAO_CLIENT_SECRET: token_data["client_secret"] = KAKAO_CLIENT_SECRET

    token_res = requests.post(token_url, data=token_data, headers={"Content-type": "application/x-www-form-urlencoded;charset=utf-8"}).json()
    access_token = token_res.get('access_token')
    if not access_token: return redirect(url_for('login'))

    user_info = requests.get("https://kapi.kakao.com/v2/user/me", headers={"Authorization": f"Bearer {access_token}"}).json()
    kakao_id = str(user_info.get('id'))
    nickname = user_info.get('kakao_account', {}).get('profile', {}).get('nickname', '카카오사용자')

    user = User.query.filter_by(kakao_id=kakao_id).first()
    if not user:
        user = User(kakao_id=kakao_id, nickname=nickname)
        db.session.add(user)
        db.session.commit()
        
    token = jwt.encode({'user_id': user.id, 'exp': datetime.utcnow() + timedelta(days=365)}, app.secret_key, algorithm='HS256')
    
    return render_template_string(TOKEN_SAVE_HTML, token=token)

@app.route('/onboarding', methods=['GET', 'POST'])
def onboarding():
    user = User.query.get(request.user_id)
    if user.ledger_id: return redirect(url_for('home'))
    
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
            return redirect(url_for('home'))
            
        elif action == 'join':
            invite_code = request.form.get('invite_code', '').strip()
            ledger = Ledger.query.filter_by(invite_hash=invite_code).first()
            if ledger and len(ledger.users) < 2:
                user.ledger_id = ledger.id
                db.session.commit()
                return redirect(url_for('home'))
            else:
                error_msg = "유효하지 않거나 이미 2명이 참여 중인 초대 코드입니다."
                
    return render_template('onboarding.html', error=error_msg)

@app.route('/invite_process')
def invite_process():
    hash = request.args.get('hash')
    user = User.query.get(request.user_id)
    if user.ledger_id:
        return "<script>localStorage.removeItem('pending_invite'); alert('이미 가계부에 참여 중입니다.'); window.location.href='/home';</script>"
    
    ledger = Ledger.query.filter_by(invite_hash=hash).first()
    if ledger and len(ledger.users) < 2:
        user.ledger_id = ledger.id
        db.session.commit()
        return "<script>localStorage.removeItem('pending_invite'); window.location.href='/home';</script>"
    else:
        return "<script>localStorage.removeItem('pending_invite'); alert('유효하지 않거나 이미 인원이 가득 찬 초대 링크입니다.'); window.location.href='/onboarding';</script>"

@app.route('/invite/<hash>')
def invite(hash):
    user = User.query.get(request.user_id)
    if user.ledger_id:
        return "<script>alert('이미 가계부에 참여 중입니다. 설정에서 기존 가계부를 나간 후 초대를 수락해주세요.'); window.location.href='/home';</script>"
        
    ledger = Ledger.query.filter_by(invite_hash=hash).first()
    if ledger and len(ledger.users) < 2:
        user.ledger_id = ledger.id
        db.session.commit()
        return redirect(url_for('home'))
    else:
        return "<script>alert('유효하지 않거나 이미 인원이 가득 찬 초대 링크입니다.'); window.location.href='/home';</script>"

@app.route('/leave_ledger', methods=['POST'])
def leave_ledger():
    user = User.query.get(request.user_id)
    if not user or not user.ledger_id:
        return redirect(url_for('onboarding'))

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
        
    return redirect(url_for('onboarding'))

def build_home_data(user_id, y, m):
    user = User.query.get(user_id)
    ledger = Ledger.query.get(user.ledger_id)
    categories = Category.query.filter_by(ledger_id=ledger.id).order_by(Category.sort_order.asc(), Category.id.asc()).all()
    all_tx = Transaction.query.filter_by(ledger_id=ledger.id).all()
    txs = [tx for tx in all_tx if tx.datetime_val.year == y and tx.datetime_val.month == m and not tx.exclude_analysis]
    
    monthly_income = sum(tx.amount for tx in txs if tx.tx_type == '수입')
    monthly_expense = sum(tx.amount for tx in txs if tx.tx_type == '지출')
    
    cat_names = [c.name for c in categories]
    dow_expense_by_cat = {c: [0]*7 for c in cat_names}
    cat_expense_total = {c: 0 for c in cat_names}
    cat_payer_expense = {c: {} for c in cat_names}
    payer_expense = {}
    
    for tx in txs:
        if tx.tx_type == '지출':
            c_name = tx.category.name
            if c_name not in cat_expense_total:
                cat_expense_total[c_name] = 0
                dow_expense_by_cat[c_name] = [0]*7
                cat_payer_expense[c_name] = {}
                
            cat_expense_total[c_name] += tx.amount
            dow_idx = tx.datetime_val.weekday()
            dow_expense_by_cat[c_name][dow_idx] += tx.amount
            cat_payer_expense[c_name][tx.transactor] = cat_payer_expense[c_name].get(tx.transactor, 0) + tx.amount
            payer_expense[tx.transactor] = payer_expense.get(tx.transactor, 0) + tx.amount

    theme_colors = ['#13bd7e', '#ff9f43', '#0abde3', '#f368e0', '#ff6b6b', '#feca57', '#5f27cd', '#48dbfb', '#ff9ff3', '#10ac84']
    payer_color_map = {}
    for i, t in enumerate(payer_expense.keys()):
        payer_color_map[t] = theme_colors[(i + 4) % len(theme_colors)]

    budget_status = []
    for c in categories:
        if c.name != '미분류':
            spent = cat_expense_total.get(c.name, 0)
            if c.budget > 0 or spent > 0:
                display_budget = c.budget if c.budget > 0 else spent
                budget_status.append({
                    'name': c.name, 
                    'budget': c.budget, 
                    'display_budget': display_budget, 
                    'spent': spent,
                    'payers': cat_payer_expense.get(c.name, {})
                })
                
    return {
        'year': y, 'month': m,
        'monthly_income': monthly_income,
        'monthly_expense': monthly_expense,
        'ledger_budget': ledger.monthly_budget,
        'budget_status': budget_status,
        'payer_expense': payer_expense,
        'payer_color_map': payer_color_map,
        'cat_expense_total': cat_expense_total,
        'dow_expense_by_cat': dow_expense_by_cat
    }

@app.route('/')
@app.route('/home')
def home():
    user = User.query.get(request.user_id)
    if not user.ledger_id: return redirect(url_for('onboarding'))
    ledger = Ledger.query.get(user.ledger_id)
    
    t_year, t_month, p_y, p_m, n_y, n_m = get_target_date()
    initial_data = build_home_data(user.id, t_year, t_month)
            
    return render_template('home.html', ledger=ledger, 
                           initial_data=initial_data,
                           t_year=t_year, t_month=t_month, p_y=p_y, p_m=p_m, n_y=n_y, n_m=n_m, current_tab='home')

@app.route('/api/home_data')
def api_home_data():
    y = int(request.args.get('year'))
    m = int(request.args.get('month'))
    return jsonify(build_home_data(request.user_id, y, m))

@app.route('/calendar')
def calendar():
    user = User.query.get(request.user_id)
    if not user.ledger_id: return redirect(url_for('onboarding'))
    ledger = Ledger.query.get(user.ledger_id)
    t_year, t_month, p_y, p_m, n_y, n_m = get_target_date()
    
    categories = Category.query.filter_by(ledger_id=ledger.id).order_by(Category.sort_order.asc(), Category.id.asc()).all()
    all_tx = Transaction.query.filter_by(ledger_id=ledger.id).order_by(Transaction.datetime_val.desc()).all()
    txs = [tx for tx in all_tx if tx.datetime_val.year == t_year and tx.datetime_val.month == t_month]
    
    daily_totals = {}
    tx_by_date = {}
    today_date = datetime.now().strftime('%Y-%m-%d')
    
    for tx in txs:
        d_str = tx.datetime_val.strftime('%Y-%m-%d')
        if d_str not in daily_totals:
            daily_totals[d_str] = {'income': 0, 'expense': 0}
            tx_by_date[d_str] = []
            
        if tx.tx_type == '수입': daily_totals[d_str]['income'] += tx.amount
        else: daily_totals[d_str]['expense'] += tx.amount
            
        tx_by_date[d_str].append({
            'id': tx.id, 'tx_type': tx.tx_type, 'title': tx.title, 'transactor': tx.transactor,
            'amount': tx.amount, 'category': tx.category.name, 'time': tx.datetime_val.strftime('%H:%M'),
            'memo': tx.memo,
            'exclude_analysis': tx.exclude_analysis,
            'category_id': tx.category_id,
            'date': d_str
        })

    import calendar as py_calendar
    cal = py_calendar.Calendar(firstweekday=6)
    month_days = cal.monthdayscalendar(t_year, t_month)
    
    initial_data = {
        'year': t_year, 'month': t_month,
        'month_days': month_days,
        'daily_totals': daily_totals,
        'tx_by_date': tx_by_date
    }

    return render_template('calendar.html', ledger=ledger, current_user=user, categories=categories, 
                           today_date=today_date, now=datetime.now(),
                           initial_data=initial_data,
                           t_year=t_year, t_month=t_month, p_y=p_y, p_m=p_m, n_y=n_y, n_m=n_m, current_tab='calendar')

@app.route('/api/calendar_data')
def api_calendar_data():
    user = User.query.get(request.user_id)
    y = int(request.args.get('year'))
    m = int(request.args.get('month'))
    
    all_tx = Transaction.query.filter_by(ledger_id=user.ledger_id).all()
    txs = [tx for tx in all_tx if tx.datetime_val.year == y and tx.datetime_val.month == m]
    
    daily_totals = {}
    tx_by_date = {}
    for tx in txs:
        d_str = tx.datetime_val.strftime('%Y-%m-%d')
        if d_str not in daily_totals:
            daily_totals[d_str] = {'income': 0, 'expense': 0}
            tx_by_date[d_str] = []
            
        if tx.tx_type == '수입': daily_totals[d_str]['income'] += tx.amount
        else: daily_totals[d_str]['expense'] += tx.amount
        
        tx_by_date[d_str].append({
            'id': tx.id, 'tx_type': tx.tx_type, 'title': tx.title, 'transactor': tx.transactor,
            'amount': tx.amount, 'category': tx.category.name, 'time': tx.datetime_val.strftime('%H:%M'),
            'memo': tx.memo,
            'exclude_analysis': tx.exclude_analysis,
            'category_id': tx.category_id,
            'date': d_str
        })
        
    import calendar as py_calendar
    cal = py_calendar.Calendar(firstweekday=6)
    month_days = cal.monthdayscalendar(y, m)
    
    return jsonify({
        'year': y, 'month': m,
        'month_days': month_days,
        'daily_totals': daily_totals,
        'tx_by_date': tx_by_date
    })

@app.route('/transactions')
def transactions():
    user = User.query.get(request.user_id)
    if not user.ledger_id: return redirect(url_for('onboarding'))
    ledger = Ledger.query.get(user.ledger_id)
    categories = Category.query.filter_by(ledger_id=ledger.id).order_by(Category.sort_order.asc(), Category.id.asc()).all()
    
    t_year, t_month, p_y, p_m, n_y, n_m = get_target_date()
    now = datetime.now()

    return render_template('transactions.html', ledger=ledger, current_user=user,
                           categories=categories, now=now,
                           t_year=t_year, t_month=t_month, p_y=p_y, p_m=p_m, n_y=n_y, n_m=n_m, current_tab='transactions')

@app.route('/api/transactions')
def api_transactions():
    user = User.query.get(request.user_id)
    page = int(request.args.get('page', 1))
    per_page = 10
    
    y = request.args.get('year')
    m = request.args.get('month')
    if y and m:
        t_year, t_month = int(y), int(m)
    else:
        t_year, t_month, _, _, _, _ = get_target_date()
    
    query = Transaction.query.filter_by(ledger_id=user.ledger_id)
    all_tx = query.order_by(Transaction.datetime_val.desc()).all()
    month_txs = [tx for tx in all_tx if tx.datetime_val.year == t_year and tx.datetime_val.month == t_month]
    
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_txs = month_txs[start_idx:end_idx]
    
    result = []
    for tx in paginated_txs:
        result.append({
            'id': tx.id, 'tx_type': tx.tx_type, 'date': tx.datetime_val.strftime('%Y-%m-%d'),
            'time': tx.datetime_val.strftime('%H:%M'), 'category': tx.category.name,
            'category_id': tx.category_id,
            'transactor': tx.transactor, 'title': tx.title, 'memo': tx.memo,
            'amount': tx.amount, 'nickname': tx.user.nickname, 'exclude_analysis': tx.exclude_analysis
        })
        
    return jsonify({'transactions': result, 'has_next': end_idx < len(month_txs)})

@app.route('/api/categories', methods=['GET'])
def api_get_categories():
    user = User.query.get(request.user_id)
    cats = Category.query.filter_by(ledger_id=user.ledger_id).order_by(Category.sort_order.asc(), Category.id.asc()).all()
    return jsonify([{'id': c.id, 'name': c.name, 'is_default': c.is_default} for c in cats])

@app.route('/api/category/add', methods=['POST'])
def api_add_category():
    user = User.query.get(request.user_id)
    name = request.json.get('name')
    if name:
        max_order = db.session.query(db.func.max(Category.sort_order)).filter_by(ledger_id=user.ledger_id).scalar() or 0
        db.session.add(Category(ledger_id=user.ledger_id, name=name, sort_order=max_order + 1))
        db.session.commit()
    return jsonify({'success': True})

@app.route('/api/category/<int:cat_id>/edit', methods=['POST'])
def api_edit_category(cat_id):
    user = User.query.get(request.user_id)
    cat = Category.query.filter_by(id=cat_id, ledger_id=user.ledger_id).first()
    name = request.json.get('name')
    if cat and name and cat.name != '미분류':
        cat.name = name
        db.session.commit()
    return jsonify({'success': True})

@app.route('/api/category/<int:cat_id>/delete', methods=['POST'])
def api_delete_category(cat_id):
    user = User.query.get(request.user_id)
    cat = Category.query.filter_by(id=cat_id, ledger_id=user.ledger_id).first()
    if cat and cat.name != '미분류':
        db.session.delete(cat)
        db.session.commit()
    return jsonify({'success': True})

@app.route('/api/category/<int:cat_id>/move', methods=['POST'])
def api_move_category(cat_id):
    user = User.query.get(request.user_id)
    direction = request.json.get('dir')
    cat = Category.query.filter_by(id=cat_id, ledger_id=user.ledger_id).first()
    if not cat or cat.name == '미분류': return jsonify({'success': False})
    
    cats = Category.query.filter(Category.ledger_id==user.ledger_id, Category.name!='미분류').order_by(Category.sort_order.asc(), Category.id.asc()).all()
    if cat not in cats: return jsonify({'success': False})
    
    idx = cats.index(cat)
    
    if direction == 'up' and idx > 0:
        cats[idx].sort_order, cats[idx-1].sort_order = cats[idx-1].sort_order, cats[idx].sort_order
    elif direction == 'down' and idx < len(cats) - 1:
        cats[idx].sort_order, cats[idx+1].sort_order = cats[idx+1].sort_order, cats[idx].sort_order
        
    db.session.commit()
    return jsonify({'success': True})

@app.route('/settings')
def settings():
    user = User.query.get(request.user_id)
    if not user.ledger_id: return redirect(url_for('onboarding'))
    ledger = Ledger.query.get(user.ledger_id)
    categories = Category.query.filter_by(ledger_id=ledger.id).order_by(Category.sort_order.asc(), Category.id.asc()).all()
    return render_template('settings.html', ledger=ledger, current_user=user, categories=categories, current_tab='settings')

@app.route('/update_nickname', methods=['POST'])
def update_nickname():
    user = User.query.get(request.user_id)
    new_nickname = request.form.get('nickname')
    update_past = request.form.get('update_past') == 'on'
    
    if new_nickname:
        old_nickname = user.nickname
        user.nickname = new_nickname
        if update_past:
            Transaction.query.filter_by(ledger_id=user.ledger_id, transactor=old_nickname).update({'transactor': new_nickname})
        db.session.commit()
    return redirect(url_for('settings'))

@app.route('/update_ledger_name', methods=['POST'])
def update_ledger_name():
    user = User.query.get(request.user_id)
    ledger = Ledger.query.get(user.ledger_id)
    new_name = request.form.get('name')
    if new_name:
        ledger.name = new_name
        db.session.commit()
    return redirect(url_for('settings'))

@app.route('/set_budget', methods=['POST'])
def set_budget():
    user = User.query.get(request.user_id)
    ledger = Ledger.query.get(user.ledger_id)
    
    tb_str = request.form.get('total_budget', '').replace(',', '')
    ledger.monthly_budget = int(tb_str) if tb_str.isdigit() else 0
    
    for key, val in request.form.items():
        if key.startswith('cat_budget_'):
            cat_id = int(key.replace('cat_budget_', ''))
            cat = Category.query.get(cat_id)
            if cat and cat.ledger_id == ledger.id and cat.name != '미분류':
                val_str = val.replace(',', '') if val else ''
                cat.budget = int(val_str) if val_str.isdigit() else 0
    
    db.session.commit()
    return redirect(url_for('settings'))

@app.route('/transaction', methods=['POST'])
def add_transaction():
    user = User.query.get(request.user_id)
    amt_str = request.form.get('amount', '').replace(',', '')
    amount = int(amt_str) if amt_str.isdigit() else 0
    
    dt = datetime.strptime(f"{request.form.get('date')} {request.form.get('time')}", "%Y-%m-%d %H:%M")
    tx_type = request.form.get('tx_type')
    transactor = request.form.get('transactor')
    title = request.form.get('title')
    cat_id = request.form.get('category_id')
    
    uncategorized_id = get_or_create_uncategorized(user.ledger_id)

    if tx_type == '지출' and (not cat_id or int(cat_id) == uncategorized_id):
        sixty_days_ago = dt - timedelta(days=60)
        past_tx = Transaction.query.filter(
            Transaction.ledger_id == user.ledger_id,
            Transaction.tx_type == tx_type,
            Transaction.transactor == transactor,
            Transaction.title == title,
            Transaction.amount == amount,
            Transaction.category_id != uncategorized_id,
            Transaction.datetime_val >= sixty_days_ago,
            Transaction.datetime_val <= dt
        ).order_by(Transaction.datetime_val.desc()).first()
        
        if past_tx:
            cat_id = past_tx.category_id
        else:
            cat_id = uncategorized_id
    else:
        if not cat_id:
            cat_id = uncategorized_id
        
    new_tx = Transaction(
        ledger_id=user.ledger_id, user_id=user.id,
        tx_type=tx_type, transactor=transactor,
        title=title, memo=request.form.get('memo', ''),
        amount=amount, category_id=cat_id, datetime_val=dt,
        exclude_analysis=(request.form.get('exclude_analysis') == 'on')
    )
    db.session.add(new_tx)
    db.session.commit()
    
    if request.form.get('ajax') == '1':
        return jsonify({'success': True})
        
    return redirect(url_for('transactions'))

@app.route('/transaction/<int:tx_id>/edit', methods=['GET', 'POST'])
def edit_transaction(tx_id):
    user = User.query.get(request.user_id)
    ledger = Ledger.query.get(user.ledger_id)
    tx = Transaction.query.filter_by(id=tx_id, ledger_id=user.ledger_id).first()
    if not tx: return redirect(url_for('transactions'))

    if request.method == 'POST':
        tx.tx_type = request.form.get('tx_type')
        tx.transactor = request.form.get('transactor')
        tx.title = request.form.get('title')
        tx.memo = request.form.get('memo', '')
        
        amt_str = request.form.get('amount', '').replace(',', '')
        tx.amount = int(amt_str) if amt_str.isdigit() else 0
        
        tx.exclude_analysis = (request.form.get('exclude_analysis') == 'on')
        
        cat_id = request.form.get('category_id')
        if not cat_id: cat_id = get_or_create_uncategorized(user.ledger_id)
        tx.category_id = cat_id
        
        tx.datetime_val = datetime.strptime(f"{request.form.get('date')} {request.form.get('time')}", "%Y-%m-%d %H:%M")
        db.session.commit()
        
        if request.form.get('ajax') == '1':
            return jsonify({'success': True})
            
        next_url = request.form.get('next') or url_for('transactions')
        return redirect(next_url)
        
    categories = Category.query.filter_by(ledger_id=user.ledger_id).order_by(Category.sort_order.asc(), Category.id.asc()).all()
    next_url = request.args.get('next', '')
    return render_template('edit_transaction.html', tx=tx, ledger=ledger, categories=categories, next_url=next_url, current_tab='transactions')

@app.route('/transaction/<int:tx_id>/delete', methods=['POST'])
def delete_transaction(tx_id):
    user = User.query.get(request.user_id)
    tx = Transaction.query.filter_by(id=tx_id, ledger_id=user.ledger_id).first()
    if tx:
        db.session.delete(tx)
        db.session.commit()
        
    if request.form.get('ajax') == '1' or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True})
        
    return redirect(request.referrer or url_for('transactions'))

@app.route('/search')
def search():
    user = User.query.get(request.user_id)
    if not user.ledger_id: return redirect(url_for('onboarding'))
    ledger = Ledger.query.get(user.ledger_id)
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    category_id = request.args.get('category_id')
    keyword = request.args.get('keyword')
    min_amount = request.args.get('min_amount')
    max_amount = request.args.get('max_amount')
    tx_type = request.args.get('tx_type')
    
    query = Transaction.query.filter_by(ledger_id=ledger.id)
    
    if tx_type in ['수입', '지출']:
        query = query.filter(Transaction.tx_type == tx_type)
    if start_date:
        st = datetime.strptime(start_date, "%Y-%m-%d")
        query = query.filter(Transaction.datetime_val >= st)
    if end_date:
        ed = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        query = query.filter(Transaction.datetime_val <= ed)
    if category_id:
        query = query.filter(Transaction.category_id == category_id)
        
    if keyword:
        search_kw = f"%{keyword}%"
        query = query.filter((Transaction.title.like(search_kw)) | (Transaction.memo.like(search_kw)))
        
    if min_amount and min_amount.isdigit():
        query = query.filter(Transaction.amount >= int(min_amount))
    if max_amount and max_amount.isdigit():
        query = query.filter(Transaction.amount <= int(max_amount))
        
    transactions = query.order_by(Transaction.datetime_val.desc()).all()
    categories = Category.query.filter_by(ledger_id=ledger.id).order_by(Category.sort_order.asc(), Category.id.asc()).all()
    
    return render_template('search.html', transactions=transactions, categories=categories, request=request, current_tab='transactions')

@app.route('/export')
def export_csv():
    user = User.query.get(request.user_id)
    ledger = Ledger.query.get(user.ledger_id)
    transactions = Transaction.query.filter_by(ledger_id=user.ledger_id).order_by(Transaction.datetime_val.desc()).all()
    categories = Category.query.filter_by(ledger_id=user.ledger_id).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['#LEDGER_META', ledger.name, ledger.monthly_budget])
    writer.writerow(['#CATEGORY_META', 'name', 'is_default', 'budget', 'sort_order'])
    for cat in categories:
        writer.writerow(['#CATEGORY_ROW', cat.name, int(cat.is_default), cat.budget, cat.sort_order])
        
    writer.writerow(['#TX_META', 'date', 'time', 'tx_type', 'transactor', 'category', 'title', 'memo', 'amount', 'exclude_analysis', 'nickname'])
    for tx in transactions:
        writer.writerow(['#TX_ROW', tx.datetime_val.strftime('%Y-%m-%d'), tx.datetime_val.strftime('%H:%M'), 
                         tx.tx_type, tx.transactor, tx.category.name, tx.title, tx.memo, tx.amount, int(tx.exclude_analysis), tx.user.nickname])
                         
    output.seek(0)
    return Response(output.getvalue().encode('utf-8-sig'), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=ledger.csv"})

@app.route('/csv_manage')
def csv_manage():
    return render_template('csv_manage.html', current_tab='settings')

@app.route('/import', methods=['POST'])
def import_csv():
    user = User.query.get(request.user_id)
    ledger = Ledger.query.get(user.ledger_id)
    file = request.files.get('csv_file')
    
    if file:
        stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
        reader = csv.reader(stream)
        
        cats_cache = {}
        for row in reader:
            if not row: continue
            
            if row[0] == '#LEDGER_META' and len(row) >= 3:
                ledger.name = row[1]
                ledger.monthly_budget = int(row[2])
            elif row[0] == '#CATEGORY_ROW' and len(row) >= 5:
                cat = Category.query.filter_by(ledger_id=user.ledger_id, name=row[1]).first()
                if not cat:
                    cat = Category(ledger_id=user.ledger_id, name=row[1])
                    db.session.add(cat)
                cat.is_default = bool(int(row[2]))
                cat.budget = int(row[3])
                cat.sort_order = int(row[4])
                db.session.flush()
                cats_cache[cat.name] = cat.id
            elif row[0] == '#TX_ROW' and len(row) >= 11:
                cat_name = row[5]
                if cat_name not in cats_cache:
                    cat = Category.query.filter_by(ledger_id=user.ledger_id, name=cat_name).first()
                    if not cat:
                        max_order = db.session.query(db.func.max(Category.sort_order)).filter_by(ledger_id=user.ledger_id).scalar() or 0
                        cat = Category(ledger_id=user.ledger_id, name=cat_name, is_default=False, sort_order=max_order+1)
                        db.session.add(cat)
                        db.session.flush()
                    cats_cache[cat_name] = cat.id
                    
                dt = datetime.strptime(f"{row[1]} {row[2]}", "%Y-%m-%d %H:%M")
                new_tx = Transaction(ledger_id=user.ledger_id, user_id=user.id, tx_type=row[3], transactor=row[4], title=row[6], memo=row[7], amount=int(row[8]), exclude_analysis=bool(int(row[9])), category_id=cats_cache[cat_name], datetime_val=dt)
                db.session.add(new_tx)
            elif not row[0].startswith('#') and len(row) >= 8 and row[0] != '일자':
                cat_name = row[4]
                if cat_name not in cats_cache:
                    cat = Category.query.filter_by(ledger_id=user.ledger_id, name=cat_name).first()
                    if not cat:
                        max_order = db.session.query(db.func.max(Category.sort_order)).filter_by(ledger_id=user.ledger_id).scalar() or 0
                        cat = Category(ledger_id=user.ledger_id, name=cat_name, is_default=False, sort_order=max_order+1)
                        db.session.add(cat)
                        db.session.flush()
                    cats_cache[cat_name] = cat.id
                dt = datetime.strptime(f"{row[0]} {row[1]}", "%Y-%m-%d %H:%M")
                new_tx = Transaction(ledger_id=user.ledger_id, user_id=user.id, tx_type=row[2], transactor=row[3], title=row[5], memo=row[6], amount=int(row[7]), category_id=cats_cache[cat_name], datetime_val=dt)
                db.session.add(new_tx)
                
        db.session.commit()
    return redirect(url_for('csv_manage'))

if __name__ == '__main__':
    if os.environ.get('SECRET_KEY') is None:
        print("[WARNING] SECRET_KEY is not set in Vercel Environment Variables.")
    app.run(host='0.0.0.0', debug=False)
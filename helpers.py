import random
from datetime import datetime
from flask import request, redirect, jsonify
from models import db, Category

# 사용자/'함께'/분류에 랜덤 배정되는 색상 풀 (홈 화면 차트에서도 그대로 사용)
COLOR_PALETTE = ['#22B57F', '#F0A94E', '#3FADD6', '#C876C2', '#EB7A6E', '#F0CB5C', '#8F79D6', '#4FC2D6', '#E0A0D6', '#4FBFA0']
FALLBACK_COLOR = '#9fa4b0'


def pick_random_color(existing_colors):
    unused = [c for c in COLOR_PALETTE if c not in existing_colors]
    pool = unused if unused else COLOR_PALETTE
    return random.choice(pool)


def spa_redirect(target_url):
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.form.get('ajax') == '1':
        return jsonify({'redirect': target_url})
    return redirect(target_url)


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


def month_range(year, month):
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start, end


def get_or_create_uncategorized(ledger_id):
    cat = Category.query.filter_by(ledger_id=ledger_id, name='미분류').first()
    if not cat:
        existing_colors = [c.color for c in Category.query.filter_by(ledger_id=ledger_id).all() if c.color]
        cat = Category(ledger_id=ledger_id, name='미분류', is_default=True, sort_order=-1, color=pick_random_color(existing_colors))
        db.session.add(cat)
        db.session.flush()
    return cat.id

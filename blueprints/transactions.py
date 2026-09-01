from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from sqlalchemy.orm import joinedload

from models import db, User, Ledger, Category, Transaction
from helpers import spa_redirect, get_or_create_uncategorized, month_range, FALLBACK_COLOR
from blueprints.push import notify_partner

transactions_bp = Blueprint('transactions', __name__)

# 자동 분류 추정에 사용하는 과거 조회 기간
_SUGGEST_DAYS = 90


def suggest_category_id(ledger_id, tx_type, title, amount, uncat_id, before_dt=None):
    """최근 3개월 내역에서 분류를 추정한다.
    1순위: 제목+금액이 모두 일치하는 가장 최근 내역
    2순위: 제목만 일치하는 가장 최근 내역
    추정 실패 시 None."""
    if not title:
        return None
    before_dt = before_dt or datetime.now()
    since = before_dt - timedelta(days=_SUGGEST_DAYS)
    base = Transaction.query.filter(
        Transaction.ledger_id == ledger_id,
        Transaction.tx_type == tx_type,
        Transaction.title == title,
        Transaction.category_id != uncat_id,
        Transaction.datetime_val >= since,
        Transaction.datetime_val <= before_dt,
    )
    if amount is not None:
        p1 = base.filter(Transaction.amount == amount).order_by(Transaction.datetime_val.desc()).first()
        if p1:
            return p1.category_id
    p2 = base.order_by(Transaction.datetime_val.desc()).first()
    return p2.category_id if p2 else None


@transactions_bp.route('/transactions')
def transactions():
    user = User.query.get(request.user_id)
    if not user: return spa_redirect(url_for('auth.logout'))
    if not user.ledger_id: return redirect(url_for('auth.onboarding'))
    ledger = Ledger.query.get(user.ledger_id)
    categories = Category.query.filter_by(ledger_id=ledger.id).order_by(Category.sort_order.asc(), Category.id.asc()).all()

    now = datetime.now()
    y = request.args.get('year')
    m = request.args.get('month')
    target_year, target_month = (int(y), int(m)) if y and m else (now.year, now.month)

    start, end = month_range(target_year, target_month)
    default_start = start.strftime('%Y-%m-%d')
    default_end = (end - timedelta(days=1)).strftime('%Y-%m-%d')

    return render_template('transactions.html', ledger=ledger, current_user=user,
                           categories=categories, now=now,
                           default_start=default_start, default_end=default_end, current_tab='transactions')


@transactions_bp.route('/api/transactions')
def api_transactions():
    user = User.query.get(request.user_id)
    if not user: return jsonify({'error': 'Unauthorized'}), 401
    page = int(request.args.get('page', 1))
    per_page = 10

    query = Transaction.query.filter(Transaction.ledger_id == user.ledger_id)

    tx_type = request.args.get('tx_type')
    if tx_type in ('수입', '지출'):
        query = query.filter(Transaction.tx_type == tx_type)

    start_date = request.args.get('start_date')
    if start_date:
        query = query.filter(Transaction.datetime_val >= datetime.strptime(start_date, "%Y-%m-%d"))

    end_date = request.args.get('end_date')
    if end_date:
        ed = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        query = query.filter(Transaction.datetime_val <= ed)

    category_id = request.args.get('category_id')
    if category_id:
        query = query.filter(Transaction.category_id == category_id)

    keyword = request.args.get('keyword')
    if keyword:
        kw = f"%{keyword}%"
        query = query.filter((Transaction.title.like(kw)) | (Transaction.memo.like(kw)))

    min_amount = request.args.get('min_amount')
    if min_amount and min_amount.isdigit():
        query = query.filter(Transaction.amount >= int(min_amount))

    max_amount = request.args.get('max_amount')
    if max_amount and max_amount.isdigit():
        query = query.filter(Transaction.amount <= int(max_amount))

    if request.args.get('exclude_budget_only') == '1':
        query = query.filter(Transaction.exclude_budget.is_(True))

    if request.args.get('exclude_analysis_only') == '1':
        query = query.filter(Transaction.exclude_analysis.is_(True))

    total_count = query.count()

    paginated_txs = query.options(joinedload(Transaction.category), joinedload(Transaction.user)) \
        .order_by(Transaction.datetime_val.desc(), Transaction.id.desc()) \
        .offset((page - 1) * per_page).limit(per_page).all()

    ledger = Ledger.query.get(user.ledger_id)
    user_color_by_nickname = {u.nickname: u.color for u in ledger.users}

    result = []
    for tx in paginated_txs:
        transactor_color = ledger.together_color if tx.transactor == '함께' else user_color_by_nickname.get(tx.transactor)
        result.append({
            'id': tx.id, 'tx_type': tx.tx_type, 'date': tx.datetime_val.strftime('%Y-%m-%d'),
            'time': tx.datetime_val.strftime('%H:%M'), 'category': tx.category.name,
            'category_id': tx.category_id,
            'transactor': tx.transactor, 'transactor_color': transactor_color or FALLBACK_COLOR,
            'title': tx.title, 'memo': tx.memo,
            'amount': tx.amount, 'nickname': tx.user.nickname,
            'exclude_analysis': tx.exclude_analysis, 'exclude_budget': tx.exclude_budget
        })

    return jsonify({'transactions': result, 'has_next': page * per_page < total_count, 'total_count': total_count})


@transactions_bp.route('/api/title_suggest')
def api_title_suggest():
    """입력된 금액과 동일하게 지출/수입한 최근 3개월 내역의 제목을 최근순 최대 3건 반환."""
    user = User.query.get(request.user_id)
    if not user or not user.ledger_id:
        return jsonify([])
    amt = request.args.get('amount', '').replace(',', '')
    if not amt.isdigit():
        return jsonify([])
    tx_type = request.args.get('tx_type', '지출')
    since = datetime.now() - timedelta(days=_SUGGEST_DAYS)
    rows = Transaction.query.filter(
        Transaction.ledger_id == user.ledger_id,
        Transaction.tx_type == tx_type,
        Transaction.amount == int(amt),
        Transaction.datetime_val >= since,
    ).order_by(Transaction.datetime_val.desc()).limit(50).all()

    seen, titles = set(), []
    for r in rows:
        if r.title and r.title not in seen:
            seen.add(r.title)
            titles.append(r.title)
        if len(titles) == 3:
            break
    return jsonify(titles)


@transactions_bp.route('/api/category_suggest')
def api_category_suggest():
    """분류 선택 팝업용. 입력 정보 기준 자동분류 유력 후보 순으로 정렬한 분류 목록을 반환."""
    user = User.query.get(request.user_id)
    if not user or not user.ledger_id:
        return jsonify({'items': [], 'matched_id': None})

    cats = Category.query.filter_by(ledger_id=user.ledger_id) \
        .order_by(Category.sort_order.asc(), Category.id.asc()).all()
    uncat = next((c for c in cats if c.name == '미분류'), None)
    uncat_id = uncat.id if uncat else None

    title = (request.args.get('title') or '').strip()
    amt = request.args.get('amount', '').replace(',', '')
    tx_type = request.args.get('tx_type', '지출')
    matched_id = suggest_category_id(user.ledger_id, tx_type, title,
                                    int(amt) if amt.isdigit() else None, uncat_id)

    ordered, added = [], set()
    if matched_id:
        c = next((c for c in cats if c.id == matched_id), None)
        if c:
            ordered.append(c); added.add(c.id)
    for c in cats:
        if c.id in added or (uncat and c.id == uncat.id):
            continue
        ordered.append(c); added.add(c.id)
    if uncat:
        ordered.append(uncat)

    return jsonify({
        'items': [{'id': c.id, 'name': c.name, 'color': c.color} for c in ordered],
        'matched_id': matched_id,
    })


@transactions_bp.route('/transaction', methods=['POST'])
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
        cat_id = suggest_category_id(user.ledger_id, tx_type, title, amount, uncategorized_id, before_dt=dt) or uncategorized_id
    else:
        if not cat_id:
            cat_id = uncategorized_id

    # 팝업에서 고른 분류가 그 사이 삭제됐을 수 있으니 소속 가계부의 분류인지 확인
    if not Category.query.filter_by(id=cat_id, ledger_id=user.ledger_id).first():
        cat_id = uncategorized_id

    new_tx = Transaction(
        ledger_id=user.ledger_id, user_id=user.id,
        tx_type=tx_type, transactor=transactor,
        title=title, memo=request.form.get('memo', ''),
        amount=amount, category_id=cat_id, datetime_val=dt,
        exclude_analysis=(request.form.get('exclude_analysis') == 'on'),
        exclude_budget=(request.form.get('exclude_budget') == 'on')
    )
    db.session.add(new_tx)
    db.session.commit()

    notify_partner(user.ledger_id, user.id, '가계쀼',
                    f"{transactor}님이 '{title}' {amount:,}원을 등록했어요")

    if request.form.get('ajax') == '1':
        return jsonify({'success': True})

    return spa_redirect(url_for('transactions.transactions'))


@transactions_bp.route('/transaction/<int:tx_id>/edit', methods=['GET', 'POST'])
def edit_transaction(tx_id):
    user = User.query.get(request.user_id)
    ledger = Ledger.query.get(user.ledger_id)
    tx = Transaction.query.filter_by(id=tx_id, ledger_id=user.ledger_id).first()
    if not tx: return redirect(url_for('transactions.transactions'))

    if request.method == 'POST':
        tx.tx_type = request.form.get('tx_type')
        tx.transactor = request.form.get('transactor')
        tx.title = request.form.get('title')
        tx.memo = request.form.get('memo', '')

        amt_str = request.form.get('amount', '').replace(',', '')
        tx.amount = int(amt_str) if amt_str.isdigit() else 0

        tx.exclude_analysis = (request.form.get('exclude_analysis') == 'on')
        tx.exclude_budget = (request.form.get('exclude_budget') == 'on')

        cat_id = request.form.get('category_id')
        if not cat_id or not Category.query.filter_by(id=cat_id, ledger_id=user.ledger_id).first():
            cat_id = get_or_create_uncategorized(user.ledger_id)
        tx.category_id = cat_id

        tx.datetime_val = datetime.strptime(f"{request.form.get('date')} {request.form.get('time')}", "%Y-%m-%d %H:%M")
        db.session.commit()

        notify_partner(user.ledger_id, user.id, '가계쀼',
                        f"{tx.transactor}님이 '{tx.title}' 내역을 수정했어요")

        if request.form.get('ajax') == '1':
            return jsonify({'success': True})

        next_url = request.form.get('next') or url_for('transactions.transactions')
        return spa_redirect(next_url)

    categories = Category.query.filter_by(ledger_id=user.ledger_id).order_by(Category.sort_order.asc(), Category.id.asc()).all()
    next_url = request.args.get('next', '')
    return render_template('edit_transaction.html', tx=tx, ledger=ledger, categories=categories, next_url=next_url, current_tab='transactions')


@transactions_bp.route('/transaction/<int:tx_id>/delete', methods=['POST'])
def delete_transaction(tx_id):
    user = User.query.get(request.user_id)
    tx = Transaction.query.filter_by(id=tx_id, ledger_id=user.ledger_id).first()
    if tx:
        transactor, title = tx.transactor, tx.title
        db.session.delete(tx)
        db.session.commit()
        notify_partner(user.ledger_id, user.id, '가계쀼',
                        f"{transactor}님이 '{title}' 내역을 삭제했어요")

    if request.form.get('ajax') == '1' or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True})

    return spa_redirect(request.referrer or url_for('transactions.transactions'))

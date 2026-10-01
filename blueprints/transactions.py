from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, g
from sqlalchemy.orm import joinedload

from models import db, User, Category, Transaction
from helpers import (spa_redirect, get_or_create_uncategorized, month_range, require_ledger, json_error,
                     parse_amount, parse_int, parse_datetime, parse_year_month, clean_text, safe_next_url,
                     resolve_transactor, TransactorInfo, TX_TYPES, UNCATEGORIZED, MAX_TITLE_LEN, MAX_MEMO_LEN)
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


def _parse_date_arg(name):
    """검색용 'YYYY-MM-DD' 파라미터. 없으면 None, 형식이 틀리면 ValueError."""
    value = request.args.get(name)
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d")


def _escape_like(s):
    return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _read_tx_form():
    """등록/수정 폼 공통 검증. (값 dict, 오류 메시지) 를 돌려준다."""
    tx_type = request.form.get('tx_type')
    if tx_type not in TX_TYPES:
        return None, '수입/지출 구분이 올바르지 않습니다.'
    amount = parse_amount(request.form.get('amount'))
    if amount is None:
        return None, '금액을 올바르게 입력해주세요.'
    dt = parse_datetime(request.form.get('date'), request.form.get('time'))
    if dt is None:
        return None, '날짜/시간을 올바르게 입력해주세요.'
    return {
        'tx_type': tx_type,
        'amount': amount,
        'datetime_val': dt,
        'title': clean_text(request.form.get('title'), MAX_TITLE_LEN),
        'memo': clean_text(request.form.get('memo'), MAX_MEMO_LEN),
        'exclude_analysis': request.form.get('exclude_analysis') == 'on',
        'exclude_budget': request.form.get('exclude_budget') == 'on',
    }, None


def _ledger_category_id(ledger_id, raw_id):
    """이 가계부 소속의 분류 id 면 그대로, 아니면 None."""
    cat_id = parse_int(raw_id)
    if cat_id is None:
        return None
    cat = Category.query.filter_by(id=cat_id, ledger_id=ledger_id).first()
    return cat.id if cat else None


@transactions_bp.route('/transactions')
@require_ledger
def transactions():
    user, ledger = g.user, g.ledger
    categories = Category.query.filter_by(ledger_id=ledger.id).order_by(Category.sort_order.asc(), Category.id.asc()).all()

    now = datetime.now()
    ym = parse_year_month(request.args.get('year'), request.args.get('month'))
    target_year, target_month = ym if ym else (now.year, now.month)

    start, end = month_range(target_year, target_month)
    default_start = start.strftime('%Y-%m-%d')
    default_end = (end - timedelta(days=1)).strftime('%Y-%m-%d')

    return render_template('transactions.html', ledger=ledger, current_user=user,
                           categories=categories, now=now,
                           default_start=default_start, default_end=default_end, current_tab='transactions')


@transactions_bp.route('/api/transactions')
@require_ledger
def api_transactions():
    ledger = g.ledger
    page = max(parse_int(request.args.get('page')) or 1, 1)
    per_page = 10

    query = Transaction.query.filter(Transaction.ledger_id == ledger.id)

    tx_type = request.args.get('tx_type')
    if tx_type in TX_TYPES:
        query = query.filter(Transaction.tx_type == tx_type)

    try:
        start_date = _parse_date_arg('start_date')
        end_date = _parse_date_arg('end_date')
    except ValueError:
        return json_error('날짜 형식이 올바르지 않습니다.')
    if start_date:
        query = query.filter(Transaction.datetime_val >= start_date)
    if end_date:
        query = query.filter(Transaction.datetime_val < end_date + timedelta(days=1))

    category_id = request.args.get('category_id')
    if category_id:
        cat_id = parse_int(category_id)
        if cat_id is None:
            return json_error('분류가 올바르지 않습니다.')
        query = query.filter(Transaction.category_id == cat_id)

    keyword = (request.args.get('keyword') or '').strip()
    if keyword:
        kw = f"%{_escape_like(keyword)}%"
        query = query.filter(Transaction.title.ilike(kw, escape='\\') | Transaction.memo.ilike(kw, escape='\\'))

    min_amount = parse_amount(request.args.get('min_amount'))
    if min_amount is not None:
        query = query.filter(Transaction.amount >= min_amount)

    max_amount = parse_amount(request.args.get('max_amount'))
    if max_amount is not None:
        query = query.filter(Transaction.amount <= max_amount)

    if request.args.get('exclude_budget_only') == '1':
        query = query.filter(Transaction.exclude_budget.is_(True))

    if request.args.get('exclude_analysis_only') == '1':
        query = query.filter(Transaction.exclude_analysis.is_(True))

    total_count = query.count()

    paginated_txs = query.options(joinedload(Transaction.category), joinedload(Transaction.user)) \
        .order_by(Transaction.datetime_val.desc(), Transaction.id.desc()) \
        .offset((page - 1) * per_page).limit(per_page).all()

    tinfo = TransactorInfo(ledger)
    result = []
    for tx in paginated_txs:
        result.append({
            'id': tx.id, 'tx_type': tx.tx_type, 'date': tx.datetime_val.strftime('%Y-%m-%d'),
            'time': tx.datetime_val.strftime('%H:%M'), 'category': tx.category.name,
            'category_id': tx.category_id,
            'transactor': tx.transactor, 'transactor_color': tinfo.color(tx),
            'transactor_value': tinfo.form_value(tx),
            'title': tx.title, 'memo': tx.memo,
            'amount': tx.amount, 'nickname': tx.user.nickname,
            'exclude_analysis': tx.exclude_analysis, 'exclude_budget': tx.exclude_budget
        })

    return jsonify({'transactions': result, 'has_next': page * per_page < total_count, 'total_count': total_count})


@transactions_bp.route('/api/title_suggest')
def api_title_suggest():
    """입력된 금액과 동일하게 지출/수입한 최근 3개월 내역의 제목을 최근순 최대 3건 반환."""
    user = db.session.get(User, request.user_id)
    if not user or not user.ledger_id:
        return jsonify([])
    amount = parse_amount(request.args.get('amount'))
    if amount is None:
        return jsonify([])
    tx_type = request.args.get('tx_type', '지출')
    since = datetime.now() - timedelta(days=_SUGGEST_DAYS)
    rows = Transaction.query.filter(
        Transaction.ledger_id == user.ledger_id,
        Transaction.tx_type == tx_type,
        Transaction.amount == amount,
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
    user = db.session.get(User, request.user_id)
    if not user or not user.ledger_id:
        return jsonify({'items': [], 'matched_id': None})

    cats = Category.query.filter_by(ledger_id=user.ledger_id) \
        .order_by(Category.sort_order.asc(), Category.id.asc()).all()
    uncat = next((c for c in cats if c.name == UNCATEGORIZED), None)
    uncat_id = uncat.id if uncat else None

    title = (request.args.get('title') or '').strip()
    tx_type = request.args.get('tx_type', '지출')
    matched_id = suggest_category_id(user.ledger_id, tx_type, title,
                                     parse_amount(request.args.get('amount')), uncat_id)

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
@require_ledger
def add_transaction():
    user, ledger = g.user, g.ledger
    data, err = _read_tx_form()
    if err:
        return json_error(err)

    transactor, transactor_user_id = resolve_transactor(ledger, request.form.get('transactor'), user)
    uncategorized_id = get_or_create_uncategorized(ledger.id)
    # 팝업에서 고른 분류가 그 사이 삭제됐을 수 있으니 소속 가계부의 분류인지 확인
    cat_id = _ledger_category_id(ledger.id, request.form.get('category_id')) or uncategorized_id

    auto_assigned = False
    if data['tx_type'] == '지출' and cat_id == uncategorized_id:
        suggested = suggest_category_id(ledger.id, data['tx_type'], data['title'], data['amount'],
                                        uncategorized_id, before_dt=data['datetime_val'])
        if suggested:
            cat_id, auto_assigned = suggested, True

    new_tx = Transaction(ledger_id=ledger.id, user_id=user.id, transactor=transactor,
                         transactor_user_id=transactor_user_id, category_id=cat_id, **data)
    db.session.add(new_tx)
    db.session.commit()

    notify_partner(ledger.id, user.id, '가계쀼',
                   f"{transactor}님이 '{new_tx.title}' {new_tx.amount:,}원을 등록했어요")

    if request.form.get('ajax') == '1':
        cat = db.session.get(Category, cat_id)
        return jsonify({'success': True, 'auto_category': cat.name if auto_assigned and cat else None})

    return spa_redirect(url_for('transactions.transactions'))


@transactions_bp.route('/transaction/<int:tx_id>/edit', methods=['GET', 'POST'])
@require_ledger
def edit_transaction(tx_id):
    user, ledger = g.user, g.ledger
    tx = Transaction.query.filter_by(id=tx_id, ledger_id=ledger.id).first()
    if not tx:
        if request.method == 'POST' and request.form.get('ajax') == '1':
            return json_error('이미 삭제된 내역입니다.', 404)
        return redirect(url_for('transactions.transactions'))

    if request.method == 'POST':
        data, err = _read_tx_form()
        if err:
            return json_error(err)

        raw_transactor = request.form.get('transactor')
        if clean_text(raw_transactor, 50) == tx.transactor and tx.transactor_user_id is not None \
                and tx.transactor_user_id not in {u.id for u in ledger.users}:
            # 가계부를 나간 사람이 거래자인 내역은 이름을 바꾸지 않은 한 연결을 그대로 유지
            transactor, transactor_user_id = tx.transactor, tx.transactor_user_id
        else:
            transactor, transactor_user_id = resolve_transactor(ledger, raw_transactor, user)

        for k, v in data.items():
            setattr(tx, k, v)
        tx.transactor, tx.transactor_user_id = transactor, transactor_user_id
        tx.category_id = _ledger_category_id(ledger.id, request.form.get('category_id')) \
            or get_or_create_uncategorized(ledger.id)
        db.session.commit()

        notify_partner(ledger.id, user.id, '가계쀼',
                       f"{tx.transactor}님이 '{tx.title}' 내역을 수정했어요")

        if request.form.get('ajax') == '1':
            return jsonify({'success': True})

        next_url = safe_next_url(request.form.get('next'), url_for('transactions.transactions'))
        return spa_redirect(next_url)

    categories = Category.query.filter_by(ledger_id=ledger.id).order_by(Category.sort_order.asc(), Category.id.asc()).all()
    next_url = safe_next_url(request.args.get('next'), '')
    tinfo = TransactorInfo(ledger)
    return render_template('edit_transaction.html', tx=tx, ledger=ledger, categories=categories, next_url=next_url,
                           transactor_value=tinfo.form_value(tx), current_tab='transactions')


@transactions_bp.route('/transaction/<int:tx_id>/delete', methods=['POST'])
@require_ledger
def delete_transaction(tx_id):
    user, ledger = g.user, g.ledger
    tx = Transaction.query.filter_by(id=tx_id, ledger_id=ledger.id).first()
    if tx:
        transactor, title = tx.transactor, tx.title
        db.session.delete(tx)
        db.session.commit()
        notify_partner(ledger.id, user.id, '가계쀼',
                       f"{transactor}님이 '{title}' 내역을 삭제했어요")

    if request.form.get('ajax') == '1' or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True})

    return spa_redirect(safe_next_url(request.referrer and _path_of(request.referrer), url_for('transactions.transactions')))


def _path_of(url):
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    return parts.path + (('?' + parts.query) if parts.query else '')

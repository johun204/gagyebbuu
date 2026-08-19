from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from sqlalchemy.orm import joinedload

from models import db, User, Ledger, Category, Transaction
from helpers import spa_redirect, get_target_date, get_or_create_uncategorized, month_range
from blueprints.push import notify_partner

transactions_bp = Blueprint('transactions', __name__)


@transactions_bp.route('/transactions')
def transactions():
    user = User.query.get(request.user_id)
    if not user: return spa_redirect(url_for('auth.logout'))
    if not user.ledger_id: return redirect(url_for('auth.onboarding'))
    ledger = Ledger.query.get(user.ledger_id)
    categories = Category.query.filter_by(ledger_id=ledger.id).order_by(Category.sort_order.asc(), Category.id.asc()).all()

    t_year, t_month, p_y, p_m, n_y, n_m = get_target_date()
    now = datetime.now()

    return render_template('transactions.html', ledger=ledger, current_user=user,
                           categories=categories, now=now,
                           t_year=t_year, t_month=t_month, p_y=p_y, p_m=p_m, n_y=n_y, n_m=n_m, current_tab='transactions')


@transactions_bp.route('/api/transactions')
def api_transactions():
    user = User.query.get(request.user_id)
    if not user: return jsonify({'error': 'Unauthorized'}), 401
    page = int(request.args.get('page', 1))
    per_page = 10

    y = request.args.get('year')
    m = request.args.get('month')
    if y and m:
        t_year, t_month = int(y), int(m)
    else:
        t_year, t_month, _, _, _, _ = get_target_date()

    start, end = month_range(t_year, t_month)
    month_query = Transaction.query.filter(
        Transaction.ledger_id == user.ledger_id,
        Transaction.datetime_val >= start,
        Transaction.datetime_val < end
    )
    total_count = month_query.count()

    paginated_txs = month_query.options(joinedload(Transaction.category), joinedload(Transaction.user)) \
        .order_by(Transaction.datetime_val.desc(), Transaction.id.desc()) \
        .offset((page - 1) * per_page).limit(per_page).all()

    result = []
    for tx in paginated_txs:
        result.append({
            'id': tx.id, 'tx_type': tx.tx_type, 'date': tx.datetime_val.strftime('%Y-%m-%d'),
            'time': tx.datetime_val.strftime('%H:%M'), 'category': tx.category.name,
            'category_id': tx.category_id,
            'transactor': tx.transactor, 'title': tx.title, 'memo': tx.memo,
            'amount': tx.amount, 'nickname': tx.user.nickname, 'exclude_analysis': tx.exclude_analysis
        })

    return jsonify({'transactions': result, 'has_next': page * per_page < total_count})


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

        cat_id = request.form.get('category_id')
        if not cat_id: cat_id = get_or_create_uncategorized(user.ledger_id)
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


@transactions_bp.route('/search')
def search():
    user = User.query.get(request.user_id)
    if not user: return spa_redirect(url_for('auth.logout'))
    if not user.ledger_id: return redirect(url_for('auth.onboarding'))
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

from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from sqlalchemy.orm import joinedload

from models import User, Ledger, Category, Transaction
from helpers import spa_redirect, get_target_date, month_range, FALLBACK_COLOR

calendar_bp = Blueprint('calendar', __name__)


def build_calendar_data(ledger_id, y, m):
    ledger = Ledger.query.get(ledger_id)
    user_color_by_nickname = {u.nickname: u.color for u in ledger.users}

    start, end = month_range(y, m)
    txs = Transaction.query.options(joinedload(Transaction.category)).filter(
        Transaction.ledger_id == ledger_id,
        Transaction.datetime_val >= start,
        Transaction.datetime_val < end
    ).order_by(Transaction.datetime_val.desc(), Transaction.id.desc()).all()

    daily_totals = {}
    tx_by_date = {}

    for tx in txs:
        d_str = tx.datetime_val.strftime('%Y-%m-%d')
        if d_str not in daily_totals:
            daily_totals[d_str] = {'income': 0, 'expense': 0}
            tx_by_date[d_str] = []

        if tx.tx_type == '수입': daily_totals[d_str]['income'] += tx.amount
        else: daily_totals[d_str]['expense'] += tx.amount

        transactor_color = ledger.together_color if tx.transactor == '함께' else user_color_by_nickname.get(tx.transactor)

        tx_by_date[d_str].append({
            'id': tx.id, 'tx_type': tx.tx_type, 'title': tx.title, 'transactor': tx.transactor,
            'transactor_color': transactor_color or FALLBACK_COLOR,
            'amount': tx.amount, 'category': tx.category.name, 'time': tx.datetime_val.strftime('%H:%M'),
            'memo': tx.memo,
            'exclude_analysis': tx.exclude_analysis,
            'exclude_budget': tx.exclude_budget,
            'category_id': tx.category_id,
            'date': d_str
        })

    import calendar as py_calendar
    cal = py_calendar.Calendar(firstweekday=6)
    month_days = cal.monthdayscalendar(y, m)

    return {
        'year': y, 'month': m,
        'month_days': month_days,
        'daily_totals': daily_totals,
        'tx_by_date': tx_by_date
    }


@calendar_bp.route('/calendar')
def calendar():
    user = User.query.get(request.user_id)
    if not user: return spa_redirect(url_for('auth.logout'))
    if not user.ledger_id: return redirect(url_for('auth.onboarding'))
    ledger = Ledger.query.get(user.ledger_id)
    t_year, t_month, p_y, p_m, n_y, n_m = get_target_date()

    categories = Category.query.filter_by(ledger_id=ledger.id).order_by(Category.sort_order.asc(), Category.id.asc()).all()
    today_date = datetime.now().strftime('%Y-%m-%d')
    initial_data = build_calendar_data(ledger.id, t_year, t_month)

    return render_template('calendar.html', ledger=ledger, current_user=user, categories=categories,
                           today_date=today_date, now=datetime.now(),
                           initial_data=initial_data,
                           t_year=t_year, t_month=t_month, p_y=p_y, p_m=p_m, n_y=n_y, n_m=n_m, current_tab='calendar')


@calendar_bp.route('/api/calendar_data')
def api_calendar_data():
    user = User.query.get(request.user_id)
    if not user: return jsonify({'error': 'Unauthorized'}), 401
    y = int(request.args.get('year'))
    m = int(request.args.get('month'))
    return jsonify(build_calendar_data(user.ledger_id, y, m))

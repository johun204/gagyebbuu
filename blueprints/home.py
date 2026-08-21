from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from sqlalchemy.orm import joinedload

from models import User, Ledger, Category, Transaction
from helpers import spa_redirect, get_target_date, month_range

home_bp = Blueprint('home', __name__)


def _aggregate_expenses(txs, cat_names):
    """지출 거래 목록에서 카테고리별/요일별/참여자별 합계를 집계한다."""
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

    return cat_expense_total, dow_expense_by_cat, cat_payer_expense, payer_expense


def build_home_data(user_id, y, m):
    user = User.query.get(user_id)
    ledger = Ledger.query.get(user.ledger_id)
    categories = Category.query.filter_by(ledger_id=ledger.id).order_by(Category.sort_order.asc(), Category.id.asc()).all()
    start, end = month_range(y, m)
    # 최신 등록순으로 명시적 정렬, 해당 월 범위만 SQL에서 필터링 (전체 이력을 불러오지 않음)
    month_tx = Transaction.query.options(joinedload(Transaction.category)).filter(
        Transaction.ledger_id == ledger.id,
        Transaction.datetime_val >= start,
        Transaction.datetime_val < end
    ).order_by(Transaction.datetime_val.desc(), Transaction.id.desc()).all()

    # "지출분석 제외"와 "예산에서만 제외"는 서로 다른 계산에 독립적으로 적용된다.
    # 지출분석 제외 -> 총수입/총지출, 요일별/카테고리별 차트에서 빠짐
    # 예산에서만 제외 -> 전체/카테고리 예산 진행률(및 참여자 구성비)에서만 빠짐
    analysis_txs = [tx for tx in month_tx if not tx.exclude_analysis]
    budget_txs = [tx for tx in month_tx if not tx.exclude_budget]

    monthly_income = sum(tx.amount for tx in analysis_txs if tx.tx_type == '수입')
    monthly_expense = sum(tx.amount for tx in analysis_txs if tx.tx_type == '지출')
    budget_expense = sum(tx.amount for tx in budget_txs if tx.tx_type == '지출')

    cat_names = [c.name for c in categories]
    cat_expense_total, dow_expense_by_cat, _, _ = _aggregate_expenses(analysis_txs, cat_names)
    budget_cat_total, _, cat_payer_expense, payer_expense = _aggregate_expenses(budget_txs, cat_names)

    theme_colors = ['#13bd7e', '#ff9f43', '#0abde3', '#f368e0', '#ff6b6b', '#feca57', '#5f27cd', '#48dbfb', '#ff9ff3', '#10ac84']
    # 최근 거래자 순서가 아니라 이름순으로 고정 배정해야 매번 접속할 때 색이 바뀌지 않는다
    payer_color_map = {}
    for i, t in enumerate(sorted(payer_expense.keys())):
        payer_color_map[t] = theme_colors[(i + 4) % len(theme_colors)]

    budget_status = []
    for c in categories:
        if c.name != '미분류':
            spent = budget_cat_total.get(c.name, 0)
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
        'budget_expense': budget_expense,
        'ledger_budget': ledger.monthly_budget,
        'budget_status': budget_status,
        'payer_expense': payer_expense,
        'payer_color_map': payer_color_map,
        'cat_expense_total': cat_expense_total,
        'dow_expense_by_cat': dow_expense_by_cat
    }


@home_bp.route('/')
@home_bp.route('/home')
def home():
    user = User.query.get(request.user_id)
    if not user: return spa_redirect(url_for('auth.logout'))
    if not user.ledger_id: return redirect(url_for('auth.onboarding'))
    ledger = Ledger.query.get(user.ledger_id)

    t_year, t_month, p_y, p_m, n_y, n_m = get_target_date()
    initial_data = build_home_data(user.id, t_year, t_month)

    return render_template('home.html', ledger=ledger,
                           initial_data=initial_data,
                           t_year=t_year, t_month=t_month, p_y=p_y, p_m=p_m, n_y=n_y, n_m=n_m, current_tab='home')


@home_bp.route('/api/home_data')
def api_home_data():
    y = int(request.args.get('year'))
    m = int(request.args.get('month'))
    return jsonify(build_home_data(request.user_id, y, m))

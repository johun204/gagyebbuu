"""홈 대시보드 / 분석 화면용 집계.

내역 플래그의 의미는 그대로 지킨다.
  - 예산에서만 제외(exclude_budget): 총수입/총지출, 예산 진행률, 사람별 분담에서 빠진다.
  - 지출분석 제외(exclude_analysis): 카테고리/추이/요일/자주 쓴 곳 등 분석에서 빠진다.

DB 조회는 fetch_txs 한 곳에서만 하고, 나머지는 내역 목록을 받아 계산하는 순수 함수라 테스트하기 쉽다.
"""
from calendar import monthrange
from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import joinedload

from models import Category, Transaction
from helpers import (month_range, norm_color, serialize_tx, TransactorInfo,
                     UNCATEGORIZED, TOGETHER, FALLBACK_COLOR)

EXPENSE, INCOME = '지출', '수입'
WEEKDAYS = ['월', '화', '수', '목', '금', '토', '일']
TOP_CATEGORIES = 5          # 홈 카테고리 목록 개수 (나머지는 '기타'로 묶음)
TREND_MONTHS = 6


# ------------------------------------------------------------------ 기본 도구

def prev_month(y, m):
    return (y - 1, 12) if m == 1 else (y, m - 1)


def shift_month(y, m, delta):
    idx = y * 12 + (m - 1) + delta
    return idx // 12, idx % 12 + 1


def fetch_txs(ledger_id, start, end):
    return Transaction.query.options(joinedload(Transaction.category)).filter(
        Transaction.ledger_id == ledger_id,
        Transaction.datetime_val >= start,
        Transaction.datetime_val < end,
    ).order_by(Transaction.datetime_val.desc(), Transaction.id.desc()).all()


def won(n):
    return f"{int(round(n)):,}원"


def _expense(txs):
    return sum(t.amount for t in txs if t.tx_type == EXPENSE)


def _income(txs):
    return sum(t.amount for t in txs if t.tx_type == INCOME)


def _budget_txs(txs):
    return [t for t in txs if not t.exclude_budget]


def _analysis_txs(txs):
    return [t for t in txs if not t.exclude_analysis]


def _upto_day(txs, day):
    return [t for t in txs if t.datetime_val.day <= day]


def month_context(y, m, today):
    """선택한 달이 이번 달/지난 달/미래인지와 '지나간 날 수'."""
    dim = monthrange(y, m)[1]
    cur = (today.year, today.month)
    if (y, m) == cur:
        return {'days_in_month': dim, 'is_current': True, 'is_future': False, 'elapsed': today.day}
    if (y, m) > cur:
        return {'days_in_month': dim, 'is_current': False, 'is_future': True, 'elapsed': 0}
    return {'days_in_month': dim, 'is_current': False, 'is_future': False, 'elapsed': dim}


def _pct_change(cur, prev):
    if prev <= 0:
        return None
    return round((cur - prev) / prev * 100)


# ------------------------------------------------------------------ 계산 함수

def cumulative_by_day(txs, days, upto=None):
    """일별 누적 지출. upto 이후 날짜는 None (아직 오지 않은 날)."""
    daily = [0] * days
    for t in txs:
        if t.tx_type == EXPENSE:
            daily[t.datetime_val.day - 1] += t.amount
    out, acc = [], 0
    for i, v in enumerate(daily):
        acc += v
        out.append(acc if upto is None or i < upto else None)
    return out


def category_breakdown(txs, prev_txs, categories):
    """분석 대상 지출의 카테고리별 합계 (지난달 비교 포함), 금액 큰 순."""
    by_id = {c.id: c for c in categories}
    cur, prev = defaultdict(int), defaultdict(int)
    for t in txs:
        if t.tx_type == EXPENSE:
            cur[t.category_id] += t.amount
    for t in prev_txs:
        if t.tx_type == EXPENSE:
            prev[t.category_id] += t.amount
    total = sum(cur.values())
    rows = []
    for cid, amount in cur.items():
        c = by_id.get(cid)
        rows.append({
            'id': cid,
            'name': c.name if c else UNCATEGORIZED,
            'color': norm_color(c.color if c else None),
            'amount': amount,
            'share': round(amount / total * 100, 1) if total else 0,
            'prev_amount': prev.get(cid, 0),
            'change_pct': _pct_change(amount, prev.get(cid, 0)),
        })
    rows.sort(key=lambda r: (-r['amount'], r['name']))
    return rows, total


def fold_top(rows, n=TOP_CATEGORIES):
    """상위 n개 + 나머지는 '기타' 한 줄로 (색이 8개를 넘지 않도록)."""
    if len(rows) <= n:
        return rows
    rest = rows[n:]
    other = {
        'id': None, 'name': f'기타 {len(rest)}개', 'color': FALLBACK_COLOR,
        'amount': sum(r['amount'] for r in rest),
        'share': round(sum(r['share'] for r in rest), 1),
        'prev_amount': sum(r['prev_amount'] for r in rest), 'change_pct': None,
    }
    return rows[:n] + [other]


def person_split(txs, tinfo):
    """사람별(+함께) 지출. 색은 각자 고른 색."""
    sums, colors = defaultdict(int), {}
    for t in txs:
        if t.tx_type == EXPENSE:
            k = tinfo.key(t)
            sums[k] += t.amount
            colors.setdefault(k, tinfo.color(t))
    total = sum(sums.values())
    # 현재 참여자 -> 함께 -> 그 외 순서로 고정 (색이 순위에 따라 바뀌지 않게)
    order = [u.nickname for u in sorted(tinfo.ledger.users, key=lambda u: u.id)] + [TOGETHER]
    keys = [k for k in order if k in sums] + sorted(k for k in sums if k not in order)
    return [{'name': k, 'amount': sums[k], 'color': colors[k],
             'share': round(sums[k] / total * 100, 1) if total else 0} for k in keys], total


def weekday_average(txs, y, m, elapsed):
    """요일별 하루 평균 지출 (이번 달 지나간 날 기준)."""
    sums = [0] * 7
    counts = [0] * 7
    for d in range(1, elapsed + 1):
        counts[datetime(y, m, d).weekday()] += 1
    for t in txs:
        if t.tx_type == EXPENSE and t.datetime_val.day <= elapsed:
            sums[t.datetime_val.weekday()] += t.amount
    return [{'label': WEEKDAYS[i], 'total': sums[i], 'days': counts[i],
             'average': round(sums[i] / counts[i]) if counts[i] else 0} for i in range(7)]


def frequent_places(txs, n=5):
    groups = defaultdict(lambda: {'count': 0, 'amount': 0})
    for t in txs:
        if t.tx_type == EXPENSE and t.title:
            g = groups[t.title]
            g['count'] += 1
            g['amount'] += t.amount
    rows = [{'title': k, **v} for k, v in groups.items()]
    rows.sort(key=lambda r: (-r['count'], -r['amount'], r['title']))
    return rows[:n]


def budget_status(budget, spent, ctx):
    """예산 진행 상황과 남은 기간 하루 권장액, 월말 예상."""
    if not budget:
        return None
    dim, elapsed = ctx['days_in_month'], ctx['elapsed']
    remaining = budget - spent
    out = {
        'budget': budget, 'spent': spent, 'remaining': remaining,
        'used_pct': round(spent / budget * 100, 1),
        'pace_pct': None, 'per_day': None, 'days_left': None, 'projected': None,
    }
    if ctx['is_current']:
        days_left = dim - elapsed + 1  # 오늘 포함
        out['pace_pct'] = round(elapsed / dim * 100, 1)
        out['days_left'] = days_left
        out['per_day'] = max(remaining, 0) // days_left if days_left else 0
        if elapsed >= 1:
            out['projected'] = round(spent / elapsed * dim)
    return out


def category_budgets(categories, budget_txs):
    spent = defaultdict(int)
    for t in budget_txs:
        if t.tx_type == EXPENSE:
            spent[t.category_id] += t.amount
    rows = []
    for c in categories:
        if c.name != UNCATEGORIZED and (c.budget or 0) > 0:
            s = spent.get(c.id, 0)
            rows.append({'id': c.id, 'name': c.name, 'color': norm_color(c.color), 'budget': c.budget,
                         'spent': s, 'used_pct': round(s / c.budget * 100, 1)})
    rows.sort(key=lambda r: -r['used_pct'])
    return rows


def build_insights(ctx, budget, cats, cat_budgets, weekdays, biggest):
    """화면 상단에 보여줄 한 줄 인사이트 (중요한 것 우선, 최대 3개).
    level: critical(초과) / warning(주의) / good(잘하고 있음) / info(참고) — 색만이 아니라 아이콘+문구로 전달."""
    out = []
    if budget:
        # 예산 초과 자체는 홈 상단 예산 카드가 이미 보여주므로 여기서는 '앞으로의 예상'만 알려준다.
        if budget['spent'] > budget['budget']:
            pass
        elif ctx['is_current'] and ctx['elapsed'] >= 3 and budget['projected']:
            over = budget['projected'] - budget['budget']
            if over > 0:
                out.append(('warning', f"지금 속도면 월말에 예산보다 {won(over)} 더 쓰게 돼요."))
            else:
                out.append(('good', f"지금 속도면 예산 안에서 마무리할 수 있어요. (예상 {won(budget['projected'])})"))
    over_cats = [c for c in cat_budgets if c['spent'] > c['budget']]
    if over_cats:
        c = over_cats[0]
        more = f" 외 {len(over_cats) - 1}개" if len(over_cats) > 1 else ''
        out.append(('critical', f"'{c['name']}'{more} 분류 예산을 초과했어요. ({c['used_pct']:.0f}%)"))

    period = '지난달 같은 기간' if ctx['is_current'] else '지난달'
    ups = [c for c in cats if c['id'] and c['change_pct'] is not None and c['change_pct'] >= 20
           and c['amount'] - c['prev_amount'] >= 30000]
    if ups:
        c = max(ups, key=lambda r: r['amount'] - r['prev_amount'])
        out.append(('warning', f"'{c['name']}' 지출이 {period}보다 {c['change_pct']}% 늘었어요. (+{won(c['amount'] - c['prev_amount'])})"))
    downs = [c for c in cats if c['id'] and c['change_pct'] is not None and c['change_pct'] <= -20
             and c['prev_amount'] - c['amount'] >= 30000]
    if downs:
        c = max(downs, key=lambda r: r['prev_amount'] - r['amount'])
        out.append(('good', f"'{c['name']}' 지출이 {period}보다 {abs(c['change_pct'])}% 줄었어요. (-{won(c['prev_amount'] - c['amount'])})"))

    wk = [w for w in weekdays[:5] if w['days']]
    we = [w for w in weekdays[5:] if w['days']]
    if wk and we:
        wk_avg = sum(w['total'] for w in wk) / sum(w['days'] for w in wk)
        we_avg = sum(w['total'] for w in we) / sum(w['days'] for w in we)
        if wk_avg > 0 and we_avg / wk_avg >= 1.5 and ctx['elapsed'] >= 7:
            out.append(('info', f"주말 하루 평균 지출({won(we_avg)})이 평일의 {we_avg / wk_avg:.1f}배예요."))
    if biggest:
        out.append(('info', f"가장 큰 지출은 '{biggest['title'] or biggest['category']}' {won(biggest['amount'])}이에요."))

    rank = {'critical': 0, 'warning': 1, 'good': 2, 'info': 3}
    out.sort(key=lambda x: rank[x[0]])
    return [{'level': lv, 'text': tx} for lv, tx in out[:3]]


# ------------------------------------------------------------------ 화면별 데이터

def _categories(ledger_id):
    return Category.query.filter_by(ledger_id=ledger_id).order_by(Category.sort_order.asc(), Category.id.asc()).all()


def home_data(ledger, y, m, today=None):
    today = today or datetime.now()
    ctx = month_context(y, m, today)
    py, pm = prev_month(y, m)
    pdim = monthrange(py, pm)[1]
    txs = fetch_txs(ledger.id, *month_range(y, m))
    ptxs = fetch_txs(ledger.id, *month_range(py, pm))
    categories = _categories(ledger.id)
    tinfo = TransactorInfo(ledger)

    # 지난달과 같은 기간끼리 비교 (이번 달이면 1일~오늘, 지난 달이면 한 달 전체)
    cmp_day = min(ctx['elapsed'], pdim) if ctx['is_current'] else pdim
    ptxs_same = _upto_day(ptxs, cmp_day)

    b_txs, a_txs = _budget_txs(txs), _analysis_txs(txs)
    expense, income = _expense(b_txs), _income(b_txs)
    prev_expense_same = _expense(_budget_txs(ptxs_same))

    budget = budget_status(ledger.monthly_budget or 0, expense, ctx)
    cats, cat_total = category_breakdown(a_txs, _analysis_txs(ptxs_same), categories)
    people, _ = person_split(b_txs, tinfo)
    cat_budgets = category_budgets(categories, b_txs)
    weekdays = weekday_average(a_txs, y, m, ctx['elapsed'])
    expenses = [t for t in a_txs if t.tx_type == EXPENSE]
    biggest = serialize_tx(max(expenses, key=lambda t: t.amount), tinfo) if expenses else None

    return {
        'year': y, 'month': m, **ctx,
        'expense': expense, 'income': income, 'net': income - expense,
        'prev_expense_same': prev_expense_same,
        'expense_change_pct': _pct_change(expense, prev_expense_same),
        'compare_label': '지난달 같은 기간' if ctx['is_current'] else '지난달',
        'budget': budget,
        'pace': {
            'current': cumulative_by_day(b_txs, ctx['days_in_month'], ctx['elapsed'] if ctx['is_current'] else None),
            'previous': cumulative_by_day(_budget_txs(ptxs), pdim),
        },
        'people': people,
        'categories': fold_top(cats),
        'category_total': cat_total,
        'category_budgets': cat_budgets,
        'insights': build_insights(ctx, budget, cats, cat_budgets, weekdays, biggest),
        'recent': [serialize_tx(t, tinfo) for t in txs[:5]],
        'has_data': bool(txs),
    }


def analysis_data(ledger, y, m, today=None):
    today = today or datetime.now()
    ctx = month_context(y, m, today)
    categories = _categories(ledger.id)
    tinfo = TransactorInfo(ledger)

    # 최근 6개월 추이 (한 번에 조회)
    first_y, first_m = shift_month(y, m, -(TREND_MONTHS - 1))
    all_txs = fetch_txs(ledger.id, month_range(first_y, first_m)[0], month_range(y, m)[1])
    by_month = defaultdict(list)
    for t in all_txs:
        by_month[(t.datetime_val.year, t.datetime_val.month)].append(t)
    trend = []
    for i in range(TREND_MONTHS):
        ty, tm = shift_month(first_y, first_m, i)
        a = _analysis_txs(by_month[(ty, tm)])
        trend.append({'year': ty, 'month': tm, 'label': f'{tm}월', 'expense': _expense(a), 'income': _income(a)})
    past = [t['expense'] for t in trend[:-1] if t['expense'] > 0]
    trend_avg = round(sum(past) / len(past)) if past else 0

    txs = by_month[(y, m)]
    a_txs, b_txs = _analysis_txs(txs), _budget_txs(txs)
    py, pm = prev_month(y, m)
    pdim = monthrange(py, pm)[1]
    cmp_day = min(ctx['elapsed'], pdim) if ctx['is_current'] else pdim
    ptxs_same = _upto_day(by_month[(py, pm)], cmp_day)
    cats, cat_total = category_breakdown(a_txs, _analysis_txs(ptxs_same), categories)

    # 사람별: 총액 + 많이 쓴 분류 3개
    people, people_total = person_split(a_txs, tinfo)
    by_person_cat = defaultdict(lambda: defaultdict(int))
    cat_name = {c.id: c.name for c in categories}
    for t in a_txs:
        if t.tx_type == EXPENSE:
            by_person_cat[tinfo.key(t)][cat_name.get(t.category_id, UNCATEGORIZED)] += t.amount
    for p in people:
        top = sorted(by_person_cat[p['name']].items(), key=lambda kv: -kv[1])[:3]
        p['top_categories'] = [{'name': k, 'amount': v} for k, v in top]

    expenses = sorted((t for t in a_txs if t.tx_type == EXPENSE), key=lambda t: -t.amount)
    income, expense = _income(b_txs), _expense(b_txs)
    return {
        'year': y, 'month': m, **ctx,
        'income': income, 'expense': expense, 'net': income - expense,
        'savings_rate': round((income - expense) / income * 100) if income > 0 else None,
        'trend': trend, 'trend_avg': trend_avg,
        'categories': cats, 'category_total': cat_total,
        'compare_label': '지난달 같은 기간' if ctx['is_current'] else '지난달',
        'weekdays': weekday_average(a_txs, y, m, ctx['elapsed']),
        'people': people, 'people_total': people_total,
        'places': frequent_places(a_txs),
        'top_expenses': [serialize_tx(t, tinfo) for t in expenses[:5]],
        'has_data': bool(txs),
    }

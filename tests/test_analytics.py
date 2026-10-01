from datetime import datetime

from analytics import (month_context, cumulative_by_day, budget_status, fold_top, weekday_average,
                       shift_month, home_data, analysis_data)
from models import db, Transaction


def _tx(ledger, user, cat, day, amount, month=9, tx_type='지출', transactor=None, title='t', **kw):
    t = Transaction(ledger_id=ledger.id, user_id=user.id, tx_type=tx_type, transactor=transactor or user.nickname,
                    transactor_user_id=None if transactor == '함께' else user.id, title=title, amount=amount,
                    category_id=cat.id, datetime_val=datetime(2026, month, day, 12, 0), **kw)
    db.session.add(t)
    return t


def test_month_context():
    today = datetime(2026, 9, 10)
    assert month_context(2026, 9, today) == {'days_in_month': 30, 'is_current': True, 'is_future': False, 'elapsed': 10}
    assert month_context(2026, 8, today)['elapsed'] == 31
    assert month_context(2026, 10, today)['elapsed'] == 0
    assert shift_month(2026, 1, -1) == (2025, 12) and shift_month(2026, 11, 3) == (2027, 2)


def test_budget_status_pace_and_daily_allowance():
    ctx = {'days_in_month': 30, 'is_current': True, 'is_future': False, 'elapsed': 10}
    b = budget_status(300000, 150000, ctx)
    assert b['used_pct'] == 50.0 and b['pace_pct'] == 33.3
    assert b['days_left'] == 21 and b['per_day'] == 150000 // 21
    assert b['projected'] == 450000
    assert budget_status(0, 1000, ctx) is None
    over = budget_status(100000, 120000, ctx)
    assert over['remaining'] == -20000 and over['per_day'] == 0


def test_cumulative_and_fold():
    class T:
        def __init__(self, d, a): self.datetime_val, self.amount, self.tx_type = datetime(2026, 9, d), a, '지출'
    assert cumulative_by_day([T(1, 100), T(3, 50)], 5, upto=3) == [100, 100, 150, None, None]
    rows = [{'id': i, 'name': str(i), 'color': '#000', 'amount': 10 - i, 'share': 10.0, 'prev_amount': 0, 'change_pct': None} for i in range(8)]
    folded = fold_top(rows, 5)
    assert len(folded) == 6 and folded[-1]['name'] == '기타 3개' and folded[-1]['amount'] == 5 + 4 + 3


def test_weekday_average_counts_only_elapsed_days():
    class T:
        def __init__(self, d, a): self.datetime_val, self.amount, self.tx_type = datetime(2026, 9, d), a, '지출'
    # 2026-09-07 월요일, 09-14 월요일
    w = weekday_average([T(7, 10000), T(14, 20000), T(20, 99999)], 2026, 9, 14)
    assert w[0]['label'] == '월' and w[0]['days'] == 2 and w[0]['average'] == 15000
    assert sum(x['total'] for x in w) == 30000  # 15일 이후 내역은 제외


def test_home_data_respects_flags_and_compares_same_period(make_ledger):
    ledger, (a, b), cats = make_ledger()
    ledger.monthly_budget = 200000
    _tx(ledger, a, cats['외식'], 2, 50000)
    _tx(ledger, b, cats['카페'], 5, 10000)
    _tx(ledger, a, cats['외식'], 8, 30000, transactor='함께')
    _tx(ledger, a, cats['외식'], 9, 70000, exclude_budget=True)       # 예산/총액에서 빠짐, 분석엔 포함
    _tx(ledger, a, cats['카페'], 9, 90000, exclude_analysis=True)     # 분석에서 빠짐, 총액엔 포함
    _tx(ledger, a, cats['외식'], 3, 1000000, tx_type='수입', title='월급')
    _tx(ledger, a, cats['외식'], 4, 20000, month=8)                     # 지난달 같은 기간 (1~10일)
    _tx(ledger, a, cats['외식'], 25, 999999, month=8)                   # 지난달이지만 비교 기간 밖
    db.session.commit()

    d = home_data(ledger, 2026, 9, today=datetime(2026, 9, 10))
    assert d['expense'] == 50000 + 10000 + 30000 + 90000
    assert d['income'] == 1000000
    assert d['prev_expense_same'] == 20000
    assert d['budget']['spent'] == d['expense'] and d['budget']['days_left'] == 21
    cats_by_name = {c['name']: c for c in d['categories']}
    assert cats_by_name['외식']['amount'] == 50000 + 30000 + 70000
    assert cats_by_name['외식']['prev_amount'] == 20000
    assert cats_by_name['카페']['amount'] == 10000
    people = {p['name']: p['amount'] for p in d['people']}
    assert people == {'철수': 50000 + 90000, '영희': 10000, '함께': 30000}
    assert [p['name'] for p in d['people']] == ['철수', '영희', '함께']    # 순서 고정
    assert d['pace']['current'][9] == d['expense'] and d['pace']['current'][10] is None
    assert len(d['recent']) == 5
    assert any('예산' in i['text'] for i in d['insights'])


def test_analysis_data_trend_and_places(make_ledger):
    ledger, (a, _), cats = make_ledger()
    for mth, amt in [(4, 100000), (7, 50000), (9, 80000)]:
        _tx(ledger, a, cats['외식'], 1, amt, month=mth, title='김밥천국')
    _tx(ledger, a, cats['카페'], 2, 4500, title='스타벅스')
    _tx(ledger, a, cats['카페'], 3, 4500, title='스타벅스')
    db.session.commit()
    d = analysis_data(ledger, 2026, 9, today=datetime(2026, 9, 30))
    assert [t['label'] for t in d['trend']] == ['4월', '5월', '6월', '7월', '8월', '9월']
    assert [t['expense'] for t in d['trend']] == [100000, 0, 0, 50000, 0, 89000]
    assert d['trend_avg'] == 75000
    assert d['places'][0] == {'title': '스타벅스', 'count': 2, 'amount': 9000}
    assert d['top_expenses'][0]['amount'] == 80000


def test_new_pages_and_apis(make_ledger, client_for):
    _, (a, _), _ = make_ledger()
    c = client_for(a)
    assert c.get('/analysis').status_code == 200
    assert c.get('/api/analysis_data?year=2026&month=9').status_code == 200
    assert c.get('/api/analysis_data?year=2026&month=13').status_code == 400
    assert c.get('/transactions?category_id=999999&tx_type=지출').status_code == 200

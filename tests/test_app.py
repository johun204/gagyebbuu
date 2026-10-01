import io
import json
from datetime import datetime

from models import db, User, Ledger, Category, Transaction


def add_tx(client, **over):
    form = {'tx_type': '지출', 'amount': '10,000', 'transactor': '철수', 'title': '점심',
            'date': '2026-09-15', 'time': '12:30', 'memo': '', 'ajax': '1'}
    form.update(over)
    return client.post('/transaction', data=form)


# ---------------------------------------------------------------- 분류 삭제

def test_delete_used_category_moves_transactions_to_uncategorized(make_ledger, client_for):
    ledger, (chulsoo, _), cats = make_ledger()
    c = client_for(chulsoo)
    assert add_tx(c, category_id=str(cats['카페'].id), title='커피').status_code == 200

    res = c.post(f"/api/category/{cats['카페'].id}/delete", json={})
    assert res.status_code == 200
    assert res.get_json()['moved'] == 1

    tx = Transaction.query.one()
    assert tx.category_id == cats['미분류'].id
    assert db.session.get(Category, cats['카페'].id) is None
    # 삭제 후에도 홈/달력 데이터가 정상
    assert c.get('/api/home_data?year=2026&month=9').status_code == 200
    assert c.get('/api/calendar_data?year=2026&month=9').status_code == 200


def test_uncategorized_cannot_be_deleted_or_renamed(make_ledger, client_for):
    _, (chulsoo, _), cats = make_ledger()
    c = client_for(chulsoo)
    assert c.post(f"/api/category/{cats['미분류'].id}/delete", json={}).status_code == 404
    assert c.post(f"/api/category/{cats['미분류'].id}/edit", json={'name': 'x'}).status_code == 404


def test_category_name_rules(make_ledger, client_for):
    _, (chulsoo, _), cats = make_ledger()
    c = client_for(chulsoo)
    assert c.post('/api/category/add', json={'name': '카페'}).status_code == 400       # 중복
    assert c.post('/api/category/add', json={'name': '미분류'}).status_code == 400     # 예약어
    assert c.post('/api/category/add', json={'name': '   '}).status_code == 400        # 빈 값
    assert c.post('/api/category/add', json={}).status_code == 400
    assert c.post(f"/api/category/{cats['외식'].id}/edit", json={'name': '카페'}).status_code == 400
    assert c.post(f"/api/category/{cats['외식'].id}/edit", json={'name': '외식'}).status_code == 200  # 그대로 저장
    res = c.post('/api/category/add', json={'name': '가' * 80})                          # 50자로 잘림
    assert res.status_code == 200
    assert Category.query.filter(Category.name == '가' * 50).count() == 1


# ---------------------------------------------------------------- 입력 검증

def test_invalid_year_month_returns_400_not_500(make_ledger, client_for):
    _, (chulsoo, _), _ = make_ledger()
    c = client_for(chulsoo)
    for q in ['year=2026&month=13', 'year=abc&month=1', '', 'year=2026']:
        assert c.get(f'/api/home_data?{q}').status_code == 400
        assert c.get(f'/api/calendar_data?{q}').status_code == 400
    # 화면은 잘못된 값이면 이번 달로 대체
    assert c.get('/home?year=2026&month=99').status_code == 200
    assert c.get('/transactions?year=x&month=1').status_code == 200


def test_add_transaction_validation(make_ledger, client_for):
    _, (chulsoo, _), _ = make_ledger()
    c = client_for(chulsoo)
    assert add_tx(c, tx_type='기타').status_code == 400
    assert add_tx(c, amount='').status_code == 400
    assert add_tx(c, amount='-5').status_code == 400
    assert add_tx(c, amount='9' * 13).status_code == 400
    assert add_tx(c, date='2026-02-30').status_code == 400
    assert add_tx(c, date='').status_code == 400
    assert Transaction.query.count() == 0
    # 시간이 비어 있으면 현재 시각으로 저장 (예전엔 500)
    assert add_tx(c, time='').status_code == 200


def test_large_amount_and_long_text_are_stored(make_ledger, client_for):
    _, (chulsoo, _), _ = make_ledger()
    c = client_for(chulsoo)
    # 21억(INTEGER 한계)을 넘는 금액, 컬럼 길이를 넘는 제목/메모 -> 오류 없이 저장
    res = add_tx(c, amount='3,000,000,000', title='t' * 300, memo='m' * 600)
    assert res.status_code == 200, res.data
    tx = Transaction.query.one()
    assert tx.amount == 3_000_000_000
    assert len(tx.title) == 100 and len(tx.memo) == 255
    data = c.get('/api/home_data?year=2026&month=9').get_json()
    assert data['budget_expense'] == 3_000_000_000


def test_title_missing_is_not_500(make_ledger, client_for):
    _, (chulsoo, _), _ = make_ledger()
    c = client_for(chulsoo)
    form = {'tx_type': '지출', 'amount': '1000', 'date': '2026-09-15', 'time': '10:00', 'ajax': '1'}
    assert c.post('/transaction', data=form).status_code == 200
    tx = Transaction.query.one()
    assert tx.title == '' and tx.transactor == '철수' and tx.transactor_user_id == chulsoo.id


def test_foreign_category_id_falls_back_to_uncategorized(make_ledger, client_for):
    _, (chulsoo, _), cats = make_ledger()
    _, _, other_cats = make_ledger(nicknames=('남',), name='남의집')
    c = client_for(chulsoo)
    assert add_tx(c, category_id=str(other_cats['카페'].id), title='새가게').status_code == 200
    assert add_tx(c, category_id='abc', title='새가게2').status_code == 200
    assert {t.category_id for t in Transaction.query.all()} == {cats['미분류'].id}


def test_search_api(make_ledger, client_for):
    _, (chulsoo, _), _ = make_ledger()
    c = client_for(chulsoo)
    add_tx(c, title='Starbucks 라떼')
    add_tx(c, title='100% 환불')
    add_tx(c, title='1000원 할인')

    def search(q):
        return c.get('/api/transactions?' + q).get_json()

    assert search('keyword=starbucks')['total_count'] == 1          # 대소문자 무시
    assert search('keyword=100%25')['total_count'] == 1             # % 는 글자 그대로
    assert search('start_date=2026-09-15&end_date=2026-09-15')['total_count'] == 3
    assert c.get('/api/transactions?start_date=bad').status_code == 400
    assert c.get('/api/transactions?category_id=abc').status_code == 400
    assert search('page=-3')['total_count'] == 3


# ---------------------------------------------------------------- 거래자 / 닉네임

def test_transactor_user_id_is_recorded(make_ledger, client_for):
    _, (chulsoo, younghee), _ = make_ledger()
    c = client_for(chulsoo)
    add_tx(c, transactor='영희')
    add_tx(c, transactor='함께')
    add_tx(c, transactor='')
    rows = {t.transactor: t.transactor_user_id for t in Transaction.query.all()}
    assert rows == {'영희': younghee.id, '함께': None, '철수': chulsoo.id}


def test_nickname_change_keeps_color_and_aggregation(make_ledger, client_for):
    _, (chulsoo, _), _ = make_ledger()
    c = client_for(chulsoo)
    add_tx(c, transactor='철수', amount='5000')

    # '과거 내역도 변경' 없이 닉네임 변경
    res = c.post('/update_nickname', data={'nickname': '철수2', 'ajax': '1'})
    assert res.status_code == 200
    add_tx(c, transactor='철수2', amount='7000')

    data = c.get('/api/home_data?year=2026&month=9').get_json()
    # 같은 사람의 지출이 새 닉네임 하나로 합쳐지고 본인 색상을 유지한다
    assert data['payer_expense'] == {'철수2': 12000}
    assert data['payer_color_map'] == {'철수2': '#3FADD6'}

    listed = c.get('/api/transactions').get_json()['transactions']
    old = next(t for t in listed if t['amount'] == 5000)
    assert old['transactor'] == '철수'            # 표시 이름은 기록 당시 그대로
    assert old['transactor_value'] == '철수2'     # 수정 시트에서는 현재 닉네임 버튼이 선택됨
    assert old['transactor_color'] == '#3FADD6'


def test_nickname_update_past_only_touches_own_rows(make_ledger, client_for):
    ledger, (chulsoo, younghee), _ = make_ledger()
    c = client_for(chulsoo)
    add_tx(c, transactor='철수')
    # 예전 방식(사용자 id 없이 이름만)으로 남은 내역
    db.session.add(Transaction(ledger_id=ledger.id, user_id=chulsoo.id, tx_type='지출', transactor='철수',
                               title='old', amount=1, category_id=Category.query.first().id,
                               datetime_val=datetime(2026, 9, 1)))
    db.session.commit()
    add_tx(c, transactor='영희')
    c.post('/update_nickname', data={'nickname': '철수씨', 'update_past': 'on', 'ajax': '1'})
    names = sorted(t.transactor for t in Transaction.query.all())
    assert names == ['영희', '철수씨', '철수씨']
    assert all(t.transactor_user_id == chulsoo.id for t in Transaction.query.filter_by(transactor='철수씨'))


def test_nickname_collisions_are_rejected(make_ledger, client_for):
    _, (chulsoo, _), _ = make_ledger()
    c = client_for(chulsoo)
    for bad in ['영희', '함께', '   ']:
        res = c.post('/update_nickname', data={'nickname': bad, 'ajax': '1'})
        assert 'msg=nickname_' in res.get_json()['redirect']
    assert db.session.get(User, chulsoo.id).nickname == '철수'


def test_edit_keeps_link_to_departed_partner(make_ledger, client_for):
    ledger, (chulsoo, younghee), cats = make_ledger()
    c = client_for(chulsoo)
    add_tx(c, transactor='영희')
    tx = Transaction.query.one()
    # 영희가 가계부를 나감
    client_for(younghee).post('/leave_ledger', data={'ajax': '1'})
    res = c.post(f'/transaction/{tx.id}/edit', data={
        'tx_type': '지출', 'amount': '20,000', 'transactor': '영희', 'title': '수정', 'date': '2026-09-15',
        'time': '12:00', 'category_id': str(cats['외식'].id), 'ajax': '1'})
    assert res.status_code == 200
    db.session.expire_all()
    tx = db.session.get(Transaction, tx.id)
    assert (tx.transactor, tx.transactor_user_id, tx.amount) == ('영희', younghee.id, 20000)


# ---------------------------------------------------------------- 초대 / 참여 / 나가기

def test_leave_rotates_invite_and_old_link_stops_working(app, make_ledger, client_for):
    ledger, (chulsoo, younghee), _ = make_ledger()
    old_hash = ledger.invite_hash
    client_for(younghee).post('/leave_ledger', data={'ajax': '1'})
    db.session.expire_all()
    ledger = db.session.get(Ledger, ledger.id)
    assert ledger.invite_hash != old_hash

    # 나간 사람이 예전 링크로 다시 들어오려 하면 실패
    res = client_for(younghee).get(f'/invite/{old_hash}')
    assert '유효하지 않거나' in res.get_data(as_text=True)
    assert db.session.get(User, younghee.id).ledger_id is None
    # 새 링크로는 참여 가능
    client_for(younghee).get(f'/invite/{ledger.invite_hash}')
    db.session.expire_all()
    assert db.session.get(User, younghee.id).ledger_id == ledger.id


def test_full_ledger_cannot_be_joined(make_ledger, client_for):
    ledger, _, _ = make_ledger()
    stranger = User(kakao_id='x', nickname='x')
    db.session.add(stranger)
    db.session.commit()
    c = client_for(stranger)
    res = c.post('/onboarding', data={'action': 'join', 'invite_code': ledger.invite_hash})
    assert json.dumps('유효하지 않거나 이미 2명이 참여 중인 초대 코드입니다.')[1:-1] in res.get_data(as_text=True)
    assert c.get(f'/invite_process?hash={ledger.invite_hash}').status_code == 200
    assert db.session.get(User, stranger.id).ledger_id is None


def test_join_renames_duplicate_nickname(make_ledger, client_for):
    ledger, (chulsoo,), _ = make_ledger(nicknames=('철수',))
    other = User(kakao_id='y', nickname='철수')
    db.session.add(other)
    db.session.commit()
    client_for(other).post('/onboarding', data={'action': 'join', 'invite_code': ledger.invite_hash})
    db.session.expire_all()
    other = db.session.get(User, other.id)
    assert other.ledger_id == ledger.id and other.nickname == '철수 2'


def test_regenerate_invite(make_ledger, client_for):
    ledger, (chulsoo, _), _ = make_ledger()
    old = ledger.invite_hash
    res = client_for(chulsoo).post('/regenerate_invite', data={'ajax': '1'})
    assert 'invite_regenerated' in res.get_json()['redirect']
    db.session.expire_all()
    assert db.session.get(Ledger, ledger.id).invite_hash != old


def test_last_member_leaving_deletes_ledger_data(make_ledger, client_for):
    ledger, (solo,), _ = make_ledger(nicknames=('혼자',))
    c = client_for(solo)
    add_tx(c, transactor='혼자')
    c.post('/leave_ledger', data={'ajax': '1'})
    assert Ledger.query.count() == 0 and Transaction.query.count() == 0 and Category.query.count() == 0
    assert db.session.get(User, solo.id).ledger_id is None


def test_onboarding_create_requires_name(app, client_for):
    u = User(kakao_id='z', nickname='z')
    db.session.add(u)
    db.session.commit()
    c = client_for(u)
    res = c.post('/onboarding', data={'action': 'create', 'ledger_name': '   '})
    assert json.dumps('가계부 이름을 입력해주세요.')[1:-1] in res.get_data(as_text=True)
    res = c.post('/onboarding', data={'action': 'create', 'ledger_name': '새 가계부'})
    assert res.get_json()['redirect'] == '/home'
    assert Category.query.filter_by(name='미분류').count() == 1


# ---------------------------------------------------------------- 가계부 없는 사용자

def test_user_without_ledger_gets_no_500(app, client_for):
    u = User(kakao_id='nolg', nickname='n')
    db.session.add(u)
    db.session.commit()
    c = client_for(u)
    for url in ['/api/home_data?year=2026&month=9', '/api/calendar_data?year=2026&month=9',
                '/api/transactions', '/api/categories']:
        assert c.get(url).status_code == 400, url
    for url in ['/home', '/calendar', '/transactions', '/settings', '/mypage', '/export']:
        res = c.get(url)
        assert res.status_code == 302 and '/onboarding' in res.headers['Location'], url
    for url in ['/update_together_color', '/set_budget', '/import', '/transaction']:
        assert c.post(url, data={'ajax': '1'}).get_json()['redirect'] == '/onboarding', url


# ---------------------------------------------------------------- CSV

def test_csv_roundtrip_skips_duplicates(make_ledger, client_for):
    _, (chulsoo, _), _ = make_ledger()
    c = client_for(chulsoo)
    add_tx(c, title='점심', amount='9000')
    add_tx(c, title='저녁', amount='15000', transactor='함께')
    exported = c.get('/export').data
    assert c.get('/export').headers['Cache-Control'] == 'no-store'

    res = c.post('/import', data={'csv_file': (io.BytesIO(exported), 'ledger.csv'), 'ajax': '1'},
                 content_type='multipart/form-data')
    redirect = res.get_json()['redirect']
    assert 'imported=0' in redirect and 'skipped_dup=2' in redirect
    assert Transaction.query.count() == 2


def test_csv_import_tolerates_bad_rows(make_ledger, client_for):
    _, (chulsoo, _), _ = make_ledger()
    c = client_for(chulsoo)
    csv_text = '\n'.join([
        '#LEDGER_META,새이름,abc',
        '#CATEGORY_ROW,간식,0,5000,3,"red;background:url(x)"',
        '#CATEGORY_ROW,,0,0,0,',
        '#TX_ROW,2026-09-01,10:00,지출,철수,간식,과자,,3000,0,철수,0',
        '#TX_ROW,2026-13-01,10:00,지출,철수,간식,날짜오류,,3000,0,철수,0',
        '#TX_ROW,2026-09-02,10:00,기타,철수,간식,구분오류,,3000,0,철수,0',
        '#TX_ROW,2026-09-03,10:00,지출,철수,간식,금액오류,,abc,0,철수,0',
        '#TX_ROW,2026-09-04,10:00,지출,모르는사람,없는분류,' + 'x' * 300 + ',,4000,1,철수',
        '2026-09-05,11:00,수입,함께,급여,월급,,5000000',
    ])
    res = c.post('/import', data={'csv_file': (io.BytesIO(csv_text.encode('utf-8-sig')), 'a.csv'), 'ajax': '1'},
                 content_type='multipart/form-data')
    redirect = res.get_json()['redirect']
    assert 'imported=3' in redirect and 'skipped_bad=3' in redirect, redirect
    snack = Category.query.filter_by(name='간식').one()
    assert snack.color and snack.color.startswith('#') and len(snack.color) == 7   # 이상한 색상값은 무시
    assert Category.query.filter_by(name='').count() == 0
    stranger = Transaction.query.filter_by(transactor='모르는사람').one()
    assert stranger.transactor_user_id is None and len(stranger.title) == 100
    assert db.session.get(Ledger, chulsoo.ledger_id).name == '새이름'


def test_csv_import_bad_encoding(make_ledger, client_for):
    _, (chulsoo, _), _ = make_ledger()
    c = client_for(chulsoo)
    res = c.post('/import', data={'csv_file': (io.BytesIO('일자'.encode('cp949')), 'a.csv'), 'ajax': '1'},
                 content_type='multipart/form-data')
    assert 'import_encoding' in res.get_json()['redirect']


# ---------------------------------------------------------------- 기타

def test_push_failure_does_not_break_saving(monkeypatch, make_ledger, client_for):
    import config
    import blueprints.push as push
    from models import PushSubscription
    _, (chulsoo, younghee), _ = make_ledger()
    db.session.add(PushSubscription(user_id=younghee.id, endpoint='https://push.example/1', p256dh='p', auth='a'))
    db.session.commit()
    monkeypatch.setattr(config, 'VAPID_PRIVATE_KEY', 'dummy')

    def boom(**kw):
        raise RuntimeError('push server down')
    monkeypatch.setattr(push, 'webpush', boom)
    assert add_tx(client_for(chulsoo)).status_code == 200
    assert Transaction.query.count() == 1


def test_push_subscribe_validation(make_ledger, client_for):
    _, (chulsoo, _), _ = make_ledger()
    c = client_for(chulsoo)
    assert c.post('/api/push/subscribe', json={'endpoint': 'x' * 600, 'keys': {'p256dh': 'a', 'auth': 'b'}}).status_code == 400
    assert c.post('/api/push/subscribe', data='not json').status_code == 400
    assert c.post('/api/push/subscribe', json={'endpoint': 'https://e', 'keys': {'p256dh': 'a', 'auth': 'b'}}).status_code == 200


def test_pages_render_and_security_headers(make_ledger, client_for):
    _, (chulsoo, _), _ = make_ledger()
    c = client_for(chulsoo)
    add_tx(c)
    tx = Transaction.query.one()
    for url in ['/home', '/calendar', '/transactions', '/settings', '/mypage',
                '/mypage?msg=imported&imported=3&skipped_dup=1', f'/transaction/{tx.id}/edit']:
        res = c.get(url)
        assert res.status_code == 200, url
        assert res.headers['X-Content-Type-Options'] == 'nosniff'


def test_edit_page_rejects_external_next_url(make_ledger, client_for):
    _, (chulsoo, _), _ = make_ledger()
    c = client_for(chulsoo)
    add_tx(c)
    tx = Transaction.query.one()
    html = c.get(f'/transaction/{tx.id}/edit?next=javascript:alert(1)').get_data(as_text=True)
    assert 'href="javascript' not in html and 'value="javascript' not in html
    form = {'tx_type': '지출', 'amount': '1', 'transactor': '철수', 'title': 'a', 'date': '2026-09-15',
            'time': '12:00', 'next': '//evil.example'}
    assert c.post(f'/transaction/{tx.id}/edit', data=form).get_json()['redirect'] == '/transactions'


def test_user_text_is_escaped_in_server_rendered_pages(make_ledger, client_for):
    ledger, (chulsoo, _), _ = make_ledger()
    c = client_for(chulsoo)
    payload = '<img src=x onerror=alert(1)>'
    c.post('/api/category/add', json={'name': payload})
    c.post('/update_ledger_name', data={'name': payload, 'ajax': '1'})
    for url in ['/settings', '/mypage', '/transactions', '/home']:
        assert payload not in c.get(url).get_data(as_text=True), url
